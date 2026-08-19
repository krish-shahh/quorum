import { useEffect, useRef, useState } from "react";
import { Play, Save, Sparkles } from "lucide-react";
import { cn, formatPct, formatUsd, gateColor } from "@/lib/utils";
import { generateValidatedSpec, type SpecAttempt } from "@/lib/codegen";

const AVAILABLE = typeof window !== "undefined" && !!window.electronAPI?.runQuorumCommand;
const GENERATE_AVAILABLE = typeof window !== "undefined" && !!window.electronAPI?.generateSpecYaml;

const ATTEMPT_GLYPHS = ["①", "②", "③"];

const TEMPLATE = `# strategy_id must match this file's name (strategies/<strategy_id>.yaml).
# Closed-grammar schema (quorum/strategy/schema.py) — every field below is
# validated on load; an unknown field or a typo'd op name fails fast with
# a clear error the moment you backtest, not silently.
strategy_id: my_strategy
version: "0.1"
description: >
  What this strategy trades and why, in a sentence or two.

universe:
  source: tag           # "tag" (from quorum/strategy/universe.py's TMT tags) or "static"
  tags: [mega_cap_platforms, semis_design]
  # static: symbols: [AAPL, MSFT]

features:
  # op options: sma, ema, rsi, atr, pct_change, zscore, abs, ratio, rank
  # (numeric) | gt, lt, gte, lte, eq, cross_above, cross_below (boolean)
  - name: xlk_sma200
    op: sma
    inputs: [XLK.close]
    window: 200
  - name: xlk_above_200dma
    op: gt
    inputs: [XLK.close, xlk_sma200]

signal:
  direction: long_only  # or long_short
  entry:
    all_of: [xlk_above_200dma]
  exit:
    any_of: []

sizing:
  method: vol_target    # flat_pct | vol_target | kelly_capped
  target_risk_pct: 0.01
  atr_window: 14
  max_position_pct: 0.15

risk:
  regime_gate:
    risk_on: 1.0
    risk_off: 0.5
    volatile: 0.5
    transition: 0.75
  stop_loss_atr_mult: 2.0
  max_positions: 15
  max_single_ticker_pct: 0.20
  max_holding_days: 252

execution:
  fill_timing: next_bar_open
  order_type: market
  cost_bps: 10
`;

interface BacktestResult {
  run_id: string | null;
  strategy_id: string;
  gate_passed: boolean | null;
  final_equity: number;
  total_return: number;
  n_trades: number;
  win_rate: number | null;
  sharpe: number | null;
  max_dd: number | null;
}

interface ShadowResult {
  run_id: string | null;
  strategy_id: string;
  final_equity: number;
  n_trades: number;
}

/** Create-and-test workbench for the closed-grammar strategy YAMLs under
 * strategies/*.yaml. Editing raw YAML (rather than a form) matches how
 * the system is actually authored elsewhere (git-committed, Claude-
 * writable files) — schema validation happens for free the moment you
 * backtest, since load_strategy raises with a specific error instead of
 * this needing its own separate validation path to keep in sync. */
