# desktop_main.py
# Place at repo root. Adjust import to your real app factory or blueprint registration.

import threading
import time
import socket
import sys
import webview

# Try to use waitress as a more stable embedded server in packaged apps
try:
    from waitress import serve as waitress_serve
    HAVE_WAITRESS = True
except Exception:
    HAVE_WAITRESS = False

# Import/create your Flask app here. If you already have create_app(), import it.
# Example: from mail_stats import create_app
# Replace with the real import in your repo.
from mail_stats import create_app

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}/"        # main page
MAIL_STATS_ROUTE = f"http://{HOST}:{PORT}/mail_stats"  # specific stats route

def start_flask_with_waitress(app, host, port):
    # waitress will block; run in a thread
    waitress_serve(app, host=host, port=port)

def start_flask_dev(app, host, port):
    # Flask dev server (threaded) — acceptable for a local desktop app
    app.run(host=host, port=port, debug=False, threaded=True)

def is_port_open(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect((host, port))
            return True
        except Exception:
            return False

def run_server_in_thread(app):
    if HAVE_WAITRESS:
        t = threading.Thread(target=start_flask_with_waitress, args=(app, HOST, PORT), daemon=True)
    else:
        t = threading.Thread(target=start_flask_dev, args=(app, HOST, PORT), daemon=True)
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
    app = create_app()  # your factory that registers routes and templates
    server_thread = run_server_in_thread(app)

    # Wait until server is ready (health-check)
    if not wait_for_server(HOST, PORT, timeout=10.0):
        print(f"ERROR: server did not start on {HOST}:{PORT}", file=sys.stderr)
        sys.exit(1)

    # Choose which URL to open (main or mail stats)
    open_url = MAIL_STATS_ROUTE  # change to URL if you want root page

    # Create a native window that loads the local web app
    window = webview.create_window("MailChess", open_url, width=1100, height=780)
    webview.start()  # blocks until window is closed

    # When window closes, exit — server thread is daemon so process ends
    sys.exit(0)

if __name__ == "__main__":
    main()

