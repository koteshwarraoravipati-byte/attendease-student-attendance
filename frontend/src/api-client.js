export const SESSION_EXPIRED = 'attendease:session-expired';
export function createApi({ baseURL, storage, events, fetchImpl = fetch, timers = globalThis }) {
  return async (path, options = {}) => {
    const { authenticated = true, ...requestOptions } = options;
    const token = authenticated ? storage.getItem('attendease_token') : null;
    const controller = new AbortController();
    const timeoutId = timers.setTimeout(() => controller.abort(), 15000);
    let response;
    try {
      response = await fetchImpl(baseURL + (path.startsWith('/') ? path : '/' + path), {
        ...requestOptions, signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}), ...(requestOptions.headers || {}) }
      });
    } catch (error) {
      if (error.name === 'AbortError') throw Error('The attendance service took too long to respond. Please try again.');
      throw Error('Could not connect to the attendance service. Check your connection and try again.');
    } finally { timers.clearTimeout(timeoutId); }
    if (response.status === 401 && token && storage.getItem('attendease_token') === token) {
      storage.removeItem('attendease_token');
      events.dispatchEvent(new Event(SESSION_EXPIRED));
    }
    const text = await response.text();
    let payload = {};
    try { payload = text ? JSON.parse(text) : {}; } catch { payload = {}; }
    if (!response.ok) {
      const error = Error(response.status >= 500
        ? 'The attendance service is temporarily unavailable. Please try again shortly.'
        : typeof payload.error === 'string' ? payload.error : 'Request failed (' + response.status + ').');
      error.status = response.status;
      throw error;
    }
    return new Response(text, { status: response.status, headers: response.headers });
  };
}
