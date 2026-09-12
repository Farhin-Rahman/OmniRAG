// Sidebar session list enhancements:
// - Uses sessions adapter to list, rename, delete, and (safely) rerun sessions.
// - Adds kebab menu with inline rename & delete confirmation, with keyboard support.
// - Keeps existing routing/auth intact; no new backend APIs are introduced.
// - Upload behavior is managed in ChatArea; this component only manages sessions.

import { useEffect, useState, useCallback, useRef } from "react";
import type { MouseEvent, KeyboardEvent } from "react";
import { MessageSquarePlus, Trash2, MoreVertical, LogOut, Check, X, RefreshCw, Plus, MessageSquare, ChevronLeft, ChevronRight, Folder, Webhook, Phone, ShieldCheck } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiClient, type Conversation, type User, onSessionExpired } from "@/lib/api-client";
import { useAuthClaims } from "@/auth/AuthProvider";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import { listSessions, renameSession, deleteSession, rerunSession } from "@/lib/sessions";
import { VersionStamp } from "@/components/VersionStamp";

interface ChatSidebarProps {
  currentConversationId: string | null;
  onSelectConversation: (id: string | null) => void;
  onNewConversation: (initialMessage?: string) => Promise<string | null>;
  user: User | null;
  onSignOut: () => void;
  lastCreatedId: string | null; // New prop for sync
}

