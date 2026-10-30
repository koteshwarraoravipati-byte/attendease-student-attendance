# Password security

This implementation is prepared for the feature/secure-password-flows review branch. No production schema, account, mail provider, or deployment was changed. Tests use SQLite and an in-memory mail transport. Apply the migration explicitly before deploying code that reads the new user columns; deployment and migration require separate approval.

## Operator setup

1. Back up the database, review \backend/migrations/20261030_password_security.sql, and run it manually against the approved PostgreSQL database. It adds columns and tables without changing existing password hashes or verifying any addresses. There is no cold-start migration or automatic table creation. New installs using schema.sql include the same additions.
2. Set a strong server-only JWT_SECRET_KEY, exact HTTPS FRONTEND_URL (no query or fragment), server-only RESEND_API_KEY, and RESEND_FROM_EMAIL. Verify the sender/domain in Resend first. Resend itself enforces sender verification; this application cannot prove ownership of a configured sender. Restrict CORS_ORIGINS to the actual frontend origin. Never expose the provider key through a VITE_ variable.
3. Independently establish ownership of each recovery mailbox through a trusted owner-controlled process. All existing and newly created accounts default to recovery_email_verified=false, including administrators. Do not mark all accounts verified. Authenticated password changes do not require a recovery-verified address.
4. Only after verifying ownership and confirming the exact target account, an authorized owner may run a narrow transaction like the example below. This is an example, NOT an action performed by this implementation.

~~~sql
BEGIN;
SELECT id, email, role, is_active, recovery_email_verified
FROM users WHERE email = 'koteshwarraoravipati@gmail.com' FOR UPDATE;
-- Inspect the single expected active ADMIN row, verify mailbox ownership separately,
-- and substitute its inspected id. ROLLBACK if any detail does not match.
UPDATE users SET recovery_email_verified = TRUE
WHERE id = <inspected_admin_id>
  AND email = 'koteshwarraoravipati@gmail.com'
  AND role = 'ADMIN' AND is_active = TRUE;
-- Confirm exactly one row affected; otherwise ROLLBACK.
COMMIT;
~~~

Setting FRONTEND_URL alone does not enable recovery. Missing/invalid mail configuration fails closed with the normal generic forgot-password response and a non-sensitive audit event. Test injection is honored only when Flask TESTING is true. There is no production mock or fallback transport. Do not enable TESTING in production.

## HTTP contract

- POST /api/auth/forgot-password with {"email":"address"}: HTTP 200 and {"message":"If an eligible account exists, a password reset link will be sent."} for known, unknown, inactive, unverified, rate-limited, malformed input, missing configuration, DB failure, and provider failure. No tokens or delivery details are returned. Only verified active users receive mail, regardless of role.
- POST /api/auth/reset-password with {"token":"opaque token","new_password":"..."}: 200 on success, 400 for invalid/expired/reused link or invalid password, 429 for rate limiting, 503 for database unavailability. Success message: "Password reset successful. Sign in again."
- POST /api/auth/change-password with Authorization: Bearer JWT and {"current_password":"...","new_password":"..."}: 200 on success, 400 for wrong old password or invalid new password, 401 for a revoked/invalid session, 429 for rate limiting, 503 for database unavailability. Success message: "Password changed successfully. Sign in again." No replacement JWT is issued.

New passwords for reset/change require 12–128 Python Unicode code points and at most 1024 UTF-8 bytes. Values are not trimmed or silently truncated; 128 multibyte characters are supported. Existing login and account-creation password behavior remains unchanged, so pre-existing short passwords can still be used to log in and then changed. Werkzeug scrypt remains the hash algorithm.

The email link uses only the configured static origin/base path and ends in /#reset-password?token=TOKEN. Host and forwarded-host headers cannot affect it. The browser must read the token from the fragment, immediately remove it with history.replaceState, keep it in component memory only, and send it only in the reset POST body. Do not store it in localStorage, analytics, telemetry, logs, or query-string URLs. Set an appropriate frontend Referrer-Policy and disable analytics on recovery UI. The frontend is owned by a separate implementation.

## Tokens, transactions, and sessions

Each link has 32 cryptographically random bytes (secrets.token_urlsafe), a 15-minute lifetime, and only its SHA-256 digest stored. Reset atomically changes used_at with a conditional UPDATE ... RETURNING; password replacement and auth_version increment are in that same transaction. A failed account/version condition rolls back the claim. Both simultaneous use of one token and simultaneous use of separately issued tokens for one account permit only one password update. User-version compare-and-update protects races with authenticated password change as well. Expiration uses UTC application time, so synchronize worker clocks.

