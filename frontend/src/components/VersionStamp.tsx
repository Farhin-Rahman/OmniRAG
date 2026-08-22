/**
 * Version stamp component showing build information.
 * 
 * Displays BUILD_SHA and BUILD_TIME injected at build time via environment variables.
 */

interface VersionStampProps {
  className?: string;
}

export const VersionStamp = ({ className }: VersionStampProps) => {
  const buildSha = import.meta.env.VITE_BUILD_SHA || "dev";
  const buildTime = import.meta.env.VITE_BUILD_TIME || new Date().toISOString();

  // Format build time for display
  const formatBuildTime = (timeStr: string) => {
    try {
      const date = new Date(timeStr);
      return date.toLocaleString();
    } catch {
      return timeStr;
    }
  };

  return (
    <div className={className || "text-xs text-muted-foreground"}>
      <div className="flex flex-col gap-0.5">
        <span>Build: {buildSha.substring(0, 7)}</span>
        <span>Built: {formatBuildTime(buildTime)}</span>
      </div>
    </div>
  );
};

