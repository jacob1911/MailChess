from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from datetime import datetime, timezone
from models import db, Thread, Message, User, CustomLabel
from utils.email_utils import fetch_new_threads, sync_existing_threads, clean_message_body
from utils.gmail_api import send_email_via_api
from utils.chess_utils import get_or_create_fen, process_move, update_thread_fen
from werkzeug.utils import secure_filename
from openai import OpenAI
import chess
import os
import re

mail_bp = Blueprint('mail', __name__)

# Helper function for file uploads
def allowed_file(filename):
    """Check if file extension is allowed"""
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Register Jinja2 filter for cleaning message bodies
@mail_bp.app_template_filter('clean_body')
def clean_body_filter(body, is_html=False):
    """Jinja2 filter to clean message bodies"""
    return clean_message_body(body, is_html)


@mail_bp.route("/", methods=["GET", "POST"])
@mail_bp.route("/inbox", methods=["GET", "POST"])
def inbox():
    """Display inbox and create new threads"""
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
    """Display and interact with email thread and chess game"""
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

        # Ensure we have a recipient
        if not other:
            flash("No recipient found for this thread", "error")
            return redirect(url_for("mail.thread", thread_id=thread_id))

        # Process chess move
        new_fen, result, game_over = process_move(fen, move_uci)

        # Update thread FEN
        update_thread_fen(thread.id, new_fen)
        thread.last_updated = datetime.now(timezone.utc)

        if game_over:
            flash(f"Game over! Result: {result}", "info")

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
                thread_id=gmail_thread_id
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

                # Save message
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
                    move=move_uci
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
            flash(f"Fejl ved afsendelse: {str(e)}", "error")

        return redirect(url_for("mail.thread", thread_id=thread_id))

    # GET request - messages already fetched above
    return render_template(
        "thread.html",
        thread=thread,
        me=me,
        other=other,
        fen=fen,
        messages=messages,
        won_count=0  # Can be calculated from thread data if needed
    )


@mail_bp.route("/api/fetch-threads", methods=["POST"])
def fetch_threads():
    """API endpoint to fetch last X new threads"""
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
    """API endpoint to sync existing threads with new emails"""
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
    """API endpoint to get updated thread list"""
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
    """API endpoint to get updated messages for a specific thread"""
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
    """API endpoint to export conversation as formatted text to terminal"""
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
            temperature=1.3,  # Kreativitet (0-2, lavere = mere forudsigeligt)
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
    """API endpoint to clear all mail-related data from database for current user"""
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
    """API endpoint to update labels for all messages in a thread (local only)"""
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
    """Debug endpoint to view raw message HTML"""
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
    """API endpoint to get all custom labels for current user"""
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
    """API endpoint to create a new custom label"""
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
    """API endpoint to delete a custom label"""
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
