from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, current_app
from datetime import datetime, timezone
from models import db, Thread, Message, User, CustomLabel
from utils.email_utils import fetch_new_threads, sync_existing_threads, clean_message_body
from utils.gmail_api import send_email_via_api, modify_message_labels
from utils.chess_utils import get_or_create_fen, process_move, update_thread_fen, get_position_evaluation, calculate_won_games
from werkzeug.utils import secure_filename
from openai import OpenAI
import chess
import os
import re
import random
import email.utils

mail_bp = Blueprint('mail', __name__)

# --- CONFIGURATION: Wheel of Fortune Rules ---
WHEEL_RULES = [
    # Action 1: Trash all UNREAD messages (Now sets status='Trashed' instead of delete)
    {'weight': 3, 'action': 'trash', 'target': 'UNREAD', 'description': 'Send alle ulæste e-mails til papirkurven!', 'icon': 'trash-alt', 'color': 'text-red-600'},
    
    # Action 2: Mark all STARRED messages as IMPORTANT
    {'weight': 5, 'action': 'label', 'target': 'STARRED', 'add_label': 'IMPORTANT', 'description': 'Alle stjernemarkerede e-mails får IMPORTANT!', 'icon': 'tag', 'color': 'text-blue-500'},
    
    # Action 3: Mark all INBOX messages as READ (remove UNREAD)
    {'weight': 5, 'action': 'label', 'target': 'INBOX', 'remove_label': 'UNREAD', 'description': 'Alle e-mails i indbakken markeres som læst!', 'icon': 'envelope-open', 'color': 'text-green-500'},
    
    # Action 4: No action
    {'weight': 10, 'action': 'none', 'target': None, 'description': 'Intet sker! (Du er heldig)', 'icon': 'hand-paper', 'color': 'text-gray-500'},
]
# ---------------------------------------------


# Helper function for file uploads
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip', 'pgn'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Register Jinja2 filter for cleaning message bodies
@mail_bp.app_template_filter('clean_body')
def clean_body_filter(body, is_html=False):
    return clean_message_body(body, is_html)


# --- UPDATED: Wheel of Fortune Logic Helpers (Local Only) ---
def _execute_wheel_action_logic(user_id, outcome):
    """
    Executes the action defined by the wheel outcome, updating ONLY the local database.
    """
    action = outcome['action']
    target_label = outcome.get('rule_target')
    add_label = outcome.get('add_label')
    remove_label = outcome.get('remove_label')
    
    messages_affected = 0
    
    if action == 'none':
        return 0

    # 1. Base query: filter by user and target label
    base_query = Message.query.filter(Message.user_id == user_id, Message.status == 'Active')
    
    if target_label:
         # Find messages that CURRENTLY have the target label
        base_query = base_query.filter(Message.label_ids.like(f"%{target_label}%"))

    messages_to_update = base_query.all()
    
    for msg in messages_to_update:
        updated_local = False
        
        if action == 'trash':
            # ACTION: TRASH (Sets status to Trashed)
            msg.status = 'Trashed'
            updated_local = True
        
        elif action == 'label':
            # ACTION: LABEL CHANGE (Local DB only)
            current_labels = set(l.strip() for l in msg.label_ids.split(',') if l.strip())

            if add_label and add_label not in current_labels:
                current_labels.add(add_label)
                updated_local = True
                
            if remove_label and remove_label in current_labels:
                current_labels.discard(remove_label)
                updated_local = True
                
            if updated_local:
                msg.label_ids = ','.join(sorted(current_labels))

        # 2. Commit local changes
        if updated_local:
            messages_affected += 1
            
    db.session.commit()
    return messages_affected


