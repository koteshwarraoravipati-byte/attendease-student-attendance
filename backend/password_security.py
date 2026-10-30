"""Password recovery; no schema changes or mail sends occur at import time."""
import hashlib
import ipaddress
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from flask import jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from sqlalchemy import or_, update, delete
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import generate_password_hash

from models import db, User, PasswordResetToken, PasswordRateLimit

GENERIC = {"message": "If an eligible account exists, a password reset link will be sent."}
INVALID = {"error": "This reset link is invalid or has expired. Request a new link."}
PASSWORD_ERROR = {"error": "Use 12–128 Unicode characters (no more than 1024 UTF-8 bytes)."}


def valid_password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        return False
    try:
        return len(value.encode("utf-8")) <= 1024
    except UnicodeError:
        return False


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ResendTransport:
    def __init__(self, key, sender):
        self.key, self.sender = key, sender

    def send(self, email, link):
        payload = json.dumps({"from": self.sender, "to": [email],
            "subject": "Reset your AttendEase password",
            "text": "Use this single-use link within 15 minutes to reset your password:\n" + link +
                    "\nIf you did not request this, ignore this message."}).encode("utf-8")
        req = Request("https://api.resend.com/emails", data=payload, method="POST",
            headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json",
                     "User-Agent": "AttendEase/1.0"})
        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read(65536))
            if response.status != 200 or not result.get("id"):
                raise RuntimeError("Email provider rejected delivery")


