import { spawn } from "child_process";
import * as path from "path";

const PROJECT_ROOT = path.resolve(__dirname, "../../..");

// Read-only MCP tools only — this bridge answers dashboard questions about
// historical/live data, it must never trade or mutate state. Mirrors
// CLAUDE.md's MCP Tools list minus execute_paper_trade, kill_switch,
// watchlist writes, and every save_*/prune_* wiki-mutation tool.
const ALLOWED_TOOLS = [
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

const DISALLOWED_TOOLS = [
  "Bash", "Write", "Edit",
  "mcp__quorum__execute_paper_trade", "mcp__quorum__kill_switch",
  "mcp__quorum__add_to_watchlist", "mcp__quorum__remove_from_watchlist",
  "mcp__quorum__save_analysis_to_wiki", "mcp__quorum__save_trade_report", "mcp__quorum__save_council_reports",
  "mcp__quorum__prune_wiki",
].join(",");

/** Spawn one headless `claude -p` for a dashboard annotation question,
 * streaming text chunks to `onChunk` as they arrive and resolving with the
 * full answer. Mirrors flask.ts's spawn-and-pipe shape. `context` (the
 * anchor's own data — a KPI's value, a run's detail) is injected via
 * --append-system-prompt so the question doesn't need to restate it. */
export function askClaude(
  question: string,
  context: string | undefined,
  onChunk: (text: string) => void,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const claudeBin = process.env.CLAUDE_BIN || "claude";
    const args = [
      "-p", question,
      "--output-format", "stream-json",
      "--include-partial-messages",
      "--allowedTools", ALLOWED_TOOLS,
      "--disallowedTools", DISALLOWED_TOOLS,
    ];
    if (context) {
      args.push("--append-system-prompt", context);
    }

    const proc = spawn(claudeBin, args, {
      cwd: PROJECT_ROOT,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let finalText = "";
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
      console.error(`[claude:ask] ${data.toString().trim()}`);
    });

    proc.on("error", (err) => reject(err));
    proc.on("exit", (code) => {
      if (code === 0) resolve(finalText);
      else reject(new Error(`claude exited with code ${code}`));
    });
  });
}
