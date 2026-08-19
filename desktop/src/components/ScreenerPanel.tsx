import { useEffect, useRef, useState } from "react";
import { ListPlus, Play, Save, Sparkles } from "lucide-react";
import { cn, formatPct } from "@/lib/utils";
import { fetchScreens, postWatchlist, runScreen, type ScreenRunResult } from "@/lib/api";
import { generateValidatedSpec, type SpecAttempt } from "@/lib/codegen";

const AVAILABLE = typeof window !== "undefined" && !!window.electronAPI?.flaskPort;
const EDIT_AVAILABLE = typeof window !== "undefined" && !!window.electronAPI?.saveStrategy;
const GENERATE_AVAILABLE = typeof window !== "undefined" && !!window.electronAPI?.generateSpecYaml;

const ATTEMPT_GLYPHS = ["①", "②", "③"];

const TEMPLATE = `# screen_id must match this file's name (screens/<screen_id>.yaml).
# Closed-grammar schema (quorum/screen/schema.py) — every field below is
# validated on load; an unknown field or metric name fails fast with a
# clear error the moment you run it, not silently. A screen never trades
# — it ranks a universe and returns a table, nothing more.
screen_id: my_screen
version: "0.1"
description: >
  What this screen ranks and why, in a sentence or two.

universe:
  source: tag           # "tag" (from quorum/strategy/universe.py's TMT tags) or "static"
  tags: [mega_cap_platforms, semis_design]
  # static: tickers: [AAPL, MSFT]

filters:
  - metric: avg_dollar_volume_20d
    op: gt
    value: 5000000

rank:
  by:
    - metric: roe
      weight: 1.0
      direction: desc
  within: universe        # "universe" or "bucket" (rank within each tag bucket separately)
  limit: 20
`;

/** Create/run workbench for git-committed screens/*.yaml — a sibling of
 * StrategyLab, not an extension of it: a screen never trades. Research
 * only, no path to execute_paper_trade. Result rows can be selected and
 * sent to the watchlist or seeded into a new Strategy Lab draft. */
