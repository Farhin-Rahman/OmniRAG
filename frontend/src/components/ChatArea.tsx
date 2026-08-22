import React, { useEffect, useState, useRef } from "react";
import type { KeyboardEvent } from "react";
import { RotateCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { apiClient, type Message, type Citation, type Source, onSessionExpired } from "@/lib/api-client";
import { useToast } from "@/hooks/use-toast";
import MessageBubble from "./MessageBubble";
import { rerunSession } from "@/lib/sessions";

interface ChatAreaProps {
  conversationId: string | null;
  onCreateConversation: (initialMessage: string) => Promise<string | null>;
}

// Type for the chat completion result data
type ChatResult = {
  session_id: string;
  conversation_id: string;
  message: { role: string; content: string; id?: string };
  citations?: Citation[];
  sources?: Source[];
};

// Type for chat error
type ChatError = {
  message: string;
  status?: number;
};

const ChatArea = ({ conversationId, onCreateConversation }: ChatAreaProps) => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [hasAuthError, setHasAuthError] = useState(false);
  const [isRerunning, setIsRerunning] = useState(false);
  const { toast } = useToast();
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const scrollAreaRef = useRef<React.ElementRef<typeof ScrollArea>>(null);
  const thinkingMessageIdRef = useRef<string | null>(null);
  const shouldAutoScrollRef = useRef(true);
  const previousMessageCountRef = useRef(0);
  const isUserScrollingRef = useRef(false);

  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const consecutiveErrorsRef = useRef(0);
  // Store citations and sources by message ID to preserve them when reloading
  const citationsMapRef = useRef<Map<string, { citations?: Citation[]; sources?: Source[] }>>(new Map());
  const motto = import.meta.env.VITE_APP_MOTTO || "Talk To Your Doc";
  const hasConversation = Boolean(conversationId);

  // Define loadMessages BEFORE useEffect that uses it (function declaration to avoid TDZ)
  async function loadMessages(activeConversationId: string): Promise<boolean> {
    // Skip if we have auth error
    if (hasAuthError) return false;

    const { data, error } = await apiClient.getMessages(activeConversationId);

    if (error) {
      // Track consecutive errors
      consecutiveErrorsRef.current++;

      // Handle auth errors specially
      if (error.status === 401) {
        console.warn('Auth error loading messages, stopping polling');
        setHasAuthError(true);
        // Stop polling on auth error
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
        return false;
      }

      // Only show toast for first few errors to avoid spam
      if (consecutiveErrorsRef.current <= 2) {
        toast({
          title: "Error loading messages",
          description: error.message,
          variant: "destructive",
        });
      }

      // Stop polling after too many consecutive errors
      if (consecutiveErrorsRef.current >= 5) {
        console.warn('Too many consecutive errors, stopping polling');
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
      }
      return false;
    }

    // Reset error counter on success
    consecutiveErrorsRef.current = 0;

    // Only update if messages actually changed (avoid unnecessary re-renders)
    setMessages((prev) => {
      const newMessages = data || [];

      // Create a map of existing messages to preserve their sources/citations
      const existingMessagesMap = new Map(prev.map(msg => [msg.id, msg]));

      // Merge citations and sources: prioritize stored map, then existing message, then new message
      const messagesWithCitations = newMessages.map((msg) => {
        const stored = citationsMapRef.current.get(msg.id);
        const existing = existingMessagesMap.get(msg.id);

        // Priority: stored map > existing message with sources > new message
        if (stored && (stored.citations || stored.sources)) {
          return {
            ...msg,
            citations: stored.citations,
            sources: stored.sources,
          };
        }

        // Preserve sources/citations from existing message if they exist
        if (existing && (existing.citations || existing.sources)) {
          // Also update the map to persist them
          citationsMapRef.current.set(msg.id, {
            citations: existing.citations,
            sources: existing.sources,
          });
          return {
            ...msg,
            citations: existing.citations,
            sources: existing.sources,
          };
        }

        return msg;
      });

      // If a thinking message is present, keep it appended so polling doesn't hide it
      if (thinkingMessageIdRef.current) {
        const existingThinking = prev.find((m) => m.id === thinkingMessageIdRef.current);
        if (existingThinking) {
          messagesWithCitations.push(existingThinking);
        }
      }

      // Compare by IDs to detect actual changes
      if (prev.length !== messagesWithCitations.length) {
        return messagesWithCitations;
      }
      const hasChanges = prev.some((msg, idx) => msg.id !== messagesWithCitations[idx]?.id || msg.content !== messagesWithCitations[idx]?.content);
      return hasChanges ? messagesWithCitations : prev;
    });

    return true;
  }

  // Define subscribeToMessages BEFORE useEffect that uses it (function declaration to avoid TDZ)
  function subscribeToMessages(activeConversationId: string) {
    // Clear any existing polling interval
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
    }

    // Reset error counter when starting new subscription
    consecutiveErrorsRef.current = 0;

    // Poll for new messages every 2 seconds (replace with WebSocket in production)
    pollingIntervalRef.current = setInterval(async () => {
      // Skip if auth error
      if (hasAuthError) {
        if (pollingIntervalRef.current) {
          clearInterval(pollingIntervalRef.current);
          pollingIntervalRef.current = null;
        }
        return;
      }
      await loadMessages(activeConversationId);
    }, 2000);

    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
    };
  }

  // Handle session expiry - redirect to login (after helpers defined)
  useEffect(() => {
    const unsubscribe = onSessionExpired(() => {
      setHasAuthError(true);
      // Stop polling
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current);
        pollingIntervalRef.current = null;
      }
      toast({
        title: "Session expired",
        description: "Please sign in again to continue.",
        variant: "destructive",
      });
      // Delay redirect slightly to show toast
      setTimeout(() => navigate('/auth'), 1500);
    });

    return unsubscribe;
  }, [navigate, toast]);

  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      previousMessageCountRef.current = 0;
      shouldAutoScrollRef.current = true;
      // Only clear citations when explicitly starting fresh (no conversation)
      citationsMapRef.current.clear();
      return;
    }

    // Skip if auth error
    if (hasAuthError) return;

    // Reset scroll state when switching conversations
    previousMessageCountRef.current = 0;
    shouldAutoScrollRef.current = true;
    isUserScrollingRef.current = false;
    consecutiveErrorsRef.current = 0;
    // Don't clear citations map when switching - preserve sources for better UX
    // Citations are conversation-specific and will be reloaded with messages

    loadMessages(conversationId);
    const unsubscribe = subscribeToMessages(conversationId);

    return () => {
      unsubscribe?.();
    };
    // We intentionally omit loadMessages/subscribeToMessages from deps because
    // they are stable function declarations; only auth/conversation changes matter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId, hasAuthError]);

  // Check if user is near the bottom of the scroll area
  const isNearBottom = (): boolean => {
    if (!scrollAreaRef.current) return true;

    // Find the viewport element inside the ScrollArea
    const viewport = scrollAreaRef.current.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement;
    if (!viewport) return true;

    const threshold = 150; // pixels from bottom
    const distanceFromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    return distanceFromBottom < threshold;
  };

  const scrollToBottom = () => {
    if (scrollRef.current) {
      scrollRef.current.scrollIntoView({ behavior: "smooth" });
    }
  };

  // Only auto-scroll if user is near bottom and new messages were actually added
  useEffect(() => {
    const currentMessageCount = messages.length;
    const previousMessageCount = previousMessageCountRef.current;
    const hasNewMessages = currentMessageCount > previousMessageCount;

    // Update the ref for next comparison
    previousMessageCountRef.current = currentMessageCount;

    // Only auto-scroll if:
    // 1. User is near bottom (or it's the first load)
    // 2. New messages were actually added (not just polling refresh)
    // 3. User is not actively scrolling
    if (shouldAutoScrollRef.current && (hasNewMessages || previousMessageCount === 0) && !isUserScrollingRef.current) {
      // Small delay to ensure DOM is updated
      setTimeout(() => {
        if (shouldAutoScrollRef.current && !isUserScrollingRef.current) {
          scrollToBottom();
        }
      }, 50);
    }
  }, [messages]);

  // Track scroll position to determine if user has scrolled up
  useEffect(() => {
    if (!hasConversation) return;

    const scrollElement = scrollAreaRef.current?.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement;
    if (!scrollElement) return;

    const handleScroll = () => {
      isUserScrollingRef.current = true;
      shouldAutoScrollRef.current = isNearBottom();

      // Clear existing timeout
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }

      // Reset scrolling flag after user stops scrolling
      scrollTimeoutRef.current = setTimeout(() => {
        isUserScrollingRef.current = false;
        // Re-check if we're near bottom after scrolling stops
        shouldAutoScrollRef.current = isNearBottom();
      }, 200);
    };

    scrollElement.addEventListener('scroll', handleScroll, { passive: true });

    return () => {
      scrollElement.removeEventListener('scroll', handleScroll);
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
    };
  }, [hasConversation]);

  const handleSend = async () => {
    if (!inputValue.trim() || isLoading || hasAuthError) return;

    const userMessage = inputValue.trim();
    setIsLoading(true);
    // Do NOT setIsThinking(false) here - we haven't started thinking yet

    try {
      let activeConversationId = conversationId;

      if (!activeConversationId) {
        const createdId = await onCreateConversation(userMessage);
        if (!createdId) {
          setIsLoading(false);
          return;
        }
        activeConversationId = createdId;
      }

      setInputValue("");

      // Save user message to backend first
      const { error: userError } = await apiClient.createMessage(
        activeConversationId,
        "user",
        userMessage
      );

      if (userError) {
        toast({
          title: "Error sending message",
          description: userError.message,
          variant: "destructive",
        });
        setIsLoading(false);
        return;
      }

      // Reload messages to show the saved user message
      await loadMessages(activeConversationId);

      // Force scroll to bottom when user sends a message
      shouldAutoScrollRef.current = true;
      setTimeout(() => scrollToBottom(), 100);

      // Show thinking indicator with animated dots - stays visible during entire request
      setIsThinking(true);
      const thinkingId = `thinking-${Date.now()}`;
      thinkingMessageIdRef.current = thinkingId;

      // Add thinking message to UI - this will show animated dots
      setMessages((prev) => [
        ...prev,
        {
          id: thinkingId,
          conversation_id: activeConversationId,
          role: "assistant" as const,
          content: "Thinking...",
          created_at: new Date().toISOString(),
        },
      ]);

      // Get AI response from backend - thinking indicator stays visible until this completes
      let chatData: ChatResult | null = null;
      let chatError: ChatError | null = null;

      const result = await apiClient.chatCompletion(
        activeConversationId,
        userMessage,
        undefined,
        (chunk: string) => {
          // Update thinking message with streaming content as it arrives
          if (chunk && chunk.trim()) {
            setMessages((prev) =>
              prev.map((msg) =>
                msg.id === thinkingId
                  ? { ...msg, content: chunk }
                  : msg
              )
            );
          }
        }
      );

      chatData = result.data ?? null;
      chatError = result.error ?? null;

      // Handle error case - clear thinking state and remove thinking bubble
      if (chatError || !chatData) {
        setIsThinking(false);
        thinkingMessageIdRef.current = null;
        setMessages((prev) => prev.filter((msg) => msg.id !== thinkingId));

        let errorMessage = chatError?.message || "Failed to get AI response";
        if (errorMessage.includes("402")) {
          errorMessage = "OpenRouter API quota exceeded. Please check your account balance or contact your administrator.";
        }

        toast({
          title: "Error getting response",
          description: errorMessage,
          variant: "destructive",
        });
        // setIsLoading will be handled in finally block
        return;
      }

      // Success - clear thinking state and remove thinking bubble
      setIsThinking(false);
      thinkingMessageIdRef.current = null;
      setMessages((prev) => prev.filter((msg) => msg.id !== thinkingId));

      // Backend already saves the assistant message, so just reload to get it with citations
      await loadMessages(activeConversationId);

      // Attach citations to the last assistant message
      if (chatData.citations || chatData.sources) {
        const assistantMessageId = chatData.message?.id;

        setMessages((prev) => {
          // Find the last assistant message and attach citations
          const messagesWithCitations = prev.map((msg, index) => {
            // Attach citations to the last assistant message (match by ID if available, otherwise by index)
            const isTargetMessage = assistantMessageId ? msg.id === assistantMessageId : (index === prev.length - 1 && msg.role === 'assistant');

            if (isTargetMessage) {
              // Store in map for persistence
              citationsMapRef.current.set(msg.id, {
                citations: chatData!.citations,
                sources: chatData!.sources,
              });
              return {
                ...msg,
                citations: chatData!.citations,
                sources: chatData!.sources,
              };
            }
            return msg;
          });
          return messagesWithCitations;
        });
      }
    } finally {
      // Only clear isLoading here; isThinking is cleared explicitly in success/error branches
      setIsLoading(false);
    }
  };

  const handleRerun = async () => {
    if (!conversationId || isLoading || isRerunning || hasAuthError) return;

    setIsRerunning(true);
    try {
      const result = await rerunSession(conversationId);
      if (result.success) {
        toast({
          title: "Rerun completed",
          description: "The last message has been regenerated.",
        });
        // Reload messages to show the new response
        await loadMessages(conversationId);

        // Attach sources from rerun response to the last assistant message
        if ('sources' in result && result.sources && result.sources.length > 0) {
          setMessages((prev) => {
            const lastIndex = prev.length - 1;
            if (lastIndex >= 0 && prev[lastIndex].role === 'assistant') {
              const updated = [...prev];
              updated[lastIndex] = {
                ...updated[lastIndex],
                sources: result.sources,
              };
              // Store in citations map for persistence
              citationsMapRef.current.set(updated[lastIndex].id, {
                sources: result.sources,
              });
              return updated;
            }
            return prev;
          });
        }
      } else {
        toast({
          title: "Rerun failed",
          description: 'message' in result ? result.message : "Failed to rerun.",
          variant: "destructive",
        });
      }
    } catch (err) {
      toast({
        title: "Rerun error",
        description: err instanceof Error ? err.message : "Unknown error",
        variant: "destructive",
      });
    } finally {
      setIsRerunning(false);
    }
  };


  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-background overflow-hidden h-full">
      <ScrollArea ref={scrollAreaRef} className="flex-1 min-h-0">
        <div className="max-w-3xl mx-auto px-6 py-8 space-y-6 min-h-full flex flex-col">
          {!hasConversation && (
            <div className="flex-1 flex items-center justify-center">
              <div className="space-y-3 text-center">
                <h2 className="text-xs uppercase tracking-[0.5em] text-muted-foreground">Initiate</h2>
                <h1 className="text-5xl font-semibold text-foreground">
                  OmniRAG
                </h1>
                <p className="text-sm text-muted-foreground">{motto}</p>
                <p className="text-xs text-muted-foreground">
                  Type anything in the starting text box to open a new chat session.
                </p>
              </div>
            </div>
          )}

          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              isThinking={message.id === thinkingMessageIdRef.current}
            />
          ))}
          {isThinking && !thinkingMessageIdRef.current && (
            <MessageBubble
              message={{
                id: "thinking-temp",
                role: "assistant",
                content: "Thinking...",
                created_at: new Date().toISOString(),
              }}
              isThinking={true}
            />
          )}
          <div ref={scrollRef} />
        </div>
      </ScrollArea>

      <div className="border-t bg-chat-input px-6 py-4">
        <div className="max-w-3xl mx-auto">
          <div className="relative">
            <Textarea
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={hasAuthError ? "Session expired. Please sign in again..." : "Message OmniRAG..."}
              className="min-h-[60px] max-h-[200px] pr-24 resize-none rounded-3xl text-base text-foreground placeholder:text-muted-foreground"
              disabled={isLoading || isRerunning || hasAuthError}
            />

            <div className="absolute bottom-2 right-2 flex gap-1">
              {/* Rerun button - only visible when there's a conversation with messages */}
              {conversationId && messages.length > 0 && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 rounded-full border border-border"
                  onClick={handleRerun}
                  disabled={isLoading || isRerunning || hasAuthError}
                  aria-label="Regenerate last response"
                  title="Regenerate last response"
                >
                  <RotateCcw className={`h-4 w-4 ${isRerunning ? 'animate-spin' : ''}`} />
                </Button>
              )}
              <Button
                onClick={handleSend}
                disabled={!inputValue.trim() || isLoading || isRerunning || hasAuthError}
                size="icon"
                className="h-9 w-9 rounded-full bg-primary hover:bg-primary/90 transition-all"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="h-4 w-4"
                >
                  <path d="M7 11l5-5 5 5M7 18l5-5 5 5" />
                </svg>
              </Button>
            </div>
          </div>

          <p className="text-center text-xs text-muted-foreground mt-3">
            {hasConversation ? motto : "Type anything in the starting text box; this counts as a new chat session."}
          </p>
        </div>
      </div>
    </div>
  );
};

export default ChatArea;
