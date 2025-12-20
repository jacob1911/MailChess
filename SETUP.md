# MailChess - Setup & Installation Guide

This guide walks you through setting up MailChess on your Windows machine.

## Prerequisites

Before starting, ensure you have:

- **Python 3.10+** installed ([Download](https://www.python.org/downloads/))
- **Git** installed ([Download](https://git-scm.com/download/win))
- A **Google account** (for OAuth)
- The **shared OpenAI API key** (ask the development team)

## Installation Steps

### Step 1: Clone the Repository

```powershell
git clone https://github.com/jacob1911/MailChess.git
cd MailChess
```

### Step 2: Run Setup Script

Double-click **`start.bat`** (or run in PowerShell):

```powershell
.\start.bat
```

This script will:
1. ✅ Check Python installation
2. ✅ Create a virtual environment (`.venv`)
3. ✅ Install all dependencies from `requirements.txt`
4. ✅ **Generate Flask secret key automatically**
5. ✅ Create `environ.env` with placeholders
6. ✅ Create necessary directories (`instance/`, `static/label_icons/`)

**Console Output:**
```
[1/5] Configuring Execution Policy...
[2/5] Checking Python installation...
[3/5] Setting up Virtual Environment...
[4/5] Setting up environment configuration...


```

### Step 3: Configure Environment Variables

After `start.bat` completes, edit the file **`environ.env`** in the project root folder if not already filled. 

#### Getting OpenAI API Key

**⚠️ IMPORTANT: Do NOT create your own key!**

- Use the **shared OpenAI API key** provided by the development team
- This key has **paid tokens** that are shared for development
- Copy the shared key (format: `sk-proj-...`) into `environ.env`
- Contact the team if you don't have the key

### Step 4: Launch the Application

Double-click **`desktop_start.bat`** (or run in PowerShell):

```powershell
.\desktop_start.bat
```

The app will:
1. Start Flask server on `http://127.0.0.1:5000`
2. Open a native window (pywebview)
3. Load the MailChess interface

A window titled **"MailChess"** should appear. You can now:
- Log in with your Google account
- Browse your emails
- Play chess with collaborators

## Troubleshooting

### Python not found
**Error:** `[ERROR] Python is not installed!`

**Solution:** Install Python 3.10+ from [python.org](https://www.python.org/downloads/) and make sure to check "Add Python to PATH" during installation.

### Dependencies installation fails
**Error:** `[ERROR] Failed to install dependencies`

**Solution:** 
```powershell
# Try upgrading pip first
python -m pip install --upgrade pip
# Then run setup.bat again
.\setup.bat
```

### environ.env not created
**Error:** Script runs but no `environ.env` file appears

**Solution:** Check that `setup_env.py` ran without errors. You can manually run:
```powershell
python setup_env.py
```

### App crashes on startup
**Error:** Black window appears and closes, or error message in console

**Solution:**
1. Check that all credentials are filled in `environ.env`
2. Verify Flask secret key is present
3. Check `environ.env` has no typos or trailing spaces
4. Run `desktop_start.bat` again with the console open to see error messages

### Google login fails
**Error:** "Unauthorized" or "Invalid credentials"

**Solution:**
1. Verify `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are correct in `environ.env`

### OpenAI API errors
**Error:** "Invalid API key" or "Authentication failed"

**Solution:**
1. Verify you're using the **shared team key**, not a personal key
2. Check that the key is correctly copied into `environ.env` (no extra spaces)
3. Contact the development team if the key has expired

## File Structure Reference

```
MailChess/
├── setup.bat              # Run first for setup
├── desktop_start.bat            # Run to launch the app
├── setup_env.py           # Auto-generates environ.env
├── environ.env            # Your configuration (auto-created, add credentials here)
├── environ.env.example    # Template showing what's needed
├── requirements.txt       # Python dependencies
├── app.py                 # Flask application entry point
├── models.py              # Database models
├── .venv/                 # Virtual environment (created by start.bat)
├── instance/              # Database location (created by start.bat)
├── templates/             # HTML templates (Jinja2)
├── static/                # CSS, JavaScript, images
└── blueprints/            # Flask blueprints (auth, mail, stats, etc.)
```

## Next Steps

After successful setup:

1. **Log in** with your Google account
2. **Explore the inbox** - your emails will sync from Gmail
3. **Play chess** - Send moves in emails, the app tracks the game
4. **View statistics** - Check email patterns and language usage

## Need Help?

- Check the `README.md` for project overview
- See `ARCHITECTURE.md` for technical details
- Ask the development team for clarification

---

**Happy chess mailing!** ♟️
