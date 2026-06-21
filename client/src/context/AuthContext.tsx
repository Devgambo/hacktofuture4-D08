import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { fetchCurrentUser, logout as apiLogout } from '../api/api';
import type { User, UserRepo } from '../api/api';

// ── Types ──────────────────────────────────────────────────────────────────

interface AuthContextValue {
  user: User | null;
  repos: UserRepo[];
  isLoading: boolean;
  isAuthenticated: boolean;
  refetch: () => Promise<void>;
  logout: () => Promise<void>;
}


// ── Context ────────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue | null>(null);

// ── Provider ───────────────────────────────────────────────────────────────

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [repos, setRepos] = useState<UserRepo[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const refetch = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    try {
      const data = await fetchCurrentUser();
      setUser(data.user);
      setRepos(data.repos || []);
    } catch {
      setUser(null);
      setRepos([]);
    } finally {
      setIsLoading(false);
    }
  }, []);


  const logout = useCallback(async (): Promise<void> => {
    try {
      await apiLogout();
    } catch (err) {
      console.error(err);
      toast.error('Logout request failed — clearing local session anyway.');
    } finally {
      setUser(null);
      setRepos([]);
      window.location.href = '/';
    }
  }, []);

  // Check session on mount
  useEffect(() => {
    void refetch();
  }, [refetch]);

  return (
    <AuthContext.Provider
      value={{
        user,
        repos,
        isLoading,
        isAuthenticated: user !== null,
        refetch,
        logout,

      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

// ── Hook ───────────────────────────────────────────────────────────────────

// eslint-disable-next-line react-refresh/only-export-components
export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>');
  return ctx;
};
