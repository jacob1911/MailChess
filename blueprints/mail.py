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
import random
import email.utils  # <--- CRITICAL FIX: Needed for contact autocomplete

mail_bp = Blueprint('mail', __name__)

# Helper function for file uploads
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Register Jinja2 filter for cleaning message bodies
@mail_bp.app_template_filter('clean_body')
def clean_body_filter(body, is_html=False):
    return clean_message_body(body, is_html)


@mail_bp.route("/", methods=["GET", "POST"])
@mail_bp.route("/inbox", methods=["GET", "POST"])
def inbox():
    if session.get("user") is None:
        return redirect(url_for("auth.auth_login_page"))

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    # Get all threads for this user, sorted by newest message first
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

    # Determine who is "me" and who is "other" from messages
    messages = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).all()
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
        body = request.form.get("body", "")
        move_uci = request.form.get("move")
        is_html = request.form.get("is_html") == "true"

        if not other:
            flash("No recipient found for this thread", "error")
            return redirect(url_for("mail.thread", thread_id=thread_id))

        new_fen, game_result, game_over, evaluation_score = process_move(fen, move_uci)

        update_thread_fen(thread.id, new_fen)
        thread.last_updated = datetime.now(timezone.utc)

        if game_over:
            thread.game_result = game_result
            flash(f"Game over! Result: {game_result}", "info")

        db.session.commit()

        last_message = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.desc()).first()
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
                    evaluation_score=evaluation_score
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
    threads = db.session.query(Thread)\
        .filter(Thread.user_id == user_id)\
        .outerjoin(Message, Thread.id == Message.thread_id)\
        .group_by(Thread.id)\
        .order_by(func.max(Message.date).desc())\
        .all()

    thread_list = []
    for t in threads:
        all_labels = set()
        latest_message_date = None
        other_person = None

        for msg in t.messages:
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
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")

    thread = Thread.query.get_or_404(thread_id)

    if thread.user_id != user_id:
        return jsonify({"error": "Unauthorized"}), 403

    messages = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).all()

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

    messages = Message.query.filter_by(thread_id=thread.id).order_by(Message.date.asc()).all()

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
        for msg in thread.messages:
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