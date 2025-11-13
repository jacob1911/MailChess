"""
Mail Blueprint - Refactored to follow SOLID principles
Separated concerns into services and smaller route modules
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from models import db, CustomLabel
from services.thread_service import ThreadService
from services.label_service import LabelService
from services.email_service import EmailService
from services.summary_service import SummaryService
from utils.chess_utils import get_or_create_fen, process_move, update_thread_fen
from utils.gmail_api import send_email_via_api
import chess

mail_bp = Blueprint('mail', __name__)

# Initialize services (Dependency Injection pattern)
thread_service = ThreadService()
label_service = LabelService()
email_service = EmailService()


def get_summary_service():
    """Factory method for SummaryService (lazy initialization)"""
    return SummaryService()


# === PAGE ROUTES ===

@mail_bp.route("/", methods=["GET", "POST"])
@mail_bp.route("/inbox", methods=["GET", "POST"])
def inbox():
    """Display inbox page with email threads"""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    # Handle POST: Create new thread
    if request.method == "POST":
        new_mail = request.form.get("new_mail")
        subject = request.form.get("subject")

        if new_mail and subject:
            # Get or create FEN for new game
            fen = get_or_create_fen(None)

            # Create thread
            thread = thread_service.create_thread(
                user_id=user_id,
                subject=subject,
                fen=fen
            )

            return redirect(url_for("mail.thread", thread_id=thread.id))
        else:
            flash("Please provide both recipient and subject", "error")

    # Get threads for user
    threads = thread_service.get_threads_for_user(user_id, user_email)

    # Get custom labels
    custom_labels = label_service.get_user_labels(user_id)

    return render_template("inbox.html", user=user, threads=threads, custom_labels=custom_labels)


@mail_bp.route("/thread/<int:thread_id>", methods=["GET", "POST"])
def thread(thread_id):
    """Display individual thread page"""
    if session.get("user") is None:
        return redirect(url_for("auth.login"))

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    # Get thread and verify ownership
    thread_obj = thread_service.get_thread_by_id(thread_id, user_id)
    if not thread_obj:
        flash("Thread not found", "error")
        return redirect(url_for("mail.inbox"))

    # Handle POST: Send reply
    if request.method == "POST":
        body = request.form.get("body")
        move_uci = request.form.get("move")
        is_html = request.form.get("is_html") == "true"

        if not body:
            flash("Message body is required", "error")
            return redirect(url_for("mail.thread", thread_id=thread_id))

        # Process chess move if provided
        fen = thread_obj.fen
        if move_uci:
            fen, error = process_move(fen, move_uci)
            if error:
                flash(f"Invalid move: {error}", "error")
                return redirect(url_for("mail.thread", thread_id=thread_id))

        # Send email
        access_token = session.get("access_token")
        recipient = thread_obj.messages[0].sender if thread_obj.messages else None

        if not recipient:
            flash("No recipient found", "error")
            return redirect(url_for("mail.thread", thread_id=thread_id))

        try:
            send_email_via_api(
                access_token=access_token,
                to_email=recipient,
                subject=thread_obj.subject,
                body=body,
                is_html=is_html,
                thread_id=thread_obj.gmail_thread_id
            )

            # Update thread FEN
            update_thread_fen(thread_obj.id, fen)

            flash("Message sent successfully", "success")
        except Exception as e:
            flash(f"Failed to send message: {str(e)}", "error")

        return redirect(url_for("mail.thread", thread_id=thread_id))

    # GET: Render thread page
    # Find other participant
    other = None
    for msg in thread_obj.messages:
        if msg.sender and msg.sender != user_email:
            other = msg.sender
            break
        elif msg.recipient and msg.recipient != user_email:
            other = msg.recipient
            break

    # Count won games (placeholder)
    won_count = 0

    return render_template(
        "thread.html",
        user=user,
        thread=thread_obj,
        fen=thread_obj.fen,
        me=user_email,
        other=other,
        won_count=won_count
    )


# === EMAIL API ROUTES ===

@mail_bp.route("/api/fetch-threads", methods=["POST"])
def api_fetch_threads():
    """API: Fetch new threads from Gmail"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    access_token = session.get("access_token")

    count = request.json.get("count", 5) if request.json else 5

    result = email_service.fetch_new(
        user_id=user.get("id"),
        user_email=user.get("email"),
        access_token=access_token,
        count=count
    )

    return jsonify(result), 200 if result["success"] else 500


