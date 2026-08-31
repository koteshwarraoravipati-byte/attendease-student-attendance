# Deployment checklist

## Free local development
The default backend database is SQLite and activity events fall back to backend/activity_logs.jsonl. No Docker is required.

## Current free production path
- Persistent database: Supabase PostgreSQL Free plan
- Backend: Vercel Python serverless deployment
- Frontend: Vercel static deployment
- Activity logs: optional MongoDB; JSONL fallback remains available

Run `backend/schema.sql` once in Supabase SQL Editor. Set `DATABASE_URL` and `JWT_SECRET_KEY` only in the Vercel backend environment; keep database passwords and service-role credentials out of GitHub and the frontend. Set `VITE_API_URL` only in the Vercel frontend environment. Restrict CORS to the deployed frontend domain before production.

## MongoDB Atlas activity logs
The Flask API supports MongoDB Atlas through `MONGODB_URI` and `MONGODB_DB`. When available, activity events are written to MongoDB; otherwise the local JSONL fallback is used. For Vercel, configure the Atlas URI as a server-side secret and allow Vercel traffic in the Atlas network-access settings.

## Optional AWS deployment
The repository includes Dockerfiles and `docker-compose.yml`. An AWS deployment still requires an authenticated AWS account and a chosen target such as App Runner, Elastic Beanstalk, ECS, or EC2. Keep the current Vercel deployment as the free fallback until AWS credentials and billing limits are confirmed.

## Before release
1. Run migrations instead of relying on db.create_all.
2. Run backend tests and frontend build.
3. Configure HTTPS, backups, logs, and secret storage.
4. Create a non-admin production account and remove demo credentials.
