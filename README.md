# MailChess (Danish)
//For English scroll

En webapplikation der kombinerer email-funktionalitet med skakspil. Spil skak med dine venner gennem Gmail!

## Features

- Gmail integration via OAuth 2.0
- Interaktivt skakbræt i email-tråde
- Real-time IMAP/SMTP email synkronisering
- Automatisk parsing af chess moves fra emails (format: "Move: e2e4")
- Live opdatering af tråde uden side reload
- Spilhistorik og statistikker

## Teknologi

- **Backend**: Flask, SQLAlchemy, Python Chess
- **Frontend**: HTML, CSS, JavaScript, Chess.js, Chessboard.js
- **Database**: SQLite
- **Authentication**: Google OAuth 2.0

## Opsætning

**For detaljerede installations-instruktioner, se [SETUP.md](SETUP.md)**

### Hurtig start (Windows):

1. **Extract** zip-filen til en mappe
2. **Kør** `start.bat` for at sætte miljøet op:
   ```
   start.bat
   ```
   Dette vil automatisk:
   - Installere Python dependencies
   - Generere Flask secret key
   - Oprette `environ.env` fil
   - Sætte nødvendige mapper op

3. **Rediger** `environ.env` og tilføj dine Google OAuth credentials
4. **Kør** `desktop.bat` for at starte applikationen:
   ```
   desktop.bat
   ```

Applikationen åbner automatisk i et window på `http://localhost:5000`

### Krav:
- Python 3.10+
- Windows OS (Mac/Linux: se SETUP.md)

## Projekt Struktur

```
MailChess/
├── app.py                    # Hovedapplikation (Flask init)
├── models.py                 # Database modeller (User, Thread, Message, CustomLabel)
├── mail_stats.py             # Mail statistik service
├── blueprints/               # Flask blueprints
│   ├── auth.py              # Google OAuth autentificering
│   ├── mail.py              # Email, threads, wheel of fortune, og API endpoints
│   └── stats.py             # Email statistik og analyse
├── utils/                    # Hjælpefunktioner
│   ├── email_utils.py       # Email håndtering, IMAP/SMTP, thread storage
│   ├── gmail_api.py         # Google Gmail API integration
│   └── chess_utils.py       # Skak logik og validering
├── templates/                # HTML skabeloner (Jinja2)
│   ├── base.html            # Base template med navigation
│   ├── inbox.html           # Inbox UI med wheel of fortune modal
│   ├── thread.html          # Tråd visning
│   └── ...
├── static/                   # Statiske filer
│   ├── css/                 # Stylesheets (Tailwind CSS)
│   ├── js/                  # JavaScript
│   └── img/                 # Billeder og ikoner
├── instance/                 # Database og lokale data (SQLite)
├── stockfish/                # Stockfish chess engine source
├── start.bat                 # Windows setup script
├── desktop.bat               # Windows app launcher
├── setup_env.py              # Auto-generates environ.env
├── SETUP.md                  # Detaljeret installations guide
├── ARCHITECTURE.md           # Teknisk arkitektur dokumentation
└── requirements.txt          # Python dependencies
```

## Funktionalitet

### Hovedfeatures
- **Gmail Integration**: OAuth 2.0 login og email sync via IMAP
- **Chess Game Tracking**: Automatisk parsing af skak-moves fra emails
- **Live Email Sync**: Henter nye emails uden at reload siden
- **Custom Labels**: Opret og håndter custom email labels
- **Email Statistics**: Analyser dit email-mønster og sprogebrug
- **Wheel of Fortune**: Tilfældig email action selector med lokal database-ændring
- **Webview Desktop App**: Native window via pywebview

### Teknologi
- **Backend**: Flask, SQLAlchemy, Python Chess
- **Frontend**: HTML, CSS (Tailwind), JavaScript
- **Database**: SQLite
- **Authentication**: Google OAuth 2.0
- **Email**: IMAP, SMTP
- **Chess**: python-chess library

---

# MailChess (English)

A web application that combines email functionality with chess. Play chess with your friends through Gmail!

## Features

- Gmail integration via OAuth 2.0
- Interactive chess board in email threads
- Real-time IMAP/SMTP email synchronization
- Automatic chess move parsing from emails (format: "Move: e2e4")
- Live thread updates without page reload
- Game history and statistics
- Custom email labels with icons and colors
- Email pattern analysis and language statistics
- Wheel of Fortune: Random email action selector

