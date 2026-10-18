import { createContext, useContext, useState, useCallback } from 'react';
import { login as apiLogin, getMe } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => sessionStorage.getItem('tw_token'));
  const [user, setUser]   = useState(() => {
    const raw = sessionStorage.getItem('tw_user');
    try { return raw ? JSON.parse(raw) : null; } catch { return null; }
  });
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const login = useCallback(async (email, password) => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiLogin(email, password);
      const me   = await getMe(data.access_token);
      sessionStorage.setItem('tw_token', data.access_token);
      sessionStorage.setItem('tw_user', JSON.stringify(me));
      setToken(data.access_token);
      setUser(me);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    sessionStorage.removeItem('tw_token');
    sessionStorage.removeItem('tw_user');
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ token, user, login, logout, error, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
