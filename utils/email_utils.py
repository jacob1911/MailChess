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

# Import from other utils if needed, or keep local if self-contained.
# Note: cyclic imports can be tricky, so we import inside functions where possible.

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

        allowed_protocols = ['http', 'https', 'data', 'mailto', 'cid']

        return bleach.clean(
            html_content,
            tags=allowed_tags,
            attributes=allowed_attrs,
            protocols=allowed_protocols,
            strip=True
        )
    except ImportError:
        return html_content


def clean_message_body(body, is_html=False):
    """Clean email body by removing quoted text and email chains"""
    if not body:
        return ""

    if is_html:
        body = sanitize_html(body)
        # Remove Gmail quoted text
        body = re.sub(r'<div[^>]*class="[^"]*gmail_quote[^"]*"[^>]*>.*?</div>', '', body, flags=re.DOTALL | re.IGNORECASE)
        # Remove "On ... wrote:"
        body = re.sub(r'<div[^>]*>On\s+.+?wrote:\s*</div>', '', body, flags=re.IGNORECASE)
        # Remove signature separators
        body = re.sub(r'<div[^>]*>--\s*</div>', '', body)
        # Remove blockquotes that are replies
        body = re.sub(r'<blockquote[^>]*class="[^"]*gmail_quote[^"]*"[^>]*>.*?</blockquote>', '', body, flags=re.DOTALL | re.IGNORECASE)
        # Remove Move: line
        body = re.sub(r'<p[^>]*>\s*Move:\s*[a-h][1-8][a-h][1-8][qrbn]?\s*</p>', '', body, flags=re.IGNORECASE)
        body = re.sub(r'<div[^>]*>\s*Move:\s*[a-h][1-8][a-h][1-8][qrbn]?\s*</div>', '', body, flags=re.IGNORECASE)
        body = re.sub(r'Move:\s*[a-h][1-8][a-h][1-8][qrbn]?', '', body, flags=re.IGNORECASE)
        
        # Cleanup whitespace
        body = re.sub(r'\n\s*\n\s*\n+', '\n\n', body)
        body = re.sub(r'(<br\s*/?>\s*){3,}', '<br><br>', body, flags=re.IGNORECASE)
        return body.strip()

    # Plain text cleaning
    lines = body.split('\n')
    cleaned_lines = []
    skip_rest = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith('>'): continue
        if re.search(r'On .+ wrote:', stripped): 
            skip_rest = True
            continue
        if re.search(r'<[\w\.-]+@[\w\.-]+\.\w+>', stripped):
            skip_rest = True
            continue
        if re.search(r'On \w+, \w+ \d+, \d{4} at', stripped):
            skip_rest = True
            continue
        if re.match(r'^Move:\s*[a-h][1-8][a-h][1-8]', stripped, re.IGNORECASE):
            continue
        if skip_rest: continue
        if stripped: cleaned_lines.append(stripped)

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
                label_ids="",
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
            if board.is_game_over():
                print(f"Game over! Result: {board.result()}")
        else:
            print(f"Illegal move attempted: {move_uci}")
    except Exception as e:
        print(f"Error updating FEN: {e}")


