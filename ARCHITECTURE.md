# MailChess Architecture (Main Branch)

## Overview

MailChess is a Flask-based web application that combines email communication with chess gameplay through Gmail API integration. Users can play chess via email with moves embedded in their messages.

## Architecture Pattern

The main branch follows a **monolithic Flask blueprint architecture** with utility modules for specific concerns. All business logic resides in route handlers with helper utilities for Gmail API, email processing, and chess move validation.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (Browser)                           │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Templates (Jinja2)                                          │   │
│  │  • inbox.html    - Thread list with custom labels            │   │
│  │  • thread.html   - Conversation view with chess board        │   │
│  │  • login.html    - OAuth authentication                      │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              │ AJAX/Forms                            │
│                              ▼                                       │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               │ HTTP/HTTPS
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Backend (Flask)                                │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  blueprints/mail.py (Routes + Business Logic)                │   │
│  │                                                              │   │
│  │  View Routes:                                                │   │
│  │  • inbox()              - List threads, create new threads   │   │
│  │  • thread()             - View conversation, send messages   │   │
│  │  • debug_message()      - Debug endpoint for HTML rendering  │   │
│  │                                                              │   │
│  │  API Routes:                                                 │   │
│  │  • fetch_threads()      - Fetch new threads from Gmail      │   │
│  │  • sync_existing()      - Sync existing threads              │   │
│  │  • get_threads()        - Get thread list (JSON)             │   │
│  │  • get_thread_messages()- Get messages (JSON)                │   │
│  │  • export_conversation()- AI summary via OpenAI              │   │
│  │  • clear_database()     - Delete all user data               │   │
│  │  • update_thread_labels() - Apply/remove labels              │   │
│  │  • get_custom_labels()  - Get user's labels                  │   │
│  │  • create_custom_label()- Create label with icon             │   │
│  │  • delete_custom_label()- Delete label                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              │ calls                                 │
│                              ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Utils Layer                                                 │   │
│  │                                                              │   │
│  │  utils/email_utils.py                                        │   │
│  │  • fetch_new_threads()  - Fetch from Gmail API              │   │
│  │  • sync_existing_threads() - Update existing conversations  │   │
│  │  • clean_message_body() - Sanitize email content            │   │
│  │                                                              │   │
│  │  utils/gmail_api.py                                          │   │
│  │  • send_email_via_api() - Send email with threading headers │   │
│  │  • Handles MIME message creation                            │   │
│  │  • Manages In-Reply-To/References headers                   │   │
│  │                                                              │   │
│  │  utils/chess_utils.py                                        │   │
│  │  • get_or_create_fen()  - Get/initialize board position     │   │
│  │  • process_move()       - Validate and execute move         │   │
│  │  • update_thread_fen()  - Save new position                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                       │
│                              │ reads/writes                          │
│                              ▼                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Data Layer (SQLAlchemy)                                     │   │
│  │                                                              │   │
│  │  models.py                                                   │   │
│  │  • User          - OAuth user info                           │   │
│  │  • Thread        - Email thread with FEN position            │   │
│  │  • Message       - Individual emails with moves              │   │
│  │  • CustomLabel   - User-created labels with icons            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  External Services                                                   │
│                                                                       │
│  • Gmail API      - Email sending/receiving, OAuth                   │
│  • OpenAI API     - GPT-4o-mini for conversation summaries           │
│  • SQLite/PostgreSQL - Data persistence                              │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### 1. User Sends Chess Move via Email

