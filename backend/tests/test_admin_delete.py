import os
os.environ.setdefault('DATABASE_URL', 'sqlite:///test_attendance.db')
os.environ.setdefault('MONGO_URI', 'mongodb://127.0.0.1:27018/')
from datetime import date
import pytest
from app import create_app
from models import db, User, Student, Faculty, Subject, Enrollment, ClassSession, AttendanceRecord, PasswordResetToken
from datetime import datetime, timedelta

@pytest.fixture
def app(tmp_path):
    a = create_app({'TESTING': True, 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(tmp_path / 'delete.db'), 'ACTIVITY_LOG_FILE': str(tmp_path / 'activity.jsonl')})
    with a.app_context():
        db.create_all()
        for role in ['ADMIN', 'STUDENT', 'FACULTY']:
            u = User(email=role.lower() + '@example.test', role=role)
            u.set_password('Original password 123!')
            db.session.add(u)
        db.session.flush()
        db.session.add_all([Student(id=1, user_id=2, name='Student', roll_number='S1', department='CSE', year=1, section='A'), Faculty(id=1, user_id=3, name='Faculty', department='CSE')])
        db.session.flush()
        db.session.add(Subject(id=1, name='Subject', code='CS1', department='CSE', year=1, section='A', faculty_id=1))
        db.session.flush()
        db.session.add(Enrollment(student_id=1, subject_id=1))
        db.session.add(PasswordResetToken(token_hash='a'*64, user_id=2, auth_version=0, expires_at=datetime.utcnow()+timedelta(minutes=15)))
        db.session.commit()
    yield a
    with a.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()

def headers(app, role='admin'):
    r = app.test_client().post('/api/auth/login', json={'email':role+'@example.test','password':'Original password 123!'})
    return {'Authorization': 'Bearer ' + r.json['token']}

@pytest.mark.parametrize('kind', ['students', 'faculty', 'subjects'])
def test_permissions(app, kind):
    c = app.test_client()
    assert c.delete('/api/admin/'+kind+'/1').status_code == 401
    assert c.delete('/api/admin/'+kind+'/1', headers=headers(app, 'student')).status_code == 403
    assert c.delete('/api/admin/'+kind+'/1', headers=headers(app, 'faculty')).status_code == 403

@pytest.mark.parametrize('kind', ['students', 'faculty', 'subjects'])
def test_delete_and_cleanup(app, kind):
    h = headers(app)
    old_student = headers(app, 'student')
    assert app.test_client().delete('/api/admin/'+kind+'/1', headers=h).status_code == 200
    with app.app_context():
        assert db.session.get({'students':Student,'faculty':Faculty,'subjects':Subject}[kind],1) is None
        if kind == 'students':
            assert db.session.get(User,2) is None
            assert PasswordResetToken.query.count() == 0
            assert Enrollment.query.count() == 0
        if kind == 'faculty':
            assert db.session.get(User,3) is None
            assert db.session.get(Subject,1).faculty_id is None
        if kind == 'subjects':
            assert Enrollment.query.count() == 0
    if kind == 'students':
        assert app.test_client().get('/api/auth/me',headers=old_student).status_code == 401
    assert app.test_client().delete('/api/admin/'+kind+'/1', headers=h).status_code == 404

@pytest.mark.parametrize('kind', ['students', 'faculty', 'subjects'])
def test_preserve_history(app, kind):
    with app.app_context():
        db.session.add(ClassSession(id=1,subject_id=1,faculty_id=1,session_date=date.today(),period='1'))
        db.session.flush()
        db.session.add(AttendanceRecord(student_id=1,session_id=1,status='PRESENT'))
        db.session.commit()
    assert app.test_client().delete('/api/admin/'+kind+'/1',headers=headers(app)).status_code == 409
    with app.app_context():
        assert AttendanceRecord.query.count() == 1
        assert ClassSession.query.count() == 1
        assert User.query.count() == 3

def test_cannot_delete_admin_or_unknown_kind(app):
    c = app.test_client()
    h = headers(app)
    assert c.delete('/api/admin/users/1', headers=h).status_code == 404
    with app.app_context():
        db.session.get(Student,1).user_id=1
        db.session.commit()
    assert c.delete('/api/admin/students/1', headers=h).status_code == 409
