from app import app
from models import db, User, Student, Faculty, Subject, Enrollment
with app.app_context():
    db.create_all()
    admin = User.query.filter_by(email="admin@attendease.local").first()
    if not admin:
        admin = User(email="admin@attendease.local", role="ADMIN"); admin.set_password("Admin@123"); db.session.add(admin)
    faculty_user = User.query.filter_by(email="faculty@attendease.local").first()
    if not faculty_user:
        faculty_user = User(email="faculty@attendease.local", role="FACULTY"); faculty_user.set_password("Faculty@123"); db.session.add(faculty_user); db.session.flush(); db.session.add(Faculty(user_id=faculty_user.id, name="Dr. Priya Sharma", department="Computer Science"))
    student_user = User.query.filter_by(email="student@attendease.local").first()
    if not student_user:
        student_user = User(email="student@attendease.local", role="STUDENT"); student_user.set_password("Student@123"); db.session.add(student_user); db.session.flush(); db.session.add(Student(user_id=student_user.id, name="Rahul Kumar", roll_number="CSE001", department="Computer Science", year=2, section="A"))
    db.session.commit()
    faculty = Faculty.query.filter_by(user_id=faculty_user.id).first(); student = Student.query.filter_by(user_id=student_user.id).first(); subject = Subject.query.filter_by(code="CS201").first()
    if not subject: subject = Subject(name="Data Structures", code="CS201", department="Computer Science", year=2, section="A", faculty_id=faculty.id); db.session.add(subject); db.session.flush()
    if not Enrollment.query.filter_by(student_id=student.id, subject_id=subject.id).first(): db.session.add(Enrollment(student_id=student.id, subject_id=subject.id))
    db.session.commit(); print("Seed complete.")
