import os
os.environ.setdefault("DATABASE_URL", "sqlite:///test_attendance.db")
os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:27018/")
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pytest
from flask_jwt_extended import create_access_token
from app import create_app
from models import db, User, PasswordResetToken, PasswordRateLimit
from password_security import digest, GENERIC, ResendTransport

OLD = "Original password 123!"
NEW = "A replacement password 456!"

class MemoryMail:
    def __init__(self):
        self.messages = []
        self.fail = False
    def send(self, email, link):
        if self.fail:
            raise RuntimeError("provider failure with secret that must not be logged")
        self.messages.append((email, link))

@pytest.fixture
def app(tmp_path):
    mail = MemoryMail()
    a = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///" + str(tmp_path / "security.db"),
        "SQLALCHEMY_ENGINE_OPTIONS": {"connect_args": {"timeout": 15}},
        "JWT_SECRET_KEY": "test-secret-which-is-more-than-thirty-two-characters", "FRONTEND_URL": "https://trusted.example",
        "PASSWORD_MAIL_TRANSPORT": mail, "ACTIVITY_LOG_FILE": str(tmp_path / "activity.jsonl")})
    with a.app_context():
        db.create_all()
        for email, active, verified in [("admin@example.test", True, True), ("inactive@example.test", False, True),
                ("unverified@example.test", True, False)]:
            u = User(email=email, role="ADMIN", is_active=active, recovery_email_verified=verified)
            u.set_password(OLD)
            db.session.add(u)
        db.session.commit()
    a.mail = mail
    yield a
    with a.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()

def login(app, password=OLD):
    return app.test_client().post("/api/auth/login", json={"email": "admin@example.test", "password": password}).json["token"]

def issue(app, email="admin@example.test", **kwargs):
    response = app.test_client().post("/api/auth/forgot-password", json={"email": email}, **kwargs)
    assert response.status_code == 200 and response.json == GENERIC
    if app.mail.messages:
        return app.mail.messages[-1][1].split("token=")[1]

def reset(app, token, password=NEW):
    return app.test_client().post("/api/auth/reset-password", json={"token": token, "new_password": password})

def test_generic_eligibility_and_no_host_injection(app):
    for email in ["missing@example.test", "inactive@example.test", "unverified@example.test"]:
        issue(app, email)
    assert not app.mail.messages
    raw = issue(app, headers={"Host": "evil.example", "X-Forwarded-Host": "evil.example"})
    assert app.mail.messages[-1][1] == "https://trusted.example/#reset-password?token=" + raw
    with app.app_context():
        t = PasswordResetToken.query.one()
        assert t.token_hash == digest(raw) and raw not in t.token_hash
        assert 890 < (t.expires_at - datetime.utcnow()).total_seconds() <= 900

def test_reset_single_use_and_all_session_invalidation(app):
    old_jwt = login(app)
    raw = issue(app)
    another = issue(app)
    assert reset(app, raw).status_code == 200
    assert reset(app, raw).status_code == 400
    assert reset(app, another).status_code == 400
    for path in ["/api/auth/me", "/api/admin/overview", "/api/faculty/subjects", "/api/student/summary"]:
        assert app.test_client().get(path, headers={"Authorization": "Bearer " + old_jwt}).status_code == 401
    token = login(app, NEW)
    assert app.test_client().get("/api/admin/overview", headers={"Authorization": "Bearer " + token}).status_code == 200
    assert app.test_client().post("/api/auth/login", json={"email": "admin@example.test", "password": OLD}).status_code == 401

def test_expired_invalid_and_policy(app):
    assert reset(app, "x" * 43).status_code == 400
    for password in ["short", "a" * 129, "😀" * 129, "a" * 1025, "界" * 342, None, 123]:
        assert reset(app, "x" * 43, password).status_code == 400
    raw = issue(app)
    with app.app_context():
        PasswordResetToken.query.update({"expires_at": datetime.utcnow() - timedelta(seconds=1)})
        db.session.commit()
    assert reset(app, raw).status_code == 400
    raw = issue(app)
    assert reset(app, raw, "界" * 128).status_code == 200

def test_old_missing_version_and_change(app):
    with app.app_context():
        legacy = create_access_token(identity="1")
    c = app.test_client()
    assert c.get("/api/auth/me", headers={"Authorization": "Bearer " + legacy}).status_code == 401
    token = login(app)
    h = {"Authorization": "Bearer " + token}
    raw = issue(app)
    assert c.post("/api/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": NEW}).status_code == 400
    assert c.get("/api/auth/me", headers=h).status_code == 200  # Wrong old password must not sign out.
    assert c.post("/api/auth/change-password", headers=h, json={"current_password": OLD, "new_password": "short"}).status_code == 400
    assert c.post("/api/auth/change-password", headers=h, json={"current_password": OLD, "new_password": NEW}).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401
    assert reset(app, raw).status_code == 400
    assert login(app, NEW)

def test_rate_limits_and_spoofed_ip(app):
    for _ in range(5):
        issue(app)
    assert len(app.mail.messages) == 3
    for i in range(30):
        issue(app, f"none{i}@example.test", headers={"X-Forwarded-For": f"10.1.1.{i}"})
    with app.app_context():
        assert max(r.count for r in PasswordRateLimit.query.filter(PasswordRateLimit.key.like("forgot:ip:%"))) == 20
    for _ in range(20):
        assert reset(app, "x" * 43).status_code == 400
    assert reset(app, "x" * 43).status_code == 429