def install_password_security(app, jwt):
    def audit(action, user_id=None):
        # Do NOT log emails, IPs, bodies, tokens, hashes, links or provider errors.
        app.logger.warning("password_security %s", json.dumps({"action": action, "user_id": user_id}))

    @jwt.token_in_blocklist_loader
    def revoked(_header, claims):
        try:
            user = db.session.get(User, int(claims["sub"]))
            version = claims.get("auth_version")
            return not user or not user.is_active or type(version) is not int or version != user.auth_version
        except (TypeError, ValueError, KeyError):
            return True

    @jwt.revoked_token_loader
    def revoked_response(_header, _claims):
        return jsonify({"error": "Session expired. Sign in again."}), 401

    def body():
        value = request.get_json(silent=True)
        return value if isinstance(value, dict) else {}

    def client_ip():
        # Do not read X-Forwarded-For, Forwarded, X-Real-IP or user headers.
        try:
            return str(ipaddress.ip_address(request.remote_addr or "0.0.0.0"))
        except ValueError:
            return "unknown"

    def limited(action, dimensions):
        """Atomic per-slot fixed-window counters, shared by every DB-backed worker.

        4096 slots per dimension/action; hash collisions intentionally fail closed.
        An ON CONFLICT conditional increment avoids check-then-write races.
        """
        dialect = db.engine.dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert
        else:
            raise RuntimeError("Password security requires PostgreSQL or SQLite")
        now = int(time.time()) // 900
        allowed = True
        for dimension, value, maximum in dimensions:
            slot = int(digest(value), 16) % 4096
            key = f"{action}:{dimension}:{slot}"
            statement = insert(PasswordRateLimit).values(key=key, window_start=now, count=1)
            statement = statement.on_conflict_do_update(index_elements=[PasswordRateLimit.key],
                set_={"window_start": now, "count": db.case(
                    (PasswordRateLimit.window_start != now, 1), else_=PasswordRateLimit.count + 1)},
                where=or_(PasswordRateLimit.window_start != now, PasswordRateLimit.count < maximum)
            ).returning(PasswordRateLimit.key)
            if db.session.execute(statement).scalar_one_or_none() is None:
                allowed = False
        db.session.commit()
        return not allowed

    def mail_settings():
        base = app.config.get("FRONTEND_URL", "").strip().rstrip("/")
        parsed = urlsplit(base)
        local = app.testing and parsed.hostname in ("localhost", "127.0.0.1")
        if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        injected = app.config.get("PASSWORD_MAIL_TRANSPORT") if app.testing else None
        if injected is not None:
            return base, injected
        key, sender = app.config.get("RESEND_API_KEY", ""), app.config.get("RESEND_FROM_EMAIL", "")
        if not key or not sender or "@" not in sender or "\n" in sender or "\r" in sender:
            return None
        return base, ResendTransport(key, sender)

    @app.post("/api/auth/forgot-password")
    def forgot_password():
        data = body()
        email = data.get("email")
        email = email.lower().strip() if isinstance(email, str) else ""
        # Bound input before hashing/querying, with identical public output.
        email = email if len(email) <= 160 else ""
        token_hash = None
        try:
            if limited("forgot", [("ip", client_ip(), 20), ("email", email, 3)]):
                audit("forgot_rate_limited")
                return jsonify(GENERIC)
            settings = mail_settings()
            if not settings:
                audit("mail_not_configured")
                return jsonify(GENERIC)
            user = User.query.filter_by(email=email, is_active=True, recovery_email_verified=True).first()
            if not user:
                audit("forgot_requested")
                return jsonify(GENERIC)
            raw = secrets.token_urlsafe(32)
            token_hash = digest(raw)
            # Cleanup is bounded by issuance limits; schedule separate maintenance as well.
            db.session.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < datetime.utcnow()))
            db.session.add(PasswordResetToken(token_hash=token_hash, user_id=user.id,
                auth_version=user.auth_version, expires_at=datetime.utcnow() + timedelta(minutes=15),
                used_at=datetime.utcnow()))  # Pending delivery: not claimable until transport succeeds.
            user_id = user.id
            db.session.commit()
            base, transport = settings
            try:
                transport.send(email, base + "/#reset-password?token=" + raw)
            except Exception:
                db.session.execute(delete(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
                db.session.commit()
                audit("mail_failed", user_id)
                return jsonify(GENERIC)
            # Only activate after the provider confirms acceptance. If cleanup or activation
            # fails, the pending non-null used_at marker keeps the token unusable.
            db.session.execute(update(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash).values(used_at=None))
            db.session.commit()
            audit("reset_link_sent", user_id)
        except Exception:
            db.session.rollback()
            audit("forgot_unavailable")
        return jsonify(GENERIC)

    @app.post("/api/auth/reset-password")
    def reset_password():
        data = body()
        raw, password = data.get("token"), data.get("new_password")
        try:
            if limited("reset", [("ip", client_ip(), 20)]):
                audit("reset_rate_limited")
                return jsonify({"error": "Too many attempts. Try again later."}), 429
            if not valid_password(password):
                return jsonify(PASSWORD_ERROR), 400
            if not isinstance(raw, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw):
                return jsonify(INVALID), 400
            now = datetime.utcnow()
            # First writer atomically claims this token. All mutations commit together.
            claimed = db.session.execute(update(PasswordResetToken).where(
                PasswordResetToken.token_hash == digest(raw), PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now).values(used_at=now).returning(
                    PasswordResetToken.user_id, PasswordResetToken.auth_version)).first()
            if not claimed:
                db.session.rollback()
                audit("reset_rejected")
                return jsonify(INVALID), 400
            changed = db.session.execute(update(User).where(User.id == claimed.user_id,
                User.is_active.is_(True), User.recovery_email_verified.is_(True),
                User.auth_version == claimed.auth_version).values(
                    password_hash=generate_password_hash(password), auth_version=User.auth_version + 1))
            if changed.rowcount != 1:
                db.session.rollback()
                return jsonify(INVALID), 400
            # auth_version invalidates all other links without cross-token lock ordering.
            db.session.commit()
            audit("password_reset", claimed.user_id)
            return jsonify({"message": "Password reset successful. Sign in again."})
        except SQLAlchemyError:
            db.session.rollback()
            audit("reset_unavailable")
            return jsonify({"error": "Password service temporarily unavailable."}), 503

    @app.post("/api/auth/change-password")
    @jwt_required()
    def change_password():
        data = body()
        user_id = int(get_jwt_identity())
        try:
            if limited("change", [("ip", client_ip(), 20), ("user", str(user_id), 5)]):
                audit("change_rate_limited", user_id)
                return jsonify({"error": "Too many attempts. Try again later."}), 429
            user = db.session.get(User, user_id)
            old = data.get("current_password")
            try:
                old_valid = isinstance(old, str) and len(old.encode("utf-8")) <= 1024
            except UnicodeError:
                old_valid = False
            if not old_valid or not user.check_password(old):
                audit("change_rejected", user_id)
                return jsonify({"error": "Current password is incorrect."}), 400
            password = data.get("new_password")
            if not valid_password(password):
                return jsonify(PASSWORD_ERROR), 400
            changed = db.session.execute(update(User).where(User.id == user_id,
                User.is_active.is_(True), User.auth_version == get_jwt()["auth_version"]).values(
                    password_hash=generate_password_hash(password), auth_version=User.auth_version + 1))
            if changed.rowcount != 1:
                db.session.rollback()
                return jsonify({"error": "Session expired. Sign in again."}), 401
            # Outstanding reset links are invalidated by the auth_version increment.
            db.session.commit()
            audit("password_changed", user_id)
            return jsonify({"message": "Password changed successfully. Sign in again."})
        except SQLAlchemyError:
            db.session.rollback()
            audit("change_unavailable", user_id)
            return jsonify({"error": "Password service temporarily unavailable."}), 503
