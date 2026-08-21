import { spawn } from "child_process";
import * as path from "path";

const PROJECT_ROOT = path.resolve(__dirname, "../../..");

// Pin a model per use case rather than letting these inherit the account's
// ambient/interactive default — that default isn't visible from here and
// could silently be an expensive tier. (Headless usage is billed the same
// as interactive under the current plan, not a separate credit pool — an
// earlier belief to the contrary was reverted; this pin is about picking
// the right cost/quality tier per task, not rationing a scarce budget.)
const DASHBOARD_QA_MODEL = "haiku"; // cheap — answering questions about already-fetched data
const SPEC_CODEGEN_MODEL = "sonnet"; // needs to get the closed-grammar schema right — retry ladder's default

// Read-only MCP tools only — this bridge answers dashboard questions about
// historical/live data, it must never trade or mutate state. Mirrors
// CLAUDE.md's MCP Tools list minus execute_paper_trade, kill_switch,
// watchlist writes, and every save_*/prune_* wiki-mutation tool.
const DASHBOARD_QA_ALLOWED_TOOLS = [
  "mcp__quorum__get_portfolio", "mcp__quorum__get_trades", "mcp__quorum__get_watchlist",
  "mcp__quorum__get_market_regime", "mcp__quorum__get_sector_rotation", "mcp__quorum__get_earnings_calendar",
  "mcp__quorum__get_indicators", "mcp__quorum__get_indicators_bulk", "mcp__quorum__get_stock_data",
  "mcp__quorum__get_fundamentals", "mcp__quorum__get_financial_statements",
  "mcp__quorum__get_news", "mcp__quorum__get_global_news",
  "mcp__quorum__get_reddit_sentiment", "mcp__quorum__get_stocktwits_sentiment",
  "mcp__quorum__get_insider_transactions", "mcp__quorum__get_insider_clusters",
  "mcp__quorum__get_congress_trades", "mcp__quorum__get_congress_summary",
  "mcp__quorum__get_portfolio_risk", "mcp__quorum__get_live_risk", "mcp__quorum__get_trade_reflections",
  "mcp__quorum__get_asset_info", "mcp__quorum__get_full_ticker_data",
  "mcp__quorum__get_cache_stats", "mcp__quorum__get_analytics_summary", "mcp__quorum__get_rules",
  "mcp__quorum__get_wiki_page", "mcp__quorum__search_wiki", "mcp__quorum__get_trading_calendar",
  "mcp__quorum__get_13f_holdings", "mcp__quorum__get_consensus_estimates", "mcp__quorum__get_sec_filings",
  "mcp__quorum__list_screens", "mcp__quorum__run_screen",
].join(",");

const DASHBOARD_QA_DISALLOWED_TOOLS = [
  "Bash", "Write", "Edit",
  "mcp__quorum__execute_paper_trade", "mcp__quorum__kill_switch",
  "mcp__quorum__add_to_watchlist", "mcp__quorum__remove_from_watchlist",
  "mcp__quorum__save_analysis_to_wiki", "mcp__quorum__prune_wiki",
].join(",");

// Strategy codegen only ever needs to read schema.py + example YAML files
// to ground its output — no MCP tools, no Bash, no Write. It returns YAML
// as plain text for the Research tab to show for review; the app (not this
// session) writes the file after the user approves it.
const CODEGEN_ALLOWED_TOOLS = "Read,Glob,Grep";
const CODEGEN_DISALLOWED_TOOLS = "Bash,Write,Edit,WebFetch,WebSearch";

interface SpawnResult {
  text: string;
  sessionId: string | null;
}

/** One normalized event extracted from a single `claude -p --output-format
 * stream-json` line. A line can carry a session_id alongside assistant
 * content, and assistant content can carry several blocks, so parsing one
 * line can yield zero or more events — order matches the order `runHeadless`
 * must apply them in (session id before content, blocks in array order). */
export type StreamJsonEvent =
  | { type: "session"; sessionId: string }
  | { type: "text"; text: string }
  | { type: "tool_use"; name: string; input: Record<string, unknown> }
  | { type: "result"; text: string };

/** Pure parse of one stream-json line into normalized events — no I/O, no
 * subprocess, so it's unit-testable against canned transcript lines.
 * Mirrors quorum/execution/trace_parser.py's parse_stream_json_line, kept
 * separate from the subprocess lifecycle for the same reason: an
 * unparseable or unrecognized line is simply skipped (empty result) rather
 * than raising, so one odd line doesn't kill the rest of a stream. */
export function parseStreamJsonLine(line: string): StreamJsonEvent[] {
  let obj: any;
  try {
    obj = JSON.parse(line);
  } catch {
    return [];
  }

  const events: StreamJsonEvent[] = [];
  if (typeof obj.session_id === "string") {
    events.push({ type: "session", sessionId: obj.session_id });
  }
  if (obj.type === "assistant") {
    const content = obj.message?.content ?? [];
    for (const block of content) {
      if (block?.type === "text" && block.text) {
        events.push({ type: "text", text: block.text });
      } else if (block?.type === "tool_use" && typeof block.name === "string") {
        events.push({ type: "tool_use", name: block.name, input: block.input ?? {} });
      }
    }
  } else if (obj.type === "result" && typeof obj.result === "string") {
    events.push({ type: "result", text: obj.result });
  }
  return events;
}

/** Shared spawn-and-parse core for both headless bridges: streams text
 * chunks to `onChunk` as they arrive, forwards each tool call (Read/Glob/
 * Grep) to `onToolUse` as its own event so a caller can render "reading
 * schema.py" style process steps instead of only the raw text output,
 * captures the session_id every stream-json line carries (so a caller can
 * `--resume` it for a real follow-up instead of paying full re-init cost
 * on an unrelated fresh session), and resolves with the final answer once
 * the process exits. */
