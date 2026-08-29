# Deployment checklist

## Free local development
The default backend database is SQLite and activity events fall back to backend/activity_logs.jsonl. No Docker is required.

## Current free production path
- Persistent database: Supabase PostgreSQL Free plan
- Backend: Vercel Python serverless deployment
- Frontend: Vercel static deployment
- Activity logs: optional MongoDB; JSONL fallback remains available

Run `backend/schema.sql` once in Supabase SQL Editor. Set `DATABASE_URL` and `JWT_SECRET_KEY` only in the Vercel backend environment; keep database passwords and service-role credentials out of GitHub and the frontend. Set `VITE_API_URL` only in the Vercel frontend environment. Restrict CORS to the deployed frontend domain before production.

## Optional future infrastructure
MySQL/MongoDB on AWS remain supported future targets, but are not required for the current free deployment.

## Before release
1. Run migrations instead of relying on db.create_all.
2. Run backend tests and frontend build.
3. Configure HTTPS, backups, logs, and secret storage.
4. Create a non-admin production account and remove demo credentials.