@mail_bp.route("/api/spin-wheel", methods=["POST"])
def spin_wheel():
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    # 1. Randomly select a rule based on weight
    weights = [rule['weight'] for rule in WHEEL_RULES]
    chosen_rule = random.choices(WHEEL_RULES, weights=weights, k=1)[0]
    
    # 2. Calculate impact
    target_count = 0
    # ONLY COUNT ACTIVE MESSAGES
    query = Message.query.filter(Message.user_id == user_id, Message.status == 'Active')

    if chosen_rule['action'] != 'none' and chosen_rule['target']:
        target_count = query.filter(Message.label_ids.like(f"%{chosen_rule['target']}%")).count()
    
    # 3. Construct the final outcome dictionary
    outcome = {
        'action': chosen_rule['action'],
        'rule_target': chosen_rule.get('target'),
        'description': chosen_rule['description'],
        'target_count': target_count,
        'icon': chosen_rule['icon'],
        'color': chosen_rule['color'],
        'add_label': chosen_rule.get('add_label'),
        'remove_label': chosen_rule.get('remove_label'),
    }

    return jsonify({"success": True, "outcome": outcome}), 200


@mail_bp.route("/api/execute-wheel-action", methods=["POST"])
def execute_wheel_action():
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")
    outcome = request.get_json()

    if not outcome:
        return jsonify({"success": False, "error": "Invalid outcome data."}), 400

    try:
        # EXECUTE LOGIC (Purely local database update)
        messages_affected = _execute_wheel_action_logic(user_id, outcome)

        return jsonify({
            "success": True, 
            "message": f"Action completed. {messages_affected} messages affected.", 
            "messages_affected": messages_affected
        }), 200

    except Exception as e:
        return jsonify({"success": False, "error": f"Execution failed: {str(e)}"}), 500
# ---------------------------------------------------


# --- UPDATED: Standard Inbox Route (Only fetch Active messages) ---
@mail_bp.route("/", methods=["GET", "POST"])
@mail_bp.route("/inbox", methods=["GET", "POST"])
def inbox():
    if session.get("user") is None:
        return redirect(url_for("auth.auth_login_page"))

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    # GET THREADS FILTERED BY MESSAGES WITH STATUS = 'Active'
    from sqlalchemy import func
    threads = db.session.query(Thread)\
        .filter(Thread.user_id == user_id)\
        .outerjoin(Message, Thread.id == Message.thread_id)\
        .filter(Message.status == 'Active') \
        .group_by(Thread.id)\
        .order_by(func.max(Message.date).desc())\
        .all()

    # Get all custom labels for this user
    custom_labels = CustomLabel.query.filter_by(user_id=user_id).all()

    # Enrich threads with latest_message_date and other_person
    for thread in threads:
        thread.latest_message_date = None
        thread.other_person = None
        
        # Only check active messages for enrichment
        active_messages = Message.query.filter_by(thread_id=thread.id, status='Active').all()

        for msg in active_messages:
            if msg.date:
                if thread.latest_message_date is None or msg.date > thread.latest_message_date:
                    thread.latest_message_date = msg.date

            if not thread.other_person:
                if msg.sender and msg.sender != user_email:
                    thread.other_person = msg.sender
                elif msg.recipient and msg.recipient != user_email:
                    thread.other_person = msg.recipient
                    
        # Update snippet if no active messages remain (should not happen if thread exists, but good safety)
        if not active_messages:
             thread.snippet = "Papirkurv"
             
    if request.method == "POST":
        # Handle new thread creation
        new_mail = request.form.get("new_mail")
        subject = request.form.get("subject")

        if new_mail and subject:
            import time
            temp_thread_id = f"temp_{user_id}_{int(time.time() * 1000)}"

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


