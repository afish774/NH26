import axios from 'axios';

const BASE = 'http://localhost:8080/api';
const api = axios.create({ baseURL: BASE, headers: { 'Content-Type': 'application/json' } });

export const sendChat = (message, history, sessionId) =>
  api.post('/chat/', { message, history, session_id: sessionId }).then(r => r.data);

export const getTickets = () => api.get('/tickets/').then(r => r.data);

export const createTicket = (title, description, extras = {}) =>
  api.post('/tickets/', { title, description, ...extras }).then(r => r.data);

export const updateTicketStatus = (id, status) =>
  api.patch(`/tickets/${id}/status`, { status }).then(r => r.data);

export const analyzeScreenshot = (image_base64, media_type) =>
  api.post('/tickets/screenshot/', { image_base64, media_type }).then(r => r.data);

export const getAnalytics = () => api.get('/analytics/').then(r => r.data);
