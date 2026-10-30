export const PASSWORD_MIN = 12;
export const PASSWORD_MAX = 128;
export const RECOVERY_MESSAGE = 'If an eligible account exists for this email, a password reset link has been sent. Check your inbox and spam folder.';

export function validateNewPassword(password, confirmation) {
  if (typeof password !== 'string' || [...password].length < PASSWORD_MIN || [...password].length > PASSWORD_MAX) return 'Use a password between 12 and 128 characters.';
  if (password !== confirmation) return 'The new passwords do not match.';
  return '';
}

// Fragment tokens never enter storage, analytics, logs, or a server URL.
export function consumeResetLocation(location, history) {
  const hash = location.hash || '';
  const isReset = hash === '#reset-password' || hash.startsWith('#reset-password?');
  if (!isReset) return { isReset: false, token: '' };
  // Scrub even malformed/missing tokens before any asynchronous work.
  history.replaceState(null, '', location.pathname + location.search);
  const params = new URLSearchParams(hash.split('?').slice(1).join('?'));
  const tokens = params.getAll('token');
  return { isReset: true, token: tokens.length === 1 ? tokens[0] : '' };
}
