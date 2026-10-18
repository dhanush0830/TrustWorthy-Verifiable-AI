/** Format integer minor-unit amount (e.g. 49900) to "$499.00" */
export function formatAmount(cents, currency = 'USD') {
  if (cents == null) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(cents / 100);
}

/** Format ISO datetime to readable local string */
export function formatDate(isoString) {
  if (!isoString) return '—';
  return new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(isoString));
}

/** Map payment status to CSS class suffix */
export function statusClass(status) {
  const map = {
    settled: 'settled',
    authorized: 'authorized',
    pending: 'pending',
    refunded: 'refunded',
    failed: 'failed',
    open: 'open',
    investigating: 'investigating',
  };
  return map[status?.toLowerCase()] ?? 'unknown';
}

/** Map action type to a readable label */
export function actionLabel(actionType) {
  const map = {
    refund: 'Refund',
    dismiss: 'Dismiss',
    escalate_human: 'Human Review Recommended — No Refund Authorized',
    request_info: 'Request Information',
  };
  return map[actionType] ?? actionType;
}

/** Map action type to CSS modifier */
export function actionClass(actionType) {
  const map = {
    refund: 'refund',
    dismiss: 'dismiss',
    escalate_human: 'escalate',
    request_info: 'request_info',
  };
  return map[actionType] ?? 'dismiss';
}
