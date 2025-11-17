from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from datetime import datetime, timezone
from models import db, Thread, Message, User, CustomLabel
from utils.email_utils import fetch_new_threads, sync_existing_threads, clean_message_body
from utils.gmail_api import send_email_via_api
from utils.chess_utils import get_or_create_fen, process_move, update_thread_fen, get_position_evaluation, calculate_won_games
from werkzeug.utils import secure_filename
from openai import OpenAI
import chess
import os
import re

mail_bp = Blueprint('mail', __name__)

# Helper function for file uploads
def allowed_file(filename):
    """
    Check if file extension is allowed for icon uploads.

    Args:
        filename (str): The filename to check

    Returns:
        bool: True if extension is in allowed list, False otherwise

    Dependencies:
        None - standalone validation function

    Allowed Extensions:
        png, jpg, jpeg, gif, svg, pdf, doc, docx, xls, xlsx, txt, zip, pgn
    """
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip', 'pgn'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Register Jinja2 filter for cleaning message bodies
@mail_bp.app_template_filter('clean_body')
def clean_body_filter(body, is_html=False):
    """
    Jinja2 template filter to clean and sanitize message bodies for display.

    Args:
        body (str): The message body to clean
        is_html (bool): Whether the body contains HTML

    Returns:
        str: Cleaned and sanitized message body

    Dependencies:
        - utils.email_utils.clean_message_body: Core cleaning logic

    Usage in templates:
        {{ message.body_plain|clean_body }}
        {{ message.body_html|clean_body(True) }}
    """
    return clean_message_body(body, is_html)


@mail_bp.route("/", methods=["GET", "POST"])
@mail_bp.route("/inbox", methods=["GET", "POST"])
def inbox():
    """
    Display the inbox with all email threads and handle new thread creation.

    GET:
        Displays list of threads sorted by latest message date

    POST:
        Creates a new thread when user provides recipient and subject

    Form Parameters (POST):
        new_mail (str): Recipient email address
        subject (str): Email subject line

    Returns:
        GET: Rendered inbox.html template with threads and custom labels
        POST: Redirect to new thread view

    Dependencies:
        - Session: user.id, user.email for authentication
        - Models: Thread, Message, CustomLabel, db.session
        - SQLAlchemy: func.max() for aggregation
        - Chess: chess.Board() for initializing FEN

    Side Effects:
        - POST creates new Thread in database with temporary gmail_thread_id
        - Stores recipient in session[f'thread_{thread.id}_recipient']
        - Stores subject in session['current_subject']

    Template Variables:
        - threads: List with enriched metadata (latest_message_date, other_person)
        - custom_labels: All custom labels for current user
    """
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    # Get all threads for this user, sorted by newest message first
    # Join with messages to get the latest message timestamp
    from sqlalchemy import func
    threads = db.session.query(Thread)\
        .filter(Thread.user_id == user_id)\
        .outerjoin(Message, Thread.id == Message.thread_id)\
        .group_by(Thread.id)\
        .order_by(func.max(Message.date).desc())\
        .all()

    # Get all custom labels for this user
    custom_labels = CustomLabel.query.filter_by(user_id=user_id).all()

    # Enrich threads with latest_message_date and other_person
    for thread in threads:
        thread.latest_message_date = None
        thread.other_person = None

        # Find latest message date and other person
        for msg in thread.messages:
            if msg.date:
                if thread.latest_message_date is None or msg.date > thread.latest_message_date:
                    thread.latest_message_date = msg.date

            if not thread.other_person:
                if msg.sender and msg.sender != user_email:
                    thread.other_person = msg.sender
                elif msg.recipient and msg.recipient != user_email:
                    thread.other_person = msg.recipient

    if request.method == "POST":
        # Handle new thread creation
        new_mail = request.form.get("new_mail")
        subject = request.form.get("subject")

        if new_mail and subject:
            # For creating a new thread, we need a unique gmail_thread_id
            # We'll use a temporary ID and it will be updated when the first email is sent
            import time
            temp_thread_id = f"temp_{user_id}_{int(time.time() * 1000)}"

            # Initialize FEN for new chess game
            board = chess.Board()

            thread = Thread(
                gmail_thread_id=temp_thread_id,
                subject=subject,
                snippet="",
                fen=board.fen(),
                user_id=user_id
            )
            db.session.add(thread)
            db.session.commit()

            # Store recipient in session for new thread
            session[f'thread_{thread.id}_recipient'] = new_mail
            session['current_subject'] = subject

            return redirect(url_for("mail.thread", thread_id=thread.id))
        else:
            flash("Please provide both recipient and subject", "error")

    return render_template("inbox.html", user=user, threads=threads, custom_labels=custom_labels)


