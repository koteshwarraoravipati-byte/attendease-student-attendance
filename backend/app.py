import csv
import hashlib
import hmac
import io
import json
import os
import secrets
import smtplib
import ssl
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from functools import wraps

from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from pymongo import MongoClient
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from config import Config
from models import AttendanceRecord, ClassSession, Enrollment, Faculty, PasswordResetOTP, Student, Subject, User, db


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}})
    db.init_app(app)
    JWTManager(app)

    activity_collection = None
    try:
        client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=800)
        client.server_info()
        activity_collection = client[app.config["MONGO_DB"]]["activity_logs"]
    except Exception:
        pass

    def log_activity(action, user_id=None, details=None):
        event = {"action": action, "user_id": user_id, "details": details or {}, "created_at": datetime.utcnow().isoformat()}
        if activity_collection is not None:
            try:
                activity_collection.insert_one({**event, "created_at": datetime.utcnow()})
                return
            except Exception:
                pass
        try:
            with open(app.config["ACTIVITY_LOG_FILE"], "a", encoding="utf-8") as handle:
                handle.write(json.dumps(event) + "\n")
        except OSError:
            pass

    def current_user():
        try:
            return db.session.get(User, int(get_jwt_identity()))
        except (TypeError, ValueError):
            return None

    def roles_required(*roles):
        def decorator(fn):
            @wraps(fn)
            @jwt_required()
            def wrapper(*args, **kwargs):
                user = current_user()
                if not user or not user.is_active or user.role not in roles:
                    return jsonify({"error": "You do not have permission for this action"}), 403
                return fn(user, *args, **kwargs)
            return wrapper
        return decorator

    def subject_summary(subject, student_id):
        base = db.session.query(func.count(AttendanceRecord.id)).join(ClassSession).filter(
            AttendanceRecord.student_id == student_id,
            ClassSession.subject_id == subject.id,
        )
        total = base.scalar() or 0
        attended = base.filter(AttendanceRecord.status == "PRESENT").scalar() or 0
        return {
            "subject_id": subject.id,
            "name": subject.name,
            "code": subject.code,
            "total_classes": total,
            "attended_classes": attended,
            "percentage": round(attended / total * 100, 2) if total else 0,
        }

    def faculty_owns_subject(user, subject):
        return user.role == "ADMIN" or (user.faculty and subject.faculty_id == user.faculty.id)

    schema_ready = False

    @app.before_request
    def ensure_schema():
        nonlocal schema_ready
        if schema_ready or request.path == "/api/health":
            return
        try:
            inspector = inspect(db.engine)
            tables = set(inspector.get_table_names())
            if "subjects" in tables:
                cols = {c["name"] for c in inspector.get_columns("subjects")}
                if "is_active" not in cols:
                    with db.engine.begin() as conn:
                        conn.execute(text("ALTER TABLE subjects ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE"))
            if "password_reset_otps" not in tables:
                PasswordResetOTP.__table__.create(db.engine, checkfirst=True)
            schema_ready = True
        except SQLAlchemyError:
            pass

    def hash_otp(user_id, otp_code):
        secret = str(app.config.get("JWT_SECRET_KEY") or "attendease-otp-secret").encode("utf-8")
        return hmac.new(secret, f"{user_id}:{otp_code}".encode("utf-8"), hashlib.sha256).hexdigest()

    def smtp_is_configured():
        if app.config.get("OTP_EMAIL_SENDER"):
            return True
        return bool(app.config.get("SMTP_HOST") and app.config.get("SMTP_USERNAME") and app.config.get("SMTP_PASSWORD"))

    def send_otp_email(recipient, otp_code, expiry_minutes):
        if any(ch in recipient for ch in ("\r", "\n")):
            raise ValueError("Invalid email address")
        custom_sender = app.config.get("OTP_EMAIL_SENDER")
        if custom_sender:
            custom_sender(recipient, otp_code, expiry_minutes)
            return
        host = app.config["SMTP_HOST"]
        port = int(app.config["SMTP_PORT"])
        username = app.config["SMTP_USERNAME"]
        password = app.config["SMTP_PASSWORD"]
        if host.lower() == "smtp.gmail.com":
            password = password.replace(" ", "")
        sender = app.config.get("SMTP_FROM_EMAIL") or username
        if any(ch in sender for ch in ("\r", "\n")):
            raise ValueError("Invalid sender email address")

        msg = EmailMessage()
        msg["Subject"] = f"AttendEase Password Reset OTP: {otp_code}"
        msg["From"] = sender
        msg["To"] = recipient
        msg.set_content(
            f"Hello,\n\nYour AttendEase password reset verification code (OTP) is: {otp_code}\n\n"
            f"This code expires in {expiry_minutes} minutes and can only be used once.\n"
            "If you did not request a password reset, you can safely ignore this email.\n"
        )
        msg.add_alternative(
            f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;border:1px solid #ebeaf1;border-radius:14px;">
                <h2 style="color:#6246c7;margin:0 0 12px;">AttendEase Password Reset</h2>
                <p style="color:#48435f;">Use this 6-digit verification code to reset your password:</p>
                <div style="font-size:32px;font-weight:700;letter-spacing:8px;text-align:center;background:#f3efff;color:#6246c7;padding:16px;border-radius:10px;margin:20px 0;">{otp_code}</div>
                <p style="color:#77738b;font-size:13px;">This code expires in <strong>{expiry_minutes} minutes</strong>. If you didn't request this, ignore this email.</p>
            </div>""",
            subtype="html",
        )

        context = ssl.create_default_context()
        use_tls = app.config.get("SMTP_USE_TLS", True)
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.ehlo()
                if use_tls:
                    smtp.starttls(context=context)
                    smtp.ehlo()
                smtp.login(username, password)
                smtp.send_message(msg)

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(error):
        try:
            db.session.rollback()
        except SQLAlchemyError:
            pass
        app.logger.exception("Database request failed")
        return jsonify({"error": "The attendance database is temporarily unavailable. Please try again shortly."}), 503

    @app.get("/api/health")
    def health():
        db.session.execute(db.select(1))
        return jsonify({"status": "ok", "service": "attendease-api", "database": "available"})

    @app.post("/api/auth/register")
    def register():
        data = request.get_json() or {}
        required = ["email", "password", "name", "roll_number", "department", "year", "section"]
        if any(not data.get(key) for key in required):
            return jsonify({"error": "All student fields are required"}), 400
        email = data["email"].lower().strip()
        if User.query.filter_by(email=email).first() or Student.query.filter_by(roll_number=data["roll_number"].strip()).first():
            return jsonify({"error": "Email or roll number already exists"}), 409
        user = User(email=email, role="STUDENT")
        user.set_password(data["password"])
        db.session.add(user)
        db.session.flush()
        db.session.add(Student(user_id=user.id, name=data["name"].strip(), roll_number=data["roll_number"].strip(), department=data["department"].strip(), year=int(data["year"]), section=data["section"].strip()))
        db.session.commit()
        log_activity("student_registered", user.id, {"roll_number": data["roll_number"]})
        return jsonify({"message": "Registration successful"}), 201

    @app.post("/api/auth/login")
    def login():
        data = request.get_json() or {}
        user = User.query.filter_by(email=(data.get("email") or "").lower().strip()).first()
        if not user or not user.is_active or not user.check_password(data.get("password") or ""):
            return jsonify({"error": "Invalid email, password, or inactive account"}), 401
        token = create_access_token(identity=str(user.id))
        log_activity("login", user.id)
        return jsonify({"token": token, "user": user.to_dict()})

    @app.get("/api/auth/me")
    @jwt_required()
    def me():
        user = current_user()
        if not user or not user.is_active:
            return jsonify({"error": "Account is inactive"}), 401
        return jsonify({"user": user.to_dict()})

    @app.post("/api/auth/forgot-password")
    def forgot_password():
        data = request.get_json() or {}
        email = (data.get("email") or "").lower().strip()
        if not email or "@" not in email:
            return jsonify({"error": "Enter a valid email address"}), 400
        if not smtp_is_configured():
            return jsonify({"error": "Google SMTP email service is not configured on the server yet."}), 503

        user = User.query.filter_by(email=email).first()
        if user and user.is_active:
            recent = PasswordResetOTP.query.filter_by(user_id=user.id, used_at=None).order_by(PasswordResetOTP.created_at.desc()).first()
            if recent and (datetime.utcnow() - recent.created_at).total_seconds() < 30:
                return jsonify({"error": "Please wait 30 seconds before requesting another OTP."}), 429

            PasswordResetOTP.query.filter_by(user_id=user.id, used_at=None).update({"used_at": datetime.utcnow()})
            otp_code = f"{secrets.randbelow(1000000):06d}"
            expiry_minutes = max(1, int(app.config.get("OTP_EXPIRY_MINUTES", 10)))
            otp_row = PasswordResetOTP(
                user_id=user.id,
                otp_hash=hash_otp(user.id, otp_code),
                expires_at=datetime.utcnow() + timedelta(minutes=expiry_minutes),
            )
            db.session.add(otp_row)
            db.session.flush()
            try:
                send_otp_email(user.email, otp_code, expiry_minutes)
            except Exception:
                db.session.rollback()
                app.logger.exception("Failed to send password reset OTP email")
                return jsonify({"error": "Could not send OTP email. Check Google SMTP settings and try again."}), 503
            db.session.commit()
            log_activity("password_reset_otp_sent", user.id)

        return jsonify({"message": "If an active account exists for this email, a 6-digit OTP has been sent."})

    @app.post("/api/auth/reset-password")
    def reset_password():
        data = request.get_json() or {}
        email = (data.get("email") or "").lower().strip()
        otp_code = str(data.get("otp") or "").strip()
        new_password = str(data.get("new_password") or "")
        if not email or not otp_code or not new_password:
            return jsonify({"error": "Email, OTP, and new password are required"}), 400
        if len(new_password) < 6:
            return jsonify({"error": "New password must be at least 6 characters long"}), 400
        if not otp_code.isdigit() or len(otp_code) != 6:
            return jsonify({"error": "Enter the 6-digit numeric OTP sent to your email"}), 400

        user = User.query.filter_by(email=email).first()
        if not user or not user.is_active:
            return jsonify({"error": "Invalid or expired OTP"}), 400

        otp_row = PasswordResetOTP.query.filter_by(user_id=user.id, used_at=None).order_by(PasswordResetOTP.created_at.desc()).first()
        if not otp_row:
            return jsonify({"error": "No active OTP found. Please request a new OTP."}), 400
        if otp_row.expires_at < datetime.utcnow():
            otp_row.used_at = datetime.utcnow()
            db.session.commit()
            return jsonify({"error": "OTP has expired. Please request a new OTP."}), 400
        if otp_row.attempts >= 5:
            otp_row.used_at = datetime.utcnow()
            db.session.commit()
            return jsonify({"error": "Too many incorrect OTP attempts. Please request a new OTP."}), 400

        if not hmac.compare_digest(otp_row.otp_hash, hash_otp(user.id, otp_code)):
            otp_row.attempts += 1
            if otp_row.attempts >= 5:
                otp_row.used_at = datetime.utcnow()
            db.session.commit()
            remaining = max(0, 5 - otp_row.attempts)
            msg = "Too many incorrect OTP attempts. Please request a new OTP." if remaining == 0 else f"Invalid OTP code ({remaining} attempt(s) remaining)."
            return jsonify({"error": msg}), 400

        now = datetime.utcnow()
        PasswordResetOTP.query.filter_by(user_id=user.id, used_at=None).update({"used_at": now})
        user.set_password(new_password)
        db.session.commit()
        log_activity("password_reset_completed", user.id)
        return jsonify({"message": "Password reset successful. You can now sign in with your new password."})

    @app.get("/api/student/summary")
    @roles_required("STUDENT")
    def student_summary(user):
        student = user.student
        rows = [subject_summary(enrollment.subject, student.id) for enrollment in student.enrollments]
        total = sum(row["total_classes"] for row in rows)
        attended = sum(row["attended_classes"] for row in rows)
        return jsonify({"student": {"name": student.name, "roll_number": student.roll_number, "department": student.department, "year": student.year, "section": student.section}, "subjects": rows, "overall": {"total_classes": total, "attended_classes": attended, "percentage": round(attended / total * 100, 2) if total else 0}})

    @app.get("/api/student/subjects/<int:subject_id>")
    @roles_required("STUDENT")
    def student_subject(user, subject_id):
        enrollment = Enrollment.query.filter_by(student_id=user.student.id, subject_id=subject_id).first()
        if not enrollment:
            return jsonify({"error": "Subject not found for this student"}), 404
        sessions = ClassSession.query.filter_by(subject_id=subject_id).order_by(ClassSession.session_date.desc(), ClassSession.period).all()
        records = []
        for session in sessions:
            record = AttendanceRecord.query.filter_by(session_id=session.id, student_id=user.student.id).first()
            if record:
                records.append({"date": session.session_date.isoformat(), "period": session.period, "status": record.status})
        return jsonify({"summary": subject_summary(enrollment.subject, user.student.id), "records": records})

    @app.get("/api/student/history")
    @roles_required("STUDENT")
    def student_history(user):
        rows = []
        records = AttendanceRecord.query.join(ClassSession).filter(AttendanceRecord.student_id == user.student.id).order_by(ClassSession.session_date.desc(), ClassSession.period).all()
        for record in records:
            rows.append({"date": record.session.session_date.isoformat(), "period": record.session.period, "subject": record.session.subject.name, "code": record.session.subject.code, "status": record.status})
        return jsonify({"records": rows})

    @app.get("/api/student/report")
    @roles_required("STUDENT")
    def student_report(user):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Subject", "Code", "Total Classes", "Attended Classes", "Percentage"])
        for enrollment in user.student.enrollments:
            row = subject_summary(enrollment.subject, user.student.id)
            writer.writerow([row["name"], row["code"], row["total_classes"], row["attended_classes"], str(row["percentage"]) + "%"])
        return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=attendance-report.csv"})

    @app.get("/api/faculty/subjects")
    @roles_required("FACULTY", "ADMIN")
    def faculty_subjects(user):
        subjects = Subject.query.filter_by(faculty_id=user.faculty.id, is_active=True).all() if user.role == "FACULTY" else Subject.query.filter_by(is_active=True).order_by(Subject.code).all()
        return jsonify({"subjects": [{"id": s.id, "name": s.name, "code": s.code, "department": s.department, "year": s.year, "section": s.section} for s in subjects]})

    @app.post("/api/faculty/sessions")
    @roles_required("FACULTY", "ADMIN")
    def create_session(user):
        data = request.get_json() or {}
        subject = db.session.get(Subject, data.get("subject_id"))
        if not subject or not faculty_owns_subject(user, subject):
            return jsonify({"error": "Subject not found or not assigned to you"}), 403
        if not subject.is_active:
            return jsonify({"error": "This subject is deactivated and cannot accept new class sessions"}), 400
        if not data.get("date") or not data.get("period"):
            return jsonify({"error": "Date and period are required"}), 400
        try:
            session_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Date must use YYYY-MM-DD format"}), 400
        faculty_id = user.faculty.id if user.role == "FACULTY" else subject.faculty_id
        if not faculty_id:
            return jsonify({"error": "Assign a faculty member to the subject first"}), 400
        session = ClassSession(subject_id=subject.id, faculty_id=faculty_id, session_date=session_date, period=str(data["period"]).strip())
        db.session.add(session)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "A session already exists for this subject, date, and period"}), 409
        log_activity("class_session_created", user.id, {"session_id": session.id, "subject_id": subject.id})
        return jsonify({"session_id": session.id, "message": "Class session created"}), 201

    @app.get("/api/faculty/sessions/<int:session_id>")
    @roles_required("FACULTY", "ADMIN")
    def get_session(user, session_id):
        session = db.session.get(ClassSession, session_id)
        if not session or (user.role == "FACULTY" and session.faculty_id != user.faculty.id):
            return jsonify({"error": "Session not found"}), 404
        return jsonify({"id": session.id, "subject_id": session.subject_id, "date": session.session_date.isoformat(), "period": session.period, "attendance": [{"student_id": r.student_id, "status": r.status} for r in session.records]})

    @app.post("/api/faculty/sessions/<int:session_id>/attendance")
    @roles_required("FACULTY", "ADMIN")
    def mark_attendance(user, session_id):
        session = db.session.get(ClassSession, session_id)
        if not session or (user.role == "FACULTY" and session.faculty_id != user.faculty.id):
            return jsonify({"error": "Session not found or not assigned to you"}), 404
        entries = (request.get_json() or {}).get("attendance", [])
        enrolled_ids = {enrollment.student_id for enrollment in Enrollment.query.filter_by(subject_id=session.subject_id).all()}
        saved = 0
        for entry in entries:
            student_id = entry.get("student_id")
            if student_id not in enrolled_ids or entry.get("status") not in ("PRESENT", "ABSENT"):
                continue
            record = AttendanceRecord.query.filter_by(session_id=session.id, student_id=student_id).first()
            if record:
                record.status = entry["status"]
            else:
                db.session.add(AttendanceRecord(session_id=session.id, student_id=student_id, status=entry["status"]))
            saved += 1
        db.session.commit()
        log_activity("attendance_marked", user.id, {"session_id": session.id, "records": saved})
        return jsonify({"message": "Attendance saved", "records_saved": saved})

    @app.get("/api/faculty/subjects/<int:subject_id>/students")
    @roles_required("FACULTY", "ADMIN")
    def subject_students(user, subject_id):
        subject = db.session.get(Subject, subject_id)
        if not subject or not faculty_owns_subject(user, subject):
            return jsonify({"error": "Subject not found or not assigned to you"}), 403
        return jsonify({"students": [{"id": e.student.id, "name": e.student.name, "roll_number": e.student.roll_number} for e in subject.enrollments]})

    @app.get("/api/admin/overview")
    @roles_required("ADMIN")
    def admin_overview(user):
        return jsonify({"students": Student.query.count(), "faculty": Faculty.query.count(), "subjects": Subject.query.count(), "sessions": ClassSession.query.count()})

    @app.get("/api/admin/catalog")
    @roles_required("ADMIN")
    def admin_catalog(user):
        students = Student.query.order_by(Student.name).all()
        faculty = Faculty.query.order_by(Faculty.name).all()
        subjects = Subject.query.order_by(Subject.code).all()
        return jsonify({"students": [{"id": s.id, "name": s.name, "roll_number": s.roll_number, "department": s.department, "year": s.year, "section": s.section, "email": s.user.email if s.user else "", "user_id": s.user_id, "is_active": s.user.is_active if s.user else True} for s in students], "faculty": [{"id": f.id, "name": f.name, "department": f.department, "email": f.user.email if f.user else "", "user_id": f.user_id, "subject_count": len(f.subjects), "is_active": f.user.is_active if f.user else True} for f in faculty], "subjects": [{"id": s.id, "name": s.name, "code": s.code, "department": s.department, "year": s.year, "section": s.section, "faculty_id": s.faculty_id, "faculty_name": s.faculty.name if s.faculty else "Unassigned", "enrollment_count": len(s.enrollments), "is_active": s.is_active} for s in subjects]})

    @app.post("/api/admin/students")
    @roles_required("ADMIN")
    def admin_student(user):
        d = request.get_json() or {}; required = ["name", "roll_number", "department", "year", "section", "email", "password"]
        if any(not d.get(k) for k in required): return jsonify({"error": "All student fields are required"}), 400
        email = d["email"].lower().strip()
        if User.query.filter_by(email=email).first() or Student.query.filter_by(roll_number=d["roll_number"].strip()).first(): return jsonify({"error": "Email or roll number already exists"}), 409
        account = User(email=email, role="STUDENT"); account.set_password(d["password"]); db.session.add(account); db.session.flush()
        student = Student(user_id=account.id, name=d["name"].strip(), roll_number=d["roll_number"].strip(), department=d["department"].strip(), year=int(d["year"]), section=d["section"].strip()); db.session.add(student); db.session.commit(); log_activity("admin_created_student", user.id, {"student_id": student.id})
        return jsonify({"id": student.id, "message": "Student created"}), 201

    @app.post("/api/admin/faculty")
    @roles_required("ADMIN")
    def admin_faculty(user):
        d = request.get_json() or {}; required = ["name", "department", "email", "password"]
        if any(not d.get(k) for k in required): return jsonify({"error": "All faculty fields are required"}), 400
        email = d["email"].lower().strip()
        if User.query.filter_by(email=email).first(): return jsonify({"error": "Email already exists"}), 409
        account = User(email=email, role="FACULTY"); account.set_password(d["password"]); db.session.add(account); db.session.flush(); faculty = Faculty(user_id=account.id, name=d["name"].strip(), department=d["department"].strip()); db.session.add(faculty); db.session.commit(); log_activity("admin_created_faculty", user.id, {"faculty_id": faculty.id})
        return jsonify({"id": faculty.id, "message": "Faculty created"}), 201

    @app.post("/api/admin/subjects")
    @roles_required("ADMIN")
    def admin_subject(user):
        d = request.get_json() or {}; required = ["name", "code", "department", "year", "section"]
        if any(not d.get(k) for k in required): return jsonify({"error": "All subject fields are required"}), 400
        code = d["code"].upper().strip()
        if Subject.query.filter_by(code=code).first(): return jsonify({"error": "Subject code already exists"}), 409
        if d.get("faculty_id") and not db.session.get(Faculty, int(d["faculty_id"])): return jsonify({"error": "Faculty not found"}), 404
        subject = Subject(name=d["name"].strip(), code=code, department=d["department"].strip(), year=int(d["year"]), section=d["section"].strip(), faculty_id=int(d["faculty_id"]) if d.get("faculty_id") else None); db.session.add(subject); db.session.commit(); log_activity("admin_created_subject", user.id, {"subject_id": subject.id})
        return jsonify({"id": subject.id, "message": "Subject created"}), 201

    @app.post("/api/admin/enrollments")
    @roles_required("ADMIN")
    def admin_enrollment(user):
        d = request.get_json() or {}; student_id, subject_id = d.get("student_id"), d.get("subject_id")
        if not student_id or not subject_id: return jsonify({"error": "Student and subject are required"}), 400
        student = db.session.get(Student, int(student_id))
        subject = db.session.get(Subject, int(subject_id))
        if not student or not subject: return jsonify({"error": "Student or subject not found"}), 404
        if not subject.is_active or (student.user and not student.user.is_active):
            return jsonify({"error": "Cannot enroll a deactivated student or subject"}), 400
        if Enrollment.query.filter_by(student_id=int(student_id), subject_id=int(subject_id)).first(): return jsonify({"error": "Student is already enrolled in this subject"}), 409
        enrollment = Enrollment(student_id=int(student_id), subject_id=int(subject_id)); db.session.add(enrollment); db.session.commit(); log_activity("admin_created_enrollment", user.id, {"enrollment_id": enrollment.id})
        return jsonify({"id": enrollment.id, "message": "Student enrolled"}), 201

    @app.put("/api/admin/students/<int:student_id>")
    @roles_required("ADMIN")
    def update_student(user, student_id):
        student = db.session.get(Student, student_id)
        if not student: return jsonify({"error": "Student not found"}), 404
        d = request.get_json() or {}
        for key in ["name", "roll_number", "department", "section"]:
            if key in d and d[key]: setattr(student, key, str(d[key]).strip())
        if "year" in d: student.year = int(d["year"])
        db.session.commit(); log_activity("admin_updated_student", user.id, {"student_id": student_id})
        return jsonify({"message": "Student updated"})

    @app.put("/api/admin/faculty/<int:faculty_id>")
    @roles_required("ADMIN")
    def update_faculty(user, faculty_id):
        faculty = db.session.get(Faculty, faculty_id)
        if not faculty: return jsonify({"error": "Faculty not found"}), 404
        d = request.get_json() or {}
        if d.get("name"): faculty.name = str(d["name"]).strip()
        if d.get("department"): faculty.department = str(d["department"]).strip()
        db.session.commit(); log_activity("admin_updated_faculty", user.id, {"faculty_id": faculty_id})
        return jsonify({"message": "Faculty updated"})

    @app.put("/api/admin/subjects/<int:subject_id>")
    @roles_required("ADMIN")
    def update_subject(user, subject_id):
        subject = db.session.get(Subject, subject_id)
        if not subject: return jsonify({"error": "Subject not found"}), 404
        d = request.get_json() or {}
        for key in ["name", "department", "section"]:
            if key in d and d[key]: setattr(subject, key, str(d[key]).strip())
        if "year" in d: subject.year = int(d["year"])
        if "faculty_id" in d: subject.faculty_id = int(d["faculty_id"]) if d["faculty_id"] else None
        db.session.commit(); log_activity("admin_updated_subject", user.id, {"subject_id": subject_id})
        return jsonify({"message": "Subject updated"})

    @app.patch("/api/admin/users/<int:user_id>/status")
    @roles_required("ADMIN")
    def update_user_status(user, user_id):
        target = db.session.get(User, user_id)
        if not target or target.role == "ADMIN": return jsonify({"error": "User not found or cannot be deactivated"}), 404
        target.is_active = bool((request.get_json() or {}).get("is_active", True)); db.session.commit(); log_activity("admin_changed_user_status", user.id, {"target_user_id": user_id, "is_active": target.is_active})
        return jsonify({"message": "User status updated", "is_active": target.is_active})

    @app.patch("/api/admin/subjects/<int:subject_id>/status")
    @roles_required("ADMIN")
    def update_subject_status(user, subject_id):
        subject = db.session.get(Subject, subject_id)
        if not subject: return jsonify({"error": "Subject not found"}), 404
        subject.is_active = bool((request.get_json() or {}).get("is_active", True))
        db.session.commit()
        log_activity("admin_changed_subject_status", user.id, {"subject_id": subject_id, "is_active": subject.is_active})
        return jsonify({"message": "Subject status updated", "is_active": subject.is_active})

    ADMIN_MODELS = {"students": Student, "faculty": Faculty, "subjects": Subject}

    def attempt_hard_delete(kind, record_id):
        model = ADMIN_MODELS.get(kind)
        if not model:
            return False, "Record type not found", 404, None
        target = db.session.get(model, record_id)
        if not target:
            return False, f"{kind[:-1].title()} #{record_id} not found", 404, None
        name = target.name
        if kind == "faculty":
            session_count = ClassSession.query.filter_by(faculty_id=target.id).count()
            if session_count > 0:
                return False, f"{name}: has {session_count} existing class session(s). Deactivate instead.", 409, name
            for subject in target.subjects:
                subject.faculty_id = None
        if kind in ("students", "faculty"):
            expected_role = "STUDENT" if kind == "students" else "FACULTY"
            account = target.user
            if account and account.role != expected_role:
                return False, f"{name}: linked account role mismatch", 409, name
            db.session.delete(account if account else target)
        else:
            db.session.delete(target)
        return True, None, 200, name

    @app.delete("/api/admin/<string:kind>/<int:record_id>")
    @roles_required("ADMIN")
    def delete_admin_record(user, kind, record_id):
        if kind not in ADMIN_MODELS:
            return jsonify({"error": "Record type not found"}), 404
        ok, err, code, name = attempt_hard_delete(kind, record_id)
        if not ok:
            return jsonify({"error": err}), code
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": f"Could not delete {kind[:-1]} due to database constraints"}), 409
        log_activity(f"admin_deleted_{kind[:-1]}", user.id, {"record_id": record_id, "name": name})
        return jsonify({"message": f"{kind[:-1].title()} permanently deleted"})

    @app.post("/api/admin/<string:kind>/bulk-delete")
    @roles_required("ADMIN")
    def bulk_delete_admin_records(user, kind):
        if kind not in ADMIN_MODELS:
            return jsonify({"error": "Record type not found"}), 404
        ids = (request.get_json() or {}).get("ids") or []
        try:
            clean_ids = list(dict.fromkeys(int(i) for i in ids))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid record IDs"}), 400
        if not clean_ids:
            return jsonify({"error": "Select at least one record"}), 400

        deleted_ids, skipped = [], []
        for record_id in clean_ids:
            ok, err, _, _ = attempt_hard_delete(kind, record_id)
            if ok:
                deleted_ids.append(record_id)
            else:
                skipped.append(err)
        if not deleted_ids:
            db.session.rollback()
            return jsonify({"error": skipped[0] if len(skipped) == 1 else "None of the selected records could be deleted: " + "; ".join(skipped)}), 409
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return jsonify({"error": "Could not complete bulk deletion due to database constraints"}), 409
        log_activity(f"admin_bulk_deleted_{kind}", user.id, {"deleted_ids": deleted_ids, "skipped": skipped})
        msg = f"Permanently deleted {len(deleted_ids)} {kind[:-1] if len(deleted_ids) == 1 else kind}."
        if skipped:
            msg += f" Skipped {len(skipped)}: " + "; ".join(skipped)
        return jsonify({"message": msg, "deleted": len(deleted_ids), "skipped": skipped})

    @app.post("/api/admin/<string:kind>/bulk-status")
    @roles_required("ADMIN")
    def bulk_status_admin_records(user, kind):
        if kind not in ADMIN_MODELS:
            return jsonify({"error": "Record type not found"}), 404
        data = request.get_json() or {}
        ids = data.get("ids") or []
        is_active = bool(data.get("is_active", True))
        try:
            clean_ids = list(dict.fromkeys(int(i) for i in ids))
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid record IDs"}), 400
        if not clean_ids:
            return jsonify({"error": "Select at least one record"}), 400

        updated, skipped = 0, []
        model = ADMIN_MODELS[kind]
        for record_id in clean_ids:
            target = db.session.get(model, record_id)
            if not target:
                skipped.append(f"#{record_id} not found")
                continue
            if kind == "subjects":
                target.is_active = is_active
                updated += 1
            else:
                account = target.user
                if not account or account.role == "ADMIN":
                    skipped.append(f"{target.name} has no modifiable login")
                    continue
                account.is_active = is_active
                updated += 1
        if updated == 0:
            return jsonify({"error": skipped[0] if skipped else "No records updated"}), 400
        db.session.commit()
        log_activity(f"admin_bulk_status_{kind}", user.id, {"updated": updated, "is_active": is_active})
        action_word = "activated" if is_active else "deactivated"
        msg = f"Successfully {action_word} {updated} record(s)."
        if skipped:
            msg += f" Skipped {len(skipped)}."
        return jsonify({"message": msg, "updated": updated, "skipped": skipped})

    @app.get("/api/admin/activity")
    @roles_required("ADMIN")
    def admin_activity(user):
        events = []
        try:
            with open(app.config["ACTIVITY_LOG_FILE"], encoding="utf-8") as handle:
                events = [json.loads(line) for line in handle.readlines()[-100:]]
        except (OSError, json.JSONDecodeError):
            pass
        return jsonify({"events": list(reversed(events))})

    # Do not perform schema creation during serverless cold starts. Production schema is
    # managed explicitly; local development uses seed.py/tests to create its tables.
    return app


app = create_app()
