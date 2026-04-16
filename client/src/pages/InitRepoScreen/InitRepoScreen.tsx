import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import Topbar from '../../components/Topbar/Topbar';
import { useAuth } from '../../context/AuthContext';
import { initializeRepo, type UserRepo } from '../../api/api';
import './InitRepoScreen.css';

export default function InitRepoScreen() {
  const navigate = useNavigate();
  const { repos } = useAuth();

  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRepo, setSelectedRepo] = useState<UserRepo | null>(null);
  const [isInitializing, setIsInitializing] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filteredRepos = useMemo(() => {
    if (!repos?.length) return [];
    if (!searchQuery) return repos.slice(0, 8);
    return repos
      .filter((r: UserRepo) => r.full_name.toLowerCase().includes(searchQuery.toLowerCase()))
      .slice(0, 20);
  }, [repos, searchQuery]);

  const handleSelect = (repo: UserRepo) => {
    setSelectedRepo(repo);
    setSearchQuery(repo.full_name);
    setIsFocused(false);
  };

  const handleInitialize = async () => {
    if (!selectedRepo) {
      setError(searchQuery ? 'Please pick a repository from the suggestions.' : 'Please search for and select a repository first.');
      return;
    }
    setIsInitializing(true);
    setError(null);
    try {
      await initializeRepo(selectedRepo.full_name);
      navigate('/monitor');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to initialize repository');
      setIsInitializing(false);
    }
  };

  return (
    <div className="init-page">
      <main className="init-page__main">
        <Topbar title="Repository Initialization" breadcrumb="Dashboard" />

        <div className="init-content init-content--centered">
          <div className="init-search-block">
            <h2 className="init-search-block__title">
              Connect a <span className="init-title__highlight">Repository</span>
            </h2>
            <p className="init-search-block__subtitle">
              The agent will build a structural map of your codebase and enable autonomous CI/CD recovery hooks.
            </p>

            {error && (
              <div className="init-error-banner">
                <span className="material-symbols-outlined" style={{ fontSize: '18px' }}>error</span>
                <span>{error}</span>
              </div>
            )}

            <div
              className="init-search"
              onBlur={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                  setTimeout(() => setIsFocused(false), 150);
                }
              }}
            >
              <span className="material-symbols-outlined init-search__icon">search</span>
              <input
                type="text"
                className="init-search__input"
                placeholder="Search repositories (e.g. facebook/react)..."
                value={searchQuery}
                onFocus={() => setIsFocused(true)}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  setSelectedRepo(null);
                  setError(null);
                  setIsFocused(true);
                }}
                autoComplete="off"
              />
              {selectedRepo && (
                <span className="material-symbols-outlined init-search__check">check_circle</span>
              )}

              {isFocused && filteredRepos.length > 0 && (
                <ul className="init-search__results">
                  {filteredRepos.map((repo: UserRepo) => (
                    <li
                      key={repo.id ?? repo.full_name}
                      className={`init-search__result-item ${
                        selectedRepo?.full_name === repo.full_name ? 'init-search__result-item--selected' : ''
                      }`}
                      onMouseDown={() => handleSelect(repo)}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: '14px', opacity: 0.6 }}>
                        {repo.private ? 'lock' : 'public'}
                      </span>
                      {repo.full_name}
                    </li>
                  ))}
                </ul>
              )}
              {isFocused && filteredRepos.length === 0 && searchQuery && (
                <ul className="init-search__results">
                  <li className="init-search__result-item" style={{ opacity: 0.6, cursor: 'default' }}>
                    No repositories found matching "{searchQuery}"
                  </li>
                </ul>
              )}
            </div>

            <button
              onClick={handleInitialize}
              disabled={isInitializing}
              className="init-btn-primary group"
              type="button"
            >
              <span className="init-btn-primary__content">
                <span className={`material-symbols-outlined init-btn-primary__icon ${isInitializing ? 'animate-spin' : ''}`}>
                  {isInitializing ? 'progress_activity' : 'rocket_launch'}
                </span>
                {isInitializing ? 'PROCESSING ENGINE...' : 'INITIALIZE REPOSITORY'}
              </span>
              {!isInitializing && (
                <span className="material-symbols-outlined group-hover:translate-x-1 transition-transform">chevron_right</span>
              )}
            </button>
          </div>

          <div className="init-hero">
            <div className="init-icon-container">
              <div className="init-icon-ring" />
              <div className="init-icon-solid" />
              <div className="init-icon-inner">
                <span className="material-symbols-outlined init-icon">folder_managed</span>
              </div>
            </div>
            <div className="init-status">
              <span className="init-status__badge">System Standing By</span>
              <p className="init-status__text">Choose a repository above to initiate architectural indexing.</p>
            </div>
          </div>
        </div>

      </main>
    </div>
  );
}
