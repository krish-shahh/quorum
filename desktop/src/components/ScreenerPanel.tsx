import { useEffect, useState } from "react";
import { Play } from "lucide-react";
import { formatPct } from "@/lib/utils";
import { fetchScreens, runScreen, type ScreenRunResult } from "@/lib/api";

const AVAILABLE = typeof window !== "undefined" && !!window.electronAPI?.flaskPort;

/** Run a git-committed screens/*.yaml screen and show its ranked table.
 * Research only — a screen result carries no weight/direction, and
 * nothing here reaches execute_paper_trade. Selecting rows and sending
 * them to the watchlist or Strategy Lab is Feature B6, not built yet. */
export default function ScreenerPanel() {
  const [screens, setScreens] = useState<string[]>([]);
  const [selected, setSelected] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ScreenRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchScreens()
      .then((r) => {
        setScreens(r.screens);
        setSelected((prev) => prev || r.screens[0] || "");
      })
      .catch(() => {});
  }, []);

  async function run() {
    if (!selected) return;
    setRunning(true);
    setError(null);
    try {
      setResult(await runScreen(selected));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  if (!AVAILABLE) return null;

  const metricColumns = result?.rows.length ? Object.keys(result.rows[0].metrics) : [];

  return (
    <div className="rounded-lg border bg-card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">Screener</h3>
        <div className="flex items-center gap-2">
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            disabled={screens.length === 0}
            className="text-xs font-mono rounded-md border bg-background px-2 py-1.5 disabled:opacity-50"
          >
            {screens.length === 0 && <option value="">No screens found</option>}
            {screens.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <button
            onClick={run}
            disabled={running || !selected}
            className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded bg-accent text-accent-foreground disabled:opacity-50"
          >
            <Play className="w-3 h-3" /> {running ? "Running..." : "Run"}
          </button>
        </div>
      </div>

      {error && <p className="text-[11px] text-loss">{error}</p>}

      {result && (
        <>
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
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b bg-muted/50">
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
          )}
        </>
      )}
    </div>
  );
}
