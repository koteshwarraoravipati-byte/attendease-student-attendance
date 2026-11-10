import os
os.environ["DATABASE_URL"] = "sqlite:///test_attendance.db"
os.environ["MONGO_URI"] = "mongodb://127.0.0.1:27018/"
from app import app
from models import db

def setup_module():
    with app.app_context():
        db.drop_all(); db.create_all()

def teardown_module():
    with app.app_context(): db.drop_all()

def test_health():
    assert app.test_client().get("/api/health").status_code == 200

def test_registration_and_login():
    c = app.test_client()
    assert c.post("/api/auth/register", json={"email":"a@test.local","password":"Password@123","name":"A Student","roll_number":"A001","department":"CSE","year":1,"section":"A"}).status_code == 201
    assert c.post("/api/auth/login", json={"email":"a@test.local","password":"Password@123"}).status_code == 200

def test_soft_and_hard_delete():
    from models import User, Student, Faculty, Subject
    with app.app_context():
        admin = User(email="admin@test.local", role="ADMIN")
        admin.set_password("Admin@12345")
        db.session.add(admin)
        db.session.commit()

    c = app.test_client()
    token = c.post("/api/auth/login", json={"email": "admin@test.local", "password": "Admin@12345"}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    # Create student, faculty, subject, enrollment
    s_id = c.post("/api/admin/students", json={"name": "Stu", "roll_number": "S100", "department": "CSE", "year": 1, "section": "A", "email": "s100@test.local", "password": "Pass@12345"}, headers=h).get_json()["id"]
    f_id = c.post("/api/admin/faculty", json={"name": "Prof", "department": "CSE", "email": "prof@test.local", "password": "Pass@12345"}, headers=h).get_json()["id"]
    sub_id = c.post("/api/admin/subjects", json={"name": "Algo", "code": "CS301", "department": "CSE", "year": 1, "section": "A", "faculty_id": f_id}, headers=h).get_json()["id"]
    assert c.post("/api/admin/enrollments", json={"student_id": s_id, "subject_id": sub_id}, headers=h).status_code == 201

    # Soft delete subject & verify cannot create session while deactivated
    assert c.patch(f"/api/admin/subjects/{sub_id}/status", json={"is_active": False}, headers=h).get_json()["is_active"] is False
    assert c.post("/api/faculty/sessions", json={"subject_id": sub_id, "date": "2026-11-10", "period": "1"}, headers=h).status_code == 400
    assert c.patch(f"/api/admin/subjects/{sub_id}/status", json={"is_active": True}, headers=h).get_json()["is_active"] is True

    # Create session and mark attendance, then verify faculty delete blocked (409) and student hard delete cascades
    sess_id = c.post("/api/faculty/sessions", json={"subject_id": sub_id, "date": "2026-11-10", "period": "1"}, headers=h).get_json()["session_id"]
    assert c.post(f"/api/faculty/sessions/{sess_id}/attendance", json={"attendance": [{"student_id": s_id, "status": "PRESENT"}]}, headers=h).status_code == 200
    assert c.delete(f"/api/admin/faculty/{f_id}", headers=h).status_code == 409

    # Hard delete student (cascades enrollments + attendance), then subject (cascades session), then faculty
    assert c.delete(f"/api/admin/students/{s_id}", headers=h).status_code == 200
    assert c.delete(f"/api/admin/subjects/{sub_id}", headers=h).status_code == 200
    assert c.delete(f"/api/admin/faculty/{f_id}", headers=h).status_code == 200

    with app.app_context():
        assert db.session.get(Student, s_id) is None
        assert db.session.get(Subject, sub_id) is None
        assert db.session.get(Faculty, f_id) is None

def test_bulk_actions_and_otp_password_reset():
    from models import Student, Subject
    c = app.test_client()
    token = c.post("/api/auth/login", json={"email": "admin@test.local", "password": "Admin@12345"}).get_json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    # Bulk soft & hard delete on students and subjects
    s1 = c.post("/api/admin/students", json={"name": "S1", "roll_number": "B101", "department": "CSE", "year": 1, "section": "A", "email": "b101@test.local", "password": "Pass@12345"}, headers=h).get_json()["id"]
    s2 = c.post("/api/admin/students", json={"name": "S2", "roll_number": "B102", "department": "CSE", "year": 1, "section": "A", "email": "b102@test.local", "password": "Pass@12345"}, headers=h).get_json()["id"]
    assert c.post("/api/admin/students/bulk-status", json={"ids": [s1, s2], "is_active": False}, headers=h).get_json()["updated"] == 2
    assert c.post("/api/auth/login", json={"email": "b101@test.local", "password": "Pass@12345"}).status_code == 401
    assert c.post("/api/admin/students/bulk-status", json={"ids": [s1, s2], "is_active": True}, headers=h).get_json()["updated"] == 2
    assert c.post("/api/admin/students/bulk-delete", json={"ids": [s1, s2]}, headers=h).get_json()["deleted"] == 2

    sub1 = c.post("/api/admin/subjects", json={"name": "DB", "code": "CS401", "department": "CSE", "year": 2, "section": "A"}, headers=h).get_json()["id"]
    sub2 = c.post("/api/admin/subjects", json={"name": "OS", "code": "CS402", "department": "CSE", "year": 2, "section": "A"}, headers=h).get_json()["id"]
    assert c.post("/api/admin/subjects/bulk-status", json={"ids": [sub1, sub2], "is_active": False}, headers=h).get_json()["updated"] == 2
    assert c.post("/api/admin/subjects/bulk-delete", json={"ids": [sub1, sub2]}, headers=h).get_json()["deleted"] == 2
    with app.app_context():
        assert db.session.get(Student, s1) is None and db.session.get(Student, s2) is None
        assert db.session.get(Subject, sub1) is None and db.session.get(Subject, sub2) is None

    # Forgot password / OTP reset flow
    app.config["SMTP_USERNAME"] = ""
    app.config["SMTP_PASSWORD"] = ""
    app.config["OTP_EMAIL_SENDER"] = None
    assert c.post("/api/auth/forgot-password", json={"email": "a@test.local"}).status_code == 503

    sent_otps = []
    app.config["OTP_EMAIL_SENDER"] = lambda email, otp, mins: sent_otps.append((email, otp, mins))
    try:
        res = c.post("/api/auth/forgot-password", json={"email": "a@test.local"})
        assert res.status_code == 200
        assert len(sent_otps) == 1 and len(sent_otps[0][1]) == 6
        otp = sent_otps[0][1]

        # Wrong OTP rejected
        assert c.post("/api/auth/reset-password", json={"email": "a@test.local", "otp": "000000" if otp != "000000" else "999999", "new_password": "NewPassword@1"}).status_code == 400
        # Valid OTP resets password
        assert c.post("/api/auth/reset-password", json={"email": "a@test.local", "otp": otp, "new_password": "NewPassword@1"}).status_code == 200
        # Replay OTP rejected
        assert c.post("/api/auth/reset-password", json={"email": "a@test.local", "otp": otp, "new_password": "NewPassword@2"}).status_code == 400
        # Old password fails, new password works
        assert c.post("/api/auth/login", json={"email": "a@test.local", "password": "Password@123"}).status_code == 401
        assert c.post("/api/auth/login", json={"email": "a@test.local", "password": "NewPassword@1"}).status_code == 200
    finally:
        app.config["OTP_EMAIL_SENDER"] = None
