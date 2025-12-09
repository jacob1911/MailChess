import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formataddr
import requests
import mimetypes

def send_email_via_api(access_token, user_email, to, subject, body, is_html=False, in_reply_to=None, references=None, thread_id=None, attachments=None):
    """
    Send email using Gmail API. Supports attachments and threading.
    """
    try:
        # 1. Construct Message
        if attachments:
            message = MIMEMultipart('mixed')
        elif is_html:
            message = MIMEMultipart('alternative')
        else:
            message = MIMEText(body, 'plain', 'utf-8')
            message['Subject'] = subject
            message['From'] = formataddr(("MailChess", user_email))
            message['To'] = to
            if in_reply_to: message['In-Reply-To'] = in_reply_to
            if references: message['References'] = references
            
            # Simple path for plain text no attachments
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            return _post_to_gmail(access_token, raw_message, thread_id)

        # 2. Complex Message (HTML or Attachments)
        message['Subject'] = subject
        message['From'] = formataddr(("MailChess", user_email))
        message['To'] = to
        if in_reply_to: message['In-Reply-To'] = in_reply_to
        if references: message['References'] = references

        if is_html:
            # If attachments exist, we need a nested alternative part
            if attachments:
                msg_alternative = MIMEMultipart('alternative')
                message.attach(msg_alternative)
                target_part = msg_alternative
            else:
                target_part = message

            import re
            plain_text = re.sub(r'<[^>]+>', '', body)
            plain_text = re.sub(r'\s+', ' ', plain_text).strip()
            
            target_part.attach(MIMEText(plain_text, 'plain', 'utf-8'))
            target_part.attach(MIMEText(body, 'html', 'utf-8'))
        else:
            if attachments:
                message.attach(MIMEText(body, 'plain', 'utf-8'))

        if attachments:
            for file_obj in attachments:
                if file_obj and file_obj.filename:
                    file_data = file_obj.read()
                    filename = file_obj.filename
                    mime_type, _ = mimetypes.guess_type(filename)
                    if mime_type:
                        main_type, sub_type = mime_type.split('/', 1)
                        part = MIMEBase(main_type, sub_type)
                    else:
                        part = MIMEBase('application', 'octet-stream')
                    
                    part.set_payload(file_data)
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                    message.attach(part)

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        return _post_to_gmail(access_token, raw_message, thread_id)

    except Exception as e:
        if "OAuth token" in str(e): raise
        raise Exception(f"Fejl ved email afsendelse: {str(e)}")

def _post_to_gmail(access_token, raw_message, thread_id):
    """Helper to post the raw message to Gmail API"""
    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {"raw": raw_message}

    if thread_id:
        # Convert Decimal (IMAP) to Hex (API) if needed
        try:
            thread_id_hex = format(int(thread_id), 'x')
            data["threadId"] = thread_id_hex
        except (ValueError, TypeError):
            data["threadId"] = thread_id

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        response_data = response.json()
        
        # Fetch Message-ID
        message_id_value = None
        if 'id' in response_data:
            try:
                msg_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{response_data['id']}"
                msg_response = requests.get(msg_url, headers=headers, params={'format': 'metadata', 'metadataHeaders': ['Message-ID']})
                if msg_response.status_code == 200:
                    for header in msg_response.json().get('payload', {}).get('headers', []):
                        if header['name'].lower() == 'message-id':
                            message_id_value = header['value']
                            break
            except: pass

        # Convert back to Decimal for DB consistency
        thread_id_hex = response_data.get('threadId')
        thread_id_decimal = None
        if thread_id_hex:
            try:
                thread_id_decimal = str(int(thread_id_hex, 16))
            except ValueError:
                thread_id_decimal = thread_id_hex

        return {
            'success': True,
            'message_id': message_id_value,
            'gmail_message_id': response_data.get('id'),
            'thread_id': thread_id_decimal
        }
    elif response.status_code == 401:
        raise Exception("OAuth token er udløbet. Log venligst ud og ind igen.")
    elif response.status_code == 403:
        raise Exception("Utilstrækkelige tilladelser til at sende email.")
    else:
        raise Exception(f"Gmail API fejl: {response.text}")

def get_message_labels(access_token, message_id):
    """Get labels for a specific message"""
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"format": "minimal"}
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json().get('labelIds', [])
        return []
    except Exception as e:
        print(f"Error getting labels: {e}")
        return []

def modify_message_labels(access_token, message_id, add_labels=None, remove_labels=None):
    """Add or remove labels from a message"""
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        data = {}
        if add_labels: data['addLabelIds'] = add_labels
        if remove_labels: data['removeLabelIds'] = remove_labels
        
        response = requests.post(url, headers=headers, json=data)
        if response.status_code == 200:
            return response.json().get('labelIds', [])
        else:
            raise Exception(f"Gmail API error: {response.text}")
    except Exception as e:
        raise Exception(f"Error updating labels: {e}")