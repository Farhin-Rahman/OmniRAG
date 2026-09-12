import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { onAuthStateChanged, signOut as firebaseSignOut } from "firebase/auth";
import { auth } from "@/auth/firebase";
import { apiClient, type User, onSessionExpired } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";
import ChatSidebar from "@/components/ChatSidebar";
import ChatArea from "@/components/ChatArea";
import ChatDetails from "@/components/ChatDetails";

const Chat = () => {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [lastCreatedId, setLastCreatedId] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Handle session expiry globally
  useEffect(() => {
    const unsubscribe = onSessionExpired(() => {
      setUser(null);
      setIsLoading(false);
      toast({
        title: "Session expired",
        description: "Please sign in again to continue.",
        variant: "destructive",
      });
      navigate("/auth");
    });

    return unsubscribe;
  }, [navigate, toast]);

  // Real session check: this used to read a localStorage access_token that
  // only the old mock auth (api-client.ts's signIn/signUp) ever wrote.
  // Once auth/Auth.tsx switched to Firebase, nothing set that token anymore,
  // so this always found no session and bounced straight back to /auth —
  // even right after a successful Firebase sign-in. Firebase's own auth
  // state (the same source Auth.tsx and Moderation.tsx already use) is
  // the actual source of truth.
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      if (firebaseUser && firebaseUser.emailVerified) {
        setUser({
          id: firebaseUser.uid,
          email: firebaseUser.email || "",
          full_name: firebaseUser.displayName || undefined,
          avatar_url: firebaseUser.photoURL || undefined,
          created_at: firebaseUser.metadata.creationTime || new Date().toISOString(),
        });
        setIsLoading(false);
      } else {
        setUser(null);
        setIsLoading(false);
        navigate("/auth");
      }
    });

    return unsubscribe;
  }, [navigate]);

  const handleSignOut = async () => {
    await firebaseSignOut(auth);
    await apiClient.signOut();
    navigate("/auth");
  };

  const handleNewConversation = async (initialMessage?: string): Promise<string | null> => {
    if (!user) return null;

    const fallbackTitle = `Session ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
    const proposedTitle = initialMessage?.trim().slice(0, 60) || "New Conversation";
    const title = initialMessage ? proposedTitle || fallbackTitle : "New Conversation";

    const { data, error } = await apiClient.createConversation(title);

    if (error) {
      toast({
        title: "Error creating conversation",
        description: error.message,
        variant: "destructive",
      });
      return null;
    }

    if (data) {
      setCurrentConversationId(data.id);
      setLastCreatedId(data.id); // Set last created ID for sidebar sync
      return data.id;
    }

    return null;
  };

  // Show loading state while checking session
  if (isLoading) {
    return (
      <div style={{ 
        display: 'flex', 
        height: '100vh', 
        alignItems: 'center', 
        justifyContent: 'center', 
        backgroundColor: '#f9fafb',
        fontFamily: 'system-ui, -apple-system, sans-serif'
      }}>
        <div style={{ textAlign: 'center' }}>
          <div 
            style={{
              width: '48px',
              height: '48px',
              border: '4px solid #e5e7eb',
              borderTopColor: '#3b82f6',
              borderRadius: '50%',
              animation: 'spin 1s linear infinite',
              margin: '0 auto 16px'
            }}
          />
          <p style={{ color: '#6b7280', fontSize: '14px' }}>Loading session...</p>
          <style>{`
            @keyframes spin {
              to { transform: rotate(360deg); }
            }
          `}</style>
        </div>
      </div>
    );
  }

  // Don't render chat UI if no user (will redirect to auth)
  if (!user) {
    // Small delay to allow navigation to complete
    if (!isLoading) {
      setTimeout(() => navigate("/auth"), 100);
    }
    return (
      <div style={{ 
        display: 'flex', 
        height: '100vh', 
        alignItems: 'center', 
        justifyContent: 'center', 
        backgroundColor: '#f9fafb',
        fontFamily: 'system-ui, -apple-system, sans-serif'
      }}>
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: '#6b7280', fontSize: '14px', marginBottom: '8px' }}>No session found</p>
          <p style={{ color: '#9ca3af', fontSize: '12px' }}>Redirecting to sign in...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-white" style={{ minHeight: '100vh', width: '100%' }}>
      <ChatSidebar
        currentConversationId={currentConversationId}
        onSelectConversation={setCurrentConversationId}
        onNewConversation={handleNewConversation}
        user={user}
        onSignOut={handleSignOut}
        lastCreatedId={lastCreatedId}
      />

      <div className="flex-1 flex flex-col relative z-0" style={{ minWidth: 0 }}>
        <header className="border-b bg-white px-6 py-4 flex items-center justify-center relative z-10" style={{ borderColor: '#e5e7eb' }}>
          <h1 className="text-lg font-semibold text-gray-900">
            OmniRAG
          </h1>
        </header>

        <div className="flex-1 flex overflow-hidden relative z-0" style={{ minHeight: 0 }}>
          <div className="flex-1 relative z-0" style={{ minWidth: 0 }}>
            <ChatArea
              conversationId={currentConversationId}
              onCreateConversation={handleNewConversation}
            />
          </div>
          <ChatDetails conversationId={currentConversationId} />
        </div>
      </div>
    </div>
  );
};

export default Chat;
