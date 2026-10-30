-- Explicit operator-run additive migration. NEVER execute during cold starts.
BEGIN;
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS recovery_email_verified BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS password_reset_tokens (
 token_hash VARCHAR(64) PRIMARY KEY,
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 auth_version INTEGER NOT NULL,
 expires_at TIMESTAMP NOT NULL,
 used_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user_id ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_expires_at ON password_reset_tokens(expires_at);
CREATE TABLE IF NOT EXISTS password_rate_limits (
 key VARCHAR(64) PRIMARY KEY,
 window_start BIGINT NOT NULL,
 count INTEGER NOT NULL
);
COMMIT;
