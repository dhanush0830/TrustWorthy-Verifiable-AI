/**
 * API client for TrustWorthy AI backend.
 * In production (e.g. on Vercel), uses VITE_API_BASE_URL.
 * In local development, falls back to '/api/v1' proxied by Vite dev server.
 */

const rawBase = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/+$/, '');
const BASE = rawBase
  ? (rawBase.endsWith('/api/v1') ? rawBase : `${rawBase}/api/v1`)
  : '/api/v1';

function authHeaders(token) {
  return { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
}

async function handleResponse(res) {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) { /* ignore parse error */ }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/** POST /api/v1/auth/token — returns { access_token, token_type, user_id, role } */
export async function login(email, password) {
  const res = await fetch(`${BASE}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  return handleResponse(res);
}

/** GET /api/v1/auth/me — returns UserRead */
export async function getMe(token) {
  const res = await fetch(`${BASE}/auth/me`, { headers: authHeaders(token) });
  return handleResponse(res);
}

/** GET /api/v1/payments — returns PaymentRead[] */
export async function listPayments(token) {
  const res = await fetch(`${BASE}/payments`, { headers: authHeaders(token) });
  return handleResponse(res);
}

/** GET /api/v1/payments/:id — returns PaymentRead */
export async function getPayment(token, paymentId) {
  const res = await fetch(`${BASE}/payments/${paymentId}`, { headers: authHeaders(token) });
  return handleResponse(res);
}

/** GET /api/v1/cases — returns CaseRead[] */
export async function listCases(token) {
  const res = await fetch(`${BASE}/cases`, { headers: authHeaders(token) });
  return handleResponse(res);
}

/** GET /api/v1/cases/:id — returns CaseRead */
export async function getCase(token, caseId) {
  const res = await fetch(`${BASE}/cases/${caseId}`, { headers: authHeaders(token) });
  return handleResponse(res);
}

/**
 * POST /api/v1/cases/:caseId/investigate — returns InvestigationResult.
 * complaint is optional; if provided it overrides the case description.
 * provider can be 'mock', 'sarvam', 'ollama', or 'auto'.
 */
export async function investigateCase(token, caseId, complaint = null, provider = null) {
  const payload = {};
  if (complaint) payload.complaint = complaint;
  if (provider) payload.provider = provider;
  const res = await fetch(`${BASE}/cases/${caseId}/investigate`, {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  return handleResponse(res);
}