```
User submits form (thread.html)
    ↓
POST to thread(thread_id)
    ↓
Extract form data: body, move, is_html
    ↓
chess_utils.process_move(fen, move_uci)
    ├─ Returns: (new_fen, result, game_over)
    ├─ Validates move with chess.Board
    └─ Updates FEN position
    ↓
chess_utils.update_thread_fen(thread_id, new_fen)
    ↓
Retrieve threading headers from last message
    ├─ in_reply_to (Message-ID of parent)
    └─ references (chain of Message-IDs)
    ↓
gmail_api.send_email_via_api()
    ├─ Creates MIME message
    ├─ Adds threading headers
    ├─ Sends via Gmail API
    └─ Returns gmail_message_id + thread_id
    ↓
Save Message to database
    ├─ Stores gmail_message_id
    ├─ Stores threading headers
    ├─ Stores move in UCI format
    └─ Links to Thread
    ↓
Update Thread
    ├─ Update snippet
    ├─ Update gmail_thread_id (if temp)
    └─ Update last_updated timestamp
    ↓
Clean up session (remove temp recipient)
    ↓
Redirect to thread view
```

### 2. Fetching New Threads from Gmail

```
User clicks "Fetch New" button
    ↓
POST /api/fetch-threads {count: 5}
    ↓
email_utils.fetch_new_threads(user_id, email, token, count)
    ↓
Connect to Gmail API
    ├─ Query: "category:primary -label:sent"
    ├─ Fetch last N threads
    └─ For each thread:
        ├─ Get all messages in thread
        ├─ Extract sender, recipient, body, headers
        ├─ Parse chess moves from body
        ├─ Create Thread record
        └─ Create Message records
    ↓
Return stats: {threads_fetched, messages_fetched, errors}
    ↓
JSON response to frontend
    ↓
JavaScript refreshes inbox UI
```

### 3. Syncing Existing Threads

```
User clicks "Sync" button
    ↓
POST /api/sync-existing
    ↓
email_utils.sync_existing_threads(user_id, email, token)
    ↓
Query all threads from database
    ↓
For each thread:
    ├─ Query Gmail API for thread by gmail_thread_id
    ├─ Get list of message IDs
    ├─ Compare with database
    ├─ Fetch only NEW messages
    └─ Save to database
    ↓
Return stats: {threads_synced, new_messages, errors}
    ↓
JSON response to frontend
    ↓
JavaScript refreshes inbox UI
```

### 4. AI Summary Generation (OpenAI Integration)

```
User clicks "Export/Summary" button
    ↓
POST /api/thread/<id>/export
    ↓
Fetch all messages from thread
    ↓
Format as conversation text
    ↓
OpenAI GPT-4o-mini API call
    ├─ System prompt: "Brief Danish summary of chess game"
    ├─ Max tokens: 200 (~$0.00012 cost)
    ├─ Temperature: 1.3 (creative)
    └─ Includes rule: "Make a joke about Denmark"
    ↓
Return summary + token usage
    ↓
JavaScript displays in modal with typewriter effect
```

## Database Schema

```sql
┌─────────────────────────────────────────────────────────────────┐
│ User                                                             │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)                                                          │
│ email (unique)                                                   │
│ name                                                             │
│ profile_pic                                                      │
│ created_at                                                       │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ 1:N
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Thread                                                           │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)                                                          │
│ gmail_thread_id (unique)  ← Gmail's thread ID                   │
│ user_id (FK)                                                     │
│ subject                                                          │
│ snippet                   ← Preview text                         │
│ fen                       ← Chess board position (FEN notation)  │
│ last_updated                                                     │
└─────────────────────────────────────────────────────────────────┘
                          │
                          │ 1:N
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ Message                                                          │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)                                                          │
│ gmail_message_id (unique) ← Gmail's message ID                  │
│ thread_id (FK)                                                   │
│ user_id (FK)                                                     │
│ sender                                                           │
│ recipient                                                        │
│ subject                                                          │
│ body_plain                ← Plain text content                   │
│ body_html                 ← HTML content                         │
│ date                                                             │
│ in_reply_to               ← Message-ID of parent (RFC 2822)     │
│ references                ← Chain of Message-IDs (RFC 2822)     │
│ label_ids                 ← Comma-separated label names          │
│ move                      ← Chess move in UCI format (e.g. e2e4) │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ CustomLabel                                                      │
├─────────────────────────────────────────────────────────────────┤
│ id (PK)                                                          │
│ user_id (FK)                                                     │
│ name                      ← Internal name (UPPERCASE_NO_SPACES)  │
│ display_name              ← User-friendly name                   │
│ icon_path                 ← Path to uploaded icon image          │
│ color                     ← Hex color code                       │
│ created_at                                                       │
└─────────────────────────────────────────────────────────────────┘
```

