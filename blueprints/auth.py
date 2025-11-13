from flask import Blueprint, redirect, url_for, session, render_template
from authlib.integrations.flask_client import OAuth
from models import db, User

auth_bp = Blueprint('auth', __name__)

# OAuth will be initialized in app.py and passed here
oauth = None

def init_oauth(oauth_instance):
    global oauth
    oauth = oauth_instance


@auth_bp.route("/login")
def login():
    # Check if user is already logged in
    if session.get("user"):
        return redirect(url_for("mail.inbox"))

    # Show login page
    return render_template("login.html")


@auth_bp.route("/login/google")
def login_google():
    """Actual OAuth redirect"""
    redirect_uri = url_for("auth.auth_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/auth/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    access_token = token["access_token"]
    userinfo = token["userinfo"]

    # Get or create user in database
    google_id = userinfo.get("sub")
    email = userinfo.get("email")
    name = userinfo.get("name")
    picture = userinfo.get("picture")

    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            picture=picture
        )
        db.session.add(user)
        db.session.commit()
    else:
        # Update user info if changed
        user.email = email
        user.name = name
        user.picture = picture
        db.session.commit()

    # Store user info and access token in session
    session["user"] = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture
    }
    session["access_token"] = access_token
    return redirect(url_for("mail.inbox"))


@auth_bp.route("/logout")
def logout():
    """Logout user and clear session"""
    session.clear()
    return redirect(url_for("auth.login"))
