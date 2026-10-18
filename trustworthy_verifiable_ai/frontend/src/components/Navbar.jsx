import { useAuth } from '../context/AuthContext';

export default function Navbar() {
  const { user, logout } = useAuth();

  return (
    <nav className="navbar" id="main-navbar" aria-label="Main Navigation">
      <div className="navbar-brand">
        <div className="navbar-logo" aria-hidden="true">T</div>
        <div>
          <div className="navbar-title">TrustWorthy AI</div>
          <div className="navbar-meta">Complaint Investigation</div>
        </div>
      </div>

      <div className="navbar-actions">
        {user && (
          <div className="navbar-user">
            <span style={{ color: '#cbd5e1', fontSize: '0.85rem', fontWeight: 500 }}>
              {user.name}
            </span>
            <span className="user-badge" id="user-role-badge">
              {user.role}
            </span>
            <button
              id="logout-btn"
              className="btn btn-sm"
              style={{
                backgroundColor: 'transparent',
                borderColor: '#334155',
                color: '#e2e8f0',
                marginLeft: '0.5rem',
              }}
              onClick={logout}
              type="button"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