## Key Technical Decisions

### 1. Email Threading (RFC 2822)

Gmail uses standard email headers to group messages into conversations:

- **In-Reply-To**: Contains Message-ID of the message being replied to
- **References**: Contains chain of all Message-IDs in the conversation

When sending a reply, the system:
1. Retrieves the last message in the thread
2. Extracts `in_reply_to` header from that message
3. Builds `references` chain by appending `in_reply_to` to existing `references`
4. Passes these headers to Gmail API

This ensures Gmail properly threads the conversation.

**Location**: `blueprints/mail.py:thread()` function (lines 171-183)

### 2. Temporary Thread IDs for New Conversations

When creating a new thread (no messages sent yet):

1. Generate temporary ID: `temp_{user_id}_{timestamp_ms}`
2. Store recipient in session: `session[f'thread_{thread.id}_recipient']`
3. After first message sent, update with real gmail_thread_id from API response
4. Clean up session storage

**Why**: Gmail doesn't assign thread_id until first message is sent

**Location**: `blueprints/mail.py:inbox()` (lines 77-95) and `thread()` (lines 219-257)

### 3. Chess Move Validation

Uses python-chess library for move validation:

```python
def process_move(fen, move_uci):
    board = chess.Board(fen)
    move = board.parse_uci(move_uci)  # Validates format
    if move in board.legal_moves:     # Validates legality
        board.push(move)
        return board.fen(), result, game_over
    return fen, None, False
```

**Returns 3 values**: (new_fen, result, game_over) - critical for proper unpacking!

**Location**: `utils/chess_utils.py`

### 4. Session-based Authentication

User authentication via Flask sessions:
- User info stored in `session['user']` (id, email, name)
- OAuth access token stored in `session['access_token']`
- All routes check `if session.get("user") is None`

**Security**: Session secret should be strong in production

### 5. OpenAI Integration

Configuration for AI summaries:
- **Model**: gpt-4o-mini (cost-effective, ~$0.00012 per summary)
- **Max Tokens**: 200 (limits response length and cost)
- **Temperature**: 1.3 (high creativity for entertaining summaries)
- **System Prompt**: Instructs Danish summaries with humor

**Environment**: Requires `OPENAI_API_KEY` in `environ.env`

**Location**: `blueprints/mail.py:export_conversation()` (lines 555-580)

## API Endpoints Reference

### View Endpoints

| Route | Method | Description | Template |
|-------|--------|-------------|----------|
| `/` | GET | Redirect to inbox | - |
| `/inbox` | GET | Display thread list | inbox.html |
| `/inbox` | POST | Create new thread | → redirect |
| `/thread/<id>` | GET | View conversation | thread.html |
| `/thread/<id>` | POST | Send message | → redirect |
| `/debug/message/<id>` | GET | Debug message HTML | inline HTML |

### API Endpoints (JSON)

| Route | Method | Description | Authentication |
|-------|--------|-------------|----------------|
| `/api/fetch-threads` | POST | Fetch new threads from Gmail | Required |
| `/api/sync-existing` | POST | Sync existing threads | Required |
| `/api/threads` | GET | Get thread list | Required |
| `/api/thread/<id>/messages` | GET | Get messages in thread | Required + Owner |
| `/api/thread/<id>/export` | POST | Generate AI summary | Required + Owner |
| `/api/thread/<id>/labels` | POST | Update thread labels | Required + Owner |
| `/api/clear-database` | POST | Delete all user data | Required |
| `/api/custom-labels` | GET | Get user's labels | Required |
| `/api/custom-labels` | POST | Create new label | Required |
| `/api/custom-labels/<id>` | DELETE | Delete label | Required + Owner |