def fetch_new_threads(user_id, user_email, access_token, count=5):
    """
    Fetch last X new email threads from Gmail that don't exist in local database.
    Uses 'email_utils1.py' logic: search by category:primary, get metadata, compare with DB.
    """
    stats = {'threads_fetched': 0, 'messages_added': 0, 'errors': []}

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

        # Collect latest timestamp per thread
        thread_timestamps = {}  # {gmail_thread_id: (mail_id, timestamp)}

        for mail_id in ids:
            try:
                result, msg_data = imap.fetch(mail_id, "(X-GM-THRID INTERNALDATE)")
                if result != "OK" or not msg_data or not msg_data[0]: continue

                gmail_thread_id = None
                timestamp = None
                metadata_str = msg_data[0].decode() if isinstance(msg_data[0], bytes) else str(msg_data[0])

                match = re.search(r'X-GM-THRID (\d+)', metadata_str)
                if match: gmail_thread_id = match.group(1)

                match = re.search(r'INTERNALDATE "([^"]+)"', metadata_str)
                if match: timestamp = parsedate_to_datetime(match.group(1))

                if gmail_thread_id and timestamp:
                    if gmail_thread_id not in thread_timestamps or timestamp > thread_timestamps[gmail_thread_id][1]:
                        thread_timestamps[gmail_thread_id] = (mail_id, timestamp)
            except Exception as e:
                stats['errors'].append(f"Error fetching metadata: {str(e)}")
                continue

        # Filter out existing
        existing_threads = Thread.query.filter_by(user_id=user_id).with_entities(Thread.gmail_thread_id).all()
        existing_thread_ids = set(thread.gmail_thread_id for thread in existing_threads)

        new_threads = {
            tid: data for tid, data in thread_timestamps.items()
            if tid not in existing_thread_ids
        }

        if not new_threads:
            imap.logout()
            return stats

        # Fetch emails for the top 'count' new threads
        sorted_new_threads = sorted(new_threads.items(), key=lambda x: x[1][1], reverse=True)
        threads_to_fetch = sorted_new_threads[:count]
        
        threads_by_gmail_id = {}

        for gmail_thread_id, (sample_mail_id, _) in threads_to_fetch:
            try:
                # Search ALL emails for this thread
                result, data = imap.search(None, f'X-GM-THRID {gmail_thread_id}')
                thread_email_ids = data[0].split() if data[0] else []

                for mail_id in thread_email_ids:
                    try:
                        result, msg_data = imap.fetch(mail_id, "(RFC822 X-GM-THRID X-GM-MSGID)")
                        if result != "OK" or not msg_data or not msg_data[0]: continue

                        gmail_message_id = None
                        raw = None
                        for item in msg_data:
                            if isinstance(item, tuple) and len(item) >= 2:
                                metadata = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                                if 'X-GM-MSGID' in metadata:
                                    match = re.search(r'X-GM-MSGID (\d+)', metadata)
                                    if match: gmail_message_id = match.group(1)
                                raw = item[1]
                                break

                        if not raw: continue
                        msg = email.message_from_bytes(raw)

                        if gmail_thread_id not in threads_by_gmail_id:
                            threads_by_gmail_id[gmail_thread_id] = []

                        threads_by_gmail_id[gmail_thread_id].append({
                            'msg': msg,
                            'gmail_thread_id': gmail_thread_id,
                            'gmail_message_id': gmail_message_id
                        })
                    except Exception as e:
                         stats['errors'].append(f"Error fetching email: {str(e)}")

            except Exception as e:
                stats['errors'].append(f"Error fetching thread {gmail_thread_id}: {str(e)}")

        # Store threads
        for gmail_thread_id, messages in threads_by_gmail_id.items():
            def get_msg_date(email_data):
                try:
                    msg = email_data['msg'] if isinstance(email_data, dict) else email_data
                    date = msg.get("Date")
                    if date: return parsedate_to_datetime(date)
                except: pass
                return None

            messages.sort(key=get_msg_date)
            store_thread(user_id, messages)
            stats['threads_fetched'] += 1
            stats['messages_added'] += len(messages)

        imap.logout()
    except Exception as e:
        stats['errors'].append(f"IMAP error: {str(e)}")

    return stats


