import React from 'react';
import { NavLink, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import './Sidebar.css';

const Sidebar: React.FC = () => {
  const { isAuthenticated, logout } = useAuth();

  const handleLogout = async (): Promise<void> => {
    try {
      await logout();
    } catch (err) {
      console.error('Logout failed:', err);
    }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar__header">
        <Link to="/" className="sidebar__brand group">
          <div className="sidebar__logo-container">
            <span className="material-symbols-outlined sidebar__logo-icon text-surface-bright">terminal</span>
          </div>
          <div>
            <h1 className="sidebar__title">AI Technical Suite</h1>
            <p className="sidebar__version">v1.0.4</p>
          </div>
        </Link>

        <nav className="sidebar__nav">
          <NavLink
            to="/init"
            className={({ isActive }) => `sidebar__nav-link ${isActive ? 'sidebar__nav-link--active' : ''}`}
          >
            <span className="material-symbols-outlined">add_box</span>
            <span>Init Repo</span>
          </NavLink>
          <NavLink
            to="/monitor"
            className={({ isActive }) => `sidebar__nav-link ${isActive ? 'sidebar__nav-link--active' : ''}`}
          >
            <span className="material-symbols-outlined">dashboard</span>
            <span>Dashboard</span>
          </NavLink>
          <NavLink
            to="/oauth"
            className={({ isActive }) => `sidebar__nav-link ${isActive ? 'sidebar__nav-link--active' : ''}`}
          >
            <span className="material-symbols-outlined">send</span>
            <span>Integrations</span>
          </NavLink>
        </nav>
      </div>

      {isAuthenticated && (
        <div className="sidebar__footer">
          <button onClick={handleLogout} className="sidebar__logout" type="button">
            <span className="material-symbols-outlined">logout</span>
            <span>Logout</span>
          </button>
        </div>
      )}
    </aside>
  );
};

export default Sidebar;
