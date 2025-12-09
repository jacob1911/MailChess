from flask import Blueprint, render_template, session, redirect, url_for
from models import db, Message
from sqlalchemy import func
from collections import Counter
import re

stats_bp = Blueprint('stats', __name__)

# Common words to ignore (Stop words) - Danish and English mixed
STOP_WORDS = {
    'the', 'and', 'a', 'to', 'of', 'in', 'i', 'is', 'that', 'it', 'for', 'you', 'on',
    'er', 'det', 'at', 'jeg', 'en', 'til', 'af', 'med', 'og', 'for', 'ikke', 'der',
    'som', 'på', 'de', 'var', 'mig', 'vi', 'du', 'har', 'om', 'et', 'ja', 'nej',
    'move', 'træk', 'game', 'spil', 'chess', 'skak', 're', 'fwd', 'subject', 'fra', 'dato',
    'den', 'min', 'din', 'mit', 'dit', 'hvad', 'hvor', 'hvorfor', 'hvordan', 'hvem',
    'vil', 'kan', 'skal', 'må', 'burde', 'kunne', 'ville', 'skulle', 'måtte', 'bør',
    'så', 'nu', 'her', 'der', 'lidt', 'meget', 'mange', 'få', 'alt', 'intet',
    'bare', 'kun', 'nok', 'vist', 'jo', 'vel', 'vist', 'sgu', 'dog', 'da'
}

# --- CONFIGURATION: Add your list of "slurs" or bad words here ---
# WARNING: This list is case-insensitive.
BAD_WORDS_LIST = {
    "idiot", "stupid", "fjols", "taber", "skod", "lort", "fuck", "sgu", "helvede", "pik", "fisse", "bøsse", "luder", "nigga", "nigger", "spick", "gayboy"
    # Add the specific words you want to track here
}

def analyze_text(messages):
    """Helper to analyze word usage, starters, and specific bad words"""
    word_counter = Counter()
    starter_counter = Counter()
    bad_word_counter = Counter()

    for msg in messages:
        # Prefer plain text, fallback to stripped HTML
        body = msg.body_plain or ""
        if not body and msg.body_html:
            # Simple strip tags if plain is missing
            body = re.sub(r'<[^>]+>', ' ', msg.body_html) # Replace tags with space
        
        if not body:
            continue

        # Normalize whitespace
        body = re.sub(r'\s+', ' ', body).strip()
        
        # 1. Analyze Starters (First line or first few words)
        # Remove "On ... wrote:" headers if they exist at the top (simple check)
        if not body.lower().startswith('on ') and not body.startswith('>'):
            # Get the first 2-3 words as the "Starter"
            words = body.split()[:3]
            if words:
                starter = " ".join(words).strip(',.:')
                # Keep starter reasonable length and not just a name
                if len(starter) > 2:
                    starter_counter[starter] += 1

        # 2. Analyze Words & Slurs
        # Lowercase and extract words, ignoring punctuation
        words = re.findall(r'\w+', body.lower())
        
        for word in words:
            # Count Bad Words
            if word in BAD_WORDS_LIST:
                bad_word_counter[word] += 1
            
            # Count Normal Words (filter stop words, short words, and bad words)
            if word not in STOP_WORDS and len(word) > 2 and word not in BAD_WORDS_LIST and not word.isdigit():
                word_counter[word] += 1

    return {
        'top_words': word_counter.most_common(10),
        'top_starters': starter_counter.most_common(5),
        'top_bad_words': bad_word_counter.most_common(10)
    }

@stats_bp.route("/")
def index():
    # Ensure user is logged in
    if session.get("user") is None:
        return redirect(url_for("auth.auth_login_page"))

    user = session.get("user")
    user_id = user.get("id")
    user_email = user.get("email")

    # --- Standard Stats ---
    total_emails = Message.query.filter_by(user_id=user_id).count()
    
    # Check if 'UNREAD' is in label_ids (simple string check)
    unread_emails = Message.query.filter(
        Message.user_id == user_id,
        Message.label_ids.like('%UNREAD%')
    ).count()
    
    read_emails = total_emails - unread_emails

    # Top Sender
    most_sent_sender = db.session.query(
        Message.sender, func.count(Message.sender)
    ).filter(
        Message.user_id == user_id,
        Message.sender != user_email # Exclude self
    ).group_by(Message.sender).order_by(
        func.count(Message.sender).desc()
    ).first()

    # Top Recipient (from messages sent by you)
    most_sent_receiver = db.session.query(
        Message.recipient, func.count(Message.recipient)
    ).filter(
        Message.user_id == user_id,
        Message.sender == user_email # Only messages sent by you
    ).group_by(Message.recipient).order_by(
        func.count(Message.recipient).desc()
    ).first()

    sender_stat = most_sent_sender if most_sent_sender else ("Ingen", 0)
    receiver_stat = most_sent_receiver if most_sent_receiver else ("Ingen", 0)

    # --- Text Analysis (ALL emails in database) ---
    all_messages = Message.query.filter_by(user_id=user_id).all()

    text_stats = analyze_text(all_messages)

    # Also get stats for just sent messages for comparison
    sent_messages = Message.query.filter_by(user_id=user_id, sender=user_email).all()
    sent_text_stats = analyze_text(sent_messages)

    return render_template(
        "mail_stats.html",
        total=total_emails,
        read=read_emails,
        unread=unread_emails,
        most_sender=sender_stat,
        most_receiver=receiver_stat,
        # Pass stats for ALL messages
        top_words=text_stats['top_words'],
        top_starters=text_stats['top_starters'],
        top_bad_words=text_stats['top_bad_words'],
        # Pass stats for SENT messages
        sent_top_words=sent_text_stats['top_words'],
        sent_top_starters=sent_text_stats['top_starters'],
        sent_top_bad_words=sent_text_stats['top_bad_words'],
        total_analyzed=len(all_messages),
        sent_count=len(sent_messages)
    )