export default function ScreenerPanel({ onSendToStrategyLab }: { onSendToStrategyLab: (tickers: string[]) => void }) {
  const [screens, setScreens] = useState<string[]>([]);
  const [selected, setSelected] = useState(""); // "" = new screen
  const [screenId, setScreenId] = useState("");
  const [yamlText, setYamlText] = useState(TEMPLATE);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ text: string; ok: boolean } | null>(null);

  const [description, setDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [attempts, setAttempts] = useState<SpecAttempt[]>([]);
  const [expandedAttempt, setExpandedAttempt] = useState<number | null>(null);
  const streamingAttemptRef = useRef(0);

  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ScreenRunResult | null>(null);
  const [runError, setRunError] = useState<string | null>(null);

  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [addingToWatchlist, setAddingToWatchlist] = useState(false);
  const [watchlistMsg, setWatchlistMsg] = useState<string | null>(null);

  useEffect(() => {
    if (AVAILABLE) refreshScreens();
  }, []);

  async function refreshScreens() {
    setScreens((await fetchScreens()).screens);
  }

  async function loadExisting(id: string) {
    setSelected(id);
    setSaveMsg(null);
    setResult(null);
    if (!id) {
      setScreenId("");
      setYamlText(TEMPLATE);
      return;
    }
    setScreenId(id);
    const content = await window.electronAPI.readStrategyFile(id, "screen");
    setYamlText(content ?? TEMPLATE);
  }

  async function save() {
    setSaving(true);
    setSaveMsg(null);
    try {
      const res = await window.electronAPI.saveStrategy(screenId, yamlText, "screen");
      if (res.ok) {
        setSaveMsg({ text: `Saved screens/${screenId}.yaml`, ok: true });
        await refreshScreens();
        setSelected(screenId);
      } else {
        setSaveMsg({ text: res.error ?? "Save failed.", ok: false });
      }
    } finally {
      setSaving(false);
    }
  }

  async function generate() {
    if (!description.trim() || !/^[a-z][a-z0-9_]{1,63}$/.test(screenId)) return;
    const existingYaml = selected ? yamlText : undefined;
    setGenerating(true);
    setAttempts([]);
    setExpandedAttempt(null);
    setYamlText("");
    streamingAttemptRef.current = 0;
    try {
      const result = await generateValidatedSpec({
        kind: "screen",
        specId: screenId,
        description: description.trim(),
        existingYaml,
        onAttempt: (attempt) => setAttempts((prev) => [...prev, attempt]),
        onChunk: (attempt, chunk) => {
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
    if (!selected) return;
    setRunning(true);
    setRunError(null);
    setChecked(new Set());
    setWatchlistMsg(null);
    try {
      setResult(await runScreen(selected));
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  function toggleChecked(symbol: string) {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }

  async function addSelectedToWatchlist() {
    if (checked.size === 0) return;
    setAddingToWatchlist(true);
    setWatchlistMsg(null);
    try {
      const res = await postWatchlist([...checked]);
      setWatchlistMsg(`Added to watchlist (${res.tickers.length} total).`);
    } catch (e) {
      setWatchlistMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setAddingToWatchlist(false);
    }
  }

  function sendSelectedToStrategyLab() {
    if (checked.size === 0) return;
    onSendToStrategyLab([...checked]);
  }

  if (!AVAILABLE) return null;

  const metricColumns = result?.rows.length ? Object.keys(result.rows[0].metrics) : [];

  return (
    <div className="rounded-lg border bg-card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Screener</h3>
        <select
          value={selected}
          onChange={(e) => loadExisting(e.target.value)}
          className="text-xs font-mono rounded-md border bg-background px-2 py-1.5"
        >
          <option value="">+ New screen</option>
          {screens.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
      </div>

      {EDIT_AVAILABLE && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <label className="text-[10px] text-muted-foreground uppercase tracking-wider shrink-0">
              screen_id (filename)
            </label>
            <input
              value={screenId}
              onChange={(e) => setScreenId(e.target.value.trim())}
              placeholder="my_screen"
              className="flex-1 text-xs font-mono rounded-md border bg-background px-2 py-1"
            />
            <button
              onClick={save}
              disabled={saving || !/^[a-z][a-z0-9_]{1,63}$/.test(screenId)}
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
                  ? "Describe how to change this screen..."
                  : "Describe a screen in plain English, e.g. \"rank semis by ROE and 20-day momentum, filtered to liquid names\"..."}
                disabled={generating}
                className="flex-1 text-xs rounded-md border bg-background px-2 py-1.5 outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
              />
              <button
                onClick={generate}
                disabled={generating || !description.trim() || !/^[a-z][a-z0-9_]{1,63}$/.test(screenId)}
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
            className="w-full h-56 text-[11px] font-mono rounded-md border bg-background p-2 resize-y"
          />
          <p className="text-[10px] text-muted-foreground">
            Review before saving — Claude's draft is a starting point, not a guarantee of a valid or good screen.
          </p>

          {saveMsg && (
            <p className={cn("text-[11px]", saveMsg.ok ? "text-profit" : "text-loss")}>{saveMsg.text}</p>
          )}
          {!/^[a-z][a-z0-9_]{1,63}$/.test(screenId) && screenId.length > 0 && (
            <p className="text-[11px] text-loss">
              screen_id must start with a letter and contain only lowercase letters, digits, underscores.
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        <button
          onClick={run}
          disabled={running || !selected}
          title={selected ? undefined : "Save this screen first — Run reads from the saved file"}
          className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded bg-accent text-accent-foreground disabled:opacity-50"
        >
          <Play className="w-3 h-3" /> {running ? "Running..." : "Run"}
        </button>
      </div>

      {runError && <p className="text-[11px] text-loss">{runError}</p>}

      {result && (
        <div className="space-y-2">
          <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
            <span>Universe: {result.universe_size}</span>
            <span>As of {result.as_of}</span>
            {result.fetched.ohlcv && <span>price data fetched</span>}
            {result.fetched.fundamentals && <span>fundamentals fetched</span>}
          </div>

          {result.warnings.length > 0 && (
            <div className="text-[10px] text-loss space-y-0.5">
              {result.warnings.map((w) => <div key={w}>{w}</div>)}
            </div>
          )}

          {result.rows.length === 0 ? (
            <p className="text-xs text-muted-foreground">No symbols passed the filters.</p>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <button
                  onClick={addSelectedToWatchlist}
                  disabled={checked.size === 0 || addingToWatchlist}
                  className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded bg-accent text-accent-foreground disabled:opacity-50"
                >
                  <ListPlus className="w-3 h-3" /> Add {checked.size > 0 ? checked.size : ""} to watchlist
                </button>
                <button
                  onClick={sendSelectedToStrategyLab}
                  disabled={checked.size === 0}
                  title="Seed a new strategy's universe with the selected tickers"
                  className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded border disabled:opacity-50"
                >
                  <Sparkles className="w-3 h-3" /> Send {checked.size > 0 ? checked.size : ""} to Strategy Lab
                </button>
                {watchlistMsg && <span className="text-[11px] text-muted-foreground">{watchlistMsg}</span>}
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b bg-muted/50">
                      <th className="px-3 py-2 w-8"></th>
                      <th className="text-left px-3 py-2 font-medium text-muted-foreground">#</th>
                      <th className="text-left px-3 py-2 font-medium text-muted-foreground">Symbol</th>
                      <th className="text-right px-3 py-2 font-medium text-muted-foreground">Score</th>
                      <th className="text-right px-3 py-2 font-medium text-muted-foreground">Coverage</th>
                      {metricColumns.map((m) => (
                        <th key={m} className="text-right px-3 py-2 font-medium text-muted-foreground">{m}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.rows.map((row, i) => (
                      <tr key={row.symbol} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                        <td className="px-3 py-2">
                          <input
                            type="checkbox"
                            checked={checked.has(row.symbol)}
                            onChange={() => toggleChecked(row.symbol)}
                          />
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">{i + 1}</td>
                        <td className="px-3 py-2 font-mono font-medium">{row.symbol}</td>
                        <td className="px-3 py-2 text-right font-mono">
                          {row.rank_score != null ? row.rank_score.toFixed(3) : "—"}
                        </td>
                        <td className="px-3 py-2 text-right font-mono">{formatPct(row.coverage)}</td>
                        {metricColumns.map((m) => (
                          <td key={m} className="px-3 py-2 text-right font-mono text-muted-foreground">
                            {row.metrics[m] != null ? row.metrics[m]!.toFixed(2) : "—"}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
