import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { onAuthStateChanged, type AuthCredential } from "firebase/auth";
import { FirebaseError } from "firebase/app";
import {
  auth,
  loginWithGoogle,
  completeGoogleRedirect,
  signUpWithEmail,
  signInWithEmail,
  resendVerificationEmail,
  getPendingGoogleCredential,
  linkCredentialToCurrentUser,
  buildPasswordCredential,
} from "@/auth/firebase";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";

// Survives the full-page redirect to Google and back: set right before
// sending a user to link an existing Google account with a password,
// so the returning page knows to offer "set a password" instead of
// dropping straight into /chat.
const LINK_INTENT_KEY = "omnirag_link_intent_email";

const Auth = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [loading, setLoading] = useState(false);
  const [googleLoading, setGoogleLoading] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [needsVerification, setNeedsVerification] = useState(false);
  const [linkNotice, setLinkNotice] = useState<string | null>(null);
  const [pendingGoogleCredential, setPendingGoogleCredential] = useState<AuthCredential | null>(null);
  const [showSetPassword, setShowSetPassword] = useState(false);
  // Set only when a Sign Up just hit "email already in use" — read at the
  // moment "Continue with Google" is actually clicked (not before), so an
  // abandoned Sign Up attempt can't leave a stale link-intent flag behind
  // to misfire on some later, unrelated Google sign-in for the same email.
  const [blockedSignupEmail, setBlockedSignupEmail] = useState<string | null>(null);

  useEffect(() => {
    // Real Firebase auth state. Google accounts arrive pre-verified;
    // email/password accounts only pass once their link's been clicked.
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      if (user && user.emailVerified) {
        // Came back from Google specifically to link a password onto this
        // account (see handleEmailSignUp) — offer that instead of
        // navigating straight past it.
        const intentEmail = sessionStorage.getItem(LINK_INTENT_KEY);
        if (intentEmail && user.email === intentEmail) {
          sessionStorage.removeItem(LINK_INTENT_KEY);
          setShowSetPassword(true);
          return;
        }
        navigate("/chat");
      } else if (user && !user.emailVerified) {
        setNeedsVerification(true);
      }
    });
    return unsubscribe;
  }, [navigate]);

  useEffect(() => {
    // Surfaces a redirect-sign-in failure. A successful redirect (incl.
    // the password-linking return trip) is instead picked up by
    // onAuthStateChanged above; this only fires on the way back from
    // Google, and does nothing on a normal page load.
    completeGoogleRedirect().catch((error) => {
      if (error instanceof FirebaseError && error.code === "auth/account-exists-with-different-credential") {
        // This email already has a password account. Hang onto the Google
        // credential the user was trying to use and offer to link it once
        // they prove ownership via the password sign-in form below.
        setPendingGoogleCredential(getPendingGoogleCredential(error));
        const existingEmail = (error.customData?.email as string | undefined) ?? "";
        if (existingEmail) setEmail(existingEmail);
        setLinkNotice("This email already has a password account here. Sign in with your password below to link Google to it.");
        return;
      }
      toast({
        title: "Google sign-in failed",
        description: error instanceof Error ? error.message : "Something went wrong",
        variant: "destructive",
      });
    });
  }, [toast]);

  const handleGoogleSignIn = async () => {
    setGoogleLoading(true);
    try {
      // Only carry a link-intent flag through the redirect if this click
      // is actually resolving a just-seen "email already in use" — never
      // leave a stale one from an earlier, abandoned attempt.
      if (blockedSignupEmail && blockedSignupEmail === email) {
        sessionStorage.setItem(LINK_INTENT_KEY, blockedSignupEmail);
      } else {
        sessionStorage.removeItem(LINK_INTENT_KEY);
      }
      // signInWithRedirect navigates this whole tab to Google — there is
      // no "after" on success to run here. The onAuthStateChanged listener
      // above picks up the signed-in user and navigates once Google sends
      // the browser back. Calling navigate()/resetting loading state here
      // raced against that real navigation and caused the stuck/glitchy
      // behaviour.
      await loginWithGoogle();
    } catch (error) {
      toast({
        title: "Google sign-in failed",
        description: error instanceof Error ? error.message : "Something went wrong",
        variant: "destructive",
      });
      setGoogleLoading(false);
    }
  };

  const handleEmailSignUp = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      toast({
        title: "Passwords don't match",
        description: "Make sure both password fields are the same.",
        variant: "destructive",
      });
      return;
    }
    setLoading(true);
    try {
      await signUpWithEmail(email, password);
      setNeedsVerification(true);
      setPassword("");
      setConfirmPassword("");
      toast({
        title: "Check your inbox",
        description: `We sent a verification link to ${email}. Click it, then sign in.`,
      });
    } catch (error) {
      if (error instanceof FirebaseError && error.code === "auth/email-already-in-use") {
        // An account already exists under this email, but this project has
        // email enumeration protection on, so fetchSignInMethodsForEmail
        // can't tell us which provider it uses — it always comes back
        // empty. Point at "Continue with Google" either way: if the
        // existing account is password-based, that Google attempt fails
        // with account-exists-with-different-credential (handled below,
        // prompts for the password instead); if it's Google-based, it
        // just signs in and we offer to set a password afterward.
        setBlockedSignupEmail(email);
        setLinkNotice("An account with this email already exists. Click \"Continue with Google\" below to link it.");
      } else {
        toast({
          title: "Sign up failed",
          description: error instanceof Error ? error.message : "Something went wrong",
          variant: "destructive",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleEmailSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const user = await signInWithEmail(email, password);
      sessionStorage.removeItem(LINK_INTENT_KEY);
      if (pendingGoogleCredential) {
        // Proved ownership of the password account — now attach the
        // Google credential the user originally tried to sign in with.
        await linkCredentialToCurrentUser(user, pendingGoogleCredential);
        setPendingGoogleCredential(null);
        setLinkNotice(null);
        toast({
          title: "Google account linked",
          description: "You can now sign in with either Google or your password.",
        });
      }
      navigate("/chat");
    } catch (error) {
      if (error instanceof Error && error.message === "EMAIL_NOT_VERIFIED") {
        setNeedsVerification(true);
      } else {
        toast({
          title: "Sign in failed",
          description: error instanceof Error ? error.message : "Something went wrong",
          variant: "destructive",
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleSetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirmPassword) {
      toast({
        title: "Passwords don't match",
        description: "Make sure both password fields are the same.",
        variant: "destructive",
      });
      return;
    }
    if (!auth.currentUser?.email) return;
    setLoading(true);
    try {
      const credential = buildPasswordCredential(auth.currentUser.email, password);
      await linkCredentialToCurrentUser(auth.currentUser, credential);
      toast({
        title: "Password set",
        description: "You can now sign in with either Google or your password.",
      });
      setShowSetPassword(false);
      setPassword("");
      setConfirmPassword("");
      navigate("/chat");
    } catch (error) {
      toast({
        title: "Couldn't set password",
        description: error instanceof Error ? error.message : "Something went wrong",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    if (!auth.currentUser) return;
    try {
      await resendVerificationEmail(auth.currentUser);
      toast({ title: "Verification email resent" });
    } catch (error) {
      toast({
        title: "Couldn't resend",
        description: error instanceof Error ? error.message : "Something went wrong",
        variant: "destructive",
      });
    }
  };

  const motto = import.meta.env.VITE_APP_MOTTO || "Talk To Your Doc";

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-secondary/20 to-background p-4">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center space-y-2">
          <div className="flex justify-center mb-4">
            <h1 className="text-5xl font-bold tracking-tight" style={{
              color: '#000000',
              fontFamily: 'serif',
              textShadow: '0 2px 4px rgba(0,0,0,0.1)'
            }}>
              OmniRAG
            </h1>
          </div>
          <p className="text-muted-foreground">{motto}</p>
        </div>

        {showSetPassword ? (
          <Card>
            <CardHeader>
              <CardTitle>Set a password</CardTitle>
              <CardDescription>
                Add a password to {auth.currentUser?.email}, so you can sign in with either Google or a password.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSetPassword} className="space-y-4">
                <div className="space-y-2">
                  <Label htmlFor="link-password">Password</Label>
                  <Input
                    id="link-password"
                    type="password"
                    placeholder="At least 6 characters"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    minLength={6}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="link-confirm-password">Confirm Password</Label>
                  <Input
                    id="link-confirm-password"
                    type="password"
                    placeholder="Re-enter your password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    minLength={6}
                    required
                  />
                </div>
                <Button type="submit" className="w-full" disabled={loading}>
                  {loading ? "Saving..." : "Set password"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className="w-full"
                  onClick={() => {
                    setShowSetPassword(false);
                    navigate("/chat");
                  }}
                >
                  Skip for now
                </Button>
              </form>
            </CardContent>
          </Card>
        ) : needsVerification ? (
          <Card>
            <CardHeader>
              <CardTitle>Verify your email</CardTitle>
              <CardDescription>
                Click the link we sent to {auth.currentUser?.email || "your inbox"} to finish signing in.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <Button onClick={handleResend} variant="outline" className="w-full">
                Resend verification email
              </Button>
              <Button
                onClick={() => setNeedsVerification(false)}
                variant="ghost"
                className="w-full"
              >
                Back
              </Button>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Welcome</CardTitle>
              <CardDescription>Sign in to your account or create a new one</CardDescription>
            </CardHeader>
            <CardContent>
              {linkNotice && (
                <p className="text-sm text-muted-foreground bg-secondary/40 rounded-md p-3 mb-4">
                  {linkNotice}
                </p>
              )}
              <Button
                type="button"
                variant="outline"
                className="w-full mb-4"
                onClick={handleGoogleSignIn}
                disabled={googleLoading}
              >
                {googleLoading ? "Signing in..." : "Continue with Google"}
              </Button>

              <div className="relative mb-4">
                <div className="absolute inset-0 flex items-center">
                  <span className="w-full border-t" />
                </div>
                <div className="relative flex justify-center text-xs uppercase">
                  <span className="bg-card px-2 text-muted-foreground">Or</span>
                </div>
              </div>

              <Tabs defaultValue="signin" className="w-full">
                <TabsList className="grid w-full grid-cols-2">
                  <TabsTrigger value="signin">Sign In</TabsTrigger>
                  <TabsTrigger value="signup">Sign Up</TabsTrigger>
                </TabsList>

                <TabsContent value="signin">
                  <form onSubmit={handleEmailSignIn} className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="signin-email">Email</Label>
                      <Input
                        id="signin-email"
                        type="email"
                        placeholder="you@example.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="signin-password">Password</Label>
                      <Input
                        id="signin-password"
                        type="password"
                        placeholder="••••••••"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                      />
                    </div>
                    <Button type="submit" className="w-full" disabled={loading}>
                      {loading ? "Signing in..." : "Sign In"}
                    </Button>
                  </form>
                </TabsContent>

                <TabsContent value="signup">
                  <form onSubmit={handleEmailSignUp} className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="signup-email">Email</Label>
                      <Input
                        id="signup-email"
                        type="email"
                        placeholder="you@example.com"
                        value={email}
                        onChange={(e) => setEmail(e.target.value)}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="signup-password">Password</Label>
                      <Input
                        id="signup-password"
                        type="password"
                        placeholder="At least 6 characters"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        minLength={6}
                        required
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="signup-confirm-password">Confirm Password</Label>
                      <Input
                        id="signup-confirm-password"
                        type="password"
                        placeholder="Re-enter your password"
                        value={confirmPassword}
                        onChange={(e) => setConfirmPassword(e.target.value)}
                        minLength={6}
                        required
                      />
                    </div>
                    <Button type="submit" className="w-full" disabled={loading}>
                      {loading ? "Creating account..." : "Sign Up"}
                    </Button>
                  </form>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
};

export default Auth;
