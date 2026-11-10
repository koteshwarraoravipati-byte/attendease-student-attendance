"""Run a disposable local app and inbox. Never deploy this development script."""
import os
# Set these before importing app/config; ignore any production connection settings.
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['MONGO_URI'] = 'mongodb://127.0.0.1:27018/'
os.environ['MONGODB_URI'] = 'mongodb://127.0.0.1:27018/'
import html
import secrets
import tempfile
import threading
from collections import deque
from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from aiosmtpd.controller import Controller
from flask import send_from_directory
from app import create_app
from models import db, User

MESSAGES = deque(maxlen=20)
LOCK = threading.Lock()

class CaptureMail:
    async def handle_DATA(self, server, session, envelope):
        message = BytesParser(policy=policy.default).parsebytes(envelope.content)
        body = message.get_body(preferencelist=('plain',))
        text = body.get_content() if body else ''
        with LOCK:
            MESSAGES.append({'to': str(message.get('To', '')), 'subject': str(message.get('Subject', '')), 'body': text})
        return '250 Captured locally; no external delivery'

class Inbox(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass
    def do_GET(self):
        if self.path != '/':
            self.send_error(404)
            return
        with LOCK:
            messages = list(MESSAGES)
        parts = ['<!doctype html><html><head><meta charset="utf-8"><title>AttendEase local test inbox</title></head><body>',
                 '<h1>AttendEase local test inbox</h1><p>Local-only captured emails. Nothing is sent externally. Refresh to see new messages.</p>',
                 '<p><a href="http://127.0.0.1:5001/">Open AttendEase demo</a></p>']
        for message in reversed(messages):
            parts.append('<article><h2>' + html.escape(message['subject']) + '</h2><p>To: ' + html.escape(message['to']) + '</p><pre>' + html.escape(message['body']) + '</pre>')
            for line in message['body'].splitlines():
                parsed = urlsplit(line.strip())
                if parsed.scheme == 'http' and parsed.netloc == '127.0.0.1:5001' and parsed.fragment.startswith('reset-password?token='):
                    parts.append('<p><a href="' + html.escape(line.strip(), quote=True) + '">Set a new demo password</a></p>')
            parts.append('</article><hr>')
        if not messages:
            parts.append('<p>No messages yet. Request a reset for demo@attendease.test.</p>')
        payload = (''.join(parts) + '</body></html>').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

def main():
    frontend = Path(__file__).resolve().parent.parent / 'frontend' / 'dist-local'
    if not (frontend / 'index.html').exists():
        raise SystemExit('Build frontend/dist-local first; see SMTP_LOCAL_TEST.md.')
    smtp = Controller(CaptureMail(), hostname='127.0.0.1', port=1025, data_size_limit=65536)
    inbox = ThreadingHTTPServer(('127.0.0.1', 8025), Inbox)
    with tempfile.TemporaryDirectory(prefix='attendease-demo-') as folder:
        app = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(Path(folder) / 'demo.db'),
            'SQLALCHEMY_ENGINE_OPTIONS': {}, 'JWT_SECRET_KEY': secrets.token_urlsafe(48),
            'ACTIVITY_LOG_FILE': str(Path(folder) / 'activity.jsonl'), 'CORS_ORIGINS': ['http://127.0.0.1:5001'],
            'FRONTEND_URL': 'http://127.0.0.1:5001', 'PASSWORD_MAIL_PROVIDER': 'smtp',
            'PASSWORD_MAIL_TRANSPORT': None, 'SMTP_HOST': '127.0.0.1', 'SMTP_PORT': 1025,
            'SMTP_SECURITY': 'none', 'SMTP_USERNAME': '', 'SMTP_PASSWORD': '', 'SMTP_FROM_EMAIL': 'AttendEase <no-reply@attendease.test>'})
        with app.app_context():
            db.create_all()
            user = User(email='demo@attendease.test', role='ADMIN', is_active=True, recovery_email_verified=True)
            user.set_password('Local demo password 123!')
            db.session.add(user)
            db.session.commit()
        @app.get('/')
        def index():
            return send_from_directory(frontend, 'index.html')
        @app.get('/assets/<path:filename>')
        def assets(filename):
            return send_from_directory(frontend / 'assets', filename)
        smtp.start()
        threading.Thread(target=inbox.serve_forever, daemon=True).start()
        print('Demo: http://127.0.0.1:5001/ | Inbox: http://127.0.0.1:8025/', flush=True)
        print('Synthetic account: demo@attendease.test | Initial password: Local demo password 123!', flush=True)
        try:
            app.run(host='127.0.0.1', port=5001, debug=False, use_reloader=False)
        finally:
            inbox.shutdown()
            inbox.server_close()
            smtp.stop()
            with app.app_context():
                db.session.remove()
                db.engine.dispose()

if __name__ == '__main__':
    main()
