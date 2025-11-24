import imaplib
import smtplib
import email
import base64
import re
import chess
from email.mime.text import MIMEText
from email.utils import formataddr, parsedate_to_datetime, parseaddr
from models import db, Thread, Message, User
from html import escape
import html.parser
from datetime import datetime, timezone


def extract_email_address(email_header):
    """Extract just the email address from header like 'Name <email@example.com>'"""
    if not email_header:
        return None
    name, addr = parseaddr(email_header)
    return addr if addr else email_header


def sanitize_html(html_content):
    """Sanitize HTML content to allow safe formatting and images"""
    if not html_content:
        return ""

    try:
        import bleach

        # Allowed tags and attributes for rich formatting and images
        allowed_tags = ['p', 'br', 'b', 'strong', 'i', 'em', 'u', 'span', 'div',
                        'img', 'a', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
                        'blockquote', 'pre', 'code', 'hr', 'table', 'tr', 'td', 'th', 'tbody', 'thead']

        allowed_attrs = {
            '*': ['class', 'style'],
            'img': ['src', 'alt', 'width', 'height', 'class', 'style', 'title'],
            'a': ['href', 'title', 'target', 'rel'],
            'span': ['class', 'style'],
            'div': ['class', 'style', 'id'],
            'td': ['colspan', 'rowspan', 'class', 'style'],
            'th': ['colspan', 'rowspan', 'class', 'style']
        }

        # Allow data URIs for inline images, cid for Content-ID references, and common image CDNs
        # Note: cid: will be replaced with data: URIs before sanitization in most cases
        allowed_protocols = ['http', 'https', 'data', 'mailto', 'cid']

        return bleach.clean(
            html_content,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=allowed_protocols,
            strip=True
        )
    except ImportError:
        # If bleach is not available, return content as-is (less secure)
        return html_content


def clean_message_body(body, is_html=False):
    """Clean email body by removing quoted text and email chains"""
    if not body:
        return ""

    if is_html:
        # For HTML content, sanitize first to keep safe content
        body = sanitize_html(body)

        # Remove Gmail quoted text (usually in a div with class "gmail_quote")
        # This is a greedy match, so be careful
        body = re.sub(r'<div[^>]*class="[^"]*gmail_quote[^"]*"[^>]*>.*?</div>', '', body, flags=re.DOTALL | re.IGNORECASE)

        # More conservative: only remove the "On ... wrote:" line itself, not everything after
        body = re.sub(r'<div[^>]*>On\s+.+?wrote:\s*</div>', '', body, flags=re.IGNORECASE)

        # Also remove common email signature separators
        body = re.sub(r'<div[^>]*>--\s*</div>', '', body)

        # Remove blockquotes that are clearly quoted replies (but keep blockquotes with content)
        body = re.sub(r'<blockquote[^>]*class="[^"]*gmail_quote[^"]*"[^>]*>.*?</blockquote>', '', body, flags=re.DOTALL | re.IGNORECASE)

        # Remove Move: line from HTML (both in tags and standalone)
        body = re.sub(r'<p[^>]*>\s*Move:\s*[a-h][1-8][a-h][1-8][qrbn]?\s*</p>', '', body, flags=re.IGNORECASE)
        body = re.sub(r'<div[^>]*>\s*Move:\s*[a-h][1-8][a-h][1-8][qrbn]?\s*</div>', '', body, flags=re.IGNORECASE)
        body = re.sub(r'Move:\s*[a-h][1-8][a-h][1-8][qrbn]?', '', body, flags=re.IGNORECASE)

        # Clean up excessive whitespace but preserve structure
        body = re.sub(r'\n\s*\n\s*\n+', '\n\n', body)
        body = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', body, flags=re.IGNORECASE)

        return body.strip()

    # Plain text cleaning
    lines = body.split('\n')
    cleaned_lines = []
    skip_rest = False

    for line in lines:
        stripped = line.strip()

        # Skip quoted lines (starting with >)
        if stripped.startswith('>'):
            continue

        # Skip email chain headers (On ... wrote:)
        if re.search(r'On .+ wrote:', stripped):
            skip_rest = True
            continue

        # Skip lines with email signatures like <email@example.com>
        if re.search(r'<[\w\.-]+@[\w\.-]+\.\w+>', stripped):
            skip_rest = True
            continue

        # Skip lines that look like email headers with date/time
        if re.search(r'On \w+, \w+ \d+, \d{4} at', stripped):
            skip_rest = True
            continue

        # Skip the "Move: xxx" line as it's displayed separately
        if re.match(r'^Move:\s*[a-h][1-8][a-h][1-8]', stripped, re.IGNORECASE):
            continue

        # If we're past an email chain header, skip everything after
        if skip_rest:
            continue

        # Keep non-empty lines
        if stripped:
            cleaned_lines.append(stripped)

    return '\n'.join(cleaned_lines)


