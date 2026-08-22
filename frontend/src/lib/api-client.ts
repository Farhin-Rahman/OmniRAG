import { config } from '@/config';
import { v4 as uuidv4 } from 'uuid';

const API_BASE_URL = config.apiBaseUrl;

export interface ApiResponse<T = unknown> {
  data?: T;
  error?: {
    message: string;
    status: number;
  };
}

export interface User {
  id: string;
  email: string;
  full_name?: string;
  avatar_url?: string;
  tenant_id?: string;
  created_at: string;
}

export interface Session {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  user: User;
}

export interface SessionStatus {
  user: User;
}

export interface Conversation {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Citation {
  text: string;
  source_ids: string[];
  evidence_id?: string;
  chunk_id?: string;
  page?: number;
  doc_id?: string;
  span?: [number, number];
}

export interface Source {
  chunk_id: string;
  doc_id: string;
  doc_name?: string;
  mime?: string;
  text: string;
  page: number;
  score: number;
  personalization_score: number;
  metadata: any;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
  citations?: Citation[];
  sources?: Source[];
}

type SessionExpiredCallback = () => void;
const sessionExpiredCallbacks: SessionExpiredCallback[] = [];

export function onSessionExpired(callback: SessionExpiredCallback): () => void {
  sessionExpiredCallbacks.push(callback);
  return () => {
    const index = sessionExpiredCallbacks.indexOf(callback);
    if (index > -1) sessionExpiredCallbacks.splice(index, 1);
  };
}

const MOCK_USER: User = {
  id: "00000000-0000-0000-0000-000000000000",
  email: "admin@omnirag.ai",
  full_name: "OmniRAG Admin",
  tenant_id: "default",
  created_at: new Date().toISOString()
};

class ApiClient {
  private token: string | null = null;

  constructor() {
    this.token = localStorage.getItem('access_token');
  }

  // --- Document File Helpers (Real Backend) ---
  async uploadFile(file: File): Promise<ApiResponse<any>> {
    try {
      const formData = new FormData();
      formData.append("file", file);

      const response = await fetch(`${API_BASE_URL}/webhooks/upload-file`, {
        method: "POST",
        body: formData,
        // Don't set Content-Type header here; let the browser boundary magic handle it for FormData
      });

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }
      const data = await response.json();
      return { data };
    } catch (error) {
      console.error("Upload error:", error);
      return { error: { message: error instanceof Error ? error.message : "Network error", status: 0 } };
    }
  }

  getDocumentFileUrl(docId: string, view: "inline" | "download" = "inline"): string {
    const params = new URLSearchParams();
    if (view === "download") params.append("view", "download");
    return `${API_BASE_URL}/documents/${docId}/file${params.toString() ? `?${params.toString()}` : ""}`;
  }

  async getDocumentFile(docId: string, view: "inline" | "download" = "inline"): Promise<ApiResponse<Blob>> {
    try {
      const response = await fetch(this.getDocumentFileUrl(docId, view));
      if (!response.ok) throw new Error("Failed to fetch file");
      const blob = await response.blob();
      return { data: blob };
    } catch (error) {
      return { error: { message: error instanceof Error ? error.message : "Network error", status: 0 } };
    }
  }

  // --- Document Sync ---
  async getDocumentStatus(folderPath?: string, minDate?: string): Promise<ApiResponse<{ is_syncing: boolean; files: any[] }>> {
    try {
      const response = await fetch(`${API_BASE_URL}/documents`);
      if (!response.ok) throw new Error("Failed to fetch documents");
      const data = await response.json();
      
      const mappedFiles = (data.documents || []).map((doc: any) => ({
        item_id: doc.doc_id,
        fileName: doc.doc_name,
        filestatus: doc.status,
        filepath: "/Local Uploads"
      }));

      return { 
        data: { 
          is_syncing: false, 
          files: mappedFiles 
        } 
      };
    } catch (error) {
      return { error: { message: error instanceof Error ? error.message : "Network error", status: 0 } };
    }
  }

  async triggerDocumentSync(): Promise<ApiResponse<{ is_syncing: boolean; files: any[] }>> {
    return { data: { is_syncing: true, files: [] } };
  }

  async syncSingleFile(itemId: string): Promise<ApiResponse<void>> {
    return { data: undefined };
  }

  async syncBatch(itemIds: string[]): Promise<ApiResponse<{ status: string; message: string }>> {
    return { data: { status: "success", message: "Batch sync triggered" } };
  }

  // --- Authentication (Mocked) ---
  isAuthenticated(): boolean {
    return !!localStorage.getItem('access_token');
  }

  async signUp(email: string, password: string, fullName?: string): Promise<ApiResponse<Session>> {
    return this.signIn(email, password);
  }

  async signIn(email: string, password: string): Promise<ApiResponse<Session>> {
    const session: Session = {
      access_token: "mock-jwt-token",
      refresh_token: "mock-refresh-token",
      expires_at: Date.now() + 3600000,
      user: MOCK_USER
    };
    this.token = session.access_token;
    localStorage.setItem('access_token', session.access_token);
    localStorage.setItem('user', JSON.stringify(session.user));
    return { data: session };
  }

  async signOut(): Promise<ApiResponse<void>> {
    this.clearSession();
    return { data: undefined };
  }

