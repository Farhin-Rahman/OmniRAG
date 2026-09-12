import { initializeApp } from "firebase/app";
import {
  getAuth,
  GoogleAuthProvider,
  signInWithRedirect,
  getRedirectResult,
  createUserWithEmailAndPassword,
  signInWithEmailAndPassword,
  sendEmailVerification,
  linkWithCredential,
  EmailAuthProvider,
  type User,
  type AuthCredential,
  type AuthError,
} from "firebase/auth";

const firebaseConfig = {
  apiKey: "AIzaSyB70KbsQXxAF0Sh9ZMWZCWeNy2MbAUKdIA",
  authDomain: "omnirag-2ceb2.firebaseapp.com",
  projectId: "omnirag-2ceb2",
  storageBucket: "omnirag-2ceb2.firebasestorage.app",
  messagingSenderId: "630765691634",
  appId: "1:630765691634:web:052c03f5e4470972a8666b",
  measurementId: "G-XNDYE97EGR"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);

// Initialize and export Auth tools
export const auth = getAuth(app);
export const provider = new GoogleAuthProvider();

/** Redirect-based, not popup-based: signInWithPopup needs a cross-origin
 * cookie channel between the popup and this tab, which modern Chrome
 * blocks by default (third-party cookies) and fails with the sign-in
 * silently "glitching." Redirect navigates the whole tab instead, so it
 * doesn't depend on that channel. The result comes back through the
 * onAuthStateChanged listener in Auth.tsx once Google redirects here. */
export const loginWithGoogle = async () => {
  await signInWithRedirect(auth, provider);
};

/** Completes the redirect flow above. onAuthStateChanged alone picks up a
 * *successful* redirect, but swallows any error the redirect itself
 * failed with (wrong OAuth client config, blocked domain, etc.) — call
 * this once on load so that failure actually surfaces instead of the
 * page just silently sitting there. Resolves to null if the page was
 * loaded normally (not returning from a redirect). */
export const completeGoogleRedirect = async (): Promise<User | null> => {
  const result = await getRedirectResult(auth);
  return result?.user ?? null;
};

/** Create an account and send a verification link — the account exists
 * immediately in Firebase, but signInWithEmail below refuses entry until
 * the link is clicked (user.emailVerified becomes true). */
export const signUpWithEmail = async (email: string, password: string): Promise<User> => {
  const credential = await createUserWithEmailAndPassword(auth, email, password);
  await sendEmailVerification(credential.user);
  return credential.user;
};

/** Sign in with email/password. Throws a clearly-labeled error if the
 * account exists but hasn't clicked its verification link yet, rather
 * than silently letting an unverified account through. */
export const signInWithEmail = async (email: string, password: string): Promise<User> => {
  const credential = await signInWithEmailAndPassword(auth, email, password);
  if (!credential.user.emailVerified) {
    throw new Error("EMAIL_NOT_VERIFIED");
  }
  return credential.user;
};

export const resendVerificationEmail = async (user: User): Promise<void> => {
  await sendEmailVerification(user);
};

/** Firebase enforces one account per email: signing in with Google when
 * that email already has a password account fails with
 * auth/account-exists-with-different-credential, but attaches the Google
 * credential the user was trying to use to the error. Pull it out so it
 * can be linked to the existing account once the user proves ownership by
 * signing in with their password (see linkCredentialToCurrentUser). */
export const getPendingGoogleCredential = (error: unknown): AuthCredential | null => {
  return GoogleAuthProvider.credentialFromError(error as AuthError);
};

/** Attaches an extra credential (a pending Google credential from above, or
 * a freshly-typed password via buildPasswordCredential) to the currently
 * signed-in user, so one email ends up usable with both providers instead
 * of Firebase creating two separate accounts. */
export const linkCredentialToCurrentUser = async (user: User, credential: AuthCredential): Promise<void> => {
  await linkWithCredential(user, credential);
};

export const buildPasswordCredential = (email: string, password: string): AuthCredential => {
  return EmailAuthProvider.credential(email, password);
};