# --- NEW: Trash Bin Route ---
@mail_bp.route("/trash")
def trash():
    if session.get("user") is None:
        return redirect(url_for("auth.auth_login_page"))

    user = session.get("user")
    user_id = user.get("id")

    # Get all messages with status='Trashed'
    trashed_messages = Message.query.filter_by(user_id=user_id, status='Trashed').order_by(Message.date.desc()).all()
    
    # We group trashed messages by subject/sender for cleaner display
    trashed_list = []
    
    # A set to track unique gmail_message_id being shown (in case of duplicates)
    seen_message_ids = set() 
    
    for msg in trashed_messages:
        if msg.gmail_message_id in seen_message_ids:
            continue
            
        seen_message_ids.add(msg.gmail_message_id)

        trashed_list.append({
            'id': msg.id,
            'subject': msg.subject,
            'sender': msg.sender,
            'date': msg.date.strftime('%d/%m/%y %H:%M') if msg.date else 'Ukendt dato',
            'snippet': clean_message_body(msg.body_plain or msg.body_html, is_html=bool(msg.body_html))[:100] + '...'
        })

    return render_template("trash.html", trashed_messages=trashed_list, user=user)


# --- NEW: Trash Bin Restore API ---
@mail_bp.route("/api/trash/restore/<int:message_id>", methods=["POST"])
def trash_restore(message_id):
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401
    
    user = session.get("user")
    user_id = user.get("id")
    
    msg = Message.query.filter_by(id=message_id, user_id=user_id, status='Trashed').first()
    
    if not msg:
        return jsonify({"success": False, "error": "Message not found in trash"}), 404
        
    try:
        # Change status back to Active
        msg.status = 'Active'
        db.session.commit()
        return jsonify({"success": True, "message": "Message restored to inbox."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# --- NEW: Trash Bin Purge API (Local permanent delete) ---
@mail_bp.route("/api/trash/purge/<int:message_id>", methods=["POST"])
def trash_purge(message_id):
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401
    
    user = session.get("user")
    user_id = user.get("id")
    
    msg = Message.query.filter_by(id=message_id, user_id=user_id, status='Trashed').first()
    
    if not msg:
        return jsonify({"success": False, "error": "Message not found in trash"}), 404
        
    try:
        # PERMANENT LOCAL DELETE
        db.session.delete(msg)
        db.session.commit()
        return jsonify({"success": True, "message": "Message permanently purged."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# --- UPDATED: Thread Route (Only show Active messages) ---
@mail_bp.route("/thread/<int:thread_id>", methods=["GET", "POST"])
def thread(thread_id):
    if session.get("user") is None:
        return redirect(url_for("auth.auth_login_page"))

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

    # Filter messages to include ONLY active ones
    messages = Message.query.filter_by(thread_id=thread.id, status='Active').order_by(Message.date.asc()).all()
    me = user_email
    other = None

    if messages:
        for msg in messages:
            if msg.sender != user_email:
                other = msg.sender
                break
            elif msg.recipient != user_email:
                other = msg.recipient
                break
    else:
        session_key = f'thread_{thread.id}_recipient'
        if session_key in session:
            other = session.get(session_key)

    if session.get("current_subject"):
        thread_subject = session.get("current_subject")
    else:
        thread_subject = thread.subject
    session.pop("current_subject", None)

    if request.method == "POST":
        # ... (POST logic remains unchanged, but relies on active messages)
        body = request.form.get("body", "")
        move_uci = request.form.get("move")
        is_html = request.form.get("is_html") == "true"

        if not other:
            flash("No recipient found for this thread", "error")
            return redirect(url_for("mail.thread", thread_id=thread_id))

        # --- UPDATED: Handle Attachments ---
        attachments = []
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            for file in files:
                if file and file.filename:
                    if allowed_file(file.filename):
                        attachments.append(file)
                    else:
                        flash(f"Filtype ikke tilladt: {file.filename}", "warning")
        # -----------------------------------

        new_fen, game_result, game_over, evaluation_score = process_move(fen, move_uci)

        update_thread_fen(thread.id, new_fen)
        thread.last_updated = datetime.now(timezone.utc)

        if game_over:
            thread.game_result = game_result
            flash(f"Game over! Result: {game_result}", "info")

        db.session.commit()

        # Last message is now filtered by status='Active' for accurate reference
        last_message = Message.query.filter_by(thread_id=thread.id, status='Active').order_by(Message.date.desc()).first()
        in_reply_to = None
        references = None
        gmail_thread_id = thread.gmail_thread_id if not thread.gmail_thread_id.startswith("temp_") else None

        if last_message and last_message.in_reply_to:
            in_reply_to = last_message.in_reply_to
            if last_message.references:
                references = f"{last_message.references} {last_message.in_reply_to}"
            else:
                references = last_message.in_reply_to

        reply_subject = thread_subject
        if last_message:
            if not thread_subject.lower().startswith("re:"):
                reply_subject = f"Re: {thread_subject}"

        try:
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

            # --- UPDATED: Pass attachments to API ---
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
                attachments=attachments  # <--- Attachment list passed here
            )
            # ----------------------------------------

            if result and result.get('gmail_message_id'):
                if thread.gmail_thread_id.startswith("temp_") and result.get('thread_id'):
                    thread.gmail_thread_id = result['thread_id']
                    db.session.commit()

                import re
                if is_html:
                    snippet_text = re.sub(r'<[^>]+>', '', body)
                    snippet_text = re.sub(r'\s+', ' ', snippet_text).strip()
                else:
                    snippet_text = body.strip()
                thread.snippet = snippet_text[:200]
                thread.last_updated = datetime.now(timezone.utc)

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
                    evaluation_score=evaluation_score,
                    status='Active' # New sent message defaults to Active
                )
                db.session.add(msg)
                db.session.commit()

                session_key = f'thread_{thread.id}_recipient'
                if session_key in session:
                    session.pop(session_key)

                flash("Besked sendt!", "success")
            else:
                flash("Email sent but couldn't save to database", "warning")

        except Exception as e:
            flash(f"Fejl ved afsendelse: {str(e)}", "error")

        return redirect(url_for("mail.thread", thread_id=thread_id))

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
        evaluation=current_evaluation['score']
    )


@mail_bp.route("/api/fetch-threads", methods=["POST"])
def fetch_threads():
    # ... (content remains the same, no status filtering needed here)
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

    data = request.get_json()
    count = int(data.get('count', 5))

    try:
        stats = fetch_new_threads(user_id, user_email, access_token, count)

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
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    from sqlalchemy import func
    # UPDATED QUERY: Filter messages by status = 'Active'
    threads = db.session.query(Thread)\
        .filter(Thread.user_id == user_id)\
        .outerjoin(Message, Thread.id == Message.thread_id)\
        .filter(Message.status == 'Active') \
        .group_by(Thread.id)\
        .order_by(func.max(Message.date).desc())\
        .all()

    thread_list = []
    for t in threads:
        all_labels = set()
        latest_message_date = None
        other_person = None
        
        # Only iterate over active messages for display data
        active_messages = Message.query.filter_by(thread_id=t.id, status='Active').all()

        for msg in active_messages:
            if msg.label_ids:
                labels = [label.strip() for label in msg.label_ids.split(',') if label.strip()]
                all_labels.update(labels)

            if msg.date:
                if latest_message_date is None or msg.date > latest_message_date:
                    latest_message_date = msg.date

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
            "message_count": len(active_messages),
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
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)

    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    # UPDATED QUERY: Filter messages by status = 'Active'
    messages = Message.query.filter_by(thread_id=thread.id, status='Active').order_by(Message.date.asc()).all()

    message_list = []
    for msg in messages:
        body = msg.body_html if msg.body_html else msg.body_plain
        is_html = bool(msg.body_html)

        message_list.append({
            "id": msg.id,
            "sender": msg.sender,
            "recipient": msg.recipient,
            "body": body,
            "is_html": is_html,
            "move": msg.move,
            "timestamp": msg.date.isoformat() if msg.date else None
        })

    return jsonify({
        "success": True,
        "messages": message_list,
        "fen": thread.fen,
        "count": len(message_list)
    }), 200


