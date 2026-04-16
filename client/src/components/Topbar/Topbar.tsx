import type { TopbarProps } from '../../types';
import './Topbar.css';

export default function Topbar({ title, breadcrumb }: TopbarProps) {
  return (
    <header className="topbar">
      <div className="topbar__breadcrumb">
        <span className="topbar__breadcrumb-path">{breadcrumb}</span>
        <span className="topbar__breadcrumb-sep">/</span>
        <span className="topbar__breadcrumb-current">{title}</span>
      </div>

      <div className="topbar__actions">
        <button className="topbar__notify-btn" aria-label="Notifications" type="button">
          <span className="material-symbols-outlined topbar__notify-icon">notifications</span>
        </button>

        <div className="topbar__divider" aria-hidden="true" />

        <div className="topbar__profile">
          <div className="topbar__profile-info">
            <div className="topbar__profile-name">Admin User</div>
            <div className="topbar__profile-role">Maintainer</div>
          </div>
          <img
            alt="User Profile"
            className="topbar__profile-img"
            src="https://lh3.googleusercontent.com/aida-public/AB6AXuAs_hjHTg4fd2ru7jeqCNEQl2OfB-wPLlVZIwWStxwPu-OoynKZIRPJoyvQV1ctO16LiFkKWqgr5BaOpWSva_3OSniMYGy_yUVyI4YtP-7EwyuEHAOzlzecxIvixJqPP8Q_ArzJYZ-EKqjsq0odjJQ3tzayOLmGSvxcLKM8CcfxKj2186O5soZ7mf4BTwqo-Z3BNQw2J87jZGW2JCm0dbLi2zejwcwe6lDbBVMKjcKbbi_5K5WMsQKhSliCLMsmEQLwK_NOL3iep28d"
          />
        </div>
      </div>
    </header>
  );
}