def sync_existing_threads(user_id, user_email, access_token):
    """
    Sync existing threads with new emails from Gmail.
    Uses 'email_utils1.py' logic: Search by SUBJECT -> Filter by X-GM-THRID.
    This handles Gmail's IMAP search limitations better.
    """
    stats = {'threads_updated': 0, 'messages_added': 0, 'moves_parsed': 0, 'errors': []}

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", port=993)
        auth_string = f"user={user_email}\1auth=Bearer {access_token}\1\1"
        imap.authenticate("XOAUTH2", lambda x: auth_string.encode("utf-8"))
        imap.select("INBOX")

        existing_threads = Thread.query.filter_by(user_id=user_id).all()
        print(f"Syncing {len(existing_threads)} existing threads...")

        for thread in existing_threads:
            try:
                # 1. Search by Subject
                normalized_subject = re.sub(r'^(Re:|Fwd:)\s*', '', thread.subject, flags=re.IGNORECASE).strip()
                search_query = f'SUBJECT "{normalized_subject}"'
                result, data = imap.search(None, search_query)
                if result != "OK" or not data[0]: continue

                ids = data[0].split()
                messages = []
                
                # 2. Fetch metadata (Gmail Thread ID + Msg ID)
                for mail_id in ids:
                    try:
                        result, msg_data = imap.fetch(mail_id, "(RFC822 X-GM-THRID X-GM-MSGID)")
                        if result != "OK" or not msg_data or not msg_data[0]: continue

                        gmail_thread_id = None
                        gmail_message_id = None
                        raw = None
                        for item in msg_data:
                            if isinstance(item, tuple) and len(item) >= 2:
                                metadata = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
                                if 'X-GM-THRID' in metadata:
                                    match = re.search(r'X-GM-THRID (\d+)', metadata)
                                    if match: gmail_thread_id = match.group(1)
                                if 'X-GM-MSGID' in metadata:
                                    match = re.search(r'X-GM-MSGID (\d+)', metadata)
                                    if match: gmail_message_id = match.group(1)
                                raw = item[1]
                                break
                        
                        if not raw: continue
                        msg = email.message_from_bytes(raw)
                        messages.append({
                            'msg': msg,
                            'gmail_thread_id': gmail_thread_id,
                            'gmail_message_id': gmail_message_id
                        })
                    except Exception as e:
                        print(f"Error fetching msg: {e}")

                # 3. Filter strictly by Thread ID to avoid mixing similar subjects
                if messages and thread.gmail_thread_id:
                    filtered_messages = [
                        m for m in messages 
                        if m.get('gmail_thread_id') == thread.gmail_thread_id
                    ]
                    
                    def get_msg_date(email_data):
                        try:
                            msg = email_data['msg'] if isinstance(email_data, dict) else email_data
                            date = msg.get("Date")
                            if date: return parsedate_to_datetime(date)
                        except: pass
                        return None
                    
                    filtered_messages.sort(key=get_msg_date)
                    
                    new_msg_count, moves_count = _update_thread_messages(thread, filtered_messages, access_token)
                    
                    if new_msg_count > 0:
                        stats['threads_updated'] += 1
                        stats['messages_added'] += new_msg_count
                        stats['moves_parsed'] += moves_count

            except Exception as e:
                stats['errors'].append(f"Error syncing thread {thread.subject}: {str(e)}")

        imap.logout()
    except Exception as e:
        stats['errors'].append(f"IMAP error: {str(e)}")

    return stats


def _update_thread_messages(thread, messages, access_token=None):
    """Helper to update thread with new messages"""
    new_messages_count = 0
    moves_parsed_count = 0

    if not thread.fen:
        board = chess.Board()
        thread.fen = board.fen()

    for email_data in messages:
        if isinstance(email_data, dict):
            msg = email_data['msg']
            gmail_message_id = email_data.get('gmail_message_id')
        else:
            msg = email_data
            gmail_message_id = msg.get("Message-ID")

        if not gmail_message_id: continue

        # Check existing
        existing_msg = Message.query.filter_by(
            gmail_message_id=gmail_message_id, thread_id=thread.id
        ).first()

        if existing_msg: continue

        body, is_html = get_body_from_msg(msg)
        move_uci = extract_chess_move(body)
        msg_sender = extract_email_address(msg.get("From", ""))
        msg_recipient = extract_email_address(msg.get("To", ""))
        
        date_str = msg.get("Date")
        timestamp = None
        if date_str:
            try:
                parsed_time = parsedate_to_datetime(date_str)
                if parsed_time.tzinfo is not None:
                    timestamp = parsed_time.astimezone(timezone.utc)
                else:
                    timestamp = parsed_time.replace(tzinfo=timezone.utc)
            except: pass

        in_reply_to = msg.get("In-Reply-To")
        references = msg.get("References")
        subject = msg.get("Subject", "")

        label_list = []
        if access_token and gmail_message_id:
            # We need to import this here to avoid circular imports if possible,
            # or rely on it being available in the path.
            try:
                from utils.gmail_api import get_message_labels
                label_list = get_message_labels(access_token, gmail_message_id)
            except ImportError:
                pass

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

        if body:
            if is_html:
                snippet_text = re.sub(r'<[^>]+>', '', body)
                snippet_text = re.sub(r'\s+', ' ', snippet_text).strip()
            else:
                snippet_text = body.strip()
            thread.snippet = snippet_text[:200]

        db.session.add(new_message)
        new_messages_count += 1

        if move_uci and thread:
            update_thread_fen(thread, move_uci)
            moves_parsed_count += 1

    if new_messages_count > 0:
        thread.last_updated = datetime.now(timezone.utc)
        db.session.commit()

    return new_messages_count, moves_parsed_count
