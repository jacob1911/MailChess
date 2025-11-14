from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone

db = SQLAlchemy()

# --- Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    google_id = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120))
    picture = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    threads = db.relationship('Thread', backref='user', lazy=True)
    messages = db.relationship('Message', backref='user', lazy=True)


class Thread(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gmail_thread_id = db.Column(db.String(255), unique=True, nullable=False)
    subject = db.Column(db.String(500))
    snippet = db.Column(db.String(500))
    fen = db.Column(db.String(100))  # Current chess position (FEN)
    game_result = db.Column(db.String(10))  # '1-0', '0-1', '1/2-1/2', or None
    last_updated = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    messages = db.relationship("Message", backref="thread", lazy=True)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    gmail_message_id = db.Column(db.String(255), unique=True, nullable=False)
    thread_id = db.Column(db.Integer, db.ForeignKey("thread.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    sender = db.Column(db.String(120))
    recipient = db.Column(db.String(120))
    date = db.Column(db.DateTime)
    subject = db.Column(db.String(500))
    body_plain = db.Column(db.Text)
    body_html = db.Column(db.Text)
    in_reply_to = db.Column(db.String(255))
    references = db.Column(db.Text)
    label_ids = db.Column(db.String(255))
    move = db.Column(db.String(20), nullable=True)  # Chess move in UCI format
    evaluation_score = db.Column(db.Integer, nullable=True)  # Stockfish centipawn evaluation


class CustomLabel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(50), nullable=False)  # Label name (e.g., "WORK", "PERSONAL")
    display_name = db.Column(db.String(100), nullable=False)  # Display name (e.g., "Work", "Personal")
    icon_path = db.Column(db.String(255))  # Path to uploaded icon file
    color = db.Column(db.String(7), default="#6B7280")  # Hex color code
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Ensure unique label names per user
    __table_args__ = (db.UniqueConstraint('user_id', 'name', name='_user_label_uc'),)