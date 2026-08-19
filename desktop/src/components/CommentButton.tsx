import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Check, Sparkles } from "lucide-react";
import { useAnnotations } from "@/hooks/use-annotations";
import { createAnnotation, replyToAnnotation, resolveAnnotation, type AnchorType } from "@/lib/api";
import { anchorElementId } from "@/lib/anchor";
import { cn, timeAgo } from "@/lib/utils";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";

const CLAUDE_BRIDGE_AVAILABLE = typeof window !== "undefined" && !!window.electronAPI?.askClaude;

/** Plannotator-style comment affordance, scoped to one dashboard element
 * (a KPI card, a run row, a table row, a chart series) rather than a
 * free-text selection range. Renders a small hover-visible icon that opens
 * a threaded popover — highlight-and-comment on a specific thing, not a
 * chatbot. */
export default function CommentButton({
  anchorType, anchor, className,
}: {
  anchorType: AnchorType;
  anchor: Record<string, unknown>;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [asking, setAsking] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Kept in memory only (not persisted) — lets a follow-up "Ask Claude" in
  // this same thread resume the prior session instead of paying for a
  // fresh one, for as long as this popover stays mounted.
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  const queryClient = useQueryClient();
  const { data } = useAnnotations(anchorType, anchor);

  const elementId = anchorElementId(anchorType, anchor);

  // The comments drawer (Header badge) scrolls to this element then fires
  // this event so the thread opens without every CommentButton call site
  // having to thread an "open" prop down from App.
  useEffect(() => {
    function onOpenRequest(e: Event) {
      if ((e as CustomEvent<{ id: string }>).detail?.id === elementId) setOpen(true);
    }
    window.addEventListener("quorum:open-thread", onOpenRequest);
    return () => window.removeEventListener("quorum:open-thread", onOpenRequest);
  }, [elementId]);

  const threads = data?.annotations ?? [];
  const openThreads = threads.filter((t) => t.status === "open");
  const hasThreads = threads.length > 0;

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["annotations"] });
  }

  async function ensureThread(question: string): Promise<string> {
    const existing = threads[0];
    if (existing) {
      await replyToAnnotation(existing.id, question);
      return existing.id;
    }
    const created = await createAnnotation(anchorType, anchor, question);
    return created.id;
  }

  async function submit() {
    if (!draft.trim()) return;
    setError(null);
    try {
      await ensureThread(draft.trim());
      setDraft("");
      invalidate();
    } catch {
      setError("Couldn't send — try again.");
    }
  }

  async function askClaude() {
    const question = draft.trim();
    if (!question || !CLAUDE_BRIDGE_AVAILABLE) return;
    setError(null);
    setDraft("");
    let threadId: string;
    try {
      threadId = await ensureThread(question);
      invalidate();
    } catch {
      setError("Couldn't send — try again.");
      return;
    }

    setAsking(true);
    setStreamText("");
    const context = `Dashboard annotation context — anchor_type: ${anchorType}, anchor: ${JSON.stringify(anchor)}`;
    try {
      const { text: finalText, sessionId: newSessionId } = await window.electronAPI.askClaude(
        question, context, (chunk) => setStreamText((prev) => prev + chunk), sessionId
      );
      if (newSessionId) setSessionId(newSessionId);
      await replyToAnnotation(threadId, finalText, "claude");
      invalidate();
    } catch {
      setError("Claude couldn't answer — try again.");
    } finally {
      setAsking(false);
      setStreamText("");
    }
  }

  async function resolve(id: string) {
    await resolveAnnotation(id);
    invalidate();
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={elementId}
          className={cn(
            "inline-flex items-center gap-1 rounded p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground",
            !hasThreads && "opacity-0 group-hover:opacity-100",
            openThreads.length > 0 && "text-accent-foreground opacity-100",
            className
          )}
          aria-label="Comment"
        >
          <MessageCircle className="w-3.5 h-3.5" />
          {threads.length > 0 && <span className="text-[10px] font-medium">{threads.length}</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent className="space-y-2">
        <div className="max-h-56 overflow-y-auto space-y-2">
          {threads.length === 0 ? (
            <p className="text-xs text-muted-foreground">No comments yet.</p>
          ) : (
            threads.flatMap((thread) =>
              thread.thread.map((c, i) => (
                <div key={`${thread.id}-${i}`} className="text-xs">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span className="font-medium">{c.author === "claude" ? "Claude" : "You"}</span>
                    <span className="text-[10px] text-muted-foreground">{timeAgo(c.ts)}</span>
                    {i === 0 && (
                      <span className={cn(
                        "ml-auto px-1.5 py-0.5 rounded-full text-[9px] font-medium",
                        thread.status === "open" ? "bg-gate-skip/10 text-gate-skip" : "bg-gate-pass/10 text-gate-pass"
                      )}>
                        {thread.status}
                      </span>
                    )}
                  </div>
                  <p className="text-muted-foreground whitespace-pre-wrap">{c.body}</p>
                  {i === 0 && thread.status === "open" && (
                    <button
                      onClick={() => resolve(thread.id)}
                      className="mt-1 inline-flex items-center gap-1 text-[10px] text-muted-foreground hover:text-foreground"
                    >
                      <Check className="w-3 h-3" /> Resolve
                    </button>
                  )}
                </div>
              ))
            )
          )}
          {asking && (
            <div className="text-xs">
              <div className="flex items-center gap-1.5 mb-0.5">
                <span className="font-medium">Claude</span>
                <span className="text-[10px] text-muted-foreground">thinking...</span>
              </div>
              <p className="text-muted-foreground whitespace-pre-wrap">{streamText || "…"}</p>
            </div>
          )}
        </div>

        {error && <p className="text-[10px] text-destructive">{error}</p>}

        <div className="flex items-center gap-1.5 pt-1 border-t">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Add a comment..."
            disabled={asking}
            className="flex-1 text-xs rounded border bg-background px-2 py-1 outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
          />
          {CLAUDE_BRIDGE_AVAILABLE && (
            <button
              onClick={askClaude}
              disabled={!draft.trim() || asking}
              title="Ask Claude (read-only — can't trade or edit)"
              className="text-muted-foreground hover:text-accent-foreground disabled:opacity-50"
            >
              <Sparkles className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={submit}
            disabled={!draft.trim() || asking}
            className="text-[11px] font-medium text-accent-foreground disabled:text-muted-foreground disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