@mail_bp.route("/thread/<int:thread_id>", methods=["GET", "POST"])
def thread(thread_id):
    """
    Display thread conversation with messages and chess board, handle sending new messages.

    GET:
        Shows all messages in thread with current chess position

    POST:
        Sends new email message (optionally with chess move) via Gmail API

    URL Parameters:
        thread_id (int): Database ID of the thread

    Form Parameters (POST):
        body (str): Email message body
        move (str): Chess move in UCI format (e.g., "e2e4")
        is_html (str): "true" if body contains HTML

    Returns:
        GET: Rendered thread.html with messages and chess board
        POST: Redirect back to same thread view

    Dependencies:
        - Session: user.id, user.email, access_token
        - Models: Thread, Message, db.session
        - Utils:
            - chess_utils.get_or_create_fen(): Get current board position
            - chess_utils.process_move(): Validate and process chess move (returns 4 values!)
            - chess_utils.update_thread_fen(): Save new position
            - chess_utils.get_position_evaluation(): Get Stockfish evaluation for current position
            - chess_utils.calculate_won_games(): Calculate user's won game count
            - gmail_api.send_email_via_api(): Send email with threading headers
        - Chess: For FEN management
        - Stockfish: For position evaluation

    Side Effects:
        - POST sends email via Gmail API
        - Creates new Message record in database with Gmail IDs
        - Updates Thread.gmail_thread_id if it was temporary
        - Updates Thread.snippet and Thread.last_updated
        - Updates Thread.fen with new chess position
        - Cleans up session[f'thread_{thread_id}_recipient'] after first message

    Email Threading:
        Extracts In-Reply-To and References headers from last message
        to ensure Gmail groups messages correctly in conversations

    Recipient Logic:
        - If messages exist: Uses sender from first message
        - If new thread: Uses recipient from session storage
    """
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")
    thread = Thread.query.get_or_404(thread_id)

    # Verify user owns this thread
    if thread.user_id != user_id:
        flash("You don't have permission to view this thread", "error")
        return redirect(url_for("mail.inbox"))

    # Get FEN from thread
    fen = get_or_create_fen(thread.id) or thread.fen

    # Determine who is "me" and who is "other" from messages
    messages = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).all()
    me = user_email
    other = None

    if messages:
        # Find the other participant from messages
        for msg in messages:
            if msg.sender != user_email:
                other = msg.sender
                break
            elif msg.recipient != user_email:
                other = msg.recipient
                break
    else:
        # No messages yet - check if recipient is in session (new thread)
        session_key = f'thread_{thread.id}_recipient'
        if session_key in session:
            other = session.get(session_key)

    if session.get("current_subject"):
        thread_subject = session.get("current_subject")
    else:
        thread_subject = thread.subject
    session.pop("current_subject", None)

    if request.method == "POST":
        body = request.form.get("body", "")
        move_uci = request.form.get("move")
        is_html = request.form.get("is_html") == "true"

        # Get attachments from request
        attachments = []
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            for file in files:
                if file and file.filename:
                    # Validate file extension
                    if allowed_file(file.filename):
                        attachments.append(file)
                        print(f"[DEBUG] Attachment added for processing: {file.filename}")
                    else:
                        flash(f"Filtype ikke tilladt: {file.filename}", "warning")

        print(f"[DEBUG] Total attachments to send: {len(attachments)}")

        # Ensure we have a recipient
        if not other:
            flash("No recipient found for this thread", "error")
            return redirect(url_for("mail.thread", thread_id=thread_id))

        # Process chess move (returns: new_fen, result, game_over, evaluation_score)
        new_fen, game_result, game_over, evaluation_score = process_move(fen, move_uci)

        print(f"[DEBUG] Stockfish evaluation: {evaluation_score} centipawns")

        # Update thread FEN
        update_thread_fen(thread.id, new_fen)
        thread.last_updated = datetime.now(timezone.utc)

        # Update game result if game has ended
        if game_over:
            thread.game_result = game_result  # Store '1-0', '0-1', or '1/2-1/2'
            flash(f"Game over! Result: {game_result}", "info")

        db.session.commit()

        # Get threading headers BEFORE saving the new message
        last_message = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.desc()).first()
        in_reply_to = None
        references = None
        gmail_thread_id = thread.gmail_thread_id if not thread.gmail_thread_id.startswith("temp_") else None

        if last_message and last_message.in_reply_to:
            in_reply_to = last_message.in_reply_to
            # Build References header
            if last_message.references:
                references = f"{last_message.references} {last_message.in_reply_to}"
            else:
                references = last_message.in_reply_to

        # Add "Re:" prefix to subject if this is a reply
        reply_subject = thread_subject
        if last_message:
            if not thread_subject.lower().startswith("re:"):
                reply_subject = f"Re: {thread_subject}"

        # Send email via Gmail API first
        try:
            # Prepare email body
            if is_html:
                if move_uci:
                    email_body = f"{body}<p><strong>Move:</strong> {move_uci}</p>"
                else:
                    email_body = body
            else:
                if move_uci:
                    email_body = f"{body}\n\nMove: {move_uci}"
                else:
                    email_body = body

            result = send_email_via_api(
                session["access_token"],
                user_email,
                other,
                reply_subject,
                email_body,
                is_html=is_html,
                in_reply_to=in_reply_to,
                references=references,
                thread_id=gmail_thread_id,
                attachments=attachments  # Pass attachments to Gmail API
            )

            # Now save message with Gmail IDs
            if result and result.get('gmail_message_id'):
                # Update thread's gmail_thread_id if it was temporary
                if thread.gmail_thread_id.startswith("temp_") and result.get('thread_id'):
                    thread.gmail_thread_id = result['thread_id']
                    db.session.commit()

                # Update thread snippet with new message
                import re
                if is_html:
                    # Remove HTML tags
                    snippet_text = re.sub(r'<[^>]+>', '', body)
                    snippet_text = re.sub(r'\s+', ' ', snippet_text).strip()
                else:
                    snippet_text = body.strip()
                thread.snippet = snippet_text[:200]
                thread.last_updated = datetime.now(timezone.utc)

                # Save message with evaluation score
                msg = Message(
                    gmail_message_id=result['gmail_message_id'],
                    thread_id=thread.id,
                    user_id=user_id,
                    sender=me,
                    recipient=other,
                    date=datetime.now(timezone.utc),
                    subject=reply_subject,
                    body_plain=body if not is_html else "",
                    body_html=body if is_html else "",
                    in_reply_to=in_reply_to or result.get('message_id'),
                    references=references,
                    label_ids="",
                    move=move_uci,
                    evaluation_score=evaluation_score  # Store Stockfish evaluation
                )
                db.session.add(msg)
                db.session.commit()

                # Clean up session recipient after first message is sent
                session_key = f'thread_{thread.id}_recipient'
                if session_key in session:
                    session.pop(session_key)

                flash("Besked sendt!", "success")
            else:
                flash("Email sent but couldn't save to database", "warning")

        except Exception as e:
            print(f"[ERROR] Email send failed: {str(e)}")
            import traceback
            traceback.print_exc()
            flash(f"Fejl ved afsendelse: {str(e)}", "error")

        return redirect(url_for("mail.thread", thread_id=thread_id))

    # GET request - calculate current evaluation and won games
    current_evaluation = get_position_evaluation(fen)
    won_count = calculate_won_games(user_id, user_email)

    return render_template(
        "thread.html",
        thread=thread,
        me=me,
        other=other,
        fen=fen,
        messages=messages,
        won_count=won_count,
        evaluation=current_evaluation['score']  # Pass evaluation dict to template
    )


