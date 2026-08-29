-- AttendEase persistent PostgreSQL schema
-- Safe to run repeatedly in Supabase SQL Editor.

DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('STUDENT', 'FACULTY', 'ADMIN');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE attendance_status AS ENUM ('PRESENT', 'ABSENT');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email VARCHAR(160) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  role user_role NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS students (
  id SERIAL PRIMARY KEY,
  user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(140) NOT NULL,
  roll_number VARCHAR(50) NOT NULL UNIQUE,
  department VARCHAR(120) NOT NULL,
  year INTEGER NOT NULL,
  section VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS faculty (
  id SERIAL PRIMARY KEY,
  user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  name VARCHAR(140) NOT NULL,
  department VARCHAR(120) NOT NULL
);

CREATE TABLE IF NOT EXISTS subjects (
  id SERIAL PRIMARY KEY,
  name VARCHAR(140) NOT NULL,
  code VARCHAR(40) NOT NULL UNIQUE,
  department VARCHAR(120) NOT NULL,
  year INTEGER NOT NULL,
  section VARCHAR(20) NOT NULL,
  faculty_id INTEGER REFERENCES faculty(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS enrollments (
  id SERIAL PRIMARY KEY,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  CONSTRAINT uq_student_subject UNIQUE (student_id, subject_id)
);

CREATE TABLE IF NOT EXISTS class_sessions (
  id SERIAL PRIMARY KEY,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  faculty_id INTEGER NOT NULL REFERENCES faculty(id) ON DELETE RESTRICT,
  session_date DATE NOT NULL,
  period VARCHAR(30) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_subject_date_period UNIQUE (subject_id, session_date, period)
);

CREATE TABLE IF NOT EXISTS attendance_records (
  id SERIAL PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES class_sessions(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  status attendance_status NOT NULL,
  marked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_session_student UNIQUE (session_id, student_id)
);

CREATE INDEX IF NOT EXISTS ix_students_department_year ON students (department, year);
CREATE INDEX IF NOT EXISTS ix_subjects_faculty_id ON subjects (faculty_id);
CREATE INDEX IF NOT EXISTS ix_sessions_subject_date ON class_sessions (subject_id, session_date);
CREATE INDEX IF NOT EXISTS ix_attendance_student ON attendance_records (student_id);
CREATE INDEX IF NOT EXISTS ix_attendance_session ON attendance_records (session_id);
