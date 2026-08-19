import { useQuery } from "@tanstack/react-query";
import { MessageCircle } from "lucide-react";
import { fetchAnnotations, type Annotation } from "@/lib/api";
import { describeAnchor } from "@/lib/anchor";
import { cn, timeAgo } from "@/lib/utils";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";

export default function CommentsDrawer({
  open, onOpenChange, onNavigate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNavigate: (thread: Annotation) => void;
}) {
  const { data } = useQuery({
    queryKey: ["annotations", "all"],
    queryFn: () => fetchAnnotations(),
    staleTime: 15_000,
    enabled: open,
  });

  const threads = data?.annotations ?? [];
  const open_ = threads.filter((t) => t.status === "open");
  const resolved = threads.filter((t) => t.status === "resolved");

  function jumpTo(thread: Annotation) {
    onOpenChange(false);
    onNavigate(thread);
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-md flex flex-col gap-0 p-0">
        <SheetHeader className="p-4 border-b">
          <SheetTitle className="text-sm">Comment threads</SheetTitle>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto">
          {threads.length === 0 && (
            <p className="p-4 text-xs text-muted-foreground">No comment threads yet.</p>
          )}

          {open_.length > 0 && (
            <ThreadGroup label="Open" threads={open_} onSelect={jumpTo} />
          )}
          {resolved.length > 0 && (
            <ThreadGroup label="Resolved" threads={resolved} onSelect={jumpTo} />
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

function ThreadGroup({
  label, threads, onSelect,
}: {
  label: string;
  threads: Annotation[];
  onSelect: (t: Annotation) => void;
}) {
  return (
    <div>
      <div className="px-4 pt-3 pb-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label} ({threads.length})
      </div>
      {threads.map((t) => {
        const last = t.thread[t.thread.length - 1];
        return (
          <button
            key={t.id}
            onClick={() => onSelect(t)}
            className="w-full text-left px-4 py-2.5 border-b hover:bg-accent/50 transition-colors"
          >
            <div className="flex items-center gap-1.5 mb-0.5">
              <MessageCircle className="w-3 h-3 text-muted-foreground shrink-0" />
              <span className="text-[11px] font-medium truncate">
                {describeAnchor(t.anchor_type, t.anchor)}
              </span>
              <span
                className={cn(
                  "ml-auto shrink-0 px-1.5 py-0.5 rounded-full text-[9px] font-medium",
                  t.status === "open" ? "bg-gate-skip/10 text-gate-skip" : "bg-gate-pass/10 text-gate-pass"
                )}
              >
                {t.status}
              </span>
            </div>
            {last && (
              <p className="text-[11px] text-muted-foreground line-clamp-2">
                <span className="font-medium">{last.author === "claude" ? "Claude: " : "You: "}</span>
                {last.body}
              </p>
            )}
            <p className="text-[10px] text-muted-foreground mt-0.5">{timeAgo(t.created_at)}</p>
          </button>
        );
      })}
    </div>
  );
}
