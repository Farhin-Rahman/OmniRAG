import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { onAuthStateChanged, type User } from "firebase/auth";
import { auth } from "./firebase";

interface AuthClaimsState {
  firebaseUser: User | null;
  isAdmin: boolean;
  loading: boolean;
}

const AuthClaimsContext = createContext<AuthClaimsState>({
  firebaseUser: null,
  isAdmin: false,
  loading: true,
});

/**
 * Single source of truth for "who is signed in" and "are they an admin,"
 * shared app-wide via context instead of every page re-deciding it from a
 * fetch's status code. Custom claims (roles, granted via backend/set_admin.py)
 * live on the ID token, not the User object, so they're read with
 * getIdTokenResult() once per auth-state change and cached here — pages that
 * need isAdmin (route guard, sidebar) read it from context instead of racing
 * their own token fetch against Firebase's session rehydration on load.
 */
export const AuthProvider = ({ children }: { children: ReactNode }) => {
  const [firebaseUser, setFirebaseUser] = useState<User | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, async (user) => {
      if (user) {
        const tokenResult = await user.getIdTokenResult();
        const roles = tokenResult.claims.roles;
        const roleList = Array.isArray(roles) ? roles : typeof roles === "string" ? [roles] : [];
        setIsAdmin(roleList.includes("TrustAndSafetyAdmin"));
      } else {
        setIsAdmin(false);
      }
      setFirebaseUser(user);
      setLoading(false);
    });
    return unsubscribe;
  }, []);

  return (
    <AuthClaimsContext.Provider value={{ firebaseUser, isAdmin, loading }}>
      {children}
    </AuthClaimsContext.Provider>
  );
};

export const useAuthClaims = () => useContext(AuthClaimsContext);
