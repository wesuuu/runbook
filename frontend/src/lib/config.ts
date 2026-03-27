const host = import.meta.env.VITE_API_HOST || 'localhost';
const port = import.meta.env.VITE_API_PORT || '8000';
export const API_BASE = `http://${host}:${port}`;
