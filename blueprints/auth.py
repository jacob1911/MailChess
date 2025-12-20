from flask import Blueprint, redirect, url_for, session, render_template, request # <-- ADDED request
from authlib.integrations.flask_client import OAuth
from models import db, User
from datetime import datetime, timezone

auth_bp = Blueprint('auth', __name__)

oauth = None

def init_oauth(oauth_instance):
    global oauth
    oauth = oauth_instance

@auth_bp.route("/logout")
def logout():
    """Logout user and clear session"""
    session.pop("user", None)
    session.pop("access_token", None)
    session.clear() 
    return redirect(url_for("auth.auth_login_page"))

@auth_bp.route("/login")
def auth_login_page():
    if session.get("user"):
        return redirect(url_for("mail.inbox"))
    return render_template("login.html")

@auth_bp.route("/login/google")
def login_google():
    """Actual OAuth redirect"""
    # --- NEW: Check if 'Remember Me' was checked ---
    if request.args.get('remember_me'):
        session['remember_me_temp'] = True
    # -----------------------------------------------

    redirect_uri = url_for("auth.auth_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route("/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    access_token = token["access_token"]
    refresh_token = token.get("refresh_token")
    userinfo = token["userinfo"]

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
            picture=picture,
            last_sync=datetime.now(timezone.utc)  # Set last_sync to login time for new users
        )
        if refresh_token:
            user.refresh_token = refresh_token
        db.session.add(user)
        db.session.commit()
    else:
        if refresh_token:
            user.refresh_token = refresh_token
        user.email = email
        user.name = name
        user.picture = picture
        db.session.commit()

    session["user"] = {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture
    }
    session["access_token"] = access_token

    # --- NEW: Apply Permanent Session ---
    if session.pop('remember_me_temp', None):
        session.permanent = True
    else:
        session.permanent = False
    # ------------------------------------

    return redirect(url_for("mail.inbox"))