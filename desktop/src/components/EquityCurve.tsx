import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, ColorType, CandlestickSeries, AreaSeries, HistogramSeries } from "lightweight-charts";
import { Home } from "lucide-react";
import type { CandleData, TradeMarker, Position } from "@/lib/api";

const BASE_URL = "http://localhost:5050";

interface Props {
  equity: { time: string; value: number }[];
  positions: Position[];
}

// Group tickers by book/sector for the dropdown
// Group held positions by book for the dropdown (only show what we own)
function buildTickerGroups(positions: Position[]): Map<string, string[]> {
  const groups = new Map<string, string[]>();
  for (const p of positions) {
    const group = p.book || "Other";
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group)!.push(p.ticker);
  }
  return groups;
}

export default function EquityCurve({ equity, positions }: Props) {
  const [selected, setSelected] = useState<string>("portfolio");
  const isTicker = selected !== "portfolio";
  const groups = buildTickerGroups(positions);

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">
          {isTicker ? selected : "Portfolio Equity"}
        </h3>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="text-xs bg-muted border-none rounded px-2 py-1 font-mono outline-none cursor-pointer"
        >
          <option value="portfolio">Portfolio</option>
          {Array.from(groups.entries()).map(([group, tickers]) => (
            <optgroup key={group} label={group}>
              {tickers.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {isTicker ? (
        <TickerChart key={selected} ticker={selected} />
      ) : (
        <PortfolioChart equity={equity} />
      )}
    </div>
  );
}

// ── Portfolio: lightweight-charts AreaSeries (matches original Chart.js look) ──

function PortfolioChart({ equity }: { equity: { time: string; value: number }[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);

  // All valid points, sequential index as "time" to avoid date dedup issues
  const points = equity.filter((p) => p.time !== "Start" && p.time.includes("-"));

  useEffect(() => {
    const container = containerRef.current;
    if (!container || points.length < 2) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const positive = points[points.length - 1].value >= points[0].value;
    const color = positive ? "#16a34a" : "#dc2626";

    const values = points.map((p) => p.value);
    const minVal = Math.min(...values);
    const maxVal = Math.max(...values);
    const padding = Math.max((maxVal - minVal) * 0.15, 5);

    const chart = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9ca3af",
        fontSize: 10,
        fontFamily: "JetBrains Mono, monospace",
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "#f3f4f6" },
      },
      width: container.clientWidth,
      height: 180,
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.1, bottom: 0.05 },
      },
      leftPriceScale: { visible: false },
      timeScale: {
        borderVisible: false,
      },
      crosshair: {
        horzLine: { visible: true, labelVisible: true },
        vertLine: { visible: true, labelVisible: true },
      },
      handleScroll: false,
      handleScale: false,
    });

    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor: color,
      lineWidth: 2,
      topColor: positive ? "rgba(22,163,74,0.08)" : "rgba(220,38,38,0.08)",
      bottomColor: "transparent",
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 3,
      priceFormat: {
        type: "custom",
        formatter: (v: number) => `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
      },
    });

    // Deduplicate by date — keep last value per day (lightweight-charts needs unique dates)
    const byDate = new Map<string, number>();
    for (const p of points) {
      byDate.set(p.time.slice(0, 10), p.value);
    }
    areaSeries.setData(
      Array.from(byDate.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([time, value]) => ({ time, value }))
    );

    chart.priceScale("right").applyOptions({
      autoScale: true,
    });

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [points]);

  if (points.length < 2) {
    return <p className="text-xs text-muted-foreground text-center py-8">Insufficient equity data</p>;
  }

  return <div ref={containerRef} className="min-h-[180px]" />;
}

// ── Ticker: lightweight-charts candlestick with trade markers ──

function TickerChart({ ticker }: { ticker: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof createChart> | null>(null);
  const [loading, setLoading] = useState(true);

  const handleHome = useCallback(() => chartRef.current?.timeScale().fitContent(), []);

  useEffect(() => {
    let cancelled = false;
    const container = containerRef.current;
    if (!container) return;

    async function load() {
      try {
        const [chartRes, tradeRes] = await Promise.all([
          fetch(`${BASE_URL}/api/v1/chart/${ticker}?days=90`).then((r) => r.json()),
          fetch(`${BASE_URL}/api/v1/trades/${ticker}`).then((r) => r.json()),
        ]);

        if (cancelled || !container) return;

        const candles: CandleData[] = chartRes.candles || [];
        const trades: TradeMarker[] = tradeRes.trades || [];

        if (candles.length === 0) { setLoading(false); return; }

        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }

        const chart = createChart(container, {
          layout: {
            background: { type: ColorType.Solid, color: "transparent" },
            textColor: "#71717a",
            fontSize: 11,
            fontFamily: "JetBrains Mono, monospace",
            attributionLogo: false,
          },
          grid: {
            vertLines: { color: "#f4f4f5" },
            horzLines: { color: "#f4f4f5" },
          },
          width: container.clientWidth,
          height: 280,
          rightPriceScale: {
            borderVisible: false,
            scaleMargins: { top: 0.05, bottom: 0.2 },
          },
          timeScale: { borderVisible: false },
          crosshair: {
            horzLine: { visible: true, labelVisible: true },
            vertLine: { visible: true, labelVisible: true },
          },
        });

        // Volume first
        const volumeSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "",
          lastValueVisible: false,
        });
        volumeSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.85, bottom: 0 },
        });
        volumeSeries.setData(
          candles.map((c) => ({
            time: c.time,
            value: c.volume,
            color: c.close >= c.open ? "rgba(22,163,74,0.25)" : "rgba(220,38,38,0.25)",
          }))
        );

        // Candlestick
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor: "#16a34a",
          downColor: "#dc2626",
          borderUpColor: "#15803d",
          borderDownColor: "#b91c1c",
          wickUpColor: "#16a34a",
          wickDownColor: "#dc2626",
        });
        candleSeries.setData(candles);

        // Trade markers
        if (trades.length > 0) {
          const candleDates = new Set(candles.map((c) => c.time));
          const markers = trades
            .filter((t) => candleDates.has(t.time))
            .map((t) => ({
              time: t.time,
              position: t.side === "buy" ? ("belowBar" as const) : ("aboveBar" as const),
              color: t.side === "buy" ? "#16a34a" : "#dc2626",
              shape: t.side === "buy" ? ("arrowUp" as const) : ("arrowDown" as const),
              text: `${t.side.toUpperCase()} ${t.qty}`,
              size: 1.5,
            }));
          if (markers.length > 0) candleSeries.setMarkers(markers);
        }

        chart.timeScale().fitContent();
        chartRef.current = chart;

        const observer = new ResizeObserver((entries) => {
          for (const entry of entries) {
            chart.applyOptions({ width: entry.contentRect.width });
          }
        });
        observer.observe(container);

        setLoading(false);
      } catch {
        if (!cancelled) setLoading(false);
      }
    }

    load();

    return () => {
      cancelled = true;
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [ticker]);

  return (
    <>
      <div className="relative">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground z-10 bg-card">
            Loading {ticker}...
          </div>
        )}
        <div ref={containerRef} className="min-h-[280px]" />
      </div>
      <div className="flex justify-end mt-2">
        <button
          onClick={handleHome}
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground px-2 py-1 rounded bg-muted/50 hover:bg-muted transition-colors"
        >
          <Home className="w-3 h-3" />
          Reset view
        </button>
      </div>
    </>
  );
}
