# AttendEase — Student Attendance Management System

Full-stack attendance system for Students, Faculty, and Admins.

## Live deployment
- Frontend: https://attendease-student-attendance.vercel.app
- API health: https://attendease-api.vercel.app/api/health


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

### Persistent production database settings

Run `backend/schema.sql` once in the Supabase SQL Editor, then set `DATABASE_URL` to the Supabase PostgreSQL connection string and `JWT_SECRET_KEY` in the Vercel backend environment. Keep database passwords and service-role credentials server-side; never commit them to GitHub or expose them in the React frontend. MongoDB remains optional for flexible activity logs, with a JSONL fallback. Never use the demo secret or demo passwords in production.

The React production build and Flask API tests have been verified locally.

The local seed creates the development accounts when you provide `ADMIN_PASSWORD`, `FACULTY_PASSWORD`, and `STUDENT_PASSWORD` in a private environment. The online database was seeded separately; passwords are not stored in GitHub. Change all development credentials before real use.

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


Admin accounts are provisioned through a protected server-side setup flow.
