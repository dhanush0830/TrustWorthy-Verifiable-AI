import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

const DEMO_CREDENTIALS = [
  { email: 'customer.a@example.com', password: 'Password123!', role: 'customer', name: 'Alice Anderson' },
  { email: 'customer.b@example.com', password: 'Password123!', role: 'customer', name: 'Bob Baker' },
  { email: 'agent@example.com',      password: 'AgentPassword123!', role: 'agent', name: 'Support Agent Sarah' },
  { email: 'reviewer@example.com',   password: 'ReviewerPassword123!', role: 'reviewer', name: 'Reviewer Ryan' },
];

export default function LoginPage() {
  const { login, error, loading } = useAuth();
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (email && password) login(email, password);
  };

  const fillCred = (cred) => {
    setEmail(cred.email);
    setPassword(cred.password);
  };

  return (
    <div className="login-page">
      <div className="card login-card">
        <div className="card-body" style={{ padding: '2rem' }}>
          <div className="login-header">
            <div
              className="navbar-logo"
              style={{
                width: '36px',
                height: '36px',
                backgroundColor: 'var(--txt-navy)',
                color: '#ffffff',
                margin: '0 auto',
                fontSize: '1.1rem',
              }}
              aria-hidden="true"
            >
              T
            </div>
            <h1 className="login-title">TrustWorthy AI</h1>
            <div className="login-subtitle">Complaint Investigation Workspace</div>
          </div>

          <form onSubmit={handleSubmit} id="login-form">
            <div className="form-group" style={{ marginBottom: '1rem' }}>
              <label className="form-label" htmlFor="email-input">Work Email</label>
              <input
                id="email-input"
                className="form-input"
                type="email"
                placeholder="name@example.com"
                value={email}
                onChange={e => setEmail(e.target.value)}
                autoComplete="username"
                required
              />
            </div>

            <div className="form-group" style={{ marginBottom: '1.25rem' }}>
              <label className="form-label" htmlFor="password-input">Password</label>
              <input
                id="password-input"
                className="form-input"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>

            {error && (
              <div className="alert alert-error" style={{ marginBottom: '1rem' }} id="login-error" role="alert">
                <span>⛔</span>
                <span>{error}</span>
              </div>
            )}

            <button
              id="login-btn"
              className="btn btn-primary w-full"
              type="submit"
              disabled={loading || !email || !password}
              style={{ padding: '0.65rem 1rem', fontSize: '0.9rem' }}
            >
              {loading ? <><span className="spinner" /> Signing in…</> : 'Sign In'}
            </button>
          </form>

          <div className="divider" style={{ margin: '1.5rem 0' }} />

          <div>
            <div className="text-xs text-muted" style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '0.5rem' }}>
              Select demo credentials
            </div>
            <div className="cred-list">
              {DEMO_CREDENTIALS.map(c => (
                <button
                  key={c.email}
                  className="cred-item"
                  type="button"
                  onClick={() => fillCred(c)}
                  id={`demo-${c.role}-${c.name.split(' ')[0].toLowerCase()}`}
                  aria-label={`Sign in as ${c.name} (${c.role})`}
                >
                  <span className="cred-name">{c.name}</span>
                  <span className="cred-role">{c.role}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
