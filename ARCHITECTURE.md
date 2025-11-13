# MailChess Architecture

## Publisher-Subscriber Pattern Implementation

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Frontend (Browser)                       │
│                                                                   │
│  ┌──────────────┐    AJAX     ┌─────────────────────────────┐  │
│  │ Sync Button  │─────────────▶│  /api/sync (POST)           │  │
│  │ (inbox.html) │             │  /api/threads (GET)          │  │
│  │ (thread.html)│◀─────────────│  /api/thread/<id>/messages  │  │
│  └──────────────┘    JSON     └─────────────────────────────┘  │
│         │                                    │                   │
└─────────┼────────────────────────────────────┼───────────────────┘
          │                                    │
          ▼                                    ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Backend (Flask)                           │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              blueprints/mail.py (Routes)                   │ │
│  │                                                            │ │
│  │  • inbox()              - Main inbox view                 │ │
│  │  • thread()             - Thread detail view              │ │
│  │  • sync_emails()        - API endpoint for sync           │ │
│  │  • get_threads()        - API endpoint for thread list    │ │
│  │  • get_thread_messages()- API endpoint for messages       │ │
│  └────────────────────────────────────────────────────────────┘ │
│                           │                                      │
│                           ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │         utils/email_sync.py (Sync Service)                 │ │
│  │                                                            │ │
│  │  EmailSyncService                                          │ │
│  │  • sync_emails()       - Main sync logic                   │ │
│  │  • _update_existing_thread() - Update logic                │ │
│  │  • Subscribes to events                                    │ │
│  │  • Publishes events during sync                            │ │
│  └────────────────────────────────────────────────────────────┘ │
│                           │                                      │
│                           │ publishes events                     │
│                           ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │           utils/event_bus.py (Event System)                │ │
│  │                                                            │ │
│  │  EventBus                                                  │ │
│  │  • subscribe(event_type, callback)                        │ │
│  │  • publish(event_type, data)                              │ │
│  │  • get_history()                                          │ │
│  │                                                            │ │
│  │  Events:                                                   │ │
│  │    - sync_started                                         │ │
│  │    - email_fetched                                        │ │
│  │    - thread_updated                                       │ │
│  │    - thread_created                                       │ │
│  │    - move_parsed                                          │ │
│  │    - sync_completed                                       │ │
│  │    - sync_failed                                          │ │
│  └────────────────────────────────────────────────────────────┘ │
│                           │                                      │
│                           │ notifies subscribers                 │
│                           ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                  Subscribers (Optional)                     │ │
│  │                                                            │ │
│  │  • Logger               - Log sync events                  │ │
│  │  • Metrics Collector    - Track statistics                │ │
│  │  • Notification Service - Send notifications              │ │
│  │  • Custom handlers      - Your own logic                  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

## Event Flow

### 1. User Clicks Sync Button

```
User Click → syncEmails() (JavaScript) → POST /api/sync
```

### 2. Backend Processing

```
mail.sync_emails()
    ↓
EmailSyncService.sync_emails(user_email, token)
    ↓
    ├─ PUBLISH: sync_started
    ├─ Connect to Gmail IMAP
    ├─ Fetch last 10 emails
    │   ├─ For each email:
    │   │   ├─ PUBLISH: email_fetched
    │   │   ├─ Parse chess move (if any)
    │   │   └─ Store in database
    │   │
    ├─ Update existing threads
    │   ├─ PUBLISH: thread_updated (if updated)
    │   └─ PUBLISH: move_parsed (if move found)
    │
    ├─ Create new threads
    │   └─ PUBLISH: thread_created
    │
    └─ PUBLISH: sync_completed (with stats)
```

### 3. Frontend Updates

```
API Response → updateThreadList() → Update DOM
                                  ↓
                            Update Chess Board
```

## Data Flow

```
Gmail IMAP Server
    ↓
Email Raw Data (RFC822)
    ↓
email_utils.get_body_from_msg()
    ↓
email_utils.extract_chess_move()  ─→  "Move: e2e4" → "e2e4"
    ↓
chess_utils.process_move()
    ↓
Update Game.fen in Database
    ↓
API Response with updated FEN
    ↓
Frontend updates Chess.js board
```

## Publisher-Subscriber Benefits

### 1. **Loose Coupling**
- Email sync service doesn't need to know who listens
- Easy to add new subscribers without modifying sync code

### 2. **Extensibility**
- Add logging by subscribing to events
- Add metrics by subscribing to events
- Add notifications by subscribing to events

### 3. **Testability**
- Can mock event bus for unit tests
- Can verify events are published correctly

### 4. **Real-time Updates**
- Multiple UI components can subscribe to same events
- Automatic updates across different views

## Example: Adding a New Subscriber

```python
# In app.py or custom module
from utils.event_bus import event_bus

def on_move_parsed(data):
    # Send push notification when opponent makes a move
    send_notification(
        user=data['user'],
        message=f"New move: {data['move']}"
    )

# Subscribe to event
event_bus.subscribe('move_parsed', on_move_parsed)
```

## API Endpoints

| Endpoint | Method | Description | Response |
|----------|--------|-------------|----------|
| `/api/sync` | POST | Trigger email sync | `{success, message, stats}` |
| `/api/threads` | GET | Get all threads | `{success, threads, count}` |
| `/api/thread/<id>/messages` | GET | Get thread messages | `{success, messages, fen, count}` |

## Database Models

```
┌─────────────┐       ┌──────────────┐       ┌──────────┐
│ Mailthread  │──1:N──│   Message    │       │   Game   │
├─────────────┤       ├──────────────┤       ├──────────┤
│ id          │       │ id           │       │ id       │
│ sender      │       │ sender       │       │ player1  │
│ recipient   │       │ recipient    │       │ player2  │
│ subject     │       │ body         │       │ fen      │
└─────────────┘       │ move         │       │ victor   │
                      │ timestamp    │       │ mail_id  │
                      │ mail_id (FK) │       └──────────┘
                      └──────────────┘
```

## Security Considerations

1. **OAuth 2.0** - All Gmail access via OAuth tokens
2. **Session Management** - User sessions required for API calls
3. **CSRF Protection** - Should be enabled for production
4. **Rate Limiting** - Consider adding for API endpoints
5. **Input Validation** - Chess moves validated by chess.Board

## Future Enhancements

1. **WebSocket Support** - Real-time updates without polling
2. **Background Tasks** - Celery for async email processing
3. **Caching** - Redis for thread/message caching
4. **Full-text Search** - Elasticsearch for message search
5. **Push Notifications** - Browser notifications for new moves