def test_change_rate_limit(app):
    h = {"Authorization": "Bearer " + login(app)}
    for _ in range(5):
        assert app.test_client().post("/api/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": NEW}).status_code == 400
    assert app.test_client().post("/api/auth/change-password", headers=h, json={"current_password": OLD, "new_password": NEW}).status_code == 429

def test_provider_failure_and_missing_config(app, caplog):
    app.mail.fail = True
    issue(app)
    with app.app_context():
        assert PasswordResetToken.query.count() == 0
    assert "provider failure with secret" not in caplog.text
    app.config["PASSWORD_MAIL_TRANSPORT"] = None
    app.config["RESEND_API_KEY"] = ""
    issue(app)
    with app.app_context():
        assert PasswordResetToken.query.count() == 0
    app.config["PASSWORD_MAIL_TRANSPORT"] = app.mail
    app.config["FRONTEND_URL"] = "https://evil.example/#bad"
    issue(app)
    assert not app.mail.messages

def test_deactivated_or_verification_revoked_after_issue(app):
    raw = issue(app)
    with app.app_context():
        User.query.filter_by(id=1).update({"recovery_email_verified": False})
        db.session.commit()
    assert reset(app, raw).status_code == 400
    with app.app_context():
        User.query.filter_by(id=1).update({"recovery_email_verified": True, "is_active": False})
        db.session.commit()
    assert reset(app, raw).status_code == 400

def test_concurrent_claim(app):
    raw = issue(app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reset(app, raw).status_code, range(2)))
    assert sorted(results) == [200, 400]
    with app.app_context():
        assert db.session.get(User, 1).auth_version == 1

def test_concurrent_separate_tokens(app):
    tokens = [issue(app), issue(app)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda t: reset(app, t).status_code, tokens))
    assert sorted(results) == [200, 400]

def test_resend_transport_uses_real_request_without_network(monkeypatch):
    captured = {}
    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, _): return b'{"id":"test-id"}'
    def fake_open(req, timeout):
        captured.update(url=req.full_url, body=req.data.decode(), headers=dict(req.header_items()), timeout=timeout)
        return FakeResponse()
    monkeypatch.setattr("password_security.urlopen", fake_open)
    ResendTransport("test-key-not-real", "Verified <security@example.test>").send("a@example.test", "https://trusted/#reset-password?token=fake")
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert "security@example.test" in captured["body"]

def test_non_json_or_malformed_inputs_are_generic(app):
    c = app.test_client()
    for value in [[], {"email": []}, {"email": "a" * 500}, None]:
        response = c.post("/api/auth/forgot-password", json=value)
        assert response.status_code == 200 and response.json == GENERIC


def test_concurrent_database_email_limit(app):
    # Each request owns a separate Flask/SQLAlchemy scoped session, like workers.
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: issue(app), range(8)))
    assert len(app.mail.messages) == 3
    with app.app_context():
        assert PasswordRateLimit.query.filter(PasswordRateLimit.key.like("forgot:email:%")).one().count == 3


def test_database_failure_is_generic(app, monkeypatch):
    from sqlalchemy.exc import OperationalError
    with app.app_context():
        def unavailable(*args, **kwargs):
            raise OperationalError("redacted", {}, Exception("unavailable"))
        monkeypatch.setattr(db.session, "execute", unavailable)
        response = app.test_client().post("/api/auth/forgot-password", json={"email": "admin@example.test"})
        assert response.status_code == 200 and response.json == GENERIC
    assert not app.mail.messages


def test_security_audit_does_not_expose_recovery_secrets(app, caplog):
    raw = issue(app)
    assert reset(app, raw).status_code == 200
    assert "password_reset" in caplog.text
    for sensitive in [raw, digest(raw), "admin@example.test", NEW, "https://trusted.example"]:
        assert sensitive not in caplog.text


def test_malformed_unicode_secrets_return_validation_errors(app):
    assert reset(app, "\ud800" * 43).status_code == 400
    h = {"Authorization": "Bearer " + login(app)}
    assert app.test_client().post("/api/auth/change-password", headers=h,
        json={"current_password": "\ud800" * 12, "new_password": NEW}).status_code == 400


def test_failed_mail_token_stays_unusable_even_when_cleanup_fails(app, monkeypatch):
    from sqlalchemy.sql.dml import Delete
    from sqlalchemy.exc import OperationalError
    captured = []
    def fail_send(email, link):
        captured.append(link.split("token=")[1])
        raise RuntimeError("simulated provider failure")
    app.mail.send = fail_send
    with app.app_context():
        original = db.session.execute
        def fail_token_cleanup(statement, *args, **kwargs):
            if isinstance(statement, Delete) and "token_hash =" in str(statement):
                raise OperationalError("redacted", {}, Exception("simulated cleanup outage"))
            return original(statement, *args, **kwargs)
        monkeypatch.setattr(db.session, "execute", fail_token_cleanup)
        response = app.test_client().post("/api/auth/forgot-password", json={"email": "admin@example.test"})
        assert response.status_code == 200 and response.json == GENERIC
        assert PasswordResetToken.query.one().used_at is not None
        monkeypatch.setattr(db.session, "execute", original)
    assert len(captured) == 1
    assert reset(app, captured[0]).status_code == 400
