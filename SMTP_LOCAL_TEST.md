# SMTP password reset and local test inbox

SMTP is the default password-recovery provider. Resend is not used by the local demo and is only available if explicitly selected with PASSWORD_MAIL_PROVIDER=resend for backward compatibility.

## Run the isolated demo on Windows

From frontend, build a separate local bundle:

```powershell
$env:VITE_API_URL='/api'
npm ci --no-audit --no-fund
npm run build -- --outDir dist-local
```

From backend:

```powershell
uv run --no-project --with-requirements requirements-dev.txt --with 'SQLAlchemy==2.0.36' python local_password_demo.py
```

The SQLAlchemy override is a local Windows compatibility workaround for the installed runtime; it is not a production dependency change.

- App: http://127.0.0.1:5001/
- Inbox: http://127.0.0.1:8025/
- SMTP listener: 127.0.0.1:1025
- Synthetic account: demo@attendease.test
- Initial demo password: Local demo password 123!

Click Forgot password, enter the synthetic account address, then refresh the inbox. Open the captured link and enter and confirm a new password. Sign in using that password. A reused link must be rejected. Do not enter real credentials or use real student data in this demo.

The runner creates its own temporary SQLite database and random JWT secret. It overrides production database, MongoDB, SMTP, and frontend settings before app initialization. The test account is marked recovery-verified only in that disposable database. All listeners bind to loopback. Captured messages stay in memory, the inbox keeps at most 20 messages, and nothing is relayed externally. Stopping the process discards the inbox; each restart creates a fresh database and account. Do not deploy this runner, expose these ports, or set TESTING=true in production.

## SMTP configuration for a later deployment

No production settings were changed by this work. Before any later deployment, back up and migrate the database and configure these server-only variables deliberately:

```text
PASSWORD_MAIL_PROVIDER=smtp
FRONTEND_URL=https://attendease-student-attendance.vercel.app
SMTP_HOST=<your provider's SMTP host>
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=<provider username>
SMTP_PASSWORD=<provider SMTP credential or app password>
SMTP_FROM_EMAIL=<authorized sender address>
```

Use SMTP_SECURITY=ssl with port 465 if required by the chosen provider. TLS certificate and hostname verification remain enabled. Do not use a normal account password when a provider requires an app password or SMTP-specific credential. Never commit credentials or put them in VITE_ variables. No paid service, domain purchase, or provider account changes are required for the local demo.

Production rejects unencrypted SMTP. The only plaintext exception is Flask TESTING mode with a loopback host and no SMTP credentials, used by this demo and tests. Missing settings and delivery failures preserve the generic forgot-password response; reset tokens become usable only after SMTP accepts delivery. SMTP acceptance is not proof of final inbox delivery.

The existing security rules still apply: verified active recovery accounts only, 15-minute single-use links, database-backed rate limits, and invalidation of old sessions and reset links after a successful reset. The local test does not verify any real mailbox. No migration or bulk verification is performed automatically. See PASSWORD_SECURITY.md for the migration and security design; this document supersedes its Resend-specific setup directions when SMTP is selected.

## Automated checks

From backend:

```powershell
uv run --no-project --with-requirements requirements-dev.txt --with 'SQLAlchemy==2.0.36' python -m pytest tests -q
```

SMTP tests cover STARTTLS/implicit TLS and authentication ordering, header injection, recipient refusal, production plaintext rejection, missing configuration, delivery failure cleanup, and a real loopback SMTP request followed by reset, replay rejection, and old-session invalidation. They never send external email.

## Verified in this run

The complete backend suite passed: 40 tests, 232 datetime.utcnow deprecation warnings, 117.45 seconds. The SMTP-only suite also passed: 11 tests. The local frontend build and browser request → captured SMTP email → new password → login flow passed. No external email was sent. Production settings, data, and main were not changed.
