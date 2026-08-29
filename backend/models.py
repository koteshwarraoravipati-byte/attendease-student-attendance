from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum("STUDENT", "FACULTY", "ADMIN"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    student = db.relationship("Student", backref="user", uselist=False, cascade="all, delete-orphan")
    faculty = db.relationship("Faculty", backref="user", uselist=False, cascade="all, delete-orphan")
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)
    def to_dict(self):
        profile = self.student or self.faculty
        name = profile.name if profile else self.email.split("@")[0].title()
        return {"id": self.id, "email": self.email, "role": self.role, "name": name, "is_active": self.is_active}

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=True)
    name = db.Column(db.String(140), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    department = db.Column(db.String(120), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    section = db.Column(db.String(20), nullable=False)
    enrollments = db.relationship("Enrollment", backref="student", cascade="all, delete-orphan")
    attendance_records = db.relationship("AttendanceRecord", backref="student", cascade="all, delete-orphan")

class Faculty(db.Model):
    __tablename__ = "faculty"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=True)
    name = db.Column(db.String(140), nullable=False)
    department = db.Column(db.String(120), nullable=False)
    subjects = db.relationship("Subject", backref="faculty", lazy=True)

class Subject(db.Model):
    __tablename__ = "subjects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(140), nullable=False)
    code = db.Column(db.String(40), unique=True, nullable=False)
    department = db.Column(db.String(120), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    section = db.Column(db.String(20), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculty.id"), nullable=True)
    sessions = db.relationship("ClassSession", backref="subject", cascade="all, delete-orphan")
    enrollments = db.relationship("Enrollment", backref="subject", cascade="all, delete-orphan")

class Enrollment(db.Model):
    __tablename__ = "enrollments"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    __table_args__ = (db.UniqueConstraint("student_id", "subject_id", name="uq_student_subject"),)

class ClassSession(db.Model):
    __tablename__ = "class_sessions"
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subjects.id"), nullable=False)
    faculty_id = db.Column(db.Integer, db.ForeignKey("faculty.id"), nullable=False)
    session_date = db.Column(db.Date, nullable=False)
    period = db.Column(db.String(30), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    records = db.relationship("AttendanceRecord", backref="session", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint("subject_id", "session_date", "period", name="uq_subject_date_period"),)

class AttendanceRecord(db.Model):
    __tablename__ = "attendance_records"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("class_sessions.id"), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    status = db.Column(db.Enum("PRESENT", "ABSENT"), nullable=False)
    marked_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint("session_id", "student_id", name="uq_session_student"),)