@mail_bp.route("/api/sync", methods=["POST"])
@mail_bp.route("/api/sync-existing", methods=["POST"])
def api_sync():
    """API: Sync existing threads with Gmail"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    access_token = session.get("access_token")

    result = email_service.sync_existing(
        user_id=user.get("id"),
        user_email=user.get("email"),
        access_token=access_token
    )

    return jsonify(result), 200 if result["success"] else 500


# === THREAD API ROUTES ===

@mail_bp.route("/api/threads", methods=["GET"])
def api_get_threads():
    """API: Get all threads for user"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    threads = thread_service.get_threads_for_user(user_id, user_email)

    # Format threads for API
    thread_list = []
    for t in threads:
        all_labels = set()
        for msg in t.messages:
            if msg.label_ids:
                all_labels.update(label.strip() for label in msg.label_ids.split(','))

        thread_list.append({
            "id": t.id,
            "subject": t.subject,
            "snippet": t.snippet,
            "labels": list(all_labels),
            "last_updated": t.latest_message_date.isoformat() if t.latest_message_date else None,
            "other_person": t.other_person
        })

    return jsonify({"success": True, "threads": thread_list}), 200


@mail_bp.route("/api/thread/<int:thread_id>/messages", methods=["GET"])
def api_get_messages(thread_id):
    """API: Get messages for a thread"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user_id = session.get("user").get("id")

    # Verify ownership
    thread = thread_service.get_thread_by_id(thread_id, user_id)
    if not thread:
        return jsonify({"error": "Unauthorized"}), 403

    # Get messages
    messages = thread_service.get_thread_messages(thread_id)

    # Format messages
    message_list = [thread_service.format_message_for_api(msg) for msg in messages]

    return jsonify({
        "success": True,
        "messages": message_list,
        "fen": thread.fen,
        "count": len(message_list)
    }), 200


@mail_bp.route("/api/thread/<int:thread_id>/export", methods=["POST"])
def api_export_conversation(thread_id):
    """API: Export conversation and generate AI summary"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user_id = session.get("user").get("id")

    # Verify ownership
    thread = thread_service.get_thread_by_id(thread_id, user_id)
    if not thread:
        return jsonify({"error": "Unauthorized"}), 403

    # Get messages
    messages = thread_service.get_thread_messages(thread_id)

    # Generate summary
    summary_service = get_summary_service()
    result = summary_service.generate_summary(messages, thread.subject)

    if result["success"]:
        result["message_count"] = len(messages)

    return jsonify(result), 200 if result["success"] else 500


@mail_bp.route("/api/clear-database", methods=["POST"])
def api_clear_database():
    """API: Clear all data for user"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user_id = session.get("user").get("id")

    stats = thread_service.clear_user_threads(user_id)
    stats["games_deleted"] = 0  # Placeholder

    return jsonify({"success": True, "stats": stats}), 200


# === LABEL API ROUTES ===

@mail_bp.route("/api/custom-labels", methods=["GET"])
def api_get_custom_labels():
    """API: Get all custom labels for user"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user_id = session.get("user").get("id")
    labels = label_service.get_user_labels(user_id)

    label_list = [label_service.format_label_for_api(label) for label in labels]

    return jsonify({"success": True, "labels": label_list}), 200


@mail_bp.route("/api/custom-labels", methods=["POST"])
def api_create_custom_label():
    """API: Create a new custom label"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user_id = session.get("user").get("id")

    display_name = request.form.get('display_name')
    color = request.form.get('color', '#6B7280')
    icon_file = request.files.get('icon')

    label, error = label_service.create_label(user_id, display_name, color, icon_file)

    if error:
        return jsonify({"success": False, "error": error}), 400

    return jsonify({
        "success": True,
        "message": f"Label '{display_name}' created successfully",
        "label": label_service.format_label_for_api(label)
    }), 201


@mail_bp.route("/api/custom-labels/<int:label_id>", methods=["DELETE"])
def api_delete_custom_label(label_id):
    """API: Delete a custom label"""
    if session.get("user") is None:
        return jsonify({"error": "Not authenticated"}), 401

    user_id = session.get("user").get("id")

    success, error = label_service.delete_label(label_id, user_id)

    if not success:
        return jsonify({"success": False, "error": error}), 403 if "Unauthorized" in error else 404

    return jsonify({
        "success": True,
        "message": "Label deleted successfully"
    }), 200


# Note: Label toggle endpoint and debug endpoint removed for simplicity
# Can be re-added if needed
