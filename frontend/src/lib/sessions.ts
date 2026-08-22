import { apiClient, type Conversation, type Source } from "@/lib/api-client";

/**
 * Session adapter for the chat sidebar.
 *
 * - Wraps existing conversation APIs (no new backend contracts).
 * - Provides safe fallbacks so callers never throw if a feature is missing.
 * - Used by the session list for rename / delete / rerun actions.
 */

export type Session = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
};

export type SessionActionResult =
  | { success: true; sources?: Source[] }
  | { success: false; message?: string }
  | { success: false; reason: "unavailable"; message?: string };

type ConversationClient = typeof apiClient & {
  updateConversation?: (id: string, title: string) => Promise<{ error?: { message: string } }>;
  deleteConversation?: (id: string) => Promise<{ error?: { message: string } }>;
};

function mapConversationToSession(conversation: Conversation): Session {
  return {
    id: conversation.id,
    title: conversation.title ?? "New Conversation",
    createdAt: conversation.created_at,
    updatedAt: conversation.updated_at,
  };
}

export async function listSessions(): Promise<Session[]> {
  const { data, error } = await apiClient.getConversations();

  if (error || !data) {
    return [];
  }

  // Sort by updatedAt desc to keep most recent at the top.
  const sessions = data.map(mapConversationToSession);
  return sessions.sort((a, b) => (a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0));
}

export async function renameSession(id: string, title: string): Promise<SessionActionResult> {
  try {
    const client: ConversationClient = apiClient as ConversationClient;

    if (typeof client.updateConversation !== "function") {
      console.info("[sessions] renameSession: updateConversation API not available");
      return { success: false, reason: "unavailable", message: "Rename is not available in this build." };
    }

    const { error } = await client.updateConversation(id, title);

    if (error) {
      return { success: false, message: error.message };
    }

    return { success: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to rename session.";
    return { success: false, message };
  }
}

export async function deleteSession(id: string): Promise<SessionActionResult> {
  try {
    const client: ConversationClient = apiClient as ConversationClient;

    if (typeof client.deleteConversation !== "function") {
      console.info("[sessions] deleteSession: deleteConversation API not available");
      return { success: false, reason: "unavailable", message: "Delete is not available in this build." };
    }

    const { error } = await client.deleteConversation(id);

    if (error) {
      return { success: false, message: error.message };
    }

    return { success: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to delete session.";
    return { success: false, message };
  }
}

export async function rerunSession(conversationId: string): Promise<SessionActionResult> {
  try {
    // Use the backend rerun endpoint which re-executes the last user message
    const result = await apiClient.rerunSession(conversationId, conversationId);

    if (result.error) {
      return {
        success: false,
        message: result.error.message || "Failed to rerun session."
      };
    }

    if (result.data) {
      // Return success with sources from the rerun response
      return {
        success: true,
        sources: result.data.sources || []
      };
    }

    return { success: true };
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to rerun session.";
    return { success: false, message };
  }
}