## Technology

- **Backend**: Flask, SQLAlchemy, Python Chess
- **Frontend**: HTML, CSS (Tailwind), JavaScript
- **Database**: SQLite
- **Authentication**: Google OAuth 2.0
- **Email**: IMAP, SMTP
- **Chess**: python-chess library
- **Desktop**: PyWebview for native window

## Setup

**For detailed installation instructions, see [SETUP.md](SETUP.md)**

### Quick Start (Windows):

1. **Extract** the zip file to a folder
2. **Run** `start.bat` to set up the environment:
   ```
   start.bat
   ```
   This will automatically:
   - Install Python dependencies
   - Generate Flask secret key
   - Create `environ.env` file
   - Set up necessary directories

3. **Edit** `environ.env` and add your Google OAuth credentials
4. **Run** `desktop.bat` to start the application:
   ```
   desktop.bat
   ```

The application will automatically open in a window on `http://localhost:5000`

### Requirements:
- Python 3.10+
- Windows OS (Mac/Linux: see SETUP.md)

## Project Structure

```
MailChess/
├── app.py                    # Main Flask application
├── models.py                 # Database models (User, Thread, Message, CustomLabel)
├── mail_stats.py             # Email statistics service
├── blueprints/               # Flask blueprints
│   ├── auth.py              # Google OAuth authentication
│   ├── mail.py              # Email, threads, wheel of fortune, and API endpoints
│   └── stats.py             # Email statistics and analysis
├── utils/                    # Helper functions
│   ├── email_utils.py       # Email handling, IMAP/SMTP, thread storage
│   ├── gmail_api.py         # Google Gmail API integration
│   └── chess_utils.py       # Chess logic and validation
├── templates/                # HTML templates (Jinja2)
│   ├── base.html            # Base template with navigation
│   ├── inbox.html           # Inbox UI with wheel of fortune modal
│   ├── thread.html          # Thread view
│   └── ...
├── static/                   # Static files
│   ├── css/                 # Stylesheets (Tailwind CSS)
│   ├── js/                  # JavaScript
│   └── img/                 # Images and icons
├── instance/                 # Database and local data (SQLite)
├── stockfish/                # Stockfish chess engine source code
├── start.bat                 # Windows setup script
├── desktop.bat               # Windows app launcher
├── setup_env.py              # Auto-generates environ.env
├── SETUP.md                  # Detailed installation guide
├── ARCHITECTURE.md           # Technical architecture documentation
└── requirements.txt          # Python dependencies
```

## Main Features

### Core Functionality
- **Gmail Integration**: OAuth 2.0 login and email sync via IMAP
- **Chess Game Tracking**: Automatic parsing of chess moves from emails
- **Live Email Sync**: Fetch new emails without page reload
- **Custom Labels**: Create and manage custom email labels
- **Email Statistics**: Analyze your email patterns and language usage
- **Wheel of Fortune**: Random email action selector with local database changes
- **Webview Desktop App**: Native window via pywebview

### API Endpoints

Main endpoints for email and thread management:

- `GET /` - Inbox view
- `GET /thread/<id>` - Thread view with messages
- `POST /api/threads` - Fetch threads for inbox
- `POST /api/sync-existing` - Sync new emails in existing threads
- `POST /api/spin-wheel` - Get random wheel of fortune action
- `POST /api/execute-wheel-action` - Execute the wheel action
- `GET /api/custom-labels` - Get user's custom labels
- `POST /api/custom-labels` - Create new custom label

## Usage

### Email Synchronization
Click the **"Sync"** button in the inbox or thread view to:
1. Fetch new emails from Gmail
2. Automatically parse chess moves from email bodies
3. Update FEN positions with valid moves
4. Update UI without page reload

### Playing Chess
1. Send an email with a chess move in format: `Move: e2e4`
2. The app automatically parses the move
3. Chess board updates to show the new position
4. Game history is tracked per email thread

### Statistics
Visit the Stats page to view:
- Total emails and read/unread counts
- Top senders and recipients
- Most used words in your emails
- Email opening phrases
- Language usage patterns

---

**For more information, see ARCHITECTURE.md for technical details.**
