import { useEffect, useState } from "react";
import { X, Download, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { apiClient } from "@/lib/api-client";
import { cn } from "@/lib/utils";

interface DocumentViewerProps {
  docId: string;
  docName: string;
  mimeType?: string;
  onClose: () => void;
}

const DocumentViewer = ({ docId, docName, mimeType, onClose }: DocumentViewerProps) => {
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      try {
        setLoading(true);
        setError(null);

        // Always fetch as blob to support auth headers
        // External URLs will be handled by backend or redirect
        const response = await apiClient.getDocumentFile(docId, "inline");

        if (response.error) {
          // Check if error indicates integration not configured
          if (response.error.message?.toLowerCase().includes("integration")) {
            setError(
              "External integration is not yet configured. " +
                "Please configure it in the admin panel to view this document."
            );
          } else {
            throw new Error(response.error.message);
          }
          return;
        }

        if (response.data) {
          // Create a blob URL for the iframe/img src
          const url = window.URL.createObjectURL(response.data);
          setFileUrl(url);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load file");
      } finally {
        setLoading(false);
      }
    };
    load();

    // Cleanup blob URL on unmount
    return () => {
      if (fileUrl && fileUrl.startsWith("blob:")) {
        window.URL.revokeObjectURL(fileUrl);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId]);

  const handleDownload = async () => {
    try {
      const response = await apiClient.getDocumentFile(docId, "download");

      if (response.error) {
        throw new Error(response.error.message);
      }

      if (response.data) {
        // Create a blob URL and trigger download
        const url = window.URL.createObjectURL(response.data);
        const a = document.createElement('a');
        a.href = url;
        a.download = docName || "document"; // Use provided doc name or fallback
        document.body.appendChild(a);
        a.click();

        // Clean up
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      }
    } catch (err) {
      console.error("Download failed:", err);
      alert("Failed to download file. Please try again.");
    }
  };

  const handleOpenInNewTab = () => {
    if (fileUrl) {
      window.open(fileUrl, "_blank");
    }
  };

  const canViewInline =
    (mimeType && mimeType.startsWith("image/")) ||
    mimeType === "application/pdf" ||
    (mimeType && mimeType.startsWith("text/"));

  if (loading) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-background rounded-lg p-6">
          <p>Loading document...</p>
        </div>
      </div>
    );
  }

  if (error && !error.toLowerCase().includes("integration")) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="bg-background rounded-lg p-6 max-w-md">
          <p className="text-destructive mb-4">{error}</p>
          <Button onClick={onClose}>Close</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold truncate max-w-md">{docName}</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="icon" onClick={handleDownload} title="Download">
            <Download className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={handleOpenInNewTab} title="Open in new tab">
            <ExternalLink className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={onClose} title="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className={cn("flex-1 overflow-auto p-4", !canViewInline && "flex items-center justify-center")}>
        {canViewInline && fileUrl ? (
          <div className="flex items-center justify-center h-full w-full">
            {mimeType?.startsWith("image/") ? (
              <img src={fileUrl} alt={docName} className="max-w-full max-h-full object-contain" />
            ) : mimeType === "application/pdf" ? (
              <iframe
                src={fileUrl}
                className="w-full h-full border-0"
                title={docName}
                allow="fullscreen"
              />
            ) : (
              <iframe src={fileUrl} className="w-full h-full border-0" title={docName} />
            )}
          </div>
        ) : error && error.toLowerCase().includes("integration") ? (
          <div className="text-center p-8 bg-amber-50 rounded-lg max-w-md">
            <h3 className="text-amber-800 font-semibold mb-2">Integration Not Configured</h3>
            <p className="text-amber-700 mb-4 text-sm">{error}</p>
            <div className="flex gap-2 justify-center">
              <Button onClick={handleDownload} variant="outline">
                <Download className="h-4 w-4 mr-2" />
                Download file
              </Button>
              <Button onClick={handleOpenInNewTab} variant="outline">
                <ExternalLink className="h-4 w-4 mr-2" />
                Open in system viewer
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center gap-4 text-center">
            <p className="text-muted-foreground">
              {error || "Preview not available for this file type."}
            </p>
            <div className="flex gap-2">
              <Button onClick={handleDownload}>
                <Download className="h-4 w-4 mr-2" />
                Download file
              </Button>
              {fileUrl && (
                <Button onClick={handleOpenInNewTab} variant="outline">
                  <ExternalLink className="h-4 w-4 mr-2" />
                  Open in system viewer
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default DocumentViewer;

