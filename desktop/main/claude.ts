import { spawn } from "child_process";
import * as path from "path";

const PROJECT_ROOT = path.resolve(__dirname, "../../..");

// No headless call site pins a model unless it says so below. Each headless
// `claude -p` draws from a small separate Agent SDK credit pool (~$20/mo on
// Pro, distinct from interactive-subscription usage — see project memory
// "Subscription plan"), not the account's ambient/interactive default,
// which is both invisible from here and could be an expensive tier. Pin
// explicitly, per use case, instead of inheriting it silently.
const DASHBOARD_QA_MODEL = "haiku"; // cheap — answering questions about already-fetched data
const STRATEGY_CODEGEN_MODEL = "sonnet"; // needs to get the closed-grammar schema right

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
  "mcp__quorum__get_quant_scores", "mcp__quorum__get_portfolio_risk", "mcp__quorum__get_live_risk",
  "mcp__quorum__get_trade_reflections", "mcp__quorum__get_ticker_state", "mcp__quorum__get_ticker_deltas",
  "mcp__quorum__get_asset_info", "mcp__quorum__get_analyst_accuracy", "mcp__quorum__get_autonomous_tickers",
  "mcp__quorum__get_full_ticker_data", "mcp__quorum__get_trade_reports", "mcp__quorum__get_council_reports",
  "mcp__quorum__get_cache_stats", "mcp__quorum__get_analytics_summary", "mcp__quorum__get_rules",
  "mcp__quorum__get_wiki_page", "mcp__quorum__search_wiki", "mcp__quorum__get_trading_calendar",
  "mcp__quorum__get_13f_holdings", "mcp__quorum__get_consensus_estimates", "mcp__quorum__get_sec_filings",
].join(",");

const DASHBOARD_QA_DISALLOWED_TOOLS = [
  "Bash", "Write", "Edit",
  "mcp__quorum__execute_paper_trade", "mcp__quorum__kill_switch",
  "mcp__quorum__add_to_watchlist", "mcp__quorum__remove_from_watchlist",
  "mcp__quorum__save_analysis_to_wiki", "mcp__quorum__save_trade_report", "mcp__quorum__save_council_reports",
  "mcp__quorum__prune_wiki",
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

/** Shared spawn-and-parse core for both headless bridges: streams text
 * chunks to `onChunk` as they arrive, captures the session_id every
 * stream-json line carries (so a caller can `--resume` it for a real
 * follow-up instead of paying full re-init cost on an unrelated fresh
 * session), and resolves with the final answer once the process exits. */
function runHeadless(args: string[], onChunk: (text: string) => void): Promise<SpawnResult> {
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
        let obj: any;
        try {
          obj = JSON.parse(line);
        } catch {
          continue;
        }
        if (typeof obj.session_id === "string") sessionId = obj.session_id;
        if (obj.type === "assistant") {
          const content = obj.message?.content ?? [];
          for (const block of content) {
            if (block?.type === "text" && block.text) {
              finalText += block.text;
              onChunk(block.text);
            }
          }
        } else if (obj.type === "result" && typeof obj.result === "string") {
          finalText = obj.result;
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

/** Generate a strategy YAML from a natural-language description, grounded
 * in the closed-grammar schema (quorum/strategy/schema.py) and an existing
 * example. Read-only session — returns text for the Research tab's editor
 * to show for review; nothing is written to disk here. `existingYaml`
 * (when editing a strategy rather than starting fresh) is included so the
 * model revises it instead of starting over. */
export function generateStrategyYaml(
  strategyId: string,
  description: string,
  existingYaml: string | undefined,
  onChunk: (text: string) => void,
): Promise<SpawnResult> {
  const prompt = [
    "Read quorum/strategy/schema.py to learn the exact closed-grammar fields",
    "and operators a strategy YAML may use, and strategies/regime_gate.yaml",
    "as a working example. Then write ONLY the complete YAML content for a",
    `new strategy file with strategy_id: ${strategyId} — no prose, no`,
    "markdown code fences, no explanation, just the raw YAML.",
    "",
    `Strategy idea (natural language): ${description}`,
    existingYaml ? `\nCurrent YAML to revise:\n${existingYaml}` : "",
  ].join("\n");

  const args = [
    "-p", prompt,
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--model", STRATEGY_CODEGEN_MODEL,
    "--allowedTools", CODEGEN_ALLOWED_TOOLS,
    "--disallowedTools", CODEGEN_DISALLOWED_TOOLS,
  ];
  return runHeadless(args, onChunk);
}