@mail_bp.route("/api/fetch-threads", methods=["POST"])
def fetch_threads():
    """
    API endpoint to fetch new email threads from Gmail and save to database.

    Fetches the most recent threads from user's Gmail inbox and creates
    Thread and Message records in local database.

    Request JSON:
        count (int): Number of threads to fetch (default: 5)

    Returns:
        JSON response with:
            success (bool): Whether operation succeeded
            message (str): Human-readable status message
            stats (dict): Statistics about fetched threads
            require_reauth (bool): If OAuth token is invalid

    Dependencies:
        - Session: user.id, user.email, access_token
        - Utils: email_utils.fetch_new_threads()
        - Models: Thread, Message (created by fetch_new_threads)

    Error Handling:
        - Returns 401 if not authenticated or token missing
        - Returns 401 with require_reauth if OAuth token expired
        - Returns 500 for other errors

    Side Effects:
        - Creates new Thread records in database
        - Creates new Message records for each email
        - Does NOT modify existing threads
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")
    access_token = session.get("access_token")

    if not access_token:
        return jsonify({
            "success": False,
            "error": "Ingen access token. Log venligst ud og ind igen.",
            "require_reauth": True
        }), 401

    # Get count from request
    data = request.get_json()
    count = int(data.get('count', 5))

    try:
        stats = fetch_new_threads(user_id, user_email, access_token, count)

        # Check for auth errors
        if stats.get('errors'):
            for error in stats['errors']:
                if 'AUTHENTICATIONFAILED' in error or 'Invalid credentials' in error:
                    return jsonify({
                        "success": False,
                        "error": "OAuth token er ugyldig. Log venligst UD og IND igen.",
                        "require_reauth": True
                    }), 401

        return jsonify({
            "success": True,
            "message": f"Hentet {stats['threads_fetched']} nye tråde",
            "stats": stats
        }), 200

    except Exception as e:
        error_msg = str(e)
        require_reauth = 'AUTHENTICATIONFAILED' in error_msg or 'Invalid credentials' in error_msg

        return jsonify({
            "success": False,
            "error": f"Hentning fejlede: {error_msg}",
            "require_reauth": require_reauth
        }), 500


@mail_bp.route("/api/sync", methods=["POST"])
@mail_bp.route("/api/sync-existing", methods=["POST"])
def sync_existing():
    """
    API endpoint to sync existing threads with new messages from Gmail.

    Checks all existing threads in database and fetches any new messages
    from Gmail that have been added to those conversations.

    Returns:
        JSON response with:
            success (bool): Whether operation succeeded
            message (str): Human-readable status message
            stats (dict): Statistics about synced messages
            require_reauth (bool): If OAuth token is invalid

    Dependencies:
        - Session: user.id, user.email, access_token
        - Utils: email_utils.sync_existing_threads()
        - Models: Thread, Message (queried and updated by sync_existing_threads)

    Error Handling:
        - Returns 401 if not authenticated or token missing
        - Returns 401 with require_reauth if OAuth token expired
        - Returns 500 for other errors

    Side Effects:
        - Adds new Message records to existing threads
        - Updates Thread.last_updated timestamp
        - Does NOT create new threads (use fetch_threads for that)
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")
    access_token = session.get("access_token")

    if not access_token:
        return jsonify({
            "success": False,
            "error": "Ingen access token. Log venligst ud og ind igen.",
            "require_reauth": True
        }), 401

    try:
        stats = sync_existing_threads(user_id, user_email, access_token)

        # Check for auth errors
        if stats.get('errors'):
            for error in stats['errors']:
                if 'AUTHENTICATIONFAILED' in error or 'Invalid credentials' in error:
                    return jsonify({
                        "success": False,
                        "error": "OAuth token er ugyldig. Log venligst UD og IND igen.",
                        "require_reauth": True
                    }), 401

        return jsonify({
            "success": True,
            "message": "Synkronisering fuldført",
            "stats": stats
        }), 200

    except Exception as e:
        error_msg = str(e)
        require_reauth = 'AUTHENTICATIONFAILED' in error_msg or 'Invalid credentials' in error_msg

        return jsonify({
            "success": False,
            "error": f"Sync fejlede: {error_msg}",
            "require_reauth": require_reauth
        }), 500


