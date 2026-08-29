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
