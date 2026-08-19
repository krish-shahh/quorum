import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Check } from "lucide-react";
import { useAnnotations } from "@/hooks/use-annotations";
import { createAnnotation, replyToAnnotation, resolveAnnotation, type AnchorType } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";

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
  const queryClient = useQueryClient();
  const { data } = useAnnotations(anchorType, anchor);

  const threads = data?.annotations ?? [];
  const openThreads = threads.filter((t) => t.status === "open");
  const hasThreads = threads.length > 0;

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ["annotations"] });
  }

  async function submit() {
    if (!draft.trim()) return;
    const existing = threads[0];
    if (existing) {
      await replyToAnnotation(existing.id, draft.trim());
    } else {
      await createAnnotation(anchorType, anchor, draft.trim());
    }
    setDraft("");
    invalidate();
  }

  async function resolve(id: string) {
    await resolveAnnotation(id);
    invalidate();
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
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
        </div>

        <div className="flex items-center gap-1.5 pt-1 border-t">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="Add a comment..."
            className="flex-1 text-xs rounded border bg-background px-2 py-1 outline-none focus:ring-1 focus:ring-ring"
          />
          <button
            onClick={submit}
            disabled={!draft.trim()}
            className="text-[11px] font-medium text-accent-foreground disabled:text-muted-foreground disabled:opacity-50"
          >
            Send
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
