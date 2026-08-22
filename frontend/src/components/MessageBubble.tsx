import { useState } from "react";
import { User, Bot, ChevronDown, ChevronUp, FileText, Download, ExternalLink } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, Source } from "@/lib/api-client";
import { apiClient } from "@/lib/api-client";
import DocumentViewer from "@/components/DocumentViewer";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations?: Citation[];
  sources?: Source[];
}

interface MessageBubbleProps {
  message: Message;
  isThinking?: boolean;
}

const MessageBubble = ({ message, isThinking = false }: MessageBubbleProps) => {
  const isUser = message.role === "user";
  const [showSources, setShowSources] = useState(
    () => !!(message.sources?.length || message.citations?.length)
  );
  const [viewingDoc, setViewingDoc] = useState<{
    docId: string;
    docName: string;
    mimeType?: string;
  } | null>(null);

  const hasSources = message.sources && message.sources.length > 0;
  const hasCitations = message.citations && message.citations.length > 0;
  const hasAnySources = hasSources || hasCitations;
  const sourceCount = message.sources?.length || message.citations?.length || 0;

  // Truncate source text for preview
  const truncateText = (text: string, maxLength: number = 150) => {
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength).trim() + "...";
  };

  // Format score as percentage
  const formatScore = (score: number) => {
    return `${Math.round(score * 100)}%`;
  };

  // Download source document
  const handleDownloadSource = async (docId: string, docName: string) => {
    try {
      console.log(`Downloading document ${docId} (${docName})`);
      const response = await apiClient.getDocumentFile(docId, "download");

      if (response.error) {
        console.error("Download failed:", response.error);
        alert(`Failed to download: ${response.error.message || "Unknown error"}`);
        return;
      }

      if (response.data) {
        const url = window.URL.createObjectURL(response.data);
        const a = document.createElement('a');
        a.href = url;
        a.download = docName || "document";
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        // Clean up after a short delay
        setTimeout(() => {
          window.URL.revokeObjectURL(url);
          document.body.removeChild(a);
        }, 100);
      } else {
        console.error("Download response has no data");
        alert("Failed to download: No file data received");
      }
    } catch (err) {
      console.error("Download exception:", err);
      alert(`Failed to download file: ${err instanceof Error ? err.message : "Unknown error"}`);
    }
  };

  // Get document name from source
  const getDocName = (source: Source) =>
    source.metadata?.doc_name || source.doc_name || "Document";

  return (
    <div
      className={cn(
        "flex gap-3 animate-in fade-in-0 slide-in-from-bottom-2",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      {!isUser && (
        <div className="flex items-start">
          <div className="p-2 rounded-full border border-border bg-card">
            <Bot className="h-4 w-4" />
          </div>
        </div>
      )}

      <div className="flex flex-col max-w-[80%] gap-2">
        <div
          className={cn(
            "rounded-2xl px-4 py-3 border",
            isUser
              ? "bg-primary text-primary-foreground border-transparent shadow-sm"
              : "bg-chat-assistant text-foreground border-border",
            isThinking && "animate-pulse"
          )}
        >
          {isThinking ? (
            <div className="flex items-center gap-3 text-sm">
              <div className="flex gap-1.5 items-center py-1">
                <div className="w-2 h-2 bg-foreground/60 rounded-full animate-bounce" style={{ animationDelay: '0ms', animationDuration: '1.4s' }}></div>
                <div className="w-2 h-2 bg-foreground/60 rounded-full animate-bounce" style={{ animationDelay: '200ms', animationDuration: '1.4s' }}></div>
                <div className="w-2 h-2 bg-foreground/60 rounded-full animate-bounce" style={{ animationDelay: '400ms', animationDuration: '1.4s' }}></div>
              </div>
              <span className="text-muted-foreground italic">{message.content || "Thinking..."}</span>
            </div>
          ) : (
            <div className={cn(
              "text-sm prose prose-sm max-w-none dark:prose-invert prose-headings:font-semibold prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-strong:font-semibold",
              isUser && "prose-invert prose-headings:text-primary-foreground prose-p:text-primary-foreground prose-ul:text-primary-foreground prose-ol:text-primary-foreground prose-li:text-primary-foreground prose-strong:text-primary-foreground prose-code:text-primary-foreground prose-pre:text-primary-foreground prose-a:text-primary-foreground"
            )}>
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* Sources section - only for assistant messages with sources or citations */}
        {!isUser && hasAnySources && !isThinking && (
          <div className="ml-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowSources(!showSources)}
              className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground gap-1"
              aria-expanded={showSources}
              aria-label={showSources ? "Hide sources" : "Show sources"}
            >
              <FileText className="h-3 w-3" />
              {sourceCount} {sourceCount === 1 ? "source" : "sources"}
              {showSources ? (
                <ChevronUp className="h-3 w-3" />
              ) : (
                <ChevronDown className="h-3 w-3" />
              )}
            </Button>

            {showSources && (
              <div className="mt-2 space-y-2 animate-in fade-in-0 slide-in-from-top-2">
                {/* Show sources if available */}
                {message.sources?.map((source, index) => {
                  const docName = getDocName(source);
                  const mimeType = source.metadata?.mime || source.mime;

                  return (
                    <div
                      key={source.chunk_id}
                      className="rounded-lg border border-border bg-muted/30 p-3 text-xs"
                    >
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2 flex-1 min-w-0">
                          <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-primary/10 text-primary text-[10px] font-medium shrink-0">
                            {index + 1}
                          </span>
                          <button
                            type="button"
                            onClick={() => setViewingDoc({
                              docId: source.doc_id,
                              docName,
                              mimeType,
                            })}
                            className="text-blue-600 hover:underline truncate text-left"
                            title={docName}
                          >
                            {docName}
                          </button>
                          <span className="text-muted-foreground shrink-0">
                            Page {source.page}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <button
                            type="button"
                            onClick={() => setViewingDoc({
                              docId: source.doc_id,
                              docName,
                              mimeType,
                            })}
                            className="p-1 hover:bg-muted rounded"
                            title="View document"
                          >
                            <ExternalLink className="h-3 w-3 text-muted-foreground" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownloadSource(source.doc_id, docName)}
                            className="p-1 hover:bg-muted rounded"
                            title="Download document"
                          >
                            <Download className="h-3 w-3 text-muted-foreground" />
                          </button>
                          <span className="text-muted-foreground text-[10px] ml-1">
                            {formatScore(source.score)}
                          </span>
                        </div>
                      </div>
                      <p className="text-foreground/80 leading-relaxed">
                        {truncateText(source.text)}
                      </p>
                    </div>
                  );
                })}
                {/* Show citations if available (and no sources) */}
                {!hasSources && message.citations?.map((citation, index) => (
                  <div
                    key={citation.evidence_id || citation.chunk_id || index}
                    className="rounded-lg border border-border bg-muted/30 p-3 text-xs"
                  >
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center justify-center h-5 w-5 rounded-full bg-primary/10 text-primary text-[10px] font-medium">
                          {index + 1}
                        </span>
                        <span className="text-muted-foreground">
                          Page {citation.page || 1}
                        </span>
                      </div>
                    </div>
                    <p className="text-foreground/80 leading-relaxed">
                      Citation {citation.evidence_id || `#${index + 1}`}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {isUser && (
        <div className="flex items-start">
          <div className="p-2 rounded-full bg-primary border border-transparent">
            <User className="h-4 w-4 text-primary-foreground" />
          </div>
        </div>
      )}

      {viewingDoc && (
        <DocumentViewer
          docId={viewingDoc.docId}
          docName={viewingDoc.docName}
          mimeType={viewingDoc.mimeType}
          onClose={() => setViewingDoc(null)}
        />
      )}
    </div>
  );
};

export default MessageBubble;