const ChatSidebar = ({
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  user,
  onSignOut,
  lastCreatedId,
}: ChatSidebarProps) => {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState<string>("");
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [hasAuthError, setHasAuthError] = useState(false);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const consecutiveErrorsRef = useRef(0);
  const { toast } = useToast();
  const navigate = useNavigate();
  const { isAdmin } = useAuthClaims();

  // Handle session expiry
  useEffect(() => {
    const unsubscribe = onSessionExpired(() => {
      setHasAuthError(true);
      // Stop polling
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    });

    return unsubscribe;
  }, []);

  const loadConversations = useCallback(async (): Promise<boolean> => {
    if (!user || hasAuthError) {
      setConversations([]);
      return false;
    }

    // Use sessions adapter for sorting; fall back to raw API if needed.
    const sessions = await listSessions();

    if (sessions.length > 0) {
      consecutiveErrorsRef.current = 0;
      setConversations(
        sessions.map((s) => ({
          id: s.id,
          user_id: user?.id || '',
          title: s.title,
          created_at: s.createdAt,
          updated_at: s.updatedAt,
        })),
      );
      return true;
    } else {
      const { data, error } = await apiClient.getConversations();

      if (error) {
        consecutiveErrorsRef.current++;

        // Handle auth errors
        if (error.status === 401) {
          setHasAuthError(true);
          if (pollingIntervalRef.current) {
            clearInterval(pollingIntervalRef.current);
            pollingIntervalRef.current = null;
          }
          return false;
        }

        // Only show toast for first few errors
        if (consecutiveErrorsRef.current <= 2) {
          toast({
            title: "Error loading conversations",
            description: error.message,
            variant: "destructive",
          });
        }

        // Stop polling after too many errors
        if (consecutiveErrorsRef.current >= 5 && pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
        return false;
      }

      consecutiveErrorsRef.current = 0;
      setConversations(data || []);
      return true;
    }
  }, [user, hasAuthError, toast]);

  useEffect(() => {
    if (!hasAuthError) {
      loadConversations();
    }
  }, [loadConversations, hasAuthError]);

  // Watch for new conversation creation to immediately refresh sidebar
  useEffect(() => {
    if (lastCreatedId) {
      loadConversations();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastCreatedId]);

  useEffect(() => {
    if (!user || hasAuthError) return;

    // Clear any existing interval
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }

    // Reset error counter
    consecutiveErrorsRef.current = 0;

    // Poll for new conversations every 5 seconds (replace with WebSocket in production)
    pollingIntervalRef.current = setInterval(() => {
      if (!hasAuthError) {
        loadConversations();
      }
    }, 5000);

    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }, [user, hasAuthError, loadConversations]);


  const openRename = (conversation: Conversation) => {
    setEditingId(conversation.id);
    setEditingTitle(conversation.title || "New Conversation");
    // Focus will be handled via autoFocus; ref is kept for potential future focus management.
  };

  const cancelRename = () => {
    setEditingId(null);
    setEditingTitle("");
  };

  const submitRename = async () => {
    if (!editingId) return;
    const trimmed = editingTitle.trim();
    if (!trimmed) {
      cancelRename();
      return;
    }

    const result = await renameSession(editingId, trimmed);

    if (!result.success) {
      // Cast to failure type to access properties safely
      const failure = result as { success: false; message?: string; reason?: string };
      const isUnavailable = failure.reason === "unavailable";
      const message = isUnavailable ? "Rename is not available in this build." : failure.message;
      if (message) {
        toast({
          title: "Error renaming session",
          description: message,
          variant: "destructive",
        });
      }
      cancelRename();
      return;
    }

    setConversations((prev) =>
      prev.map((c) => (c.id === editingId ? { ...c, title: trimmed, updated_at: new Date().toISOString() } : c)),
    );

    toast({ title: "Renamed." });
    cancelRename();
    await loadConversations();
  };

  const handleRenameKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void submitRename();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelRename();
    } else if (event.key === "Tab") {
      // Keep focus inside the row while editing.
      event.preventDefault();
    }
  };

  const confirmDelete = (id: string, e?: MouseEvent<HTMLButtonElement>) => {
    e?.stopPropagation();
    setPendingDeleteId(id);
  };

  const handleDeleteConfirmed = async () => {
    if (!pendingDeleteId) return;

    const result = await deleteSession(pendingDeleteId);
    if (!result.success) {
      const failure = result as { success: false; message?: string; reason?: string };
      const isUnavailable = failure.reason === "unavailable";
      const message = isUnavailable ? "Delete is not available in this build." : failure.message;
      if (message) {
        toast({
          title: "Error deleting session",
          description: message,
          variant: "destructive",
        });
      }
      setPendingDeleteId(null);
      return;
    }

    const updatedConversations = conversations.filter((c) => c.id !== pendingDeleteId);
    setConversations(updatedConversations);

    let shouldReload = true;
    if (currentConversationId === pendingDeleteId) {
      if (updatedConversations.length > 0) {
        onSelectConversation(updatedConversations[0].id);
      } else {
        const newId = await onNewConversation();
        if (newId) {
          await loadConversations();
          onSelectConversation(newId);
          shouldReload = false;
        } else {
          onSelectConversation(null);
        }
      }
    }

    if (shouldReload) {
      await loadConversations();
    }

    toast({ title: "Deleted." });
    setPendingDeleteId(null);
  };

  const handleRerun = async (id: string) => {
    // Confirm rerun action
    const confirmed = window.confirm(
      "This will re-execute all queries in this session and regenerate responses. " +
      "This may take a moment. Continue?"
    );

    if (!confirmed) return;

    toast({
      title: "Rerunning session...",
      description: "Re-executing queries. This may take a moment."
    });

    const result = await rerunSession(id);

    if (result.success) {
      toast({
        title: "Rerun completed",
        description: "All queries have been re-executed. Refreshing conversation..."
      });

      // If this is the current conversation, trigger a reload
      if (id === currentConversationId) {
        // Reload conversations to get updated timestamps
        await loadConversations();
        // The ChatArea component will automatically reload messages via polling
      } else {
        // Just reload the list
        await loadConversations();
      }
      return;
    }

    toast({
      title: "Rerun failed",
      description: (result as { message?: string }).message || "Failed to rerun session.",
      variant: "destructive",
    });
  };

  const handleCreateConversation = () => {
    // Just clear selection to start fresh. The conversation will be created
    // when the user sends the first message, ensuring the title is correct.
    onSelectConversation(null);
  };

  const displayName = user?.full_name?.trim() || user?.email || "Guest";
  const initials = displayName
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((segment) => segment[0]?.toUpperCase())
    .join("") || "M";

  return (
    <div
      className={cn(
        "relative shrink-0 flex flex-col h-full border-r bg-sidebar transition-all duration-300 z-30 ml-0",
        isCollapsed ? "w-0 md:w-12" : "w-72",
      )}
      aria-label="Sessions sidebar"
    >
      <Button
        variant="ghost"
        size="icon"
        className="absolute -right-4 top-4 h-8 w-8 rounded-full border bg-background shadow-md z-50 transition-all"
        onClick={() => setIsCollapsed(!isCollapsed)}
        aria-label={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
      >
        {isCollapsed ? (
          <ChevronRight className="h-4 w-4" />
        ) : (
          <ChevronLeft className="h-4 w-4" />
        )}
      </Button>

      <div
        className={cn(
          "flex flex-col h-full overflow-hidden transition-opacity duration-300",
          isCollapsed ? "opacity-0 pointer-events-none" : "opacity-100",
        )}
      >
        <div className="p-4 border-b">
          <Button
            onClick={handleCreateConversation}
            className="w-full gap-2 justify-start"
            variant="default"
          >
            <Plus className="h-4 w-4" />
            New Session
          </Button>
        </div>

        <div className="flex-1 min-h-0 relative">
          <ScrollArea className="h-full">
            <div className="space-y-1 p-3" aria-label="Session list">
              {conversations.length === 0 ? (
                <div className="text-xs text-muted-foreground space-y-2 py-4 text-left">
                  <p>No sessions yet.</p>
                  <Button size="sm" variant="outline" className="text-xs" onClick={handleCreateConversation}>
                    + Start a new session
                  </Button>
                </div>
              ) : (
                conversations.map((conversation) => {
                  const isActive = currentConversationId === conversation.id;
                  const isEditing = editingId === conversation.id;
                  const updatedLabel = conversation.updated_at
                    ? new Date(conversation.updated_at).toLocaleString()
                    : "";

                  const handleRowKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
                    // Don't handle keyboard shortcuts if we're in edit mode
                    if (isEditing) return;

                    if (event.key === "F2" || event.key.toLowerCase() === "r") {
                      event.preventDefault();
                      openRename(conversation);
                    } else if (event.key === "Delete") {
                      event.preventDefault();
                      confirmDelete(conversation.id);
                    } else if (event.key === "Enter") {
                      event.preventDefault();
                      onSelectConversation(conversation.id);
                    }
                  };

                  return (
                    <div key={conversation.id} className="group flex items-center gap-2 relative">
                      <div
                        role="button"
                        tabIndex={0}
                        onClick={() => onSelectConversation(conversation.id)}
                        onKeyDown={handleRowKeyDown}
                        className={cn(
                          "flex flex-1 items-center gap-2 rounded-lg border transition-colors focus:outline-none focus:ring-1 focus:ring-sidebar-ring p-3 cursor-pointer min-w-0",
                          isActive ? "bg-sidebar-foreground/5 border-sidebar-border" : "hover:bg-muted",
                        )}
                        aria-label={`Open session ${conversation.title || "Untitled"}`}
                      >
                        <MessageSquare className="h-4 w-4 shrink-0" aria-hidden="true" />
                        <div className="flex flex-col items-start gap-1 min-w-0 flex-1 overflow-hidden">
                          <div className="flex items-center gap-2 min-w-0 w-full">
                            {isEditing ? (
                              <Input
                                ref={renameInputRef}
                                autoFocus
                                value={editingTitle}
                                onClick={(e) => e.stopPropagation()}
                                onChange={(e) => setEditingTitle(e.target.value)}
                                onKeyDown={handleRenameKeyDown}
                                className="h-7 text-xs"
                                aria-label="Rename session"
                              />
                            ) : (
                              <span
                                className="text-sm tracking-wide text-left block min-w-0 w-[18ch] max-w-full truncate"
                                title={conversation.title || "Untitled"}
                              >
                                {(() => {
                                  const t = conversation.title || "Untitled";
                                  const maxLen = 15;
                                  return t.length > maxLen ? `${t.slice(0, maxLen)}...` : t;
                                })()}
                              </span>
                            )}
                          </div>
                          {updatedLabel && !isEditing && (
                            <span className="text-[11px] text-muted-foreground truncate block min-w-0 w-full">
                              {`Updated ${updatedLabel}`}
                            </span>
                          )}
                        </div>
                      </div>
                      {/* Kebab menu - outside the clickable row to ensure it's always visible */}
                      <DropdownMenu modal={true}>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 shrink-0 p-0 hover:bg-muted/50 border-0 shadow-none"
                            aria-label="Session actions"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <MoreVertical className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          align="end"
                          sideOffset={8}
                          className="z-[99999] min-w-[160px]"
                          onCloseAutoFocus={(e) => e.preventDefault()}
                        >
                          <DropdownMenuItem
                            onSelect={(event) => {
                              event.preventDefault();
                              openRename(conversation);
                            }}
                          >
                            Rename
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={(event) => {
                              event.preventDefault();
                              confirmDelete(conversation.id);
                            }}
                            className="text-destructive focus:text-destructive focus:bg-destructive/10"
                          >
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  );
                })
              )}
            </div>
          </ScrollArea>
        </div>

        <div className="border-t px-3 py-4 space-y-2">
          <button
            type="button"
            onClick={() => {
              // Profile click handler - can be extended later
            }}
            className="w-full flex items-center gap-3 rounded-xl border px-3 py-2 transition-colors hover:bg-muted focus:outline-none focus:ring-1 focus:ring-sidebar-ring justify-start"
          >
            <div className="h-10 w-10 rounded-full border flex items-center justify-center text-sm font-medium">
              {initials}
            </div>
            <div className="min-w-0 text-left">
              <p className="text-sm font-medium truncate">{displayName}</p>
              <p className="text-xs text-muted-foreground flex items-center gap-1.5">
                View profile
                {isAdmin && (
                  <span className="shrink-0 rounded-full bg-emerald-600/10 text-emerald-600 text-[10px] font-medium px-2 py-0.5 border border-emerald-600/20">
                    Admin
                  </span>
                )}
              </p>
            </div>
          </button>

          {isAdmin && (
            <Button
              onClick={() => window.location.href = '/moderation'}
              className="w-full bg-emerald-700 hover:bg-emerald-800 text-white shadow-md hover:shadow-lg transition-all transform active:scale-95 rounded-xl h-12 flex items-center justify-center gap-2"
            >
              <ShieldCheck className="w-5 h-5" />
              <span className="font-semibold tracking-wide">Trust & Safety</span>
            </Button>
          )}

          <Button
            onClick={() => window.location.href = '/documents'}
            className="w-full bg-indigo-600 hover:bg-indigo-700 text-white shadow-[0_4px_14px_0_rgba(79,70,229,0.39)] hover:shadow-[0_6px_20px_rgba(79,70,229,0.23)] transition-all transform active:scale-95 rounded-xl h-12 flex items-center justify-center gap-2"
          >
            <Folder className="w-5 h-5" />
            <span className="font-semibold tracking-wide">Document Library</span>
          </Button>

          <Button
            onClick={() => window.location.href = '/automation'}
            className="w-full bg-slate-800 hover:bg-slate-900 text-white shadow-md hover:shadow-lg transition-all transform active:scale-95 rounded-xl h-12 flex items-center justify-center gap-2"
          >
            <Webhook className="w-5 h-5" />
            <span className="font-semibold tracking-wide">Automations</span>
          </Button>

          <Button
            onClick={() => window.location.href = '/voice'}
            className="w-full bg-purple-700 hover:bg-purple-800 text-white shadow-md hover:shadow-lg transition-all transform active:scale-95 rounded-xl h-12 flex items-center justify-center gap-2"
          >
            <Phone className="w-5 h-5" />
            <span className="font-semibold tracking-wide">Voice Agent</span>
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={onSignOut}
            className="w-full gap-2 justify-start text-muted-foreground hover:text-foreground"
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </Button>

          <div className="pt-2 border-t">
            <VersionStamp className="text-[10px] text-muted-foreground/60" />
          </div>
        </div>
      </div>

      <AlertDialog open={Boolean(pendingDeleteId)} onOpenChange={(open) => !open && setPendingDeleteId(null)}>
        <AlertDialogContent role="dialog" aria-labelledby="delete-session-title" className="z-[10000]">
          <AlertDialogHeader>
            <AlertDialogTitle id="delete-session-title">Delete session?</AlertDialogTitle>
            <AlertDialogDescription>
              This removes the session and its chat history. This can&apos;t be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={(event) => {
                event.preventDefault();
                void handleDeleteConfirmed();
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default ChatSidebar;
