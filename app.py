import os
import secrets # REQUIRED for generating unique FLASK_SECRET_KEY
from flask import Flask, render_template, session, redirect, url_for, request
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from datetime import timedelta
from flask_babel import Babel, gettext as _

# --- HARDCODED PUBLIC KEYS (ZERO-SETUP IMPLEMENTATION) ---
# These are the actual keys extracted from environ.env, now embedded for public distribution.
MAILCHESS_GOOGLE_CLIENT_ID = "302768656386-oq61tfoje3s0u3o0ss2qhuj0cfrivq46.apps.googleusercontent.com"
MAILCHESS_GOOGLE_CLIENT_SECRET = "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" 
# ---------------------------------------------------------


# Load environment variables FIRST. This is now PRIMARILY to load the optional OPENAI_API_KEY.
load_dotenv('environ.env', override=True)

print("---------------------------------------------------")
print(f"DEBUG: Loaded Client ID: {MAILCHESS_GOOGLE_CLIENT_ID}") 
print("---------------------------------------------------")
# ---------------------------

from models import db
from blueprints.auth import auth_bp, init_oauth
from blueprints.mail import mail_bp
from blueprints.stats import stats_bp

# Initialize Flask app
app = Flask(__name__)
# Use absolute path for database to ensure it works from any directory
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instance", "mailchess.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# --- FLASK SECRET KEY GENERATION (ZERO-SETUP IMPLEMENTATION) ---
# 1. Check if FLASK_SECRET_KEY is provided in the environment (e.g., via a developer's environ.env)
provided_secret = os.environ.get("FLASK_SECRET_KEY")

if provided_secret is None:
    # 2. If missing, generate a new, secure key at runtime for this instance/session
    app.config['SECRET_KEY'] = secrets.token_hex(32)
else:
    # 3. If present, use the one from the environment (for developers/testing)
    app.config['SECRET_KEY'] = provided_secret

# Set the application's secret key
app.secret_key = app.config['SECRET_KEY']
# ----------------------------------------------------

# This keeps the login cookie valid for 31 days if requested
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)
# --------------------------------------

# --- BABEL/LOCALIZATION CONFIGURATION ---
app.config['BABEL_DEFAULT_LOCALE'] = 'da'
app.config['BABEL_TRANSLATION_DIRECTORIES'] = 'translations'
babel = Babel(app)

def get_locale():
    # 1. Check if language is explicitly set in session (via switch)
    if 'lang' in session:
        return session['lang']
    # 2. Check the language accepted by the browser
    return request.accept_languages.best_match(['da', 'en'])

babel.locale_selector = get_locale

@app.context_processor
def inject_gettext():
    # Make _() available directly in templates without passing it
    return dict(_=_)
# ----------------------------------------

# --- BLUEPRINT REGISTRATION ---
app.register_blueprint(auth_bp, url_prefix='/auth')
app.register_blueprint(mail_bp, url_prefix='/')
app.register_blueprint(stats_bp, url_prefix='/mail_stats')
# ------------------------------

# Upload configuration
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'label_icons')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'zip', 'pgn'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
db.init_app(app)

# --- REVERTED: Removed 'migrate = Migrate(app, db)' ---

# Initialize OAuth
oauth = OAuth(app)
oauth.register(
    name="google",
    # Use the hardcoded constants defined above (Zero-Setup Fix)
    client_id=MAILCHESS_GOOGLE_CLIENT_ID,
    client_secret=MAILCHESS_GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile https://mail.google.com/",
        "access_type": "offline",
        "prompt": "consent"
    }
)

# Pass oauth to auth blueprint
init_oauth(oauth)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('error.html', error_code=404, error_message=_("Siden blev ikke fundet")), 404 # <-- USED _()

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('error.html', error_code=500, error_message=_("Der opstod en intern serverfejl")), 500 # <-- USED _()

@app.errorhandler(Exception)
def handle_exception(error):
    db.session.rollback()
    app.logger.error(f"Unhandled exception: {error}")
    return render_template('error.html', error_code=500, error_message=_("Der opstod en uventet fejl")), 500 # <-- USED _()


# --- NEW: Language Switch Route
@app.route('/set_language/<lang_code>')
def set_language(lang_code):
    if lang_code in ['en', 'da']:
        session['lang'] = lang_code
    
    # 1. Check for referrer (where the user came from)
    referrer = request.referrer
    if referrer and referrer.startswith(request.url_root):
        # If the referrer is a URL within our app, redirect there.
        return redirect(referrer)
        
    # 2. Otherwise, redirect to the main inbox page.
    return redirect(url_for('mail.inbox'))


def init_db():
    """Initialize database tables"""
    with app.app_context():
        db.create_all()

# Root route to handle redirects
@app.route("/")
def index():
    # If the user is logged in, redirect them to the mail inbox
    if session.get("user"):
        return redirect(url_for("mail.inbox"))
    
    # If not logged in, redirect them to the login page
    return redirect(url_for("auth.auth_login_page"))

if __name__ == "__main__":
    if not os.path.exists("instance/mailchess.db"):
        init_db()
    app.run(debug=True)