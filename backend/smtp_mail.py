"""SMTP recovery delivery. Plaintext is allowed only for loopback test inboxes."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr


def valid_address(value):
    return isinstance(value, str) and '\r' not in value and '\n' not in value and '@' in parseaddr(value)[1]


class SMTPTransport:
    def __init__(self, host, port, sender, security='starttls', username='', password=''):
        self.host, self.port, self.sender = host, port, sender
        self.security, self.username, self.password = security, username, password

    def send(self, email, link):
        if not all(valid_address(address) for address in (self.sender, email)):
            raise ValueError('Invalid mail address')
        message = EmailMessage()
        message['From'] = self.sender
        message['To'] = email
        message['Subject'] = 'Reset your AttendEase password'
        message.set_content('Use this single-use link within 15 minutes to reset your password:\n' + link +
                            '\nIf you did not request this, ignore this message.')
        context = ssl.create_default_context()
        connection = (smtplib.SMTP_SSL(self.host, self.port, timeout=10, context=context)
                      if self.security == 'ssl' else smtplib.SMTP(self.host, self.port, timeout=10))
        with connection as smtp:
            smtp.ehlo()
            if self.security == 'starttls':
                smtp.starttls(context=context)
                smtp.ehlo()
            if self.username:
                smtp.login(self.username, self.password)
            if smtp.send_message(message):
                raise RuntimeError('SMTP recipient rejected')


def configured_smtp(app):
    host, sender = app.config.get('SMTP_HOST', ''), app.config.get('SMTP_FROM_EMAIL', '')
    security = app.config.get('SMTP_SECURITY', 'starttls')
    username, password = app.config.get('SMTP_USERNAME', ''), app.config.get('SMTP_PASSWORD', '')
    try:
        port = int(app.config.get('SMTP_PORT', 587))
    except (TypeError, ValueError):
        return None
    if not isinstance(host, str) or not host or not valid_address(sender) or not 1 <= port <= 65535:
        return None
    if security not in ('starttls', 'ssl', 'none') or bool(username) != bool(password):
        return None
    if security == 'none' and not (app.testing and host in ('127.0.0.1', '::1', 'localhost') and not username and not password):
        return None
    return SMTPTransport(host, port, sender, security, username, password)
