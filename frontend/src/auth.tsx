// Who is signed in. The token is kept in localStorage so a refresh keeps the session; see the README for why an
// httpOnly cookie would be the stronger choice in production.

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, handleUnauthorized, setToken, type Session } from "./api";

interface AuthState {
  session: Session | null;
  loading: boolean;
  signIn: (s: Session) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(() => Boolean(getToken()));

  const signOut = useCallback(() => {
    setToken(null);
    setSession(null);
  }, []);

  const signIn = useCallback((s: Session) => {
    setToken(s.token);
    setSession(s);
  }, []);

  useEffect(() => {
    handleUnauthorized(signOut);
    if (!getToken()) return;
    api
      .me()
      .then(setSession)
      .catch(signOut)
      .finally(() => setLoading(false));
  }, [signOut]);

  const value = useMemo(() => ({ session, loading, signIn, signOut }), [session, loading, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