@mail_bp.route("/api/threads", methods=["GET"])
def get_threads():
    """
    API endpoint to get complete list of threads with metadata (for UI refresh).

    Returns all threads for current user with aggregated information about
    messages, labels, and participants.

    Returns:
        JSON response with:
            success (bool): Always True
            threads (list): Array of thread objects with metadata
            count (int): Total number of threads

    Thread Object Structure:
        id (int): Thread database ID
        subject (str): Email subject
        snippet (str): Preview text
        last_updated (str): ISO timestamp of latest message
        message_count (int): Number of messages in thread
        labels (list): Unique labels from all messages
        other_person (str): Email of conversation partner

    Dependencies:
        - Session: user.id, user.email
        - Models: Thread, Message
        - SQLAlchemy: func.max() for aggregation

    Side Effects:
        None - read-only operation

    Usage:
        Called by JavaScript to refresh inbox without page reload
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    # Get threads sorted by latest message date
    from sqlalchemy import func
    threads = db.session.query(Thread)\
        .filter(Thread.user_id == user_id)\
        .outerjoin(Message, Thread.id == Message.thread_id)\
        .group_by(Thread.id)\
        .order_by(func.max(Message.date).desc())\
        .all()

    thread_list = []
    for t in threads:
        # Aggregate unique labels from all messages in thread
        all_labels = set()
        latest_message_date = None
        other_person = None

        for msg in t.messages:
            if msg.label_ids:
                labels = [label.strip() for label in msg.label_ids.split(',') if label.strip()]
                all_labels.update(labels)

            # Find the latest message date
            if msg.date:
                if latest_message_date is None or msg.date > latest_message_date:
                    latest_message_date = msg.date

            # Find the other person in the conversation
            if not other_person:
                user_email = user.get("email")
                if msg.sender and msg.sender != user_email:
                    other_person = msg.sender
                elif msg.recipient and msg.recipient != user_email:
                    other_person = msg.recipient

        thread_list.append({
            "id": t.id,
            "subject": t.subject,
            "snippet": t.snippet,
            "last_updated": latest_message_date.isoformat() if latest_message_date else None,
            "message_count": len(t.messages),
            "labels": list(all_labels),
            "other_person": other_person
        })

    return jsonify({
        "success": True,
        "threads": thread_list,
        "count": len(thread_list)
    }), 200


@mail_bp.route("/api/thread/<int:thread_id>/messages", methods=["GET"])
def get_thread_messages(thread_id):
    """
    API endpoint to get all messages in a specific thread (for UI refresh).

    Returns messages in chronological order with body content and metadata.
    Used by JavaScript to refresh conversation view without page reload.

    URL Parameters:
        thread_id (int): Database ID of the thread

    Returns:
        JSON response with:
            success (bool): Always True
            messages (list): Array of message objects
            fen (str): Current chess board position
            count (int): Number of messages

    Message Object Structure:
        id (int): Message database ID
        sender (str): Sender email address
        recipient (str): Recipient email address
        body (str): Message content (HTML or plain text)
        is_html (bool): Whether body contains HTML
        move (str): Chess move in UCI format (if any)
        timestamp (str): ISO timestamp

    Dependencies:
        - Session: user.id for authentication
        - Models: Thread, Message

    Side Effects:
        None - read-only operation

    Authorization:
        Verifies user owns the thread (403 if not)
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)

    # Verify user owns this thread
    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    messages = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).all()

    message_list = []
    for msg in messages:
        # Determine body to show (prefer HTML over plain)
        body = msg.body_html if msg.body_html else msg.body_plain
        is_html = bool(msg.body_html)

        message_list.append({
            "id": msg.id,
            "sender": msg.sender,
            "recipient": msg.recipient,
            "body": body,
            "is_html": is_html,
            "move": msg.move,
            "timestamp": msg.date.isoformat() if msg.date else None  # JavaScript expects 'timestamp'
        })

    return jsonify({
        "success": True,
        "messages": message_list,
        "fen": thread.fen,
        "count": len(message_list)
    }), 200


