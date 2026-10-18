import { formatAmount, formatDate } from '../utils';

/**
 * Payment ledger table displaying underlying transaction records.
 * Supports cross-referencing orders, payments, and statuses.
 */
export default function PaymentsTable({ payments, onSelectPayment, selectedId }) {
  if (!payments || payments.length === 0) {
    return (
      <div className="empty-state" style={{ padding: '2rem 1rem' }}>
        <div className="empty-icon">💳</div>
        <div className="empty-title">No payment records found</div>
        <div className="empty-desc">No payment transactions are associated with this customer account.</div>
      </div>
    );
  }

  return (
    <div className="table-wrapper">
      <table className="data-table" id="payments-table" aria-label="Authoritative payment ledger">
        <thead>
          <tr>
            <th>Payment ID</th>
            <th>Linked Order</th>
            <th>Amount (USD)</th>
            <th>Status</th>
            <th>Gateway Provider</th>
            <th>Timestamp</th>
          </tr>
        </thead>
        <tbody>
          {payments.map(p => {
            const isSelected = selectedId === p.id;
            const statusLower = p.status?.toLowerCase();
            const badgeClass =
              statusLower === 'settled'
                ? 'badge-pass'
                : statusLower === 'authorized'
                ? 'badge-warn'
                : statusLower === 'failed'
                ? 'badge-fail'
                : 'badge-neutral';

            return (
              <tr
                key={p.id}
                id={`payment-row-${p.id}`}
                onClick={() => onSelectPayment?.(p)}
                className={isSelected ? 'selected-row' : ''}
                style={{ cursor: onSelectPayment ? 'pointer' : 'default' }}
                aria-selected={isSelected}
              >
                <td className="col-id font-mono">
                  {p.id}
                </td>
                <td className="font-mono text-xs text-secondary">
                  {p.order_id ? (
                    <span style={{ fontWeight: 500, color: 'var(--txt-navy)' }}>{p.order_id}</span>
                  ) : (
                    <span className="text-muted">—</span>
                  )}
                </td>
                <td className="col-amount font-mono">
                  {formatAmount(p.amount, p.currency)}
                </td>
                <td>
                  <span className={`badge ${badgeClass}`}>
                    {p.status}
                  </span>
                </td>
                <td className="text-secondary text-xs">
                  {p.provider || 'payment_provider'}
                </td>
                <td className="text-secondary text-xs font-mono">
                  {formatDate(p.created_at)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
