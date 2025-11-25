# mail_stats.py
# Minimal Flask app factory and a mail_stats route. Adapt to your existing code.
# If you already have a Flask app, integrate the route function below instead.

from flask import Flask, render_template
from collections import Counter

def get_emails():
    # Replace this with your actual data access (database / files / existing code)
    # Example structure:
    return [
        {"id": 1, "sender": "alice@example.com", "receiver": "bob@example.com", "read": True},
        {"id": 2, "sender": "bob@example.com", "receiver": "alice@example.com", "read": False},
        {"id": 3, "sender": "alice@example.com", "receiver": "carol@example.com", "read": True},
    ]

def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/mail_stats')
    def mail_stats():
        emails = get_emails()
        total = len(emails)
        read_count = sum(1 for e in emails if e.get('read'))
        unread_count = total - read_count

        senders = Counter(e.get('sender') for e in emails if e.get('sender'))
        receivers = Counter(e.get('receiver') for e in emails if e.get('receiver'))

        most_sender = senders.most_common(1)[0] if senders else ('N/A', 0)
        most_receiver = receivers.most_common(1)[0] if receivers else ('N/A', 0)

        return render_template(
            'mail_stats.html',
            total=total,
            read=read_count,
            unread=unread_count,
            most_sender=most_sender,
            most_receiver=most_receiver
        )

    return app