@mail_bp.route("/api/thread/<int:thread_id>/export", methods=["POST"])
def export_conversation(thread_id):
    """
    API endpoint to generate AI-powered summary of email conversation.

    Exports conversation to formatted text (prints to terminal for debugging),
    then calls OpenAI GPT-4o-mini to generate a concise Danish summary.

    URL Parameters:
        thread_id (int): Database ID of the thread

    Returns:
        JSON response with:
            success (bool): Whether operation succeeded
            message (str): Status message
            message_count (int): Number of messages in conversation
            summary (str): AI-generated summary in Danish
            tokens_used (int): OpenAI tokens consumed
            error (str): Error message if failed

    Dependencies:
        - Session: user.id for authentication
        - Models: Thread, Message
        - OpenAI API: GPT-4o-mini model for summarization
        - Environment: OPENAI_API_KEY from environ.env

    OpenAI Configuration:
        - Model: gpt-4o-mini (cost-effective)
        - Max Tokens: 200 (~150 words, ~$0.00012 per summary)
        - Temperature: 1.3 (high creativity)
        - System Prompt: Instructs AI to write brief Danish summaries about chess games

    Side Effects:
        - Prints formatted conversation and summary to terminal (debugging)
        - Consumes OpenAI API credits

    Authorization:
        Verifies user owns the thread (403 if not)

    Error Handling:
        - Returns 500 if OPENAI_API_KEY not configured
        - Returns 500 if OpenAI API call fails
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)

    # Verify user owns this thread
    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    # Get all messages ordered by date
    messages = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).all()

    # Build formatted conversation string
    conversation_lines = []
    conversation_lines.append("=" * 80)
    conversation_lines.append(f"CONVERSATION: {thread.subject}")
    conversation_lines.append("=" * 80)
    conversation_lines.append("")

    for msg in messages:
        # Get sender name
        sender = msg.sender if msg.sender else "Unknown"

        # Get timestamp
        timestamp = msg.date.strftime('%d/%m/%Y %H:%M:%S') if msg.date else "No date"

        # Get message body (prefer plain text, or strip HTML if needed)
        if msg.body_plain:
            body = msg.body_plain
        elif msg.body_html:
            # Strip HTML tags for cleaner output
            body = re.sub(r'<[^>]+>', '', msg.body_html)
            body = body.strip()
        else:
            body = "(No content)"

        # Format message
        conversation_lines.append(f"[{timestamp}] {sender}:")
        if msg.move:
            conversation_lines.append(f"  Move: {msg.move}")
        conversation_lines.append(f"  {body}")
        conversation_lines.append("")

    conversation_lines.append("=" * 80)
    conversation_lines.append(f"Total messages: {len(messages)}")
    conversation_lines.append("=" * 80)

    # Join all lines
    conversation_text = "\n".join(conversation_lines)

    # Print to terminal for debugging
    print("\n\n" + conversation_text + "\n\n")

    # Generate summary using OpenAI
    # SECURITY NOTE: API key should be in environ.env, not hardcoded!
    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if not openai_api_key:
        return jsonify({
            "success": False,
            "error": "OpenAI API key not configured"
        }), 500

    try:
        client = OpenAI(api_key=openai_api_key)

        # Call OpenAI with controlled parameters
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Cost-effective model
            messages=[
                {
                    "role": "system",
                    "content": """Du er en hjælpsom assistent der laver korte, præcise referater af skak-email samtaler.

