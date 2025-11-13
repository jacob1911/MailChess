"""
Gmail API integration for sending emails
Alternative to SMTP that works better with OAuth
"""
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import requests


def send_email_via_api(access_token, user_email, to, subject, body, is_html=False, in_reply_to=None, references=None, thread_id=None):
    """
    Send email using Gmail API (more reliable with OAuth than SMTP)
    Supports both plain text and HTML emails

    Args:
        in_reply_to: Message-ID of the message being replied to (for threading)
        references: Space-separated list of Message-IDs in the thread (for threading)
        thread_id: Gmail's internal thread ID (for threading within Gmail)
    """
    try:
        if is_html:
            # Create multipart message for HTML with plain text fallback
            message = MIMEMultipart('alternative')
            message['Subject'] = subject
            message['From'] = formataddr(("MailChess", user_email))
            message['To'] = to

            # Add threading headers if provided
            if in_reply_to:
                message['In-Reply-To'] = in_reply_to
            if references:
                message['References'] = references

            # Create plain text version by stripping HTML tags (simple fallback)
            import re
            plain_text = re.sub(r'<[^>]+>', '', body)
            plain_text = re.sub(r'\s+', ' ', plain_text).strip()

            # Attach both plain and HTML versions
            part1 = MIMEText(plain_text, 'plain', 'utf-8')
            part2 = MIMEText(body, 'html', 'utf-8')
            message.attach(part1)
            message.attach(part2)
        else:
            # Create plain text message
            message = MIMEText(body, 'plain', 'utf-8')
            message['Subject'] = subject
            message['From'] = formataddr(("MailChess", user_email))
            message['To'] = to

            # Add threading headers if provided
            if in_reply_to:
                message['In-Reply-To'] = in_reply_to
            if references:
                message['References'] = references

        # Encode message
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        # Send via Gmail API
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = {
            "raw": raw_message
        }

        # Add threadId if provided (helps Gmail group replies)
        if thread_id:
            # Convert thread_id from DECIMAL back to HEX format for Gmail API
            # Database stores in DECIMAL (from IMAP), but Gmail API expects HEX
            try:
                # Try to convert from decimal to hex
                thread_id_hex = format(int(thread_id), 'x')
                data["threadId"] = thread_id_hex
                print(f"[DEBUG] Converting thread_id for Gmail API: {thread_id} (decimal) → {thread_id_hex} (hex)")
            except (ValueError, TypeError):
                # If conversion fails, use as-is (might already be hex)
                data["threadId"] = thread_id
                print(f"[DEBUG] Using thread_id as-is: {thread_id}")

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            # Get the sent message details to extract Message-ID
            response_data = response.json()
            message_id_value = None

            # DEBUG: Log raw response
            print(f"[DEBUG] Gmail API send response:")
            print(f"  Raw threadId: {response_data.get('threadId')}")
            print(f"  Raw id: {response_data.get('id')}")

            # Fetch the sent message to get its Message-ID header
            if 'id' in response_data:
                msg_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{response_data['id']}"
                msg_response = requests.get(msg_url, headers=headers, params={'format': 'metadata', 'metadataHeaders': ['Message-ID']})

                if msg_response.status_code == 200:
                    msg_data = msg_response.json()
                    # Extract Message-ID from headers
                    for header in msg_data.get('payload', {}).get('headers', []):
                        if header['name'].lower() == 'message-id':
                            message_id_value = header['value']
                            break

                    # DEBUG: Also log threadId from fetch response
                    print(f"  Fetched message threadId: {msg_data.get('threadId')}")

            # Gmail API returns thread_id in HEX format (e.g., "19a72efb99901b52")
            # But IMAP X-GM-THRID returns DECIMAL format (e.g., "1848583403690253138")
            # Convert to DECIMAL for consistency with IMAP sync
            thread_id_hex = response_data.get('threadId')
            thread_id_decimal = None
            if thread_id_hex:
                try:
                    # Convert from HEX to DECIMAL
                    thread_id_decimal = str(int(thread_id_hex, 16))
                    print(f"  Converted thread_id: {thread_id_hex} (hex) → {thread_id_decimal} (decimal)")
                except ValueError:
                    # Already in decimal format or invalid - use as-is
                    thread_id_decimal = thread_id_hex
                    print(f"  Warning: Could not convert thread_id from hex, using as-is: {thread_id_hex}")

            result = {
                'success': True,
                'message_id': message_id_value,
                'gmail_message_id': response_data.get('id'),
                'thread_id': thread_id_decimal
            }

            print(f"[DEBUG] Returning result: {result}")
            return result
        elif response.status_code == 401:
            raise Exception("OAuth token er udløbet. Log venligst ud og ind igen.")
        elif response.status_code == 403:
            raise Exception("Utilstrækkelige tilladelser til at sende email.")
        else:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', 'Ukendt fejl')
            raise Exception(f"Gmail API fejl: {error_msg}")

    except requests.RequestException as e:
        raise Exception(f"Netværksfejl ved email afsendelse: {str(e)}")
    except Exception as e:
        if "OAuth token" in str(e):
            raise
        raise Exception(f"Fejl ved email afsendelse: {str(e)}")


def get_message_labels(access_token, message_id):
    """
    Get labels for a specific message using Gmail API

    Args:
        access_token: OAuth access token
        message_id: Gmail message ID

    Returns:
        List of label IDs (e.g., ['INBOX', 'UNREAD', 'IMPORTANT'])
    """
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        headers = {
            "Authorization": f"Bearer {access_token}",
        }
        params = {
            "format": "minimal"  # We only need labelIds
        }

        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            return data.get('labelIds', [])
        else:
            print(f"Failed to get labels for message {message_id}: {response.status_code}")
            return []

    except Exception as e:
        print(f"Error getting message labels: {str(e)}")
        return []


def modify_message_labels(access_token, message_id, add_labels=None, remove_labels=None):
    """
    Add or remove labels from a message using Gmail API

    Args:
        access_token: OAuth access token
        message_id: Gmail message ID
        add_labels: List of label IDs to add (e.g., ['STARRED', 'IMPORTANT'])
        remove_labels: List of label IDs to remove (e.g., ['UNREAD'])

    Returns:
        Updated list of label IDs
    """
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = {}

        if add_labels:
            data['addLabelIds'] = add_labels
        if remove_labels:
            data['removeLabelIds'] = remove_labels

        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            result = response.json()
            return result.get('labelIds', [])
        else:
            error_data = response.json()
            error_msg = error_data.get('error', {}).get('message', 'Ukendt fejl')
            raise Exception(f"Gmail API fejl: {error_msg}")

    except Exception as e:
        raise Exception(f"Fejl ved opdatering af labels: {str(e)}")
