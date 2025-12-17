import imaplib
import smtplib
import email
import base64
import re
import chess
from email.mime.text import MIMEText
from email.utils import formataddr, parsedate_to_datetime, parseaddr
from email.header import decode_header
from models import db, Thread, Message, User
from html import escape
import html.parser
from datetime import datetime, timezone

# Import from other utils if needed, or keep local if self-contained.
# Note: cyclic imports can be tricky, so we import inside functions where possible.

def decode_header_value(header_value):
    """
    Decode email header values that may be encoded in RFC 2047 format (e.g., =?utf-8?B?...?=)
    Returns a plain string with decoded text.
    """
    if not header_value:
        return ""
    
    try:
        # decode_header returns a list of (decoded_bytes, charset) tuples
        decoded_parts = decode_header(header_value)
        result = []
        
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                # Decode bytes using the specified charset, or UTF-8 as fallback
                encoding = charset if charset else 'utf-8'
                try:
                    result.append(part.decode(encoding, errors='replace'))
                except (LookupError, TypeError):
                    # If charset is invalid or unknown, try UTF-8
                    result.append(part.decode('utf-8', errors='replace'))
            else:
                # Already a string
                result.append(part)
        
        return ''.join(result)
    except Exception as e:
        print(f"[WARNING] Failed to decode header: {e}")
        return header_value

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
    inline_images = {}

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_dispo = str(part.get("Content-Disposition"))

            if content_type.startswith('image/'):
                content_id = part.get('Content-ID')
                if content_id:
                    content_id = content_id.strip('<>')
                    try:
                        image_data = part.get_payload(decode=True)
                        if image_data:
                            image_base64 = base64.b64encode(image_data).decode('utf-8')
                            mime_type = content_type
                            data_uri = f"data:{mime_type};base64,{image_base64}"
                            inline_images[content_id] = data_uri
                    except:
                        pass
                continue

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

    if html_body and inline_images:
        for cid, data_uri in inline_images.items():
            html_body = html_body.replace(f"cid:{cid}", data_uri)

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
    # Flexible match for "Move: " followed by notation
    match = re.search(r'([a-h][1-8][a-h][1-8][qrbn]?)', body, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None


def store_thread(user_id, thread_emails):
    """Store email thread in database with all its messages"""
    if not thread_emails:
        return None

    first_email_data = thread_emails[0]
    first_msg = first_email_data['msg'] if isinstance(first_email_data, dict) else first_email_data
    gmail_thread_id = first_email_data.get('gmail_thread_id') if isinstance(first_email_data, dict) else None

    if not gmail_thread_id:
        print("Warning: No Gmail thread ID found, cannot create thread")
        return None

    raw_subject = first_msg.get("Subject", "No Subject")
    normalized_subject = re.sub(r'^(Re:|Fwd:)\s*', '', raw_subject, flags=re.IGNORECASE).strip()

    existing_thread = Thread.query.filter_by(gmail_thread_id=gmail_thread_id, user_id=user_id).first()

    if existing_thread:
        new_thread = existing_thread
        new_thread.subject = normalized_subject
        new_thread.last_updated = datetime.now(timezone.utc)
    else:
        body, is_html = get_body_from_msg(first_msg)
        snippet = ""
        if body:
            if is_html:
                snippet_text = re.sub(r'<[^>]+>', '', body)
                snippet_text = re.sub(r'\s+', ' ', snippet_text).strip()
            else:
                snippet_text = body.strip()
            snippet = snippet_text[:200]

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

    for email_data in thread_emails:
        if isinstance(email_data, dict):
            msg = email_data['msg']
            gmail_message_id = email_data.get('gmail_message_id')
        else:
            msg = email_data
            gmail_message_id = msg.get("Message-ID")

        if not gmail_message_id: continue

        body, is_html = get_body_from_msg(msg)
        move_uci = extract_chess_move(body)
        msg_sender = extract_email_address(msg.get("From", ""))
        msg_recipient = extract_email_address(msg.get("To", ""))
        
        date_str = msg.get("Date")
        timestamp = None
        if date_str:
            try:
                timestamp = parsedate_to_datetime(date_str)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
            except:
                pass

        in_reply_to = msg.get("In-Reply-To")
        references = msg.get("References")
        subject = msg.get("Subject", "")
        
        # Fetch labels from Gmail API
        label_list = []
        if access_token and gmail_message_id:
            try:
                from utils.gmail_api import get_message_labels
                label_list = get_message_labels(access_token, gmail_message_id)
            except:
                pass
        
        existing_msg = Message.query.filter_by(gmail_message_id=gmail_message_id, thread_id=new_thread.id).first()

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
                label_ids=','.join(label_list) if label_list else "",
                move=move_uci
            )
            db.session.add(new_message)

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
        auth_string = f"user={user_email}\1auth=Bearer {access_token}\1\1"
        imap.authenticate("XOAUTH2", lambda x: auth_string.encode("utf-8"))
        imap.select("INBOX")

        # Get all email IDs
        result, data = imap.search(None, 'X-GM-RAW "category:primary"')
        ids = data[0].split() if data[0] else []

        if not ids:
            imap.logout()
            return stats

        print(f"Found {len(ids)} emails in Gmail inbox")

        # OPTIMIZATION: Get existing thread IDs from database FIRST (fast query with index)
        existing_threads = Thread.query.filter_by(user_id=user_id).with_entities(Thread.gmail_thread_id).all()
        existing_thread_ids = set(thread.gmail_thread_id for thread in existing_threads)
        print(f"User has {len(existing_thread_ids)} existing threads in database")

        # Step 1: Process emails from NEWEST to OLDEST, stop when we have enough new threads
        thread_timestamps = {}  # {gmail_thread_id: (mail_id, timestamp)}
        new_threads_found = 0

        # Reverse the IDs to process newest first
        ids_reversed = list(reversed(ids))

        for mail_id in ids_reversed:
            # Stop early if we already found enough new threads
            if new_threads_found >= count * 2:  # Get 2x to account for duplicates
                print(f"Early stop: found {new_threads_found} new threads, processing stopped")
                break

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
                    # Skip if thread already exists in database
                    if gmail_thread_id in existing_thread_ids:
                        continue

                    # Keep track of the latest email in each NEW thread
                    if gmail_thread_id not in thread_timestamps:
                        new_threads_found += 1
                        thread_timestamps[gmail_thread_id] = (mail_id, timestamp)
                    elif timestamp > thread_timestamps[gmail_thread_id][1]:
                        thread_timestamps[gmail_thread_id] = (mail_id, timestamp)

            except Exception as e:
                stats['errors'].append(f"Error fetching thread metadata: {str(e)}")
                continue

        print(f"Found {len(thread_timestamps)} new unique threads")

        if not thread_timestamps:
            imap.logout()
            print("No new threads to fetch")
            return stats

        # Step 2: Sort by timestamp (newest first) and take last X
        sorted_new_threads = sorted(thread_timestamps.items(), key=lambda x: x[1][1], reverse=True)
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
    Sync existing threads with new emails from Gmail using subject-based search.
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
        auth_string = f"user={user_email}\1auth=Bearer {access_token}\1\1"
        imap.authenticate("XOAUTH2", lambda x: auth_string.encode("utf-8"))
        imap.select("INBOX")

        # Get all existing threads from database for this user
        existing_threads = Thread.query.filter_by(user_id=user_id).all()

        if not existing_threads:
            imap.logout()
            print("No existing threads to sync")
            return stats

        print(f"Syncing {len(existing_threads)} existing threads...")

        for thread in existing_threads:
            try:
                # Skip threads without Gmail thread ID
                if not thread.gmail_thread_id:
                    print(f"Skipping thread without Gmail ID: {thread.subject}")
                    continue

                # Decode subject in case it contains RFC 2047 encoded text (e.g., special characters)
                decoded_subject = decode_header_value(thread.subject)
                
                # Normalize subject for search (remove Re: and Fwd: prefixes)
                normalized_subject = re.sub(r'^(Re:|Fwd:)\s*', '', decoded_subject, flags=re.IGNORECASE).strip()

                print(f"Searching for thread (Gmail ID: {thread.gmail_thread_id[:16]}...) by subject: '{normalized_subject}'")

                # Search by subject (using decoded subject to avoid IMAP parse errors)
                result, data = imap.search(None, f'SUBJECT "{normalized_subject}"')

                if result != "OK" or not data[0]:
                    print(f"  No results found")
                    continue

                ids = data[0].split()
                print(f"  Search found {len(ids)} emails")

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
                    # Filter messages to only include those from this Gmail thread
                    print(f"  Thread has Gmail ID: {thread.gmail_thread_id}")
                    filtered_messages = []
                    for email_data in messages:
                        gmail_tid = email_data.get('gmail_thread_id')
                        if gmail_tid == thread.gmail_thread_id:
                            filtered_messages.append(email_data)
                            print(f"    ✓ MATCH (Gmail TID: {gmail_tid})")

                    print(f"  After Gmail ID filtering: {len(filtered_messages)} messages matched")

                    if not filtered_messages:
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

                    filtered_messages.sort(key=get_msg_date)

                    # Update thread
                    new_msg_count, moves_count = _update_thread_messages(thread, filtered_messages, access_token)

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

        # Check if message already exists (Fast lookup due to indexing in models.py)
        existing_msg = Message.query.filter_by(
            gmail_message_id=gmail_message_id,
            thread_id=thread.id
        ).first()

        if existing_msg:
            print(f"        → Already exists in thread {thread.id} (skipping)")
            continue

        print(f"        → NEW message, adding to thread {thread.id}")

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

        # Fetch labels from Gmail API if access_token is provided
        label_list = []
        if access_token and gmail_message_id:
            try:
                from utils.gmail_api import get_message_labels
                label_list = get_message_labels(access_token, gmail_message_id)
                print(f"        → Labels: {label_list}")
            except:
                pass

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