Regler for dit referat:
- Skriv på dansk
- Maksimalt 5-8 sætninger
- Fokuser på skakspillets status og vigtige træk
- Nævn hvem der spiller
- Vær kort og præcis
- Brug ikke overflødig information
- Lav mindst en joke om kongeriget danmark"""
                },
                {
                    "role": "user",
                    "content": f"Generer et kort referat af denne skak-email samtale:\n\n{conversation_text}"
                }
            ],
            max_tokens=200,  # Begrænser længden (ca. 150 ord)
            temperature=0.2,  # Kreativitet (0-2, lavere = mere forudsigeligt)
            presence_penalty=0.5,
            frequency_penalty=0.0
        )

        summary = response.choices[0].message.content.strip()

        # Print summary to terminal
        print("\n\n=== OPENAI REFERAT ===")
        print(summary)
        print("======================\n\n")

        return jsonify({
            "success": True,
            "message": "Conversation exported and summarized",
            "message_count": len(messages),
            "summary": summary,
            "tokens_used": response.usage.total_tokens
        }), 200

    except Exception as e:
        print(f"OpenAI Error: {str(e)}")
        return jsonify({
            "success": False,
            "error": f"OpenAI API error: {str(e)}"
        }), 500


@mail_bp.route("/api/clear-database", methods=["POST"])
def clear_database():
    """
    API endpoint to delete all threads and messages for current user.

    WARNING: This is a destructive operation that cannot be undone!
    Deletes all local email data but does NOT affect Gmail.

    Returns:
        JSON response with:
            success (bool): Whether operation succeeded
            message (str): Status message
            stats (dict): Deletion statistics
                threads_deleted (int): Number of threads removed
                messages_deleted (int): Number of messages removed
            error (str): Error message if failed

    Dependencies:
        - Session: user.id for authentication
        - Models: Thread, Message, db.session

    Side Effects:
        - DELETES all Thread records for user
        - DELETES all Message records for user
        - Does NOT delete User record
        - Does NOT delete CustomLabel records
        - Does NOT affect Gmail (emails remain in Gmail)
        - Transaction rolled back if any error occurs

    Authorization:
        Only deletes data for authenticated user (user_id filter)
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    try:
        # Delete all messages for this user
        messages_deleted = Message.query.filter_by(user_id=user_id).delete()

        # Delete all threads for this user
        threads_deleted = Thread.query.filter_by(user_id=user_id).delete()

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Database cleared successfully",
            "stats": {
                "threads_deleted": threads_deleted,
                "messages_deleted": messages_deleted
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": f"Failed to clear database: {str(e)}"
        }), 500