@mail_bp.route("/api/thread/<int:thread_id>/export", methods=["POST"])
def export_conversation(thread_id):
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)

    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    # UPDATED QUERY: Filter messages by status = 'Active'
    messages = Message.query.filter_by(thread_id=thread.id, status='Active').order_by(Message.date.asc()).all()

    conversation_lines = []
    conversation_lines.append("=" * 80)
    conversation_lines.append(f"CONVERSATION: {thread.subject}")
    conversation_lines.append("=" * 80)
    conversation_lines.append("")

    for msg in messages:
        sender = msg.sender if msg.sender else "Unknown"
        timestamp = msg.date.strftime('%d/%m/%Y %H:%M:%S') if msg.date else "No date"

        if msg.body_plain:
            body = msg.body_plain
        elif msg.body_html:
            body = re.sub(r'<[^>]+>', '', msg.body_html)
            body = body.strip()
        else:
            body = "(No content)"

        conversation_lines.append(f"[{timestamp}] {sender}:")
        if msg.move:
            conversation_lines.append(f"  Move: {msg.move}")
        conversation_lines.append(f"  {body}")
        conversation_lines.append("")

    conversation_lines.append("=" * 80)
    conversation_lines.append(f"Total messages: {len(messages)}")
    conversation_lines.append("=" * 80)

    conversation_text = "\n".join(conversation_lines)
    print("\n\n" + conversation_text + "\n\n")

    openai_api_key = os.environ.get("OPENAI_API_KEY")

    if not openai_api_key:
        return jsonify({
            "success": False,
            "error": "OpenAI API key not configured"
        }), 500

    try:
        client = OpenAI(api_key=openai_api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",
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
            max_tokens=200,
            temperature=1.3,
            presence_penalty=0.5,
            frequency_penalty=0.0
        )

        summary = response.choices[0].message.content.strip()

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
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    try:
        messages_deleted = Message.query.filter_by(user_id=user_id).delete()
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
    print(f"[DEBUG] update_thread_labels called for thread {thread_id}")

    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)
    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    add_labels = data.get('add_labels', [])
    remove_labels = data.get('remove_labels', [])
    print(f"[DEBUG] Add labels: {add_labels}, Remove labels: {remove_labels}")

    if not add_labels and not remove_labels:
        return jsonify({"error": "No label modifications specified"}), 400

    try:
        updated_count = 0
        # UPDATED QUERY: Filter messages by status = 'Active'
        for msg in Message.query.filter_by(thread_id=thread_id, status='Active').all():
            current_labels = set()
            if msg.label_ids:
                current_labels = set(label.strip() for label in msg.label_ids.split(',') if label.strip())

            print(f"[DEBUG] Message {msg.id} - Current labels: {current_labels}")

            for label in add_labels:
                current_labels.add(label)

            for label in remove_labels:
                current_labels.discard(label)

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


