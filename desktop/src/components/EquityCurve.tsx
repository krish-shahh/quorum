import { useEffect, useRef, useState, useCallback } from "react";
import { createChart, ColorType, CandlestickSeries, HistogramSeries } from "lightweight-charts";
import { Home } from "lucide-react";
import { fetchChart, type CandleData, type BookData } from "@/lib/api";
import { themeColor } from "@/lib/utils";
import { AreaChart } from "@/components/dither-kit/area-chart";
import { Area } from "@/components/dither-kit/area";
import { Grid } from "@/components/dither-kit/grid";
import { XAxis } from "@/components/dither-kit/x-axis";
import { YAxis } from "@/components/dither-kit/y-axis";
import { Tooltip as DitherTooltip } from "@/components/dither-kit/tooltip";
import type { ChartConfig } from "@/components/dither-kit/chart-context";
import CommentButton from "@/components/CommentButton";

interface Props {
  equity: { time: string; value: number }[];
  books: BookData[];
}

export default function EquityCurve({ equity, books }: Props) {
  const [selected, setSelected] = useState<string>("portfolio");
  const isTicker = selected !== "portfolio";

  // Build grouped dropdown: Portfolio > Books (sub-portfolios) > Individual tickers by book
  const bookNames = books.map((b) => b.name);

  return (
    <div className="group relative rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">{selected === "portfolio" ? "Portfolio" : selected}</h3>
        <div className="flex items-center gap-1">
          <CommentButton anchorType="chart_series" anchor={{ view: "overview", chart: "equity_curve", scope: selected }} />
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="text-xs bg-muted border-none rounded px-2 py-1 font-mono outline-none cursor-pointer"
        >
          <option value="portfolio">Portfolio</option>
          {books.length > 0 && (
            <optgroup label="Books">
              {bookNames.map((name) => (
                <option key={`book:${name}`} value={`book:${name}`}>{name}</option>
              ))}
            </optgroup>
          )}
          {books.map((book) => (
            <optgroup key={book.name} label={book.name}>
              {book.positions.map((p) => (
                <option key={p.ticker} value={p.ticker}>{p.ticker}</option>
              ))}
            </optgroup>
          ))}
        </select>
        </div>
      </div>

      {selected === "portfolio" ? (
        <PortfolioChart equity={equity} />
      ) : isTicker && !selected.startsWith("book:") ? (
        <TickerChart key={selected} ticker={selected} />
      ) : (
        <PortfolioChart equity={equity} />
      )}
    </div>
  );
}

// ── Portfolio / Book: dither area chart ──

function formatUsd(v: number): string {
  return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function PortfolioChart({ equity }: { equity: { time: string; value: number }[] }) {
  const points = equity.filter((p) => p.time !== "Start" && p.time.includes("-"));

  // Deduplicate by date — keep last value per day
  const byDate = new Map<string, number>();
  for (const p of points) {
    byDate.set(p.time.slice(0, 10), p.value);
  }
  const data = Array.from(byDate.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([time, value]) => ({ time, value }));

  if (data.length < 2) {
    return <p className="text-xs text-muted-foreground text-center py-8">Insufficient equity data</p>;
  }

  const positive = data[data.length - 1].value >= data[0].value;
  const config: ChartConfig = { value: { label: "Equity", color: positive ? "green" : "red" } };

  return (
    <div className="h-[180px]">
      <AreaChart data={data} config={config}>
        <Grid />
        <XAxis dataKey="time" tickFormatter={(v) => String(v).slice(5)} />
        <YAxis tickFormatter={formatUsd} />
        <Area dataKey="value" />
        <DitherTooltip valueFormatter={formatUsd} />
      </AreaChart>
    </div>
  );
}

// ── Ticker: candlestick + volume (pure price data, no trade overlays) ──

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
        const chartRes = await fetchChart(ticker, 90);

        if (cancelled || !container) return;

        const candles: CandleData[] = chartRes.candles || [];
        if (candles.length === 0) { setLoading(false); return; }

        if (chartRef.current) {
          chartRef.current.remove();
          chartRef.current = null;
        }

        const gridColor = themeColor("--border");
        const chart = createChart(container, {
          layout: {
            background: { type: ColorType.Solid, color: "transparent" },
            textColor: themeColor("--muted-foreground"),
            fontSize: 11,
            fontFamily: "JetBrains Mono, monospace",
            attributionLogo: false,
          },
          grid: {
            vertLines: { color: gridColor },
            horzLines: { color: gridColor },
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

        // Volume
        const volumeSeries = chart.addSeries(HistogramSeries, {
          priceFormat: { type: "volume" },
          priceScaleId: "",
          lastValueVisible: false,
        });
        volumeSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.85, bottom: 0 },
        });
        const upColor = themeColor("--profit");
        const downColor = themeColor("--loss");
        volumeSeries.setData(
          candles.map((c) => ({
            time: c.time,
            value: c.volume,
            color: c.close >= c.open ? themeColor("--profit", 0.25) : themeColor("--loss", 0.25),
          }))
        );

        // Candlestick
        const candleSeries = chart.addSeries(CandlestickSeries, {
          upColor,
          downColor,
          borderUpColor: upColor,
          borderDownColor: downColor,
          wickUpColor: upColor,
          wickDownColor: downColor,
        });
        candleSeries.setData(candles);

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