def get_body_from_msg(msg):
    """Extract body from email message, preferring HTML over plain text"""
    html_body = None
    plain_body = None
    is_html = False
    inline_images = {}

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_dispo = str(part.get("Content-Disposition"))

            # Handle inline images (cid: references)
            if content_type.startswith('image/'):
                content_id = part.get('Content-ID')
                if content_id:
                    # Remove < and > from Content-ID
                    content_id = content_id.strip('<>')
                    try:
                        image_data = part.get_payload(decode=True)
                        if image_data:
                            # Convert to base64 data URI
                            image_base64 = base64.b64encode(image_data).decode('utf-8')
                            mime_type = content_type
                            data_uri = f"data:{mime_type};base64,{image_base64}"
                            inline_images[content_id] = data_uri
                    except:
                        pass
                continue

            # Skip attachments but not inline content
            if "attachment" in content_dispo and "inline" not in content_dispo:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload:
                    decoded = payload.decode(part.get_content_charset() or "utf-8", errors='ignore')
                    if content_type == "text/html":
                        html_body = decoded
                    elif content_type == "text/plain":
                        plain_body = decoded
            except:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(msg.get_content_charset() or "utf-8", errors='ignore')
                if msg.get_content_type() == "text/html":
                    html_body = body
                else:
                    plain_body = body
        except:
            pass

    # Replace cid: references with data URIs in HTML
    if html_body and inline_images:
        for cid, data_uri in inline_images.items():
            html_body = html_body.replace(f"cid:{cid}", data_uri)

    # Prefer HTML over plain text
    if html_body:
        return html_body, True
    elif plain_body:
        return plain_body, False
    else:
        return "", False


