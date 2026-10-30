import { createApi } from './api-client.js';
export { SESSION_EXPIRED } from './api-client.js';
const API = String(import.meta.env.VITE_API_URL || 'http://localhost:5000/api').trim().replace(/\/+$/, '');
export const api = createApi({ baseURL: API, storage: localStorage, events: window });
