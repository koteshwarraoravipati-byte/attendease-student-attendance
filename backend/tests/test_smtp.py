from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
import socket
import pytest
from aiosmtpd.controller import Controller
from smtp_mail import SMTPTransport, configured_smtp
from test_password_security import app, issue, reset, login, NEW, GENERIC

class FakeSMTP:
    def __init__(self): self.events = []; self.message = None; self.reject = False
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def ehlo(self): self.events.append('ehlo')
    def starttls(self, context): self.events.append('starttls')
    def login(self, username, password): self.events.append(('login', username, password))
    def send_message(self, message):
        self.events.append('send'); self.message = message
        return {'recipient': (550, b'rejected')} if self.reject else {}

@pytest.mark.parametrize('security', ['starttls', 'ssl'])
def test_tls_and_auth(monkeypatch, security):
    smtp = FakeSMTP(); captured = {}
    def connect(host, port, **kwargs):
        captured.update(host=host,port=port,**kwargs)
        return smtp
    monkeypatch.setattr('smtp_mail.smtplib.SMTP', connect)
    monkeypatch.setattr('smtp_mail.smtplib.SMTP_SSL', connect)
    SMTPTransport('smtp.example.test', 587, 'AttendEase <sender@example.test>', security, 'user', 'test-password').send('demo@example.test','https://trusted.example/#reset-password?token=fake')
    assert smtp.events == (['ehlo','starttls','ehlo',('login','user','test-password'),'send'] if security == 'starttls' else ['ehlo',('login','user','test-password'),'send'])
    assert captured['timeout'] == 10
    if security == 'ssl': assert captured['context'].check_hostname
    assert smtp.message['To'] == 'demo@example.test'
    assert 'token=fake' in smtp.message.get_content()

def test_header_injection_and_refusal(monkeypatch):
    smtp = FakeSMTP(); smtp.reject = True
    monkeypatch.setattr('smtp_mail.smtplib.SMTP', lambda *a, **k: smtp)
    t = SMTPTransport('127.0.0.1',1025,'sender@example.test','none')
    with pytest.raises(ValueError): t.send('x@example.test\r\nBcc: stolen@example.test','fake')
    with pytest.raises(RuntimeError): t.send('x@example.test','fake')

@pytest.mark.parametrize('testing,host,security,allowed', [(False,'127.0.0.1','none',False),(True,'external.test','none',False),(True,'127.0.0.1','none',True),(False,'smtp.example.test','starttls',True),(False,'smtp.example.test','ssl',True),(True,'127.0.0.1','invalid',False)])
def test_configuration(testing,host,security,allowed):
    a = SimpleNamespace(testing=testing,config={'SMTP_HOST':host,'SMTP_PORT':'587','SMTP_SECURITY':security,'SMTP_FROM_EMAIL':'sender@example.test'})
    assert bool(configured_smtp(a)) == allowed
    a.config.update(SMTP_USERNAME='user',SMTP_PASSWORD='')
    assert configured_smtp(a) is None

def test_real_local_smtp_reset(app):
    messages = []
    class Capture:
        async def handle_DATA(self, server, session, envelope):
            messages.append(BytesParser(policy=policy.default).parsebytes(envelope.content))
            return '250 Local capture only'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); port = sock.getsockname()[1]
    server = Controller(Capture(),hostname='127.0.0.1',port=port)
    server.start()
    try:
        app.config.update(PASSWORD_MAIL_TRANSPORT=None,PASSWORD_MAIL_PROVIDER='smtp',SMTP_HOST='127.0.0.1',SMTP_PORT=port,SMTP_SECURITY='none',SMTP_FROM_EMAIL='sender@attendease.test',SMTP_USERNAME='',SMTP_PASSWORD='')
        old = login(app)
        response = app.test_client().post('/api/auth/forgot-password',json={'email':'admin@example.test'})
        assert response.json == GENERIC
        assert len(messages) == 1
        link = next(line for line in messages[0].get_content().splitlines() if line.startswith('https://trusted.example/'))
        token = link.split('token=')[1]
        assert reset(app,token).status_code == 200
        assert reset(app,token).status_code == 400
        assert app.test_client().get('/api/auth/me',headers={'Authorization':'Bearer '+old}).status_code == 401
        assert login(app,NEW)
    finally:
        server.stop()

def test_smtp_failure_stays_generic(app, monkeypatch):
    def fail_send(*args, **kwargs):
        raise OSError("simulated SMTP outage")
    monkeypatch.setattr("smtp_mail.SMTPTransport.send", fail_send)
    app.config.update(PASSWORD_MAIL_TRANSPORT=None,PASSWORD_MAIL_PROVIDER='smtp',SMTP_HOST='127.0.0.1',SMTP_PORT=1,SMTP_SECURITY='none',SMTP_FROM_EMAIL='sender@attendease.test',SMTP_USERNAME='',SMTP_PASSWORD='')
    response = app.test_client().post('/api/auth/forgot-password',json={'email':'admin@example.test'})
    assert response.status_code == 200 and response.json == GENERIC
    from models import db, PasswordResetToken
    with app.app_context(): assert PasswordResetToken.query.count() == 0