function runHeadless(
  args: string[],
  onChunk: (text: string) => void,
  onToolUse?: (name: string, input: Record<string, unknown>) => void,
): Promise<SpawnResult> {
  return new Promise((resolve, reject) => {
    const claudeBin = process.env.CLAUDE_BIN || "claude";
    const proc = spawn(claudeBin, args, {
      cwd: PROJECT_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let finalText = "";
    let sessionId: string | null = null;
    let buffer = "";

    proc.stdout?.on("data", (data: Buffer) => {
      buffer += data.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.trim()) continue;
        for (const event of parseStreamJsonLine(line)) {
          switch (event.type) {
            case "session":
              sessionId = event.sessionId;
              break;
            case "text":
              finalText += event.text;
              onChunk(event.text);
              break;
            case "tool_use":
              onToolUse?.(event.name, event.input);
              break;
            case "result":
              finalText = event.text;
              break;
          }
        }
      }
    });

    proc.stderr?.on("data", (data: Buffer) => {
      console.error(`[claude] ${data.toString().trim()}`);
    });

    proc.on("error", (err) => reject(err));
    proc.on("exit", (code) => {
      if (code === 0) resolve({ text: finalText, sessionId });
      else reject(new Error(`claude exited with code ${code}`));
    });
  });
}

/** Ask the dashboard's read-only Claude bridge one question. Pass
 * `resumeSessionId` (from a prior call's result, kept only in renderer
 * state — not persisted) to continue the SAME annotation thread as one
 * real conversation instead of a fresh, context-less session each reply;
 * omit it for a new/unrelated thread. `context` (the anchor's own data)
 * is only meaningful on the first turn — Claude already has it once a
 * session is resumed, so callers should pass it once and not resend it. */
export function askClaude(
  question: string,
  context: string | undefined,
  onChunk: (text: string) => void,
  opts?: { resumeSessionId?: string },
): Promise<SpawnResult> {
  const args = [
    "-p", question,
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--model", DASHBOARD_QA_MODEL,
    "--allowedTools", DASHBOARD_QA_ALLOWED_TOOLS,
    "--disallowedTools", DASHBOARD_QA_DISALLOWED_TOOLS,
  ];
  if (opts?.resumeSessionId) {
    args.push("--resume", opts.resumeSessionId);
  } else if (context) {
    args.push("--append-system-prompt", context);
  }
  return runHeadless(args, onChunk);
}

type SpecKind = "strategy" | "screen";

// One entry per spec kind the generate -> validate -> retry loop supports
// (desktop/src/lib/codegen.ts).
const GROUNDING: Record<SpecKind, { schemaFile: string; exampleFile: string; noun: string }> = {
  strategy: {
    schemaFile: "quorum/strategy/schema.py",
    exampleFile: "strategies/regime_gate.yaml",
    noun: "Strategy",
  },
  screen: {
    schemaFile: "quorum/screen/schema.py",
    exampleFile: "screens/ai_quality.yaml",
    noun: "Screen",
  },
};

/** Generate a spec YAML (strategy or screen) from a natural-language
 * description, grounded in its closed-grammar schema and a working
 * example. Read-only session — returns text for the Research tab's
 * editor to show for review; nothing is written to disk here.
 *
 * `existingYaml` seeds the "revise this" context on a FRESH generation
 * (first attempt, or the retry ladder's fresh final attempt) — omit it to
 * start from scratch. When both `retryError` and `resumeSessionId` are
 * set, the prompt collapses to just the correction: the resumed session
 * already has full schema/example grounding in its context from the first
 * attempt, so re-sending it would be redundant. `model` lets the caller's
 * retry ladder step up to a stronger model on a later attempt; omit it to
 * use the codegen default. */
export function generateSpecYaml(
  kind: SpecKind,
  specId: string,
  description: string,
  existingYaml: string | undefined,
  onChunk: (text: string) => void,
  opts?: {
    resumeSessionId?: string;
    retryError?: string;
    model?: string;
    onToolUse?: (name: string, input: Record<string, unknown>) => void;
  },
): Promise<SpawnResult> {
  const g = GROUNDING[kind];
  const model = opts?.model ?? SPEC_CODEGEN_MODEL;

  const prompt = opts?.retryError && opts?.resumeSessionId
    ? [
        "Your last draft failed validation with these errors:",
        opts.retryError,
        "",
        "Fix ONLY what's needed to pass validation. Write ONLY the complete",
        "corrected YAML content — no prose, no markdown code fences, no explanation.",
      ].join("\n")
    : [
        `Read ${g.schemaFile} to learn the exact closed-grammar fields`,
        `and operators a ${kind} YAML may use, and ${g.exampleFile}`,
        "as a working example. Then write ONLY the complete YAML content for a",
        `new ${kind} file with ${kind}_id: ${specId} — no prose, no`,
        "markdown code fences, no explanation, just the raw YAML.",
        "",
        `${g.noun} idea (natural language): ${description}`,
        existingYaml ? `\nCurrent YAML to revise:\n${existingYaml}` : "",
        opts?.retryError
          ? `\nThe previous attempt(s) failed validation with these errors:\n${opts.retryError}\nFix them.`
          : "",
      ].join("\n");

  const args = [
    "-p", prompt,
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--model", model,
    "--allowedTools", CODEGEN_ALLOWED_TOOLS,
    "--disallowedTools", CODEGEN_DISALLOWED_TOOLS,
  ];
  if (opts?.resumeSessionId) {
    args.push("--resume", opts.resumeSessionId);
  }
  return runHeadless(args, onChunk, opts?.onToolUse);
}