@mail_bp.route("/api/thread/<int:thread_id>/labels", methods=["POST"])
def update_thread_labels(thread_id):
    """
    API endpoint to add or remove custom labels from all messages in a thread.

    Updates labels locally in database only (does NOT sync to Gmail).
    Applies label changes to all messages in the thread.

    URL Parameters:
        thread_id (int): Database ID of the thread

    Request JSON:
        add_labels (list): Label names to add to messages
        remove_labels (list): Label names to remove from messages

    Returns:
        JSON response with:
            success (bool): Whether operation succeeded
            message (str): Status message
            updated_count (int): Number of messages updated
            error (str): Error message if failed

    Dependencies:
        - Session: user.id for authentication
        - Models: Thread, Message, db.session

    Side Effects:
        - Updates Message.label_ids for all messages in thread
        - Stores labels as comma-separated string
        - Transaction rolled back if any error occurs

    Authorization:
        Verifies user owns the thread (403 if not)

    Note:
        Labels are stored locally and do not affect Gmail labels
    """
    print(f"[DEBUG] update_thread_labels called for thread {thread_id}")

    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    # Get thread and verify ownership
    thread = Thread.query.get_or_404(thread_id)
    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    # Get label modifications from request
    data = request.get_json()
    add_labels = data.get('add_labels', [])
    remove_labels = data.get('remove_labels', [])
    print(f"[DEBUG] Add labels: {add_labels}, Remove labels: {remove_labels}")

    if not add_labels and not remove_labels:
        return jsonify({"error": "No label modifications specified"}), 400

    try:
        # Update labels locally for all messages in thread
        updated_count = 0
        for msg in thread.messages:
            # Get current labels
            current_labels = set()
            if msg.label_ids:
                current_labels = set(label.strip() for label in msg.label_ids.split(',') if label.strip())

            print(f"[DEBUG] Message {msg.id} - Current labels: {current_labels}")

            # Add new labels
            for label in add_labels:
                current_labels.add(label)

            # Remove labels
            for label in remove_labels:
                current_labels.discard(label)

            # Update database
            new_label_str = ','.join(sorted(current_labels)) if current_labels else ""
            msg.label_ids = new_label_str
            print(f"[DEBUG] Message {msg.id} - New labels: {new_label_str}")
            updated_count += 1

        db.session.commit()
        print(f"[DEBUG] Successfully updated {updated_count} messages")

        return jsonify({
            "success": True,
            "message": f"Labels updated for {updated_count} messages",
            "updated_count": updated_count
        }), 200

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] Failed to update labels: {str(e)}")
        import traceback
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": f"Failed to update labels: {str(e)}"
        }), 500


@mail_bp.route("/debug/message/<int:message_id>", methods=["GET"])
def debug_message(message_id):
    """
    Debug endpoint to view raw and rendered message content.

    Displays message metadata, raw HTML/text, and rendered version
    for troubleshooting display issues.

    URL Parameters:
        message_id (int): Database ID of the message

    Returns:
        HTML page with:
            - Message metadata (sender, recipient, date, subject, move)
            - Raw body content (HTML escaped)
            - Rendered version of body

    Dependencies:
        - Session: user.id for authentication
        - Models: Message

    Side Effects:
        None - read-only operation

    Authorization:
        Verifies user owns the message (403 if not)

    Usage:
        Development tool for debugging email rendering issues
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    msg = Message.query.get_or_404(message_id)

    # Verify user owns this message
    if msg.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    # Determine body to show
    body = msg.body_html if msg.body_html else msg.body_plain
    is_html = bool(msg.body_html)

    # Return raw HTML for inspection
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Debug Message {message_id}</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; }}
            .info {{ background: #f0f0f0; padding: 10px; margin-bottom: 20px; }}
            .raw {{ background: #fff; border: 1px solid #ccc; padding: 10px; margin-bottom: 20px; white-space: pre-wrap; }}
            .rendered {{ border: 2px solid #4CAF50; padding: 10px; }}
        </style>
    </head>
    <body>
        <h1>Debug Message #{message_id}</h1>
        <div class="info">
            <strong>From:</strong> {msg.sender}<br>
            <strong>To:</strong> {msg.recipient}<br>
            <strong>Is HTML:</strong> {is_html}<br>
            <strong>Move:</strong> {msg.move or 'None'}<br>
            <strong>Date:</strong> {msg.date}<br>
            <strong>Subject:</strong> {msg.subject}
        </div>

        <h2>Raw Body (from database)</h2>
        <div class="raw">{body.replace('<', '&lt;').replace('>', '&gt;') if body else 'No body'}</div>

        <h2>Rendered HTML</h2>
        <div class="rendered">
            {body if is_html else f'<pre>{body}</pre>' if body else 'No body'}
        </div>
    </body>
    </html>
    """


