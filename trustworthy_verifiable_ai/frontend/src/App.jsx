import { AuthProvider, useAuth } from './context/AuthContext';
import Navbar from './components/Navbar';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';

function AppRoutes() {
  const { token } = useAuth();
  if (!token) return <LoginPage />;

  return (
    <div className="app-shell">
      <Navbar />
      <main className="main-content">
        <DashboardPage />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
