# desktop_main.py
# Entrypoint to run the project's Flask app locally and open it in a native window (pywebview).
# Recommended location: repo root (MailChess/desktop_main.py)

import threading
import time
import socket
import sys
import webview

# ADDED specific imports needed for the direct app import
from flask import session 
from app import app # <-- DIRECTLY IMPORTING THE APP INSTANCE

HOST = "127.0.0.1"
PORT = 5000
ROOT_URL = f"http://{HOST}:{PORT}/"

# --- MODIFIED FUNCTION ---
def import_app():
    """
    Directly returns the Flask app object imported from the app module.
    """
    try:
        # Since we imported 'app' directly above, we just return it.
        # Ensure session is imported globally for context management.
        return app
    except ImportError as e:
        # This block should be caught by the general exception handler above.
        raise ImportError(
            f"Could not import Flask app: {e}"
        ) from e
    except Exception as e:
        # Re-raise initialization crashes (e.g., missing keys)
        print(f"CRITICAL APP INIT ERROR: {e}", file=sys.stderr)
        raise e
# --- END MODIFIED FUNCTION ---

def is_port_open(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False

def run_flask(app):
    # Prefer waitress if available in bundled environment
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT)
    except Exception:
        # Dev server is fine for a local desktop app
        app.run(host=HOST, port=PORT, debug=False, threaded=True)

def run_server_in_thread(app):
    t = threading.Thread(target=run_flask, args=(app,), daemon=True)
    t.start()
    return t

def wait_for_server(host, port, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_port_open(host, port):
            return True
        time.sleep(0.1)
    return False

def main():
    try:
        # The app object is now imported and returned directly
        app = import_app() 
    except Exception as e:
        print("ERROR importing app:", e, file=sys.stderr)
        sys.exit(1)

    run_server_in_thread(app)

    if not wait_for_server(HOST, PORT, timeout=10.0):
        print(f"ERROR: server did not start on {HOST}:{PORT}", file=sys.stderr)
        sys.exit(1)

    # Open the root so the window uses your existing base.html and UI
    window = webview.create_window("MailChess", ROOT_URL, width=1100, height=780, resizable=True)
    webview.start()

if __name__ == "__main__":
    main()