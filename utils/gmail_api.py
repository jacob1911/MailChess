"""
Gmail API integration for sending emails
Alternative to SMTP that works better with OAuth
"""
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formataddr
import requests
import json
import os # For file operations
import mimetypes # For attachment types

def send_email_via_api(access_token, user_email, to, subject, body, is_html=False, in_reply_to=None, references=None, thread_id=None, attachments=None):
    """
    Send email using Gmail API (more reliable with OAuth than SMTP)
    Supports both plain text and HTML emails with attachments
    """
    try:
        # --- 1. Message Setup ---
        if attachments:
            message = MIMEMultipart('mixed')
        elif is_html:
            message = MIMEMultipart('alternative')
        else:
            message = MIMEMultipart('alternative')

        # --- 2. Set Headers ---
        message['Subject'] = subject
        message['From'] = formataddr(("MailChess", user_email))
        message['To'] = to
        if in_reply_to:
            message['In-Reply-To'] = in_reply_to
        if references:
            message['References'] = references

        # --- 3. Add Body Content ---
        if is_html:
            # Create plain text version by stripping HTML tags
            import re
            plain_text = re.sub(r'<[^>]+>', '', body)
            plain_text = re.sub(r'\s+', ' ', plain_text).strip()

            part_plain = MIMEText(plain_text, 'plain', 'utf-8')
            part_html = MIMEText(body, 'html', 'utf-8')
            
            if attachments:
                msg_alternative = MIMEMultipart('alternative')
                msg_alternative.attach(part_plain)
                msg_alternative.attach(part_html)
                message.attach(msg_alternative)
            else:
                message.attach(part_plain)
                message.attach(part_html)
        else:
            part_plain = MIMEText(body, 'plain', 'utf-8')
            message.attach(part_plain)

        # --- 4. Add Attachments ---
        if attachments:
            for file_obj in attachments:
                if file_obj and file_obj.filename:
                    file_obj.seek(0)
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

        # --- 5. Encode & Send ---
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        data = {"raw": raw_message}

        if thread_id and not thread_id.startswith("temp_"):
             # Gmail API expects HEX format for threadId
            try:
                # Check if it's decimal (from IMAP) and convert to hex
                if thread_id.isdigit():
                     data["threadId"] = format(int(thread_id), 'x')
                else:
                     # Assume it's already hex
                     data["threadId"] = thread_id
            except:
                # Fallback
                data["threadId"] = thread_id

        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 200:
            response_data = response.json()
            
            # Get Message-ID header for threading
            message_id_value = None
            try:
                msg_url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{response_data['id']}"
                msg_response = requests.get(msg_url, headers=headers, params={'format': 'metadata', 'metadataHeaders': ['Message-ID']})
                if msg_response.status_code == 200:
                    for header in msg_response.json().get('payload', {}).get('headers', []):
                        if header['name'].lower() == 'message-id':
                            message_id_value = header['value']
                            break
            except:
                pass

            # Handle thread_id conversion (Hex -> Decimal string) for DB consistency
            thread_id_decimal = response_data.get('threadId')
            try:
                if thread_id_decimal:
                    thread_id_decimal = str(int(thread_id_decimal, 16))
            except:
                pass

            return {
                'success': True,
                'message_id': message_id_value,
                'gmail_message_id': response_data.get('id'),
                'thread_id': thread_id_decimal
            }
        elif response.status_code == 401:
            raise Exception("OAuth token er udløbet.")
        else:
            raise Exception(f"Gmail API fejl: {response.text}")

    except Exception as e:
        if "OAuth token" in str(e):
            raise
        raise Exception(f"Fejl ved email afsendelse: {str(e)}")


def get_message_labels(access_token, message_id):
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"format": "minimal"}
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json().get('labelIds', [])
        return []
    except:
        return []

def modify_message_labels(access_token, message_id, add_labels=None, remove_labels=None):
    try:
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        data = {}
        if add_labels: data['addLabelIds'] = add_labels
        if remove_labels: data['removeLabelIds'] = remove_labels
        
        requests.post(url, headers=headers, json=data)
        return [] 
    except:
        return []

# --- ADD THIS NEW FUNCTION ---
def refresh_access_token(client_id, client_secret, refresh_token):
    """
    Refreshes the Google OAuth access token using the refresh token.
    """
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    }
    
    try:
        response = requests.post(token_url, data=data)
        if response.status_code == 200:
            new_token_data = response.json()
            return new_token_data.get('access_token')
        else:
            print(f"Token refresh failed: {response.text}")
            return None
    except Exception as e:
        print(f"Error refreshing token: {str(e)}")
        return None