@mail_bp.route("/api/custom-labels", methods=["GET"])
def get_custom_labels():
    """
    API endpoint to retrieve all custom labels created by current user.

    Returns list of custom labels with their display properties (name, icon, color).

    Returns:
        JSON response with:
            success (bool): Always True
            labels (list): Array of label objects
            count (int): Total number of labels

    Label Object Structure:
        id (int): Label database ID
        name (str): Internal name (uppercase, no spaces)
        display_name (str): User-friendly name
        icon_path (str): Path to icon file (if any)
        color (str): Hex color code

    Dependencies:
        - Session: user.id for authentication
        - Models: CustomLabel

    Side Effects:
        None - read-only operation

    Usage:
        Called by JavaScript to populate label selector UI
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    labels = CustomLabel.query.filter_by(user_id=user_id).order_by(CustomLabel.created_at.desc()).all()

    label_list = []
    for label in labels:
        label_list.append({
            "id": label.id,
            "name": label.name,
            "display_name": label.display_name,
            "icon_path": label.icon_path,
            "color": label.color
        })

    return jsonify({
        "success": True,
        "labels": label_list,
        "count": len(label_list)
    }), 200


@mail_bp.route("/api/custom-labels", methods=["POST"])
def create_custom_label():
    """
    API endpoint to create a new custom label with optional icon.

    Handles multipart/form-data upload for icon files.
    Generates internal name from display name.

    Form Parameters:
        display_name (str, required): User-friendly label name
        color (str, optional): Hex color code (default: #6B7280)
        icon (file, optional): Icon image file

    Returns:
        JSON response with:
            success (bool): Whether operation succeeded
            message (str): Status message
            label (dict): Created label object with all properties
            error (str): Error message if failed

    Dependencies:
        - Session: user.id for authentication
        - Models: CustomLabel, db.session
        - Flask: current_app.config['UPLOAD_FOLDER']
        - Utils: secure_filename from werkzeug

    Side Effects:
        - Creates new CustomLabel record in database
        - Saves icon file to static/label_icons/ if provided
        - Filename prefixed with user_id and timestamp for uniqueness
        - Transaction rolled back if any error occurs

    Validation:
        - display_name is required
        - Label name must be unique for user (case-insensitive)
        - Icon file extension must be in allowed list

    File Naming:
        Uploaded icons saved as: {user_id}_{timestamp}_{original_filename}
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    # Get form data
    display_name = request.form.get('display_name')
    color = request.form.get('color', '#6B7280')

    if not display_name:
        return jsonify({"error": "Display name is required"}), 400

    # Generate internal name from display name (uppercase, no spaces)
    name = display_name.upper().replace(' ', '_')

    # Check if label already exists
    existing = CustomLabel.query.filter_by(user_id=user_id, name=name).first()
    if existing:
        return jsonify({"error": f"Label '{display_name}' already exists"}), 400

    # Handle icon upload
    icon_path = None
    if 'icon' in request.files:
        file = request.files['icon']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Add user_id and timestamp to make filename unique
            import time
            unique_filename = f"{user_id}_{int(time.time())}_{filename}"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)
            # Store relative path for web access
            icon_path = f"/static/label_icons/{unique_filename}"

    try:
        # Create new label
        new_label = CustomLabel(
            user_id=user_id,
            name=name,
            display_name=display_name,
            icon_path=icon_path,
            color=color
        )
        db.session.add(new_label)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Label '{display_name}' created successfully",
            "label": {
                "id": new_label.id,
                "name": new_label.name,
                "display_name": new_label.display_name,
                "icon_path": new_label.icon_path,
                "color": new_label.color
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": f"Failed to create label: {str(e)}"
        }), 500


@mail_bp.route("/api/custom-labels/<int:label_id>", methods=["DELETE"])
def delete_custom_label(label_id):
    """
    API endpoint to delete a custom label and remove it from all messages.

    Deletes label definition and removes it from all messages that have it.
    Also deletes associated icon file from filesystem.

    URL Parameters:
        label_id (int): Database ID of the label to delete

    Returns:
        JSON response with:
            success (bool): Whether operation succeeded
            message (str): Status message with label display name
            error (str): Error message if failed

    Dependencies:
        - Session: user.id for authentication
        - Models: CustomLabel, Message, db.session
        - Flask: current_app.root_path for file path
        - OS: os.path, os.remove for file deletion

    Side Effects:
        - DELETES CustomLabel record from database
        - Removes icon file from filesystem if exists
        - Removes label from Message.label_ids for all messages
        - Transaction rolled back if any error occurs

    Authorization:
        Verifies user owns the label (403 if not)

    Cleanup Process:
        1. Delete icon file from static/label_icons/
        2. Remove label name from all messages' label_ids
        3. Delete label record from database
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    # Get label and verify ownership
    label = CustomLabel.query.get_or_404(label_id)
    if label.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    try:
        # Delete icon file if exists
        if label.icon_path:
            icon_file = os.path.join(current_app.root_path, label.icon_path.lstrip('/'))
            if os.path.exists(icon_file):
                os.remove(icon_file)

        # Remove label from all messages
        label_name = label.name
        messages = Message.query.filter_by(user_id=user_id).all()
        for msg in messages:
            if msg.label_ids:
                labels = set(l.strip() for l in msg.label_ids.split(',') if l.strip())
                labels.discard(label_name)
                msg.label_ids = ','.join(sorted(labels)) if labels else ""

        # Delete label
        db.session.delete(label)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": f"Label '{label.display_name}' deleted successfully"
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": f"Failed to delete label: {str(e)}"
        }), 500
