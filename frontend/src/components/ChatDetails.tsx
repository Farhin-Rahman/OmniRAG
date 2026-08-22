import { useState } from "react";
import { ChevronLeft, ChevronRight, Calendar, MessageCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

interface ChatDetailsProps {
  conversationId: string | null;
}

const ChatDetails = ({ conversationId }: ChatDetailsProps) => {
  const [isCollapsed, setIsCollapsed] = useState(false);

  if (!conversationId) return null;

  return (
    <div className="relative">
      <Button
        variant="ghost"
        size="icon"
        className="absolute -left-4 top-4 h-8 w-8 rounded-full border bg-background shadow-md z-20"
        onClick={() => setIsCollapsed(!isCollapsed)}
      >
        {isCollapsed ? (
          <ChevronLeft className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
      </Button>
      <div
        className={cn(
          "relative flex flex-col border-l bg-sidebar transition-all duration-300",
          isCollapsed ? "w-0 overflow-hidden" : "w-80"
        )}
      >
        {!isCollapsed && (
          <>
            <div className="p-4 border-b">
              <h3 className="font-semibold text-sidebar-foreground">Chat Details</h3>
            </div>

            <ScrollArea className="flex-1">
              <div className="p-4 space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Calendar className="h-4 w-4" />
                    <span>Created today</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <MessageCircle className="h-4 w-4" />
                    <span>Active conversation</span>
                  </div>
                </div>

                <Separator />

                <div className="space-y-2">
                  <h4 className="text-sm font-medium">About this chat</h4>
                  <p className="text-sm text-muted-foreground">
                    This is your personal document assistant. Ask questions, get insights,
                    and have natural conversations about your documents.
                  </p>
                </div>

                <Separator />

                <div className="space-y-2">
                  <h4 className="text-sm font-medium">Tips</h4>
                  <ul className="text-sm text-muted-foreground space-y-1 list-disc list-inside">
                    <li>Be specific in your questions</li>
                    <li>Use context from previous messages</li>
                    <li>Ask for clarification if needed</li>
                  </ul>
                </div>
              </div>
            </ScrollArea>
          </>
        )}
      </div>
    </div>
  );
};

export default ChatDetails;
