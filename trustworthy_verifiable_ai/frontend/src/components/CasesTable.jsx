import { formatDate } from '../utils';

/**
 * Table displaying authorized complaint cases for the user.
 * Allows clicking a case or using the select action to select its real ID.
 */
export default function CasesTable({ cases, selectedId, onSelectCase }) {
  if (!cases || cases.length === 0) {
    return (
      <div className="empty-state" style={{ padding: '2rem 1rem' }}>
        <div className="empty-icon">📁</div>
        <div className="empty-title">No complaint cases found</div>
        <div className="empty-desc">No complaint cases are currently registered within your authorized tenant scope.</div>
      </div>
    );
  }

  return (
    <div className="table-wrapper">
      <table className="data-table" id="cases-table" aria-label="Complaint cases ledger">
        <thead>
          <tr>
            <th style={{ width: '130px' }}>Case ID</th>
            <th>Title & Complaint Summary</th>
            <th style={{ width: '110px' }}>Status</th>
            <th style={{ width: '160px' }}>Created</th>
            <th style={{ width: '110px', textAlign: 'right' }}>Action</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => {
            const isSelected = selectedId === c.id;
            return (
              <tr
                key={c.id}
                onClick={() => onSelectCase(c)}
                className={isSelected ? 'selected-row' : ''}
                style={{ cursor: 'pointer' }}
                id={`case-row-${c.id}`}
                aria-selected={isSelected}
              >
                <td>
                  <span className="col-id" style={{ color: 'var(--accent-blue)' }}>
                    {c.id}
                  </span>
                </td>
                <td>
                  <div style={{ fontWeight: 600, color: 'var(--txt-navy)', marginBottom: '0.15rem' }}>
                    {c.title}
                  </div>
                  <div
                    className="text-muted text-xs"
                    style={{
                      maxWidth: '520px',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                    title={c.description}
                  >
                    {c.description}
                  </div>
                </td>
                <td>
                  <span
                    className={`badge badge-${c.status === 'open' ? 'warn' : c.status === 'investigating' ? 'warn' : 'neutral'}`}
                  >
                    {c.status}
                  </span>
                </td>
                <td className="text-xs font-mono text-secondary">
                  {formatDate(c.created_at)}
                </td>
                <td style={{ textAlign: 'right' }}>
                  <button
                    type="button"
                    className={`btn btn-sm ${isSelected ? 'btn-primary' : 'btn-secondary'}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSelectCase(c);
                    }}
                    id={`select-case-btn-${c.id}`}
                    aria-label={`Select case ${c.id}`}
                  >
                    {isSelected ? 'Active' : 'Select'}
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
