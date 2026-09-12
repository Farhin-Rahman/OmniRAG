import type { ReactElement } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuthClaims } from "@/auth/AuthProvider";
import Auth from "./pages/Auth";
import Chat from "./pages/Chat";
import DocumentIngestion from "./pages/DocumentIngestion";
import AutomationPipeline from "./pages/AutomationPipeline";
import VoiceAgent from "./pages/VoiceAgent";
import Moderation from "./pages/Moderation";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient();

// Guards /moderation: a non-admin (or a still-loading claims check) never
// gets to mount the moderation page at all, rather than mounting it and
// finding out via a failed fetch.
const AdminRoute = ({ children }: { children: ReactElement }) => {
  const { loading, isAdmin } = useAuthClaims();
  if (loading) return null;
  if (!isAdmin) return <Navigate to="/chat" replace />;
  return children;
};

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<Navigate to="/auth" replace />} />
            <Route path="/auth" element={<Auth />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/documents" element={<DocumentIngestion />} />
            <Route path="/automation" element={<AutomationPipeline />} />
            <Route path="/voice" element={<VoiceAgent />} />
            <Route path="/moderation" element={<AdminRoute><Moderation /></AdminRoute>} />
            {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