export default function StrategyLab({ onOpenRun }: { onOpenRun: (runId: string) => void }) {
  const [strategies, setStrategies] = useState<string[]>([]);
  const [selected, setSelected] = useState(""); // "" = new strategy
  const [strategyId, setStrategyId] = useState("");
  const [yamlText, setYamlText] = useState(TEMPLATE);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [attempts, setAttempts] = useState<SpecAttempt[]>([]);
  const [expandedAttempt, setExpandedAttempt] = useState<number | null>(null);
  const streamingAttemptRef = useRef(0);

  const [runMode, setRunMode] = useState<"backtest" | "shadow">("backtest");
  const [start, setStart] = useState("2018-01-01");
  const [cash, setCash] = useState("100000");
  const [running, setRunning] = useState(false);
  const [output, setOutput] = useState("");
  const [result, setResult] = useState<BacktestResult | ShadowResult | null>(null);

  useEffect(() => {
    if (AVAILABLE) refreshStrategies();
  }, []);

  async function refreshStrategies() {
    setStrategies(await window.electronAPI.listStrategies());
  }

  async function loadExisting(id: string) {
    setSelected(id);
    setSaveMsg(null);
    if (!id) {
      setStrategyId("");
      setYamlText(TEMPLATE);
      return;
    }
    setStrategyId(id);
    const content = await window.electronAPI.readStrategyFile(id);
    setYamlText(content ?? TEMPLATE);
  }

  async function save() {
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await window.electronAPI.saveStrategy(strategyId, yamlText);
      if (res.ok) {
        setSaveMsg({ text: `Saved strategies/${strategyId}.yaml`, ok: true });
        await refreshStrategies();
        setSelected(strategyId);
      } else {
        setSaveMsg({ text: res.error ?? "Save failed.", ok: false });
      }
    } finally {
      setSaving(false);
    }
  }

  async function generate() {
    if (!description.trim() || !/^[a-z][a-z0-9_]{1,63}$/.test(strategyId)) return;
    const existingYaml = selected ? yamlText : undefined;
    setGenerating(true);
    setAttempts([]);
    setExpandedAttempt(null);
    setYamlText("");
    streamingAttemptRef.current = 0;
    try {
      const result = await generateValidatedSpec({
        kind: "strategy",
        specId: strategyId,
        description: description.trim(),
        existingYaml,
        onAttempt: (attempt) => setAttempts((prev) => [...prev, attempt]),
        onChunk: (attempt, chunk) => {
          // A new attempt starting replaces the editor's content instead of
          // appending to the previous attempt's draft.
          if (attempt !== streamingAttemptRef.current) {
            streamingAttemptRef.current = attempt;
            setYamlText(chunk);
          } else {
            setYamlText((prev) => prev + chunk);
          }
        },
      });
      setYamlText(result.finalText);
    } finally {
      setGenerating(false);
    }
  }

  async function run() {
    if (!strategyId) return;
    setRunning(true);
    setOutput("");
    setResult(null);
    const args = runMode === "backtest"
      ? ["backtest", strategyId, "--start", start, "--cash", cash]
      : ["shadow-sleeve", strategyId];
    const { output: fullOutput } = await window.electronAPI.runQuorumCommand(args, (chunk) => {
      setOutput((prev) => prev + chunk);
    });
    const marker = runMode === "backtest" ? "BACKTEST_RESULT" : "SHADOW_RESULT";
    const match = fullOutput.match(new RegExp(`---${marker}---(.*?)---${marker}---`, "s"));
    if (match) {
      try {
        setResult(JSON.parse(match[1]));
      } catch {
        // Strategy failed validation/load before reaching the result
        // marker — the streamed output above already shows the error.
      }
    }
    setRunning(false);
  }

  if (!AVAILABLE) return null;

  return (
    <div className="rounded-lg border bg-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Strategy lab</h3>
        <select
          value={selected}
          onChange={(e) => loadExisting(e.target.value)}
          className="text-xs font-mono rounded-md border bg-background px-2 py-1.5"
        >
          <option value="">+ New strategy</option>
          {strategies.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-muted-foreground uppercase tracking-wider shrink-0">
              strategy_id (filename)
            </label>
            <input
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value.trim())}
              placeholder="my_strategy"
              className="flex-1 text-xs font-mono rounded-md border bg-background px-2 py-1"
            />
            <button
              onClick={save}
              disabled={saving || !/^[a-z][a-z0-9_]{1,63}$/.test(strategyId)}
              className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded bg-accent text-accent-foreground disabled:opacity-50"
            >
              <Save className="w-3 h-3" /> Save
            </button>
          </div>

          {GENERATE_AVAILABLE && (
            <div className="flex items-center gap-2">
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && generate()}
                placeholder={selected
                  ? "Describe how to change this strategy..."
                  : "Describe a strategy idea in plain English, e.g. \"long semis when the sector's above its 50-day average\"..."}
                disabled={generating}
                className="flex-1 text-xs rounded-md border bg-background px-2 py-1.5 outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
              />
              <button
                onClick={generate}
                disabled={generating || !description.trim() || !/^[a-z][a-z0-9_]{1,63}$/.test(strategyId)}
                title="Claude reads the schema + an example, writes the YAML below for you to review"
                className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded bg-accent text-accent-foreground disabled:opacity-50 shrink-0"
              >
                <Sparkles className="w-3 h-3" /> {generating ? "Writing..." : "Generate"}
              </button>
            </div>
          )}

          {attempts.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 flex-wrap">
                {attempts.map((a) => (
                  <button
                    key={a.attempt}
                    onClick={() => setExpandedAttempt(expandedAttempt === a.attempt ? null : a.attempt)}
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
                <pre className="text-[10px] font-mono bg-muted/40 rounded-md p-2 max-h-32 overflow-y-auto whitespace-pre-wrap break-words">
                  {attempts.find((a) => a.attempt === expandedAttempt)?.errors.join("\n") || "Passed validation."}
                </pre>
              )}
            </div>
          )}

          <textarea
            value={yamlText}
            onChange={(e) => setYamlText(e.target.value)}
            spellCheck={false}
            placeholder="Or write/paste YAML directly."
            className="w-full h-72 text-[11px] font-mono rounded-md border bg-background p-2 resize-y"
          />
          <p className="text-[10px] text-muted-foreground">
            Review before saving — Claude's draft is a starting point, not a guarantee of a valid or good strategy.
          </p>

          {saveMsg && (
            <p className={cn("text-[11px]", saveMsg.ok ? "text-profit" : "text-loss")}>{saveMsg.text}</p>
          )}
          {!/^[a-z][a-z0-9_]{1,63}$/.test(strategyId) && strategyId.length > 0 && (
            <p className="text-[11px] text-loss">
              strategy_id must start with a letter and contain only lowercase letters, digits, underscores.
            </p>
          )}
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-1.5">
            <ModeButton active={runMode === "backtest"} onClick={() => setRunMode("backtest")}>Backtest</ModeButton>
            <ModeButton active={runMode === "shadow"} onClick={() => setRunMode("shadow")}>Shadow sleeve</ModeButton>
          </div>

          {runMode === "backtest" && (
            <div className="flex items-center gap-2">
              <input
                type="date"
                value={start}
                onChange={(e) => setStart(e.target.value)}
                className="flex-1 text-[11px] font-mono rounded-md border bg-background px-2 py-1"
              />
              <input
                type="number"
                value={cash}
                onChange={(e) => setCash(e.target.value)}
                className="w-24 text-[11px] font-mono rounded-md border bg-background px-2 py-1"
              />
            </div>
          )}

          <button
            onClick={run}
            disabled={running || !strategyId}
            className="w-full inline-flex items-center justify-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded bg-accent text-accent-foreground disabled:opacity-50"
          >
            <Play className="w-3 h-3" /> {running ? "Running..." : `Run ${runMode === "backtest" ? "backtest" : "shadow sleeve"}`}
          </button>

          {result && <ResultCard result={result} onOpenRun={onOpenRun} />}
        </div>
      </div>

      {output && (
        <pre className="text-[10px] font-mono bg-muted/40 rounded-md p-2 max-h-48 overflow-y-auto whitespace-pre-wrap break-words">
          {output}
        </pre>
      )}
    </div>
  );
}

function ModeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "text-[11px] font-medium px-2.5 py-1 rounded-full transition-colors",
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"
      )}
    >
      {children}
    </button>
  );
}

function ResultCard({ result, onOpenRun }: { result: BacktestResult | ShadowResult; onOpenRun: (runId: string) => void }) {
  const isBacktest = "gate_passed" in result;

  return (
    <div className="rounded-md border bg-muted/40 p-2.5 space-y-1.5 text-[11px]">
      {isBacktest && (
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Gate</span>
          <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", gateColor((result as BacktestResult).gate_passed))}>
            {(result as BacktestResult).gate_passed === null ? "N/A" : (result as BacktestResult).gate_passed ? "PASS" : "FAIL"}
          </span>
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">Final equity</span>
        <span className="font-mono">{formatUsd(result.final_equity)}</span>
      </div>
      {isBacktest && (
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Total return</span>
          <span className="font-mono">{formatPct((result as BacktestResult).total_return)}</span>
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground">Trades</span>
        <span className="font-mono">{result.n_trades}</span>
      </div>
      {isBacktest && (result as BacktestResult).sharpe != null && (
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Sharpe</span>
          <span className="font-mono">{(result as BacktestResult).sharpe!.toFixed(2)}</span>
        </div>
      )}
      {result.run_id && (
        <button
          onClick={() => onOpenRun(result.run_id!)}
          className="w-full text-center text-[11px] font-medium text-accent-foreground hover:underline pt-1"
        >
          View in Activity →
        </button>
      )}
    </div>
  );
}
