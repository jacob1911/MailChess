import os
from flask import Flask, render_template
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth

# Load environment variables FIRST (before importing blueprints)
load_dotenv('environ.env')

from models import db
from blueprints.auth import auth_bp, init_oauth
from blueprints.mail import mail_bp

# Initialize Flask app
app = Flask(__name__)
# Use absolute path for database to ensure it works from any directory
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{os.path.join(basedir, "instance", "mailchess.db")}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

# Upload configuration
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'label_icons')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'svg'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2MB max file size

# Create upload folder if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize database
db.init_app(app)

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
        "prompt": "consent"  # Force consent screen to update permissions
    }
)

# Pass oauth to auth blueprint
init_oauth(oauth)

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(mail_bp)


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


if __name__ == "__main__":
    if not os.path.exists("instance/mailchess.db"):
        init_db()
    app.run(debug=True)
