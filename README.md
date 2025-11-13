# MailChess

En webapplikation der kombinerer email-funktionalitet med skakspil. Spil skak med dine venner gennem Gmail!

## Features

- Gmail integration via OAuth 2.0
- Interaktivt skakbræt i email-tråde
- Real-time IMAP/SMTP email synkronisering
- **Publisher-Subscriber pattern** for email sync
- Automatisk parsing af chess moves fra emails (format: "Move: e2e4")
- Live opdatering af tråde uden side reload
- Spilhistorik og statistikker

## Teknologi

- **Backend**: Flask, SQLAlchemy, Python Chess
- **Frontend**: HTML, CSS, JavaScript, Chess.js, Chessboard.js
- **Database**: SQLite
- **Authentication**: Google OAuth 2.0

## Opsætning

1. Installer dependencies:
```bash
pip install flask flask-sqlalchemy python-chess authlib python-dotenv requests
```

2. Opret `environ.env` fil med dine credentials:
```
FLASK_SECRET_KEY=your-secret-key
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
```

3. Kør applikationen:
```bash
python app.py
```

4. Besøg `http://localhost:5000` i din browser

## Projekt Struktur

```
├── app.py              # Hovedapplikation
├── models.py           # Database modeller
├── blueprints/         # Flask blueprints
│   ├── auth.py        # Autentificering
│   └── mail.py        # Email, threads og API endpoints
├── utils/              # Hjælpefunktioner
│   ├── email_utils.py # Email håndtering
│   ├── chess_utils.py # Skak logik
│   ├── event_bus.py   # Publisher-Subscriber event system
│   └── email_sync.py  # Email synkronisering service
├── templates/          # HTML skabeloner
└── static/             # Statiske filer
```

## Publisher-Subscriber Pattern

Applikationen bruger et event-drevet architecture:

### Events
- `sync_started` - Udsendes når email sync starter
- `email_fetched` - Udsendes for hver hentet email
- `thread_updated` - Udsendes når en tråd opdateres
- `thread_created` - Udsendes når en ny tråd oprettes
- `move_parsed` - Udsendes når et chess move parses fra email
- `sync_completed` - Udsendes når sync er færdig
- `sync_failed` - Udsendes ved fejl

### API Endpoints
- `POST /api/sync` - Synkroniser emails
- `GET /api/threads` - Hent opdateret tråd liste
- `GET /api/thread/<id>/messages` - Hent opdaterede beskeder for en tråd

### Brug
Klik på **"Synkroniser"** knappen i inbox eller i en tråd for at:
1. Hente nye emails fra Gmail
2. Parse chess moves automatisk
3. Opdatere FEN position
4. Opdatere UI uden page reload