## Dependencies

### Python Packages

- **Flask**: Web framework
- **SQLAlchemy**: ORM for database
- **python-chess**: Chess move validation and FEN management
- **OpenAI**: GPT integration for summaries
- **google-auth**: OAuth 2.0 authentication
- **google-api-python-client**: Gmail API client
- **python-dotenv**: Environment variable management

### External Services

- **Gmail API**: Email sending/receiving
  - Requires OAuth 2.0 client credentials
  - Scopes: gmail.readonly, gmail.send, gmail.modify
- **OpenAI API**: Conversation summarization
  - Requires API key in environ.env

## Security Considerations

1. **OAuth 2.0**: All Gmail access via user-authorized tokens
2. **Session Management**: Flask sessions for authentication state
3. **Authorization Checks**: All API endpoints verify user ownership
4. **File Upload Security**:
   - Whitelist extensions: png, jpg, jpeg, gif, svg
   - Secure filename generation
   - User ID + timestamp prefix for uniqueness
5. **Input Validation**:
   - Chess moves validated by chess.Board
   - Email addresses not validated (trusted from Gmail)
6. **API Key Protection**: Environment variables, not hardcoded
7. **Database Isolation**: User ID filters on all queries

## File Structure

```
MailChess/
├── app.py                      # Main Flask application
├── environ.env                 # Environment variables (gitignored)
├── blueprints/
│   ├── mail.py                 # Email routes (1267 lines, documented)
│   └── auth.py                 # OAuth authentication
├── models.py                   # SQLAlchemy models
├── utils/
│   ├── email_utils.py          # Gmail fetching/syncing
│   ├── gmail_api.py            # Email sending with API
│   └── chess_utils.py          # Chess move processing
├── templates/
│   ├── inbox.html              # Thread list view
│   ├── thread.html             # Conversation + chess board
│   └── login.html              # OAuth login
├── static/
│   ├── css/                    # Tailwind CSS
│   ├── js/                     # Chess.js, Chessboard.js
│   └── label_icons/            # Uploaded custom label icons
└── ARCHITECTURE.md             # This file

```

## Known Limitations

1. **No Real-time Updates**: Requires manual sync/refresh
2. **No WebSocket Support**: Polling-based updates only
3. **Single Database Transaction**: No distributed transaction support
4. **No Caching**: Every request hits database
5. **No Background Jobs**: Email sync is synchronous
6. **Monolithic Route Handler**: All logic in mail.py (908+ lines)
7. **No Service Layer**: Business logic mixed with route handlers
8. **Direct Database Access**: No repository pattern

## Future Improvements

1. **Service Layer**: Extract business logic from routes (see refactor-solid branch)
2. **Repository Pattern**: Abstract database access
3. **Background Tasks**: Celery for async email processing
4. **WebSocket**: Real-time updates with Socket.IO
5. **Caching**: Redis for thread/message caching
6. **API Rate Limiting**: Prevent abuse
7. **Full-text Search**: Search messages by content
8. **Push Notifications**: Browser notifications for new moves
9. **Email Validation**: Validate recipient addresses
10. **CSRF Protection**: Enable for production

## Comparison with refactor-solid Branch

The `refactor-solid` branch refactors this monolithic architecture to follow SOLID principles:

| Aspect | Main Branch | refactor-solid Branch |
|--------|-------------|----------------------|
| Architecture | Monolithic routes | Service layer |
| mail.py size | 908+ lines | ~400 lines (-56%) |
| Business logic | In routes | In services |
| Dependencies | Tight coupling | Dependency injection |
| Testability | Hard to test | Easily mockable |
| SOLID compliance | Low | High |
| Maintainability | Difficult | Easier |

See `ARCHITECTURE.md` in refactor-solid branch for detailed SOLID implementation.

---

**Last Updated**: 2025-11-13
**Branch**: main
**Version**: 1.0
