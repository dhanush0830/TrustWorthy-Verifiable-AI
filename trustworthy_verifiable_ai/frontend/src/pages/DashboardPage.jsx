import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../context/AuthContext';
import { listPayments, listCases, investigateCase } from '../api';
import PaymentsTable from '../components/PaymentsTable';
import CasesTable from '../components/CasesTable';
import InvestigationResultComponent from '../components/InvestigationResult';
import { formatAmount, formatDate } from '../utils';

/**
 * Professional Financial Operations Dashboard.
 *
 * Screen Layout:
 * B. Overview: Live metrics (Cases, Open Disputes, Settled Payments, Settled Volume).
 * C. Complaint cases table: Real case IDs, title, description, status, selection.
 * D. Payment ledger: Underlying ledger transactions for audit cross-referencing.
 * E. Investigation workspace: Model provider selector, complaint review, trigger button.
 * F & G. Investigation results: 6-section verified results & deterministic validation outcomes.
 */
export default function DashboardPage() {
  const { token, user } = useAuth();

  /* ─── Cases state ─── */
  const [cases, setCases]               = useState([]);
  const [casesLoading, setCasesLoading] = useState(true);
  const [casesError, setCasesError]     = useState(null);
  const [selectedCase, setSelectedCase] = useState(null);

  /* ─── Payments state ─── */
  const [payments, setPayments]         = useState([]);
  const [payLoading, setPayLoading]     = useState(true);
  const [payError, setPayError]         = useState(null);
  const [selectedPayment, setSelectedPayment] = useState(null);

  /* ─── Investigation state ─── */
  const [caseId, setCaseId]             = useState('');
  const [complaint, setComplaint]       = useState('');
  const [provider, setProvider]         = useState('mock'); // Safe default
  const [investing, setInvesting]       = useState(false);
  const [investError, setInvestError]   = useState(null);
  const [investResult, setInvestResult] = useState(null);
  const [activeTab, setActiveTab]       = useState('cases'); // 'cases' | 'payments'

  /* ─── Initial load of payments & cases ─── */
  useEffect(() => {
    let cancelled = false;
    setPayLoading(true);
    setCasesLoading(true);
    setPayError(null);
    setCasesError(null);

    Promise.all([
      listPayments(token).catch(err => { if (!cancelled) setPayError(err.message); return []; }),
      listCases(token).catch(err => { if (!cancelled) setCasesError(err.message); return []; }),
    ]).then(([payData, caseData]) => {
      if (!cancelled) {
        setPayments(payData || []);
        setCases(caseData || []);

        if (caseData && caseData.length > 0) {
          const first = caseData[0];
          setSelectedCase(first);
          setCaseId(first.id);
          setComplaint(first.description);
        }
      }
    }).finally(() => {
      if (!cancelled) {
        setPayLoading(false);
        setCasesLoading(false);
      }
    });

    return () => { cancelled = true; };
  }, [token]);

  /* ─── Accurate metrics derived strictly from live API data ─── */
  const totalCasesCount = cases.length;
  const openCasesCount = cases.filter(c => c.status === 'open' || c.status === 'investigating').length;
  const settledPayments = payments.filter(p => p.status === 'settled');
  const settledCount = settledPayments.length;
  const settledTotalAmount = settledPayments.reduce((sum, p) => sum + (p.amount || 0), 0);
  const currency = payments[0]?.currency ?? 'USD';

  /* ─── Case selection: instantly clears previous results to avoid stale data ─── */
  const handleSelectCase = useCallback((c) => {
    setSelectedCase(c);
    setCaseId(c.id);
    setComplaint(c.description);
    // Explicit requirement: clear previous results when switching cases
    setInvestResult(null);
    setInvestError(null);
  }, []);

  /* ─── Payment selection ─── */
  const handleSelectPayment = useCallback((payment) => {
    setSelectedPayment(prev => prev?.id === payment.id ? null : payment);
  }, []);

  /* ─── Run investigation on real case ID ─── */
  const handleInvestigate = useCallback(async (e) => {
    e.preventDefault();
    if (!caseId.trim() || investing) return;

    setInvesting(true);
    setInvestError(null);
    setInvestResult(null);

    try {
      const result = await investigateCase(
        token,
        caseId.trim(),
        complaint.trim() || null,
        provider
      );
      setInvestResult(result);

      // Reflect status change in local cases state if investigating
      setCases(prev => prev.map(c => c.id === caseId.trim() ? { ...c, status: 'investigating' } : c));
    } catch (err) {
      setInvestError(err.message);
    } finally {
      setInvesting(false);
    }
  }, [token, caseId, complaint, provider, investing]);

  return (
    <div className="dashboard">

      {/* ─────────────────────────────────────────────────────────────
          B. Overview Metrics Row
         ───────────────────────────────────────────────────────────── */}
      <div className="stats-grid" id="overview-metrics-grid">
        <div className="card stat-card" id="metric-total-cases">
          <div className="stat-label">Authorized Cases</div>
          <div className="stat-value">
            {casesLoading ? <span className="spinner" /> : totalCasesCount}
          </div>
          <div className="stat-subtext">Tenant scope: {user?.role}</div>
        </div>

        <div className="card stat-card" id="metric-open-cases">
          <div className="stat-label">Open / In Review</div>
          <div className="stat-value" style={{ color: openCasesCount > 0 ? '#92400e' : 'var(--txt-navy)' }}>
            {casesLoading ? <span className="spinner" /> : openCasesCount}
          </div>
          <div className="stat-subtext">Awaiting resolution</div>
        </div>

        <div className="card stat-card" id="metric-settled-payments">
          <div className="stat-label">Settled Payments</div>
          <div className="stat-value">
            {payLoading ? <span className="spinner" /> : settledCount}
          </div>
          <div className="stat-subtext">Verified gateway records</div>
        </div>

        <div className="card stat-card" id="metric-total-value">
          <div className="stat-label">Settled Volume ({currency})</div>
          <div className="stat-value font-mono" style={{ fontSize: '1.25rem' }}>
            {payLoading ? <span className="spinner" /> : formatAmount(settledTotalAmount, currency)}
          </div>
          <div className="stat-subtext">Sum of settled transactions</div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          C & D. Tabbed Ledger View: Complaint Cases & Payment Records
         ───────────────────────────────────────────────────────────── */}
      <div className="card" id="records-ledger-card">
        <div className="card-header">
          <div className="flex items-center gap-3">
            <h2>Operations Records</h2>
            <div className="flex gap-1" style={{ backgroundColor: '#f1f5f9', padding: '2px', borderRadius: '4px' }}>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'cases' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setActiveTab('cases')}
                id="tab-cases-btn"
                style={{ borderRadius: '3px' }}
              >
                Complaint Cases ({cases.length})
              </button>
              <button
                type="button"
                className={`btn btn-sm ${activeTab === 'payments' ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setActiveTab('payments')}
                id="tab-payments-btn"
                style={{ borderRadius: '3px' }}
              >
                Payment Ledger ({payments.length})
              </button>
            </div>
          </div>
          <span className="text-xs text-muted">
            {activeTab === 'cases' ? 'Click row to select for investigation' : 'Authoritative transaction ledger'}
          </span>
        </div>

        <div className="card-body" style={{ padding: 0 }}>
          {activeTab === 'cases' ? (
            <>
              {casesError && (
                <div className="alert alert-error" style={{ margin: '1rem' }} id="cases-error">
                  <span>⚠</span>
                  <span>Failed to load cases: {casesError}</span>
                </div>
              )}
              {!casesLoading && !casesError && (
                <CasesTable
                  cases={cases}
                  selectedId={selectedCase?.id}
                  onSelectCase={handleSelectCase}
                />
              )}
            </>
          ) : (
            <>
              {payError && (
                <div className="alert alert-error" style={{ margin: '1rem' }} id="payments-error">
                  <span>⚠</span>
                  <span>Failed to load payments: {payError}</span>
                </div>
              )}
              {!payLoading && !payError && (
                <PaymentsTable
                  payments={payments}
                  selectedId={selectedPayment?.id}
                  onSelectPayment={handleSelectPayment}
                />
              )}
            </>
          )}
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          E & F. Investigation Workspace & Verified Results
         ───────────────────────────────────────────────────────────── */}
      <div className="investigate-layout">

        {/* E. Investigation Control Workspace */}
        <div className="card" id="investigate-control-card">
          <div className="card-header">
            <h2>Investigation Setup</h2>
            {selectedCase && (
              <span className="badge badge-neutral font-mono text-xs">
                {selectedCase.id}
              </span>
            )}
          </div>
          <div className="card-body">

            {selectedCase ? (
              <div
                style={{
                  padding: '0.75rem 0.85rem',
                  backgroundColor: '#f8fafc',
                  border: '1px solid var(--border-light)',
                  borderRadius: 'var(--r-sm)',
                  marginBottom: '1rem',
                }}
                id="active-case-summary-box"
              >
                <div className="text-xs text-muted" style={{ textTransform: 'uppercase', fontWeight: 600, letterSpacing: '0.03em' }}>
                  Target Case for Investigation
                </div>
                <div style={{ fontWeight: 600, color: 'var(--txt-navy)', marginTop: '0.2rem' }}>
                  {selectedCase.title}
                </div>
                <div className="text-xs text-muted" style={{ marginTop: '0.25rem' }}>
                  Customer ID: <code className="font-mono">{selectedCase.customer_id}</code> · Status: <strong>{selectedCase.status}</strong>
                </div>
              </div>
            ) : (
              <div className="alert alert-info" style={{ marginBottom: '1rem' }}>
                <span>ℹ</span>
                <span>Please select a case from the table above to start an investigation.</span>
              </div>
            )}

            <form onSubmit={handleInvestigate} id="investigate-form">
              {/* Case ID Input (Pre-filled from table) */}
              <div className="form-group" style={{ marginBottom: '0.85rem' }}>
                <label className="form-label" htmlFor="case-id-input">
                  Case Identifier *
                </label>
                <input
                  id="case-id-input"
                  className="form-input font-mono"
                  type="text"
                  placeholder="e.g. CAS-DEMO-A1"
                  value={caseId}
                  onChange={e => {
                    setCaseId(e.target.value);
                    setInvestResult(null); // Clear stale results
                  }}
                  required
                />
              </div>

              {/* Model Provider Selector */}
              <div className="form-group" style={{ marginBottom: '0.85rem' }}>
                <label className="form-label" htmlFor="provider-select">
                  LLM Investigation Provider *
                </label>
                <select
                  id="provider-select"
                  className="form-select"
                  value={provider}
                  onChange={e => setProvider(e.target.value)}
                >
                  <option value="mock">MOCK (Offline Simulation — Demo Safe)</option>
                  <option value="sarvam">Sarvam AI (sarvam-105b Cloud Live)</option>
                  <option value="auto">Auto (Sarvam if key present, else Ollama)</option>
                  <option value="ollama">Ollama (Local Self-Hosted Qwen)</option>
                </select>
                <div className="text-xs text-muted" style={{ marginTop: '0.25rem' }}>
                  {provider === 'mock' && 'Simulated mode runs offline; results are prominently labeled SIMULATED.'}
                  {provider === 'sarvam' && 'Live cloud inference on sarvam-105b. Does not fall back silently.'}
                  {provider === 'auto' && 'Dispatches to Sarvam if API key is configured.'}
                  {provider === 'ollama' && 'Queries local Ollama endpoint on 127.0.0.1:11434.'}
                </div>
              </div>

              {/* Untrusted Complaint Description */}
              <div className="form-group" style={{ marginBottom: '1.25rem' }}>
                <label className="form-label" htmlFor="complaint-input">
                  Complaint Description
                </label>
                <textarea
                  id="complaint-input"
                  className="form-textarea"
                  rows={4}
                  value={complaint}
                  onChange={e => setComplaint(e.target.value)}
                  maxLength={4000}
                  placeholder="Customer statement..."
                />
                <div className="flex justify-between text-xs text-muted" style={{ marginTop: '0.2rem' }}>
                  <span>PII is automatically redacted before model transmission</span>
                  <span>{complaint.length}/4000</span>
                </div>
              </div>

              {/* Error Box */}
              {investError && (
                <div className="alert alert-error" style={{ marginBottom: '1rem' }} id="invest-error" role="alert">
                  <span>⛔</span>
                  <div>
                    <strong>Investigation request failed:</strong> {investError}
                  </div>
                </div>
              )}

              {/* Submit Button */}
              <button
                id="investigate-btn"
                className="btn btn-primary w-full"
                type="submit"
                disabled={investing || !caseId.trim()}
              >
                {investing ? (
                  <>
                    <span className="spinner" />
                    <span>Investigating {caseId}…</span>
                  </>
                ) : (
                  <span>Run Deterministic Investigation</span>
                )}
              </button>
            </form>

            <div className="divider" />

            <div className="text-xs text-muted" style={{ lineHeight: 1.5 }}>
              <strong>Trust & Safety Guarantee:</strong> All model assertions are checked against authoritative database evidence. Contradictions or unsupported proposals trigger mandatory human review.
            </div>
          </div>
        </div>

        {/* F & G. Investigation Results Display */}
        <div className="card" id="investigation-result-card">
          <div className="card-header">
            <h2>Investigation Results & Audit Evidence</h2>
            {investResult && (
              <button
                id="clear-result-btn"
                className="btn btn-ghost btn-sm"
                onClick={() => { setInvestResult(null); setInvestError(null); }}
                type="button"
              >
                Clear Findings
              </button>
            )}
          </div>
          <div className="card-body">
            {!investResult && !investing && !investError && (
              <div className="empty-state">
                <div className="empty-icon">⚖️</div>
                <div className="empty-title">Ready for investigation</div>
                <div className="empty-desc">
                  Select a case from the operations ledger on the left, verify the complaint text, and click <strong>Run Deterministic Investigation</strong>.
                </div>
              </div>
            )}

            {investing && (
              <div className="loading-center" id="invest-loading">
                <span className="spinner spinner-lg" />
                <div style={{ fontWeight: 600, color: 'var(--txt-navy)' }}>
                  Executing investigation on {caseId}…
                </div>
                <div className="text-xs text-muted">
                  Collecting authoritative evidence, redacting PII, and validating safety invariants.
                </div>
              </div>
            )}

            {!investing && investResult && (
              <InvestigationResultComponent result={investResult} />
            )}
          </div>
        </div>

      </div>

    </div>
  );
}
