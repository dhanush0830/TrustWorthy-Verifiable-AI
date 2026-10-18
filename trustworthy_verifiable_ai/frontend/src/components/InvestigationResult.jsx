import { formatAmount, actionLabel } from '../utils';

/**
 * InvestigationResult display component.
 *
 * Organized into 6 distinct, compact sections:
 * 1. Overall verification and escalation status banner.
 * 2. Model findings & executive summary.
 * 3. Deterministic validation checks and their actual outcomes.
 * 4. Model claims with supporting or contradictory evidence.
 * 5. Proposed action (only displayed as actionable if deterministically valid).
 * 6. Audit & model metadata and limitations.
 */
export default function InvestigationResult({ result }) {
  if (!result) return null;

  const isMock = result.model_metadata?.model_name?.startsWith('mock-');
  const isSarvam = result.model_metadata?.model_name?.includes('sarvam');
  const status = result.verification_status || (result.needs_escalation ? 'escalated' : 'verified');

  const bannerConfig = {
    contradicted: {
      className: 'status-banner status-banner-contradicted',
      icon: '⛔',
      title: 'Contradiction Detected — Human Review Required',
      desc: 'One or more claims or proposed actions directly conflict with verified ledger evidence. Automated action has been rejected.',
      badgeClass: 'badge-fail',
      badgeText: 'Contradiction / Safety Violation',
    },
    inconclusive: {
      className: 'status-banner status-banner-inconclusive',
      icon: '⚠️',
      title: 'Insufficient Evidence — Escalation Required',
      desc: 'Authoritative records are incomplete or insufficient to verify the customer allegation. Human investigation required.',
      badgeClass: 'badge-warn',
      badgeText: 'Inconclusive Evidence',
    },
    escalated: {
      className: 'status-banner status-banner-escalated',
      icon: '⚠️',
      title: 'Needs Operational Human Review',
      desc: 'This case has been flagged for human review. No automated refund or resolution will be taken without manual authorization.',
      badgeClass: 'badge-warn',
      badgeText: 'Human Review Required',
    },
    verified: {
      className: 'status-banner status-banner-verified',
      icon: '✓',
      title: 'Deterministially Verified',
      desc: 'All factual claims and proposed actions passed 100% of independent deterministic validation checks against authoritative evidence.',
      badgeClass: 'badge-pass',
      badgeText: 'Fully Verified',
    },
    rejected: {
      className: 'status-banner status-banner-contradicted',
      icon: '✗',
      title: 'Claim Rejected by Safety Validation',
      desc: 'The investigation failed deterministic safety criteria and cannot be accepted.',
      badgeClass: 'badge-fail',
      badgeText: 'Rejected',
    },
  }[status] || {
    className: 'status-banner status-banner-escalated',
    icon: 'ℹ',
    title: 'Investigation Completed',
    desc: 'Review the findings and validation check outcomes below.',
    badgeClass: 'badge-neutral',
    badgeText: status,
  };

  return (
    <div className="result-container" id="investigation-result">

      {/* ─────────────────────────────────────────────────────────────
          1. Overall Verification & Escalation Status
         ───────────────────────────────────────────────────────────── */}
      <div className={bannerConfig.className} id="overall-status-banner">
        <span style={{ fontSize: '1.25rem', lineHeight: 1 }} aria-hidden="true">
          {bannerConfig.icon}
        </span>
        <div style={{ flex: 1 }}>
          <div className="flex items-center justify-between" style={{ flexWrap: 'wrap', gap: '0.5rem', marginBottom: '0.2rem' }}>
            <div className="status-banner-title">{bannerConfig.title}</div>
            <span className={`badge ${bannerConfig.badgeClass}`} id="verification-status-badge">
              {bannerConfig.badgeText}
            </span>
          </div>
          <div className="status-banner-desc">{bannerConfig.desc}</div>
        </div>
      </div>

      {/* Prominent Provenance Notice (Simulated vs Live) */}
      {isMock ? (
        <div className="sim-notice" id="simulation-alert">
          <strong style={{ color: 'var(--txt-navy)' }}>SIMULATED RESULT (Offline Mock Model):</strong>{' '}
          This investigation was generated offline by a deterministic mock engine for local testing. It is not live AI output.
        </div>
      ) : isSarvam ? (
        <div className="sim-notice" style={{ borderLeftColor: '#16a34a' }} id="sarvam-live-alert">
          <strong style={{ color: '#166534' }}>LIVE AI (Sarvam 105B):</strong>{' '}
          This investigation was returned from Sarvam AI cloud API using the verified model <code>sarvam-105b</code>.
        </div>
      ) : null}

      {/* ─────────────────────────────────────────────────────────────
          2. Model Findings & Executive Summary
         ───────────────────────────────────────────────────────────── */}
      <div className="result-section" id="executive-summary-section">
        <div className="result-section-header">
          <span>Executive Summary & Categorization</span>
          <div className="flex items-center gap-2">
            <span className="badge badge-neutral font-mono text-xs">
              Case: {result.case_id}
            </span>
            <span className="badge badge-neutral">
              Issue: {result.issue_type?.replace(/_/g, ' ')}
            </span>
          </div>
        </div>
        <div className="result-section-body">
          <p style={{ color: 'var(--txt-primary)', fontSize: '0.875rem', lineHeight: 1.55 }}>
            {result.summary}
          </p>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          3. Deterministic Validation Checks & Actual Outcomes
         ───────────────────────────────────────────────────────────── */}
      <div className="result-section" id="deterministic-checks-section">
        <div className="result-section-header">
          <span>Deterministic Validation Checks ({result.validation_checks?.length || 0})</span>
          <span className="text-xs text-muted">Independent verification rules</span>
        </div>
        <div className="result-section-body" style={{ padding: '0.5rem 1rem' }}>
          {result.validation_checks && result.validation_checks.length > 0 ? (
            <table className="validation-table" id="validation-checks-table">
              <tbody>
                {result.validation_checks.map((chk, i) => {
                  const isPass = chk.status === 'PASSED';
                  const isFail = chk.status === 'FAILED';
                  const badgeClass = isPass ? 'badge-pass' : isFail ? 'badge-fail' : 'badge-neutral';

                  return (
                    <tr key={i} id={`validation-check-${i}`}>
                      <td style={{ width: '220px', fontWeight: 600, color: 'var(--txt-navy)' }}>
                        {chk.name}
                      </td>
                      <td style={{ width: '110px' }}>
                        <span className={`badge ${badgeClass}`}>
                          {chk.status}
                        </span>
                      </td>
                      <td style={{ color: 'var(--txt-secondary)', fontSize: '0.8rem' }}>
                        <div>{chk.description}</div>
                        {chk.details && (
                          <div
                            style={{
                              marginTop: '0.2rem',
                              color: isFail ? '#991b1b' : 'var(--txt-muted)',
                              fontWeight: isFail ? 500 : 400,
                            }}
                          >
                            {chk.details}
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div className="text-muted text-xs" style={{ padding: '0.5rem 0' }}>
              No independent validation checks were executed for this output.
            </div>
          )}
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          4. Model Findings, Claims & Supporting Evidence
         ───────────────────────────────────────────────────────────── */}
      <div className="result-section" id="claims-evidence-section">
        <div className="result-section-header">
          <span>Model Claims & Authoritative Evidence ({result.claims?.length || 0})</span>
          <span className="text-xs text-muted">Traceable to database records</span>
        </div>
        <div className="result-section-body">
          {result.claims && result.claims.length > 0 ? (
            <div className="claims-list">
              {result.claims.map((claim, idx) => (
                <ClaimCard key={idx} claim={claim} index={idx} />
              ))}
            </div>
          ) : (
            <div className="text-muted text-xs">No factual claims extracted by the model.</div>
          )}
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          5. Proposed Action (Validated vs Rejected)
         ───────────────────────────────────────────────────────────── */}
      <div className="result-section" id="proposed-action-section">
        <div className="result-section-header">
          <span>Proposed Action</span>
          {result.proposed_action && (
            <span
              className={`badge ${result.proposed_action.is_valid ? 'badge-pass' : 'badge-fail'}`}
              id="action-safety-badge"
            >
              {result.proposed_action.is_valid ? 'Verified Safe' : 'Safety Rejected'}
            </span>
          )}
        </div>
        <div className="result-section-body">
          {result.proposed_action ? (
            <div
              className={`action-box ${result.proposed_action.is_valid ? 'action-box-valid' : 'action-box-rejected'}`}
              id="proposed-action-card"
            >
              <div className="flex items-center justify-between" style={{ marginBottom: '0.5rem' }}>
                <div style={{ fontWeight: 600, color: 'var(--txt-navy)', fontSize: '0.95rem' }}>
                  {actionLabel(result.proposed_action.action_type)} Proposal
                </div>
                {!result.proposed_action.is_valid && (
                  <span className="badge badge-fail">
                    Invalid Action
                  </span>
                )}
              </div>

              {result.proposed_action.target_payment_id && (
                <div className="action-row">
                  <span className="text-secondary text-xs">Target Payment ID</span>
                  <span className="font-mono text-xs font-semibold text-navy">
                    {result.proposed_action.target_payment_id}
                  </span>
                </div>
              )}

              {result.proposed_action.amount != null && (
                <div className="action-row">
                  <span className="text-secondary text-xs">Proposed Amount</span>
                  <span className="font-mono text-xs font-semibold text-navy">
                    {formatAmount(result.proposed_action.amount, result.proposed_action.currency)}
                  </span>
                </div>
              )}

              <div className="action-row">
                <span className="text-secondary text-xs">Model Justification</span>
                <span className="text-secondary text-xs" style={{ maxWidth: '420px', textAlign: 'right' }}>
                  {result.proposed_action.reason}
                </span>
              </div>

              {/* If invalid: show exact failure rationale */}
              {!result.proposed_action.is_valid && (
                <div
                  style={{
                    marginTop: '0.75rem',
                    padding: '0.6rem 0.85rem',
                    backgroundColor: '#ffffff',
                    border: '1px solid #fca5a5',
                    borderRadius: 'var(--r-sm)',
                  }}
                  id="action-rejection-rationale"
                >
                  <div style={{ fontWeight: 600, color: '#991b1b', fontSize: '0.8rem', marginBottom: '0.2rem' }}>
                    ⛔ Proposal Rejected by Deterministic Safety Validator:
                  </div>
                  <div style={{ color: '#7f1d1d', fontSize: '0.78rem', lineHeight: 1.4 }}>
                    {result.proposed_action.rejection_reason}
                  </div>
                  {result.proposed_action.validation_errors?.length > 1 && (
                    <ul style={{ marginTop: '0.35rem', paddingLeft: '1.25rem', color: '#7f1d1d', fontSize: '0.75rem' }}>
                      {result.proposed_action.validation_errors.map((err, ei) => (
                        <li key={ei}>{err}</li>
                      ))}
                    </ul>
                  )}
                  <div style={{ marginTop: '0.4rem', fontSize: '0.72rem', color: '#991b1b', fontStyle: 'italic' }}>
                    This proposal is unsafe and cannot be accepted as an actionable recommendation. Human review is required.
                  </div>
                </div>
              )}

              {result.proposed_action.is_valid && (
                <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#065f46' }}>
                  ✓ This proposed action passed all independent verification checks and is consistent with ledger records.
                </div>
              )}
            </div>
          ) : (
            <div className="text-muted text-xs">
              No automated action was proposed. Safe escalation triggered.
            </div>
          )}
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          6. Audit & Model Metadata
         ───────────────────────────────────────────────────────────── */}
      {result.model_metadata && (
        <div className="result-section" id="model-metadata-section">
          <div className="result-section-header">
            <span>Model Metadata & Audit Trail</span>
            <span className="text-xs text-muted">SEC-07 Verified</span>
          </div>
          <div className="result-section-body" style={{ padding: '0.75rem 1rem' }}>
            <div className="flex items-center gap-3" style={{ flexWrap: 'wrap', fontSize: '0.78rem' }}>
              <div>
                <span className="text-muted">Model:&nbsp;</span>
                <span className="font-mono" style={{ color: 'var(--txt-navy)', fontWeight: 600 }}>
                  {result.model_metadata.model_name}
                </span>
              </div>
              <div>
                <span className="text-muted">Temperature:&nbsp;</span>
                <span className="font-mono">{result.model_metadata.temperature}</span>
              </div>
              <div>
                <span className="text-muted">Prompt Version:&nbsp;</span>
                <span className="font-mono">{result.model_metadata.prompt_version}</span>
              </div>
              {result.model_metadata.latency_ms != null && (
                <div>
                  <span className="text-muted">Latency:&nbsp;</span>
                  <span className="font-mono">{result.model_metadata.latency_ms}ms</span>
                </div>
              )}
            </div>
            <div style={{ marginTop: '0.5rem', fontSize: '0.72rem', color: 'var(--txt-muted)', lineHeight: 1.45 }}>
              Deterministic safety invariants override raw model text. AuditEvent logged with SHA-256 model input hash (customer PII redacted prior to invocation).
            </div>
          </div>
        </div>
      )}

    </div>
  );
}

function ClaimCard({ claim, index }) {
  const isAccepted = claim.is_accepted && !claim.flagged;

  return (
    <div
      className={`claim-card ${claim.flagged ? 'claim-card-flagged' : ''}`}
      id={`claim-${index}`}
    >
      <div className="claim-header">
        <div className="flex items-center gap-2">
          <span className="badge badge-neutral">
            {claim.claim_type?.replace(/_/g, ' ')}
          </span>
          {claim.flagged ? (
            <span className="badge badge-fail" id={`claim-${index}-flagged-badge`}>
              Contradiction / Rejected
            </span>
          ) : (
            <span className="badge badge-pass" id={`claim-${index}-verified-badge`}>
              Verified
            </span>
          )}
        </div>
        <span className="text-xs text-muted font-mono">
          Claim #{index + 1}
        </span>
      </div>

      <div className="claim-statement">
        {claim.statement}
      </div>

      {/* Cited Evidence Chips */}
      {claim.evidence_ids && claim.evidence_ids.length > 0 && (
        <div className="claim-citations">
          <span className="text-xs text-muted" style={{ marginRight: '0.2rem' }}>Evidence:</span>
          {claim.evidence_ids.map(eid => (
            <span key={eid} className="citation-chip" title={`Evidence record ${eid}`}>
              {eid}
            </span>
          ))}
        </div>
      )}

      {/* Rejection / Contradiction Details */}
      {claim.flagged && claim.rejection_reason && (
        <div className="claim-rejection-box" id={`claim-${index}-rejection`}>
          <strong>Violation:</strong> {claim.rejection_reason}
        </div>
      )}
    </div>
  );
}
