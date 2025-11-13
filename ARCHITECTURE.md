# MailChess Architecture Documentation

## Table of Contents
1. [Overview](#overview)
2. [SOLID Principles Implementation](#solid-principles-implementation)
3. [Architecture Layers](#architecture-layers)
4. [Project Structure](#project-structure)
5. [Design Patterns](#design-patterns)
6. [Data Flow](#data-flow)
7. [Key Components](#key-components)

---

## Overview

MailChess is a chess-by-email application built with Flask that follows **SOLID principles** and **layered architecture**. The application allows users to play chess games through Gmail, with OAuth authentication, custom labels, and AI-powered conversation summaries.

### Technology Stack
- **Backend**: Flask (Python)
- **Database**: SQLAlchemy (SQLite)
- **Authentication**: OAuth 2.0 (Google)
- **Email**: Gmail API / IMAP
- **AI**: OpenAI API (GPT-4o-mini)
- **Frontend**: Tailwind CSS, Vanilla JS
- **Chess**: chess.js, chessboard.js

---

## SOLID Principles Implementation

### 1. Single Responsibility Principle (SRP)
**"Each class/module should have one, and only one, reason to change"**

#### Implementation:
- **Service Layer**: Each service has a single responsibility
  - `ThreadService`: Thread management
  - `LabelService`: Custom label management
  - `EmailService`: Email operations (fetch/sync)
  - `SummaryService`: AI summary generation

- **Route Handlers**: Routes only handle HTTP concerns (request/response)
  - Business logic delegated to services
  - No direct database access in routes

**Example:**
```python
# BAD (Old code - multiple responsibilities)
@mail_bp.route("/inbox")
def inbox():
    # Fetches threads, enriches data, handles POST, renders template
    threads = db.session.query(Thread)...  # DB access
    for thread in threads:
        # Complex enrichment logic
    # Label fetching
    # Thread creation logic
    return render_template(...)

# GOOD (Refactored - single responsibility)
@mail_bp.route("/inbox")
def inbox():
    threads = thread_service.get_threads_for_user(user_id, user_email)
    custom_labels = label_service.get_user_labels(user_id)
    return render_template(...)
```

### 2. Open/Closed Principle (OCP)
**"Software entities should be open for extension, closed for modification"**

#### Implementation:
- **Service Factory Pattern**: Easy to add new services without modifying existing code
- **Configuration-based**: API keys and settings in environment variables
- **Template-based rendering**: UI changes don't require code changes

**Example:**
```python
# Easy to extend with new services
def get_summary_service():
    """Factory method - can be extended to use different AI providers"""
    return SummaryService()  # Could switch to different provider without changing routes
```

### 3. Liskov Substitution Principle (LSP)
**"Subtypes must be substitutable for their base types"**

#### Implementation:
- Services use consistent interfaces
- All services return standardized dictionary responses:
  ```python
  {"success": bool, "data": ..., "error": str}
  ```

### 4. Interface Segregation Principle (ISP)
**"Clients should not be forced to depend on interfaces they don't use"**

#### Implementation:
- Small, focused service methods
- No monolithic services with unused methods
- Each route uses only the service methods it needs

**Example:**
```python
# Instead of one monolithic MailService with 20 methods,
# we have focused services:
thread_service.get_threads_for_user()  # Only thread operations
label_service.get_user_labels()        # Only label operations
```

### 5. Dependency Inversion Principle (DIP)
**"Depend on abstractions, not concretions"**

#### Implementation:
- Routes depend on service abstractions, not database models directly
- Services injected at blueprint level
- Factory methods for lazy initialization

**Example:**
```python
# Dependency injection at module level
thread_service = ThreadService()
label_service = LabelService()

# Routes depend on service interface, not implementation
@mail_bp.route("/inbox")
def inbox():
    threads = thread_service.get_threads_for_user(...)  # Abstraction
```

---

## Architecture Layers

```
┌─────────────────────────────────────────────────┐
│              Presentation Layer                  │
│  (Templates, Static Files, JavaScript)          │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              Route Handlers                      │
│  (Flask Blueprints - HTTP Request/Response)     │
│  - blueprints/auth.py                           │
│  - blueprints/mail.py                           │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              Service Layer                       │
│  (Business Logic - SOLID Services)              │
│  - services/thread_service.py                   │
│  - services/label_service.py                    │
│  - services/email_service.py                    │
│  - services/summary_service.py                  │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              Utility Layer                       │
│  (External APIs, Helper Functions)              │
│  - utils/email_utils.py (IMAP/parsing)         │
│  - utils/gmail_api.py (Gmail API)              │
│  - utils/chess_utils.py (Chess logic)          │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│              Data Layer                          │
│  (Database Models, ORM)                         │
│  - models.py (User, Thread, Message, Label)    │
└─────────────────────────────────────────────────┘
```

### Layer Responsibilities

#### 1. Presentation Layer
- HTML templates (Jinja2)
- CSS styling (Tailwind)
- Client-side JavaScript
- **No business logic**

#### 2. Route Handlers (Controllers)
- HTTP request/response handling
- Authentication checks
- Input validation
- Delegates to services
- **No direct database access**

#### 3. Service Layer ⭐ **(New in refactoring)**
- **Business logic**
- Data transformation
- Orchestrates multiple operations
- Returns standardized responses
- **Single responsibility per service**

#### 4. Utility Layer
- External API integrations
- Helper functions
- Stateless operations

#### 5. Data Layer
- SQLAlchemy models
- Database schema
- Relationships

---

## Project Structure

```
mailchess/
│
├── app.py                      # Flask app initialization
├── models.py                   # Database models
├── environ.env                 # Environment variables (gitignored)
│
├── blueprints/                 # Route handlers
│   ├── __init__.py
│   ├── auth.py                 # OAuth authentication routes
│   └── mail.py                 # Mail routes (refactored - 400 lines vs 908)
│
├── services/                   # ⭐ NEW - Business logic layer
│   ├── __init__.py
│   ├── thread_service.py       # Thread management
│   ├── label_service.py        # Label management
│   ├── email_service.py        # Email operations
│   └── summary_service.py      # AI summarization
│
├── utils/                      # Utility functions
│   ├── __init__.py
│   ├── email_utils.py          # IMAP email fetching/parsing
│   ├── gmail_api.py            # Gmail API integration
│   └── chess_utils.py          # Chess move processing
│
├── templates/                  # Jinja2 templates
│   ├── inbox.html
│   ├── thread.html
│   └── error.html
│
├── static/                     # Static files
│   ├── img/
│   └── label_icons/            # User-uploaded label icons
│
└── instance/                   # Instance-specific data
    └── mailchess.db            # SQLite database
```

---

## Design Patterns

### 1. **Service Layer Pattern**
Separates business logic from presentation logic.

```python
# Service encapsulates business rules
class ThreadService:
    @staticmethod
    def get_threads_for_user(user_id, user_email):
        threads = db.session.query(Thread)...
        for thread in threads:
            ThreadService._enrich_thread(thread, user_email)
        return threads
```

### 2. **Factory Method Pattern**
Used for lazy initialization of services.

```python
def get_summary_service():
    """Factory method for SummaryService"""
    return SummaryService()  # Can be extended to different implementations
```

### 3. **Dependency Injection**
Services injected at module level, not created in routes.

```python
# Module level (mail.py)
thread_service = ThreadService()
label_service = LabelService()

# Routes use injected services
@mail_bp.route("/inbox")
def inbox():
    threads = thread_service.get_threads_for_user(...)
```

### 4. **Repository Pattern (Implicit)**
Services abstract data access, acting as repositories.

```python
# Service acts as repository
class ThreadService:
    @staticmethod
    def get_thread_by_id(thread_id, user_id):
        # Encapsulates query logic
        thread = Thread.query.get(thread_id)
        if thread and thread.user_id == user_id:
            return thread
        return None
```

---

## Data Flow

### Example: Fetching Inbox

```
1. User Request
   └─> GET /inbox
         │
2. Route Handler (mail.py)
   └─> inbox()
         │
         ├─> thread_service.get_threads_for_user()
         │     └─> Query DB, enrich data, return
         │
         └─> label_service.get_user_labels()
               └─> Query DB, return
         │
3. Render Template
   └─> inbox.html (threads + labels)
         │
4. Response
   └─> HTML to browser
```

### Example: Generating AI Summary

```
1. User Clicks Export Button
   └─> POST /api/thread/<id>/export
         │
2. Route Handler
   └─> api_export_conversation()
         │
         ├─> thread_service.get_thread_by_id()  # Verify ownership
         │     └─> Return thread
         │
         ├─> thread_service.get_thread_messages()  # Get messages
         │     └─> Return messages
         │
         └─> summary_service.generate_summary()  # AI summary
               │
               ├─> Format conversation
               ├─> Call OpenAI API
               └─> Return summary
         │
3. Response
   └─> JSON {"success": true, "summary": "...", "tokens_used": 150}
         │
4. Frontend
   └─> Typewriter animation displays summary
```

---

## Key Components

### Services

#### ThreadService
**Responsibility**: Thread management

**Methods**:
- `get_threads_for_user()` - Fetch and enrich threads
- `get_thread_by_id()` - Get thread with authorization
- `create_thread()` - Create new thread
- `get_thread_messages()` - Get messages for thread
- `format_message_for_api()` - Format message for API response
- `clear_user_threads()` - Delete all user threads

**SOLID**: Single responsibility (thread operations only)

#### LabelService
**Responsibility**: Custom label management

**Methods**:
- `get_user_labels()` - Get labels for user
- `create_label()` - Create new label with icon upload
- `delete_label()` - Delete label and remove from messages
- `format_label_for_api()` - Format label for API response

**SOLID**: Single responsibility (label operations only)

#### EmailService
**Responsibility**: Email synchronization

**Methods**:
- `fetch_new()` - Fetch new threads from Gmail
- `sync_existing()` - Sync existing threads with Gmail

**SOLID**: Delegates to utils/email_utils.py, adds error handling layer

#### SummaryService
**Responsibility**: AI-powered summarization

**Methods**:
- `generate_summary()` - Generate conversation summary via OpenAI
- `is_configured()` - Check if API key is available

**SOLID**: Single responsibility (AI summary only), configurable via dependency injection

**Configuration**:
```python
# System prompt controls output
def _get_system_prompt(self):
    return """Du er en hjælpsom assistent...
    Regler:
    - Maksimalt 3-5 sætninger
    - Fokuser på skakspillets status
    - Vær kort og præcis"""

# Token limit controls cost
max_tokens=200  # ~$0.00012 per summary
temperature=0.7  # Creativity level
```

---

## Improvements from Refactoring

### Before (Old Architecture)
❌ **Problems**:
- `mail.py`: 908 lines, multiple responsibilities
- Business logic mixed with route handlers
- Direct database access in routes
- Duplicated code
- Hard to test
- Violates SRP, DIP

### After (Refactored Architecture)
✅ **Improvements**:
- `mail.py`: ~400 lines, only route handling
- Service layer with single responsibilities
- Clean separation of concerns
- Dependency injection
- Testable services
- Follows all SOLID principles
- Reduced from 908 to 400 lines (-56%)

### Code Comparison

**Before (Old)**:
```python
@mail_bp.route("/inbox")
def inbox():
    # 50+ lines of mixed concerns:
    # - DB queries
    # - Data enrichment
    # - Label fetching
    # - Thread creation
    # - Rendering
```

**After (Refactored)**:
```python
@mail_bp.route("/inbox")
def inbox():
    # Clean, focused, 10 lines:
    threads = thread_service.get_threads_for_user(user_id, user_email)
    custom_labels = label_service.get_user_labels(user_id)
    return render_template("inbox.html", threads=threads, custom_labels=custom_labels)
```

---

## Testing Strategy

### Unit Testing Services
Services are easy to test in isolation:

```python
def test_thread_service():
    # Given
    user_id = 1
    user_email = "test@example.com"

    # When
    threads = thread_service.get_threads_for_user(user_id, user_email)

    # Then
    assert all(hasattr(t, 'latest_message_date') for t in threads)
    assert all(hasattr(t, 'other_person') for t in threads)
```

### Integration Testing Routes
Routes are easier to test with mocked services:

```python
def test_inbox_route(mock_thread_service, mock_label_service):
    response = client.get('/inbox')
    assert response.status_code == 200
    mock_thread_service.get_threads_for_user.assert_called_once()
```

---

## Future Enhancements

### 1. Add Repositories Layer
For complete separation of data access:
```
repositories/
  ├── thread_repository.py
  └── label_repository.py
```

### 2. Add DTOs (Data Transfer Objects)
For API response standardization:
```python
class ThreadDTO:
    def __init__(self, thread):
        self.id = thread.id
        self.subject = thread.subject
        # ...
```

### 3. Add Event System
For decoupled notifications:
```python
# Emit event when thread is created
event_bus.emit('thread.created', thread_id=thread.id)

# Subscribers can react
@event_bus.on('thread.created')
def send_notification(thread_id):
    # Send notification
```

### 4. Add Caching Layer
For performance:
```python
@cache.memoize(timeout=300)
def get_threads_for_user(user_id):
    # Cached for 5 minutes
```

---

## Conclusion

The refactored MailChess application now follows **SOLID principles** and uses a **layered architecture** with:

1. ✅ **Single Responsibility**: Each service has one job
2. ✅ **Dependency Injection**: Services injected, not created in routes
3. ✅ **Separation of Concerns**: Routes → Services → Utils → Models
4. ✅ **Testability**: Services can be tested in isolation
5. ✅ **Maintainability**: 56% code reduction in main blueprint
6. ✅ **Extensibility**: Easy to add new services/features

This architecture makes the codebase more maintainable, testable, and easier to understand.
