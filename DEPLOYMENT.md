# Deployment checklist

## Free local development
The default backend database is SQLite and activity events fall back to backend/activity_logs.jsonl. No Docker is required.

## Production options
- MySQL: Amazon RDS or another managed MySQL provider
- MongoDB: MongoDB Atlas free tier or Amazon DocumentDB
- Backend: AWS Elastic Beanstalk, ECS, or EC2
- Frontend: S3 + CloudFront, or the included Nginx container

Set DATABASE_URL, JWT_SECRET_KEY, MONGO_URI, MONGO_DB, and VITE_API_URL in the deployment environment. Restrict CORS to the deployed frontend domain before production.

## Before release
1. Run migrations instead of relying on db.create_all.
2. Run backend tests and frontend build.
3. Configure HTTPS, backups, logs, and secret storage.
4. Create a non-admin production account and remove demo credentials.