JWTs from login contain an integer auth_version. Flask-JWT-Extended's global revocation callback checks the current database version and active status on every protected endpoint, not just /auth/me. Reset/change increment the version, invalidating every old JWT, including the calling JWT, and every other reset link. Tokens missing this claim are rejected even for version-zero users. Deploying this change therefore signs out all pre-change sessions. Requests already authorized/in flight cannot be retroactively stopped.

## Rate limits and proxy boundaries

All workers share atomic database counters. Windows are fixed 15-minute buckets: forgot-password 3 per email slot and 20 per IP slot; reset 20 per IP slot; change 5 per user slot and 20 per IP slot. All dimensions are consumed even when another dimension is blocked. Windows can allow a burst around the boundary. Counters fail closed if unavailable.

Keys are action/dimension plus a SHA-256-derived slot among 4096 slots, never raw email/IP values. Five slot families bound the counter table to 20,480 rows even if attackers submit unlimited identities. Hash collisions intentionally share limits and can cause conservative false throttling; use edge abuse controls as well. Recovery token rows are pruned when eligible requests issue new links; schedule operator-run cleanup of expired rows to bound retained history over time, and do not remove live rate-limit counters during a window.

The app uses request.remote_addr only. It deliberately ignores X-Forwarded-For, Forwarded, X-Real-IP, and all forwarded-host headers, so arbitrary client headers do not bypass quotas. Behind Vercel/a reverse proxy, remote_addr may represent a shared proxy or may be platform-derived. Verify its actual semantics in staging before production: never add ProxyFix or trust forwarding headers unless the trusted proxy chain is known, strips attacker-supplied values, and direct backend access is blocked. Until validated, per-email/user limits still work but shared-IP throttles may reject legitimate users. Add platform-native IP/WAF limits for reliable client IPs; do not loosen trust to solve this.

## Mail, audit, and limitations

ResendTransport makes a real HTTPS POST with a 10-second timeout. It requires a successful provider ID. New tokens start with a non-null used_at marker so they cannot be claimed while delivery is pending. Only a provider-confirmed success activates the token by clearing that marker. Failures delete the pending token and return the generic response; even if cleanup fails, its pending marker keeps it unusable. If the provider accepted mail but the response was lost, or post-send activation fails, the delivered link is invalid because the pending marker/deletion fails closed. Password changes do not automatically send notification emails in this implementation. No test sends real mail.

Security events use the server's structured logger (password_security action + internal user ID only), not optional local files or MongoDB. Configure retained, access-controlled centralized logs in production. Events cover link requests, mail failure/configuration failure, throttle events, reset rejection/success, and change rejection/success. Passwords, raw tokens, digests, links, IPs, emails, request bodies, and provider error details are excluded. Infrastructure must likewise avoid body capture and fragment/URL telemetry.

Public response content/status prevents direct account enumeration, but synchronous provider latency is not timing-constant. A distributed mail queue would be needed for stronger timing concealment. No end-to-end real-provider delivery, production proxy behavior, or live PostgreSQL migration/concurrency test was run. PostgreSQL uses the same conditional UPDATE and native ON CONFLICT mechanisms as SQLite, but review and staging validation remain necessary before release. Existing hard-coded dev JWT fallback and permissive CORS defaults are legacy configuration risks; explicitly override both in production.

## Local validation

From backend:

~~~powershell
uv run --no-project --with-requirements requirements.txt --with pytest python -m pytest tests -q
~~~

Tests include the unchanged existing API suite, eligibility and enumeration-safe responses, static link origin, token hashing/expiry, invalid and reused links, concurrent same/different-token resets, legacy and old-session rejection on protected endpoints, password policy including multibyte inputs, wrong current password, change/reset/email/IP limits, spoofed forwarding headers, provider failure, missing config, and a mocked Resend HTTP request. The provider request unit test substitutes urlopen; it never reaches the network.

Final validation: 19 passed, 151 datetime.utcnow deprecation warnings, 79.18 seconds using the complete suite command above. Both original API tests passed unchanged. This final full run includes malformed Unicode handling, the 12–128-code-point policy, session survival after wrong current password, provider failure with failed token cleanup, concurrent database-backed rate increments, and same/separate-token reset CAS concurrency. No failed tests occurred. No real Resend requests or PostgreSQL connections/migrations were made. uv used its managed cached environment; its initial hardlink-to-copy warning was a harmless performance fallback.

## Combined review validation
Parent rerun: backend 19 passed (78.34 s), frontend 15 passed, frontend production build passed. Frontend adds all three account security screens, removes external font loading, scrubs reset fragments immediately, and clears authenticated sessions on 401. Vercel configuration disables automatic deployments for feature/secure-password-flows at repository/frontend/backend roots. Main deployment behavior is unchanged.