@mail_bp.route("/api/threads/<int:thread_id>/toggle-label", methods=["POST"])
def toggle_thread_label(thread_id):
    """Toggle a label on all messages in a thread"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)
    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    label = data.get('label')
    
    if not label:
        return jsonify({"error": "No label specified"}), 400

    try:
        # Get all messages in thread (don't filter by status yet to debug)
        messages = Message.query.filter_by(thread_id=thread_id).all()
        
        updated_count = 0
        for msg in messages:
            # Skip trashed messages
            if msg.status != 'Active':
                continue
                
            current_labels = set()
            if msg.label_ids:
                current_labels = set(lbl.strip() for lbl in msg.label_ids.split(',') if lbl.strip())

            # Toggle: if present, remove; if absent, add
            if label in current_labels:
                current_labels.discard(label)
            else:
                current_labels.add(label)

            msg.label_ids = ','.join(sorted(current_labels)) if current_labels else ""
            updated_count += 1

        db.session.commit()
        return jsonify({"success": True, "message": f"Toggled label '{label}'", "updated": updated_count}), 200

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] toggle_thread_label: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@mail_bp.route("/api/threads/<int:thread_id>/mark-read", methods=["POST"])
def mark_thread_read(thread_id):
    """Mark all messages in a thread as read (remove UNREAD label)"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)
    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    try:
        # Get all messages in thread
        messages = Message.query.filter_by(thread_id=thread_id).all()
        
        updated_count = 0
        for msg in messages:
            # Skip trashed messages
            if msg.status != 'Active':
                continue
                
            current_labels = set()
            if msg.label_ids:
                current_labels = set(lbl.strip() for lbl in msg.label_ids.split(',') if lbl.strip())

            # Remove UNREAD label
            if 'UNREAD' in current_labels:
                current_labels.discard('UNREAD')
                msg.label_ids = ','.join(sorted(current_labels)) if current_labels else ""
                updated_count += 1

        db.session.commit()
        return jsonify({"success": True, "message": "Marked as read", "updated": updated_count}), 200

    except Exception as e:
        db.session.rollback()
        print(f"[ERROR] mark_thread_read: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@mail_bp.route("/debug/message/<int:message_id>", methods=["GET"])
def debug_message(message_id):
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    msg = Message.query.get_or_404(message_id)

    if msg.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    body = msg.body_html if msg.body_html else msg.body_plain
    is_html = bool(msg.body_html)

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
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    display_name = request.form.get('display_name')
    color = request.form.get('color', '#6B7280')

    if not display_name:
        return jsonify({"error": "Display name is required"}), 400

    name = display_name.upper().replace(' ', '_')

    existing = CustomLabel.query.filter_by(user_id=user_id, name=name).first()
    if existing:
        return jsonify({"error": f"Label '{display_name}' already exists"}), 400

    icon_path = None
    if 'icon' in request.files:
        file = request.files['icon']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            import time
            unique_filename = f"{user_id}_{int(time.time())}_{filename}"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)
            icon_path = f"/static/label_icons/{unique_filename}"

    try:
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
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    label = CustomLabel.query.get_or_404(label_id)
    if label.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    try:
        if label.icon_path:
            icon_file = os.path.join(current_app.root_path, label.icon_path.lstrip('/'))
            if os.path.exists(icon_file):
                os.remove(icon_file)

        label_name = label.name
        messages = Message.query.filter_by(user_id=user_id).all()
        for msg in messages:
            if msg.label_ids:
                labels = set(l.strip() for l in msg.label_ids.split(',') if l.strip())
                labels.discard(label_name)
                msg.label_ids = ','.join(sorted(labels)) if labels else ""

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

