# Admin deletion and password recovery

This branch builds on `feature/secure-password-flows` (0031cb4). It adds the missing login-page recovery controls and admin deletion. Nothing in this change applies a production migration or deletes existing records automatically.

## Admin Delete

Manage data has a Delete button for students, faculty, and subjects. A browser confirmation explains the effects before submitting a DELETE request. The server independently requires an active ADMIN account.

- Students: removes the linked STUDENT login, recovery tokens, profile, and enrollments. Any saved attendance blocks deletion.
- Faculty: removes the linked FACULTY login and recovery tokens, and unassigns their subjects. Any class session taught by that faculty member blocks deletion.
- Subjects: removes the subject and its enrollments. Any class session for the subject blocks deletion.

Keep Activate/Deactivate for accounts whose attendance history must remain available. Linked accounts with an unexpected role, including ADMIN, cannot be removed through a profile. Foreign-key conflicts return HTTP 409 rather than removing related history. All deletion tests use temporary SQLite databases, never production data.

## Forgot password

The login page links to an email request form. Reset links open a new-password form with confirmation and a 12–128 character password requirement. The token is read from the URL fragment and then removed from the address bar. Successful resets return to sign-in. The existing backend enforces expiry, single use, rate limits, and session invalidation.

Before deploying, follow PASSWORD_SECURITY.md: back up the database, apply the included password-security migration, set a strong server-only JWT_SECRET_KEY, FRONTEND_URL, RESEND_API_KEY, RESEND_FROM_EMAIL, and appropriate CORS_ORIGINS, and verify recovery mailbox ownership. Existing accounts are not automatically eligible for reset email. Never mark addresses verified in bulk or put provider secrets in VITE_ variables.

## Validation

The frontend production build passed locally. Backend pytest execution was blocked during collection by Windows Application Control refusing SQLAlchemy's compiled extension. This is an environment limitation, not a passing test result. The included Linux GitHub Actions workflow runs the full backend suite and frontend build; check its results before deployment. No real recovery email has been sent by this development work.
