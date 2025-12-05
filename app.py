import os
from flask import Flask, render_template, session, redirect, url_for
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from datetime import timedelta
# --- REVERTED: Removed 'from flask_migrate import Migrate' ---

# Load environment variables FIRST (before importing blueprints)
load_dotenv('environ.env', override=True)

print("---------------------------------------------------")
print(f"DEBUG: Loaded Client ID: {os.environ.get('GOOGLE_CLIENT_ID')}")
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
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

# This keeps the login cookie valid for 31 days if requested
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=31)
# --------------------------------------

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
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
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
    return render_template('error.html', error_code=404, error_message="Siden blev ikke fundet"), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('error.html', error_code=500, error_message="Der opstod en intern serverfejl"), 500

@app.errorhandler(Exception)
def handle_exception(error):
    db.session.rollback()
    app.logger.error(f"Unhandled exception: {error}")
    return render_template('error.html', error_code=500, error_message="Der opstod en uventet fejl"), 500

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