@mail_bp.route("/api/contacts", methods=["GET"])
def get_contacts():
    """
    API endpoint to fetch unique contacts (email addresses) for autocomplete.
    Returns a list of email addresses from messages the user has sent or received.
    """
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    # Fetch all distinct senders and recipients associated with this user's messages
    # We exclude the user's own email from the list
    
    # 1. Get all people who sent emails TO the user
    senders = db.session.query(Message.sender).filter(
        Message.user_id == user_id,
        Message.sender != user_email
    ).distinct().all()

    # 2. Get all people the user sent emails TO
    recipients = db.session.query(Message.recipient).filter(
        Message.user_id == user_id,
        Message.recipient != user_email
    ).distinct().all()

    # Combine and clean up the list
    contacts = set()
    
    for r in senders + recipients:
        # The result is a tuple (email,), extract the email
        if r and r[0]:
            # Simple cleanup to extract just the email if it's in "Name <email>" format
            # (Though your extract_email_address utility usually handles this before saving)
            name, addr = email.utils.parseaddr(r[0])
            # Use the address if valid, otherwise the raw string
            email_addr = addr if addr else r[0]
            
            if email_addr and email_addr != user_email:
                contacts.add(email_addr)

    return jsonify({
        "success": True,
        "contacts": sorted(list(contacts))
    }), 200