  async getSession(): Promise<ApiResponse<SessionStatus>> {
    if (this.isAuthenticated()) {
      return { data: { user: MOCK_USER } };
    }
    return { error: { message: 'No session', status: 401 } };
  }

  async refreshSession(): Promise<ApiResponse<Session>> {
    return this.signIn("admin@omnirag.ai", "password");
  }

  clearSession() {
    this.token = null;
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
  }

  getUser(): User | null {
    return MOCK_USER;
  }

  // --- Conversations (Mocked in LocalStorage) ---
  private getLocalConversations(): Conversation[] {
    const data = localStorage.getItem('mock_conversations');
    return data ? JSON.parse(data) : [];
  }

  private saveLocalConversations(convos: Conversation[]) {
    localStorage.setItem('mock_conversations', JSON.stringify(convos));
  }

  private getLocalMessages(): Message[] {
    const data = localStorage.getItem('mock_messages');
    return data ? JSON.parse(data) : [];
  }

  private saveLocalMessages(msgs: Message[]) {
    localStorage.setItem('mock_messages', JSON.stringify(msgs));
  }

  async getConversations(): Promise<ApiResponse<Conversation[]>> {
    const convos = this.getLocalConversations().sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());
    return { data: convos };
  }

  async getConversation(id: string): Promise<ApiResponse<Conversation>> {
    const convo = this.getLocalConversations().find(c => c.id === id);
    if (convo) return { data: convo };
    return { error: { message: "Not found", status: 404 } };
  }

  async createConversation(title?: string): Promise<ApiResponse<Conversation>> {
    const convo: Conversation = {
      id: uuidv4(),
      user_id: MOCK_USER.id,
      title: title || 'New Conversation',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
    const convos = this.getLocalConversations();
    convos.push(convo);
    this.saveLocalConversations(convos);
    return { data: convo };
  }

  async updateConversation(id: string, title: string): Promise<ApiResponse<Conversation>> {
    const convos = this.getLocalConversations();
    const idx = convos.findIndex(c => c.id === id);
    if (idx > -1) {
      convos[idx].title = title;
      convos[idx].updated_at = new Date().toISOString();
      this.saveLocalConversations(convos);
      return { data: convos[idx] };
    }
    return { error: { message: "Not found", status: 404 } };
  }

  async deleteConversation(id: string): Promise<ApiResponse<void>> {
    const convos = this.getLocalConversations().filter(c => c.id !== id);
    this.saveLocalConversations(convos);
    const msgs = this.getLocalMessages().filter(m => m.conversation_id !== id);
    this.saveLocalMessages(msgs);
    return { data: undefined };
  }

  // --- Messages (Mocked in LocalStorage) ---
  async getMessages(conversationId: string): Promise<ApiResponse<Message[]>> {
    const msgs = this.getLocalMessages().filter(m => m.conversation_id === conversationId);
    return { data: msgs.sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) };
  }

  async createMessage(conversationId: string, role: 'user' | 'assistant', content: string): Promise<ApiResponse<Message>> {
    const msg: Message = {
      id: uuidv4(),
      conversation_id: conversationId,
      role,
      content,
      created_at: new Date().toISOString()
    };
    const msgs = this.getLocalMessages();
    msgs.push(msg);
    this.saveLocalMessages(msgs);
    return { data: msg };
  }

  async rerunSession(sessionId: string, conversationId?: string): Promise<ApiResponse<any>> {
    return { data: { session_id: sessionId, conversation_id: conversationId || uuidv4(), new_run_id: uuidv4(), message: "Rerun triggered" } };
  }

  // --- Chat Completion (REAL Backend Call) ---
  async chatCompletion(
    conversationId: string,
    message: string,
    sessionId?: string,
    onChunk?: (chunk: string) => void
  ): Promise<ApiResponse<{
    session_id: string;
    conversation_id: string;
    message: { role: string; content: string };
    citations?: Citation[];
    sources?: Source[];
  }>> {
    
    try {
      // 2. Call real backend
      const response = await fetch(`${API_BASE_URL}/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId || MOCK_USER.id,
          conversation_id: conversationId,
          message: message,
          user_preferences: { user_id: MOCK_USER.id }
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }

      const responseData = await response.json();
      const data = responseData?.data || responseData;
      const content = data?.message?.content || data?.response || 'No response from backend';
      
      // 3. Save assistant message locally
      const assistantMsg = await this.createMessage(conversationId, 'assistant', content);
      
      // Update message with sources if available
      if (data?.sources) {
        const msgs = this.getLocalMessages();
        const idx = msgs.findIndex(m => m.id === assistantMsg.data!.id);
        if (idx > -1) {
          msgs[idx].sources = data.sources;
          this.saveLocalMessages(msgs);
        }
      }

      // Update conversation timestamp
      this.updateConversation(conversationId, this.getLocalConversations().find(c => c.id === conversationId)?.title || 'Chat');

      return {
        data: {
          session_id: sessionId || MOCK_USER.id,
          conversation_id: conversationId,
          message: { role: 'assistant', content },
          citations: data?.citations,
          sources: data?.sources
        }
      };
    } catch (error) {
      console.error('Chat error:', error);
      return { error: { message: error instanceof Error ? error.message : "Network error", status: 0 } };
    }
  }
}

export const apiClient = new ApiClient();