def extract_chess_move(body):
    """Extract chess move from email body (format: Move: e2e4)"""
    if not body:
        return None

    # Search for "Move: " followed by chess move notation
    match = re.search(r'([a-h][1-8][a-h][1-8][qrbn]?)', body, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


def store_thread(user_id, thread_emails):
    """Store email thread in database with all its messages

    Args:
        user_id: ID of the user who owns this thread
        thread_emails: List of dicts with {'msg': email_message, 'gmail_thread_id': thread_id, 'gmail_message_id': message_id}
    """
    if not thread_emails:
        return None

    # Use first message as thread header
    first_email_data = thread_emails[0]
    first_msg = first_email_data['msg'] if isinstance(first_email_data, dict) else first_email_data

    # Extract Gmail thread ID from first message
    gmail_thread_id = first_email_data.get('gmail_thread_id') if isinstance(first_email_data, dict) else None

    if not gmail_thread_id:
        print("Warning: No Gmail thread ID found, cannot create thread")
        return None

    # Normalize subject (remove Re:, Fwd:, etc.)
    raw_subject = first_msg.get("Subject", "No Subject")
    normalized_subject = re.sub(r'^(Re:|Fwd:)\s*', '', raw_subject, flags=re.IGNORECASE).strip()

    # Check if thread already exists
    existing_thread = Thread.query.filter_by(
        gmail_thread_id=gmail_thread_id,
        user_id=user_id
    ).first()

    if existing_thread:
        new_thread = existing_thread
        # Update subject and last_updated
        new_thread.subject = normalized_subject
        new_thread.last_updated = datetime.now(timezone.utc)
    else:
        # Extract snippet from first message
        body, is_html = get_body_from_msg(first_msg)
        snippet = ""
        if body:
            if is_html:
                # Remove HTML tags
                snippet_text = re.sub(r'<[^>]+>', '', body)
                snippet_text = re.sub(r'\s+', ' ', snippet_text).strip()
            else:
                snippet_text = body.strip()
            snippet = snippet_text[:200]

        # Initialize FEN for new chess game
        board = chess.Board()

        new_thread = Thread(
            gmail_thread_id=gmail_thread_id,
            subject=normalized_subject,
            snippet=snippet,
            fen=board.fen(),
            user_id=user_id
        )
        db.session.add(new_thread)
        db.session.flush()

    # Loop over all messages in chronological order
    for email_data in thread_emails:
        # Handle both new dict format and old format for backwards compatibility
        if isinstance(email_data, dict):
            msg = email_data['msg']
            gmail_message_id = email_data.get('gmail_message_id')
        else:
            msg = email_data
            gmail_message_id = msg.get("Message-ID")  # Fallback to RFC Message-ID

        if not gmail_message_id:
            print(f"Warning: No Gmail message ID found for message, skipping")
            continue

        body, is_html = get_body_from_msg(msg)

        # Extract chess move from email body
        move_uci = extract_chess_move(body)

        # Extract email addresses
        msg_sender = extract_email_address(msg.get("From", ""))
        msg_recipient = extract_email_address(msg.get("To", ""))

        # Parse timestamp
        date_str = msg.get("Date")
        timestamp = None
        if date_str:
            try:
                timestamp = parsedate_to_datetime(date_str)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except:
                pass

        # Extract RFC 2822 email headers for proper threading
        in_reply_to = msg.get("In-Reply-To")
        references = msg.get("References")
        subject = msg.get("Subject", "")
        label_ids = ""  # Will be populated later if needed

        # Check if message already exists
        existing_msg = Message.query.filter_by(
            gmail_message_id=gmail_message_id,
            thread_id=new_thread.id
        ).first()

        if not existing_msg:
            new_message = Message(
                gmail_message_id=gmail_message_id,
                thread_id=new_thread.id,
                user_id=user_id,
                sender=msg_sender,
                recipient=msg_recipient,
                date=timestamp,
                subject=subject,
                body_plain=body if not is_html else "",
                body_html=body if is_html else "",
                in_reply_to=in_reply_to,
                references=references,
                label_ids=label_ids,
                move=move_uci
            )
            db.session.add(new_message)

            # Update thread FEN if move is found
            if move_uci and new_thread:
                update_thread_fen(new_thread, move_uci)

    db.session.commit()
    return new_thread.id


def update_thread_fen(thread, move_uci):
    """Update thread FEN with a chess move"""
    if not move_uci or not thread:
        return

    try:
        board = chess.Board(thread.fen)
        move = board.parse_uci(move_uci)

        if move in board.legal_moves:
            board.push(move)
            thread.fen = board.fen()

            # Check if game is over
            if board.is_game_over():
                result = board.result()
                print(f"Game over! Result: {result}")

        else:
            print(f"Illegal move attempted: {move_uci}")
    except Exception as e:
        print(f"Error updating FEN: {e}")

def smtp_send_email(user_email, access_token, to, subject, body):
    """Send email via Gmail SMTP with OAuth"""
    try:
        # Build proper XOAUTH2 string
        auth_string = f"user={user_email}\1auth=Bearer {access_token}\1\1"

        # Connect to SMTP server
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.set_debuglevel(0)  # Set to 1 for debugging
        server.ehlo()
        server.starttls()
        server.ehlo()

        # Authenticate with XOAUTH2
        server.docmd("AUTH", "XOAUTH2 " + base64.b64encode(auth_string.encode()).decode())

        # Create proper MIME message
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = formataddr(("MailChess", user_email))
        msg['To'] = to

        # Send email
        server.sendmail(user_email, [to], msg.as_string())
        server.quit()

    except smtplib.SMTPAuthenticationError as e:
        # Token might be expired or invalid
        error_msg = str(e)
        if "400" in error_msg or "invalid" in error_msg.lower():
            raise Exception(
                "OAuth token er ugyldig eller udløbet. Prøv at logge ud og ind igen."
            )
        raise Exception(f"SMTP Authentication fejl: {error_msg}")

    except smtplib.SMTPException as e:
        raise Exception(f"SMTP fejl ved afsendelse: {str(e)}")

    except Exception as e:
        raise Exception(f"Uventet fejl ved email afsendelse: {str(e)}")


def caesar_encrypt(text, shift=3):
    """Simple Caesar cipher encryption"""
    result = ""
    for char in text:
        if char.isalpha():
            base = ord('A') if char.isupper() else ord('a')
            result += chr((ord(char) - base + shift) % 26 + base)
        else:
            result += char
    return result


def caesar_decrypt(text, shift=3):
    """Simple Caesar cipher decryption"""
    return caesar_encrypt(text, -shift)


# Function to generate the Base64-encoded string for IMAP XOAUTH2 authentication
def generate_oauth2_string(user_email, access_token):
    auth_string = f'user={user_email}\1auth=Bearer {access_token}\1\1'
    return base64.b64encode(auth_string.encode('utf-8'))


def fetch_new_threads(user_id, user_email, access_token, count=5):
    """
    Fetch last X new email threads from Gmail that don't exist in local database
    Returns: dict with stats
    """
    stats = {
        'threads_fetched': 0,
        'messages_added': 0,
        'errors': []
    }

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", port=993)
        # Use helper to generate Base64-encoded XOAUTH2 auth string (bytes)
        auth_string = generate_oauth2_string(user_email, access_token)
        imap.authenticate("XOAUTH2", lambda x: auth_string)
        imap.select("INBOX")

        # Get all email IDs
        result, data = imap.search(None, 'X-GM-RAW "category:primary"')
        ids = data[0].split() if data[0] else []

        if not ids:
            imap.logout()
            return stats

        print(f"Found {len(ids)} emails in Gmail inbox")

        # Step 1: Collect all thread IDs with their latest email timestamp
        thread_timestamps = {}  # {gmail_thread_id: (mail_id, timestamp)}

        for mail_id in ids:
            try:
                # Only fetch metadata to find thread IDs and dates
                result, msg_data = imap.fetch(mail_id, "(X-GM-THRID INTERNALDATE)")
                if result != "OK" or not msg_data or not msg_data[0]:
                    continue

                gmail_thread_id = None
                timestamp = None

                # Parse metadata - msg_data[0] is the bytes string directly
                metadata_str = msg_data[0].decode() if isinstance(msg_data[0], bytes) else str(msg_data[0])

                # Extract thread ID
                match = re.search(r'X-GM-THRID (\d+)', metadata_str)
                if match:
                    gmail_thread_id = match.group(1)

                # Extract timestamp
                match = re.search(r'INTERNALDATE "([^"]+)"', metadata_str)
                if match:
                    timestamp = parsedate_to_datetime(match.group(1))

                if gmail_thread_id and timestamp:
                    # Keep track of the latest email in each thread
                    if gmail_thread_id not in thread_timestamps or timestamp > thread_timestamps[gmail_thread_id][1]:
                        thread_timestamps[gmail_thread_id] = (mail_id, timestamp)

            except Exception as e:
                stats['errors'].append(f"Error fetching thread metadata: {str(e)}")
                continue

        print(f"Found {len(thread_timestamps)} unique threads")

        # Step 2: Get existing thread IDs from database for this user
        existing_threads = Thread.query.filter_by(user_id=user_id).with_entities(Thread.gmail_thread_id).all()
        existing_thread_ids = set(thread.gmail_thread_id for thread in existing_threads)
        print(f"User has {len(existing_thread_ids)} existing threads in database")

        # Step 3: Filter out threads that already exist
        new_threads = {
            thread_id: data
            for thread_id, data in thread_timestamps.items()
            if thread_id not in existing_thread_ids
        }
        print(f"Found {len(new_threads)} new threads not in database")

        if not new_threads:
            imap.logout()
            print("No new threads to fetch")
            return stats

        # Step 4: Sort by timestamp (newest first) and take last X
        sorted_new_threads = sorted(new_threads.items(), key=lambda x: x[1][1], reverse=True)
        threads_to_fetch = sorted_new_threads[:count]
        print(f"Fetching {len(threads_to_fetch)} newest threads...")

        # Step 5: Fetch all emails for selected threads
        threads_by_gmail_id = {}

        # For each selected thread, find ALL emails with that thread ID
        for gmail_thread_id, (sample_mail_id, _) in threads_to_fetch:
            try:
                # Search for all emails with this thread ID
                result, data = imap.search(None, f'X-GM-THRID {gmail_thread_id}')
                thread_email_ids = data[0].split() if data[0] else []

                print(f"Thread {gmail_thread_id}: found {len(thread_email_ids)} emails")

                for mail_id in thread_email_ids:
                    try:
                        # Fetch full email with metadata
                        result, msg_data = imap.fetch(mail_id, "(RFC822 X-GM-THRID X-GM-MSGID)")
                        if result != "OK" or not msg_data or not msg_data[0]:
                            continue

                        # Extract data
                        gmail_message_id = None
                        raw = None
                        for item in msg_data:
                            if isinstance(item, tuple) and len(item) >= 2:
                                metadata = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                                if 'X-GM-MSGID' in metadata:
                                    match = re.search(r'X-GM-MSGID (\d+)', metadata)
                                    if match:
                                        gmail_message_id = match.group(1)
                                raw = item[1]
                                break

                        if not raw:
                            continue

                        msg = email.message_from_bytes(raw)

                        if gmail_thread_id not in threads_by_gmail_id:
                            threads_by_gmail_id[gmail_thread_id] = []

                        threads_by_gmail_id[gmail_thread_id].append({
                            'msg': msg,
                            'gmail_thread_id': gmail_thread_id,
                            'gmail_message_id': gmail_message_id
                        })

                    except Exception as e:
                        stats['errors'].append(f"Error fetching email in thread: {str(e)}")
                        continue

            except Exception as e:
                stats['errors'].append(f"Error fetching thread {gmail_thread_id}: {str(e)}")
                continue

        # Step 6: Store each thread
        for gmail_thread_id, messages in threads_by_gmail_id.items():
            # Sort by date
            def get_msg_date(email_data):
                try:
                    msg = email_data['msg'] if isinstance(email_data, dict) else email_data
                    date = msg.get("Date")
                    if date:
                        return parsedate_to_datetime(date)
                except:
                    pass
                return None

            messages.sort(key=get_msg_date)

            # Create new thread
            first_msg = messages[0]['msg']
            subject = first_msg.get("Subject", "No Subject")
            store_thread(user_id, messages)
            stats['threads_fetched'] += 1
            stats['messages_added'] += len(messages)
            print(f"Created new thread: {subject} ({len(messages)} messages)")

        imap.logout()
        print(f"Fetch completed: {stats}")

    except Exception as e:
        error_msg = f"IMAP error: {str(e)}"
        print(error_msg)
        stats['errors'].append(error_msg)

    return stats


def sync_existing_threads(user_id, user_email, access_token):
    """
    Sync existing threads with new emails from Gmail
    Returns: dict with stats
    """
    stats = {
        'threads_updated': 0,
        'messages_added': 0,
        'moves_parsed': 0,
        'errors': []
    }

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", port=993)
        # Use helper to generate Base64-encoded XOAUTH2 auth string (bytes)
        auth_string = generate_oauth2_string(user_email, access_token)
        imap.authenticate("XOAUTH2", lambda x: auth_string)
        imap.select("INBOX")

        # Get all existing threads from database for this user
        existing_threads = Thread.query.filter_by(user_id=user_id).all()

        print(f"Syncing {len(existing_threads)} existing threads...")

        for thread in existing_threads:
            try:
                # Normalize subject for search
                normalized_subject = re.sub(r'^(Re:|Fwd:)\s*', '', thread.subject, flags=re.IGNORECASE).strip()

                # Gmail's X-GM-THRID can't be used directly in IMAP SEARCH
                # Instead, we search by subject and filter by X-GM-THRID after fetching
                # This is actually more reliable than trying complex IMAP queries
                search_query = f'SUBJECT "{normalized_subject}"'

                if thread.gmail_thread_id:
                    print(f"Searching for thread (Gmail ID: {thread.gmail_thread_id[:16]}...) by subject: '{normalized_subject}'")
                else:
                    print(f"Searching for new thread by subject: '{normalized_subject}'")

                result, data = imap.search(None, search_query)

                if result != "OK" or not data[0]:
                    continue

                ids = data[0].split()
                print(f"Search found {len(ids)} emails")

                # Fetch all emails for this thread
                messages = []
                for mail_id in ids:
                    try:
                        # Fetch both email content, Gmail thread ID, and Gmail message ID
                        result, msg_data = imap.fetch(mail_id, "(RFC822 X-GM-THRID X-GM-MSGID)")
                        if result != "OK" or not msg_data or not msg_data[0]:
                            continue

                        # Extract Gmail thread ID and message ID from IMAP response
                        gmail_thread_id = None
                        gmail_message_id = None
                        raw = None
                        for item in msg_data:
                            if isinstance(item, tuple) and len(item) >= 2:
                                # First item is the metadata string, second is the message
                                metadata = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                                if 'X-GM-THRID' in metadata:
                                    match = re.search(r'X-GM-THRID (\d+)', metadata)
                                    if match:
                                        gmail_thread_id = match.group(1)
                                if 'X-GM-MSGID' in metadata:
                                    match = re.search(r'X-GM-MSGID (\d+)', metadata)
                                    if match:
                                        gmail_message_id = match.group(1)
                                raw = item[1]
                                break

                        if not raw:
                            continue

                        msg = email.message_from_bytes(raw)

                        # Debug: Log each message found
                        msg_id = msg.get("Message-ID", "NO-ID")
                        msg_subject = msg.get("Subject", "NO-SUBJECT")
                        print(f"    Fetched: {msg_subject[:40]}... | MsgID: {msg_id[:50]}... | Gmail TID: {gmail_thread_id}")

                        # Store message with its Gmail thread ID and message ID
                        messages.append({
                            'msg': msg,
                            'gmail_thread_id': gmail_thread_id,
                            'gmail_message_id': gmail_message_id
                        })

                    except Exception as e:
                        print(f"    Error fetching message: {e}")
                        continue

                if messages:
                    print(f"  Found {len(messages)} messages")

                    # Filter messages to only include those from this Gmail thread
                    print(f"  Thread has Gmail ID: {thread.gmail_thread_id}")
                    filtered_messages = []
                    for email_data in messages:
                        gmail_tid = email_data.get('gmail_thread_id')
                        msg = email_data['msg']
                        msg_id = msg.get("Message-ID", "NO-ID")

                        if gmail_tid == thread.gmail_thread_id:
                            filtered_messages.append(email_data)
                            print(f"    ✓ MATCH: MsgID {msg_id[:50]}... (Gmail TID: {gmail_tid})")
                        else:
                            print(f"    ✗ SKIP: MsgID {msg_id[:50]}... (Gmail TID: {gmail_tid} != {thread.gmail_thread_id})")

                    print(f"  After Gmail ID filtering: {len(filtered_messages)} messages matched")
                    if filtered_messages:
                        messages = filtered_messages
                    else:
                        # No messages match the Gmail thread ID
                        print(f"  No messages match this Gmail thread ID - skipping")
                        continue

                    # Sort by date
                    def get_msg_date(email_data):
                        try:
                            msg = email_data['msg'] if isinstance(email_data, dict) else email_data
                            date = msg.get("Date")
                            if date:
                                return parsedate_to_datetime(date)
                        except:
                            pass
                        return None

                    messages.sort(key=get_msg_date)

                    # Update thread
                    new_msg_count, moves_count = _update_thread_messages(thread, messages, access_token)

                    if new_msg_count > 0:
                        stats['threads_updated'] += 1
                        stats['messages_added'] += new_msg_count
                        stats['moves_parsed'] += moves_count
                        print(f"Updated thread '{normalized_subject}': +{new_msg_count} messages, {moves_count} moves")

            except Exception as e:
                error_msg = f"Error syncing thread {thread.subject}: {str(e)}"
                print(error_msg)
                stats['errors'].append(error_msg)
                continue

        imap.logout()
        print(f"Sync completed: {stats}")

    except Exception as e:
        error_msg = f"IMAP error: {str(e)}"
        print(error_msg)
        stats['errors'].append(error_msg)

    return stats


def _update_thread_messages(thread, messages, access_token=None):
    """
    Internal helper to update thread with new messages
    Returns: (messages_added, moves_parsed)
    """
    new_messages_count = 0
    moves_parsed_count = 0

    # Initialize FEN if not set
    if not thread.fen:
        board = chess.Board()
        thread.fen = board.fen()

    for email_data in messages:
        # Handle both new dict format and old format for backwards compatibility
        if isinstance(email_data, dict):
            msg = email_data['msg']
            gmail_message_id = email_data.get('gmail_message_id')
        else:
            msg = email_data
            gmail_message_id = msg.get("Message-ID")  # Fallback to RFC Message-ID

        if not gmail_message_id:
            print(f"Warning: No Gmail message ID found for message, skipping")
            continue

        body, is_html = get_body_from_msg(msg)
        move_uci = extract_chess_move(body)

        # Extract email addresses
        msg_sender = extract_email_address(msg.get("From", ""))
        msg_recipient = extract_email_address(msg.get("To", ""))

        # Parse timestamp
        date_str = msg.get("Date")
        timestamp = None
        if date_str:
            try:
                parsed_time = parsedate_to_datetime(date_str)
                if parsed_time.tzinfo is not None:
                    timestamp = parsed_time.astimezone(timezone.utc)
                else:
                    timestamp = parsed_time.replace(tzinfo=timezone.utc)
            except:
                pass

        # Extract RFC 2822 email headers for proper threading
        in_reply_to = msg.get("In-Reply-To")
        references = msg.get("References")
        subject = msg.get("Subject", "")

        # Debug: Log what we're checking
        print(f"      Checking message: {gmail_message_id[:60] if gmail_message_id else 'NO-GMAIL-MESSAGE-ID'}...")

        # Check if message already exists
        existing_msg = Message.query.filter_by(
            gmail_message_id=gmail_message_id,
            thread_id=thread.id
        ).first()

        if existing_msg:
            print(f"        → Already exists in thread {thread.id} (skipping)")
        else:
            print(f"        → NEW message, adding to thread {thread.id}")

            # Fetch labels from Gmail API if access_token is provided
            label_list = []
            if access_token and gmail_message_id:
                from utils.gmail_api import get_message_labels
                label_list = get_message_labels(access_token, gmail_message_id)
                print(f"        → Labels: {label_list}")

            # Add new message
            new_message = Message(
                gmail_message_id=gmail_message_id,
                thread_id=thread.id,
                user_id=thread.user_id,
                sender=msg_sender,
                recipient=msg_recipient,
                date=timestamp,
                subject=subject,
                body_plain=body if not is_html else "",
                body_html=body if is_html else "",
                in_reply_to=in_reply_to,
                references=references,
                label_ids=','.join(label_list) if label_list else "",
                move=move_uci
            )

            # Update thread snippet with latest message
            if body:
                import re
                if is_html:
                    # Remove HTML tags
                    snippet_text = re.sub(r'<[^>]+>', '', body)
                    snippet_text = re.sub(r'\s+', ' ', snippet_text).strip()
                else:
                    snippet_text = body.strip()
                thread.snippet = snippet_text[:200]

            db.session.add(new_message)
            new_messages_count += 1

            # Update thread FEN if move found
            if move_uci and thread:
                update_thread_fen(thread, move_uci)
                moves_parsed_count += 1

    if new_messages_count > 0:
        # Update thread's last_updated timestamp
        thread.last_updated = datetime.now(timezone.utc)
        db.session.commit()

    return new_messages_count, moves_parsed_count
