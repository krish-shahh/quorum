import { FileSearch, PenLine, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SpecAttempt } from "@/lib/codegen";

export interface ToolEvent {
  attempt: number;
  name: string;
  input: Record<string, unknown>;
}

const ATTEMPT_GLYPHS = ["①", "②", "③"];

function toolIcon(name: string) {
  if (name === "Read") return FileSearch;
  if (name === "Glob" || name === "Grep") return Search;
  return PenLine;
}

function describeToolUse(name: string, input: Record<string, unknown>): string {
  switch (name) {
    case "Read":
      return String(input.file_path ?? "a file");
    case "Glob":
      return `files matching "${input.pattern ?? ""}"`;
    case "Grep":
      return `"${input.pattern ?? ""}" in the codebase`;
    default:
      return name;
  }
}

/** Live tool-use feed + attempt-result chips for the generate -> validate
 * -> retry loop (desktop/src/lib/codegen.ts) — shared by Strategy Lab and
 * the screener panel. While a generation is in flight this shows what
 * Claude is actually doing (reading the schema, reading a worked example,
 * writing the draft) instead of only a wall of streaming YAML with no
 * visible process; once an attempt finishes, its steps stay available
 * behind the attempt chip. */
export default function GenerationProgress({
  attempts, toolEvents, generating, expandedAttempt, onToggleExpand,
}: {
  attempts: SpecAttempt[];
  toolEvents: ToolEvent[];
  generating: boolean;
  expandedAttempt: number | null;
  onToggleExpand: (attempt: number) => void;
}) {
  if (attempts.length === 0 && toolEvents.length === 0) return null;

  const liveAttempt = attempts.length + 1;
  const liveEvents = generating ? toolEvents.filter((e) => e.attempt === liveAttempt) : [];

  return (
    <div className="space-y-1.5">
      {liveEvents.length > 0 && (
        <div className="rounded-md border bg-muted/30 p-2 space-y-1">
          {liveEvents.map((e, i) => {
            const Icon = toolIcon(e.name);
            const isLast = i === liveEvents.length - 1;
            return (
              <div
                key={i}
                className={cn(
                  "flex items-center gap-1.5 text-[11px] text-muted-foreground",
                  isLast && "animate-pulse"
                )}
              >
                <Icon className="w-3 h-3 shrink-0" />
                <span className="font-mono truncate">
                  {e.name === "Read" ? "Reading" : e.name === "Glob" || e.name === "Grep" ? "Searching" : e.name}{" "}
                  {describeToolUse(e.name, e.input)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {attempts.length > 0 && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            {attempts.map((a) => (
              <button
                key={a.attempt}
                onClick={() => onToggleExpand(a.attempt)}
                title={a.ok ? "Passed validation" : "Failed validation — click for the errors"}
                className={cn(
                  "text-[10px] font-mono px-1.5 py-0.5 rounded border transition-colors",
                  a.ok ? "border-profit/40 text-profit" : "border-loss/40 text-loss",
                  expandedAttempt === a.attempt && "bg-muted"
                )}
              >
                {ATTEMPT_GLYPHS[a.attempt - 1] ?? a.attempt} {a.ok ? "✓" : "✗"} {a.model}
              </button>
            ))}
            {generating && attempts.length < 3 && (
              <span className="text-[10px] text-muted-foreground">retrying...</span>
            )}
          </div>
          {expandedAttempt != null && (
            <div className="text-[10px] font-mono bg-muted/40 rounded-md p-2 max-h-32 overflow-y-auto space-y-1">
              {toolEvents
                .filter((e) => e.attempt === expandedAttempt)
                .map((e, i) => (
                  <div key={i} className="text-muted-foreground">
                    {e.name === "Read" ? "Read" : e.name} {describeToolUse(e.name, e.input)}
                  </div>
                ))}
              <div className="whitespace-pre-wrap break-words">
                {attempts.find((a) => a.attempt === expandedAttempt)?.errors.join("\n") || "Passed validation."}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
