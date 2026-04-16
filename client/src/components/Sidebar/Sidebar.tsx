import React from 'react';
import { NavLink, Link } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import logoSrc from '../../assets/logo.png';
import './Sidebar.css';

interface SidebarProps {
  isCollapsed: boolean;
  onToggle: () => void;
}

const Sidebar: React.FC<SidebarProps> = ({ isCollapsed, onToggle }) => {
  const { isAuthenticated, logout } = useAuth();

  const handleLogout = async (): Promise<void> => {
    try {
      await logout();
    } catch (err) {
      console.error('Logout failed:', err);
    }
  };

  return (
    <aside className={`sidebar ${isCollapsed ? 'sidebar--collapsed' : ''}`}>
      <div className="sidebar__header">
        <div className="sidebar__brand-container">
          <Link to="/" className="sidebar__brand group">
            <div className="sidebar__logo-wrapper">
              <img src={logoSrc} alt="EasyOps Logo" className="sidebar__logo-img" />
            </div>
            {!isCollapsed && <span className="sidebar__brand-name">EasyOps</span>}
          </Link>
          <button 
            className="sidebar__collapse-toggle" 
            onClick={onToggle}
            aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <span className="material-symbols-outlined">
              {isCollapsed ? 'last_page' : 'first_page'}
            </span>
          </button>
        </div>

        <nav className="sidebar__nav">
          <NavLink
            to="/init"
            className={({ isActive }) => `sidebar__nav-link ${isActive ? 'sidebar__nav-link--active' : ''}`}
            title="Init Repo"
          >
            <span className="material-symbols-outlined">add_box</span>
            {!isCollapsed && <span>Init Repo</span>}
          </NavLink>
          <NavLink
            to="/monitor"
            className={({ isActive }) => `sidebar__nav-link ${isActive ? 'sidebar__nav-link--active' : ''}`}
            title="Dashboard"
          >
            <span className="material-symbols-outlined">dashboard</span>
            {!isCollapsed && <span>Dashboard</span>}
          </NavLink>
          <NavLink
            to="/oauth"
            className={({ isActive }) => `sidebar__nav-link ${isActive ? 'sidebar__nav-link--active' : ''}`}
            title="Integrations"
          >
            <span className="material-symbols-outlined">send</span>
            {!isCollapsed && <span>Integrations</span>}
          </NavLink>
        </nav>
      </div>

      {isAuthenticated && (
        <div className="sidebar__footer">
          <button onClick={handleLogout} className="sidebar__logout" type="button" title="Logout">
            <span className="material-symbols-outlined">logout</span>
            {!isCollapsed && <span>Logout</span>}
          </button>
        </div>
      )}
    </aside>
  );
};

export default Sidebar;
