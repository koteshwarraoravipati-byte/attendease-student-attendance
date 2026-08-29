# AttendEase — Student Attendance Management System

Full-stack attendance system for Students, Faculty, and Admins.

## Stack
- Frontend: React + Vite
- Backend: Flask REST API
- Local database: SQLite (free, zero-setup development)
- Production database: Supabase PostgreSQL (persistent free tier)
- Activity/audit logs: MongoDB when available, with a local JSONL fallback
- Deployment: AWS-compatible Dockerfiles and deployment checklist

SQLite is the default for local development so Docker Desktop, WSL2, and BIOS virtualization are not required. MySQL and MongoDB remain supported production options through environment variables.

## MVP features
- Role-based login for Student, Faculty, and Admin
- Student subject-wise attendance percentage
- Faculty class-session creation and attendance marking
- Admin overview and management dashboard
- Admin can create login-ready student and faculty accounts
- Admin can create subjects, assign faculty, and enroll students
- Attendance history and CSV report download
- MongoDB activity logs for important actions

## Run locally (SQLite — no Docker required)

### Windows PowerShell

```powershell
cd "C:\Users\Koteshwarrao\OneDrive\Desktop\IMS PROJECT [Student Attendence]\backend"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe seed.py
Start-Process -WindowStyle Hidden -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m flask --app app run --host 127.0.0.1 --port 5000"

cd ..\frontend
& "C:\Program Files\nodejs\npm.cmd" install
Start-Process -WindowStyle Hidden -FilePath "C:\Program Files\nodejs\npm.cmd" -ArgumentList "run dev -- --host 127.0.0.1"
```

Open http://localhost:5173. The seeded demo accounts are listed below. The SQLite file is created at `backend/instance/attendance.db`, and activity events use `backend/activity_logs.jsonl` when MongoDB is unavailable.

For future starts after the first setup, run `powershell -ExecutionPolicy Bypass -File .\start-local.ps1`; it starts both services hidden in the background. Run `powershell -ExecutionPolicy Bypass -File .\stop-local.ps1` when you want to stop them.

### Optional production database settings

Copy `backend/.env.example` to `backend/.env` and set `DATABASE_URL` to a MySQL connection string plus `MONGO_URI`/`MONGO_DB` for MongoDB activity logs. Never use the demo secret or demo passwords in production.

The React production build and Flask API tests have been verified locally.

Default seeded accounts:
- Admin: admin@attendease.local / Admin@123
- Faculty: faculty@attendease.local / Faculty@123
- Student: student@attendease.local / Student@123

Change these credentials before using the application beyond local testing.

## Project flow

Student -> Subject -> Attendance Session -> Attendance Records -> Percentage -> Report

PostgreSQL is the source of truth for attendance in the live deployment. MongoDB stores flexible audit/activity events and is not used to calculate percentages.

## API overview

- POST /api/auth/register
- POST /api/auth/login
- GET /api/auth/me
- GET /api/student/summary
- GET /api/student/subjects/:subject_id
- GET /api/student/report
- GET /api/faculty/subjects
- POST /api/faculty/sessions
- POST /api/faculty/sessions/:session_id/attendance
- GET /api/admin/overview
- POST /api/admin/students
- POST /api/admin/faculty
- POST /api/admin/subjects
- POST /api/admin/enrollments


## Persistent production status
The live backend is configured to use the Supabase PostgreSQL transaction pooler through Vercel server-side environment variables. The React client never receives the database credential.
