from collections import Counter
from flask import Blueprint, render_template

mail_stats_bp = Blueprint('mail_stats', __name__)

# Dummy data: replace with actual mail data fetching logic
emails = [
    {"id": 1, "sender": "alice@example.com", "receiver": "bob@example.com", "read": True},
    {"id": 2, "sender": "bob@example.com", "receiver": "alice@example.com", "read": False},
    # ... more emails
]

@mail_stats_bp.route('/mail_stats')
def mail_stats():
    total = len(emails)
    read_count = sum(email['read'] for email in emails)
    unread_count = total - read_count

    senders = Counter([email['sender'] for email in emails])
    receivers = Counter([email['receiver'] for email in emails])

    most_sent_sender = senders.most_common(1)[0] if senders else ('N/A', 0)
    most_sent_receiver = receivers.most_common(1)[0] if receivers else ('N/A', 0)

    return render_template(
        'mail_stats.html',
        total=total,
        read=read_count,
        unread=unread_count,
        most_sender=most_sent_sender,
        most_receiver=most_sent_receiver
    )