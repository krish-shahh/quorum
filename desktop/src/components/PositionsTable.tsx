import { useState, useMemo } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import { cn, formatUsd, formatSignedUsd, formatSignedPct, signalColor } from "@/lib/utils";
import type { Position, BookData } from "@/lib/api";

interface Props {
  positions: Position[];
  books: BookData[];
  onSelectTicker: (ticker: string) => void;
}

export default function PositionsTable({ positions, books, onSelectTicker }: Props) {
  const [expandedBooks, setExpandedBooks] = useState<Set<string>>(new Set(books.map(b => b.name)));

  const toggleBook = (name: string) => {
    setExpandedBooks((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  if (positions.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">Positions</h3>
        <p className="text-xs text-muted-foreground">No open positions</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b">
        <h3 className="text-sm font-medium">Positions ({positions.length})</h3>
      </div>
      <div className="divide-y">
        {books.map((book) => {
          const isOpen = expandedBooks.has(book.name);
          return (
            <div key={book.name}>
              {/* Book header row */}
              <button
                onClick={() => toggleBook(book.name)}
                className="w-full flex items-center gap-2 px-4 py-2 text-xs hover:bg-muted/30 transition-colors text-left bg-muted/10"
              >
                {isOpen ? (
                  <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                )}
                <span className="font-medium">{book.name}</span>
                <span className="text-muted-foreground">{book.position_count} position{book.position_count !== 1 ? "s" : ""}</span>
                <div className="ml-auto flex items-center gap-4 font-mono">
                  <span>{formatUsd(book.market_value)}</span>
                  <span className={cn("font-medium", book.unrealized_pnl >= 0 ? "text-green-600" : "text-red-600")}>
                    {formatSignedUsd(book.unrealized_pnl)}
                  </span>
                  <span className="text-muted-foreground w-12 text-right">{book.allocation_pct}%</span>
                </div>
              </button>

              {/* Position rows */}
              {isOpen && (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b bg-muted/5">
                        <th className="text-left px-4 pl-10 py-1.5 font-medium text-muted-foreground">Ticker</th>
                        <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Qty</th>
                        <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Entry</th>
                        <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Mark</th>
                        <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Mkt Value</th>
                        <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">P&L</th>
                        <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Return</th>
                        <th className="text-right px-3 py-1.5 font-medium text-muted-foreground">Weight</th>
                        <th className="text-center px-3 py-1.5 font-medium text-muted-foreground">Signal</th>
                      </tr>
                    </thead>
                    <tbody>
                      {book.positions.map((p) => (
                        <tr
                          key={p.ticker}
                          onClick={() => onSelectTicker(p.ticker)}
                          className="border-b last:border-0 hover:bg-muted/30 cursor-pointer transition-colors"
                        >
                          <td className="px-4 pl-10 py-2.5">
                            <div className="flex items-center gap-2">
                              <span className="font-medium font-mono">{p.ticker}</span>
                              {p.asset_class === "etf_bond" && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600">BOND</span>
                              )}
                              {p.asset_class === "etf_commodity" && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-600">CMDTY</span>
                              )}
                              {p.asset_class === "future" && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-50 text-purple-600">
                                  {p.multiplier}x
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="text-right px-3 py-2.5 font-mono">{p.quantity}</td>
                          <td className="text-right px-3 py-2.5 font-mono">{formatUsd(p.avg_cost)}</td>
                          <td className="text-right px-3 py-2.5 font-mono">{formatUsd(p.last_price)}</td>
                          <td className="text-right px-3 py-2.5 font-mono">{formatUsd(p.market_value)}</td>
                          <td className={cn("text-right px-3 py-2.5 font-mono", p.unrealized_pnl >= 0 ? "text-green-600" : "text-red-600")}>
                            {formatSignedUsd(p.unrealized_pnl)}
                          </td>
                          <td className={cn("text-right px-3 py-2.5 font-mono", p.pct_return >= 0 ? "text-green-600" : "text-red-600")}>
                            {formatSignedPct(p.pct_return)}
                          </td>
                          <td className="text-right px-3 py-2.5 font-mono">{p.weight.toFixed(1)}%</td>
                          <td className="text-center px-3 py-2.5">
                            <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-medium", signalColor(p.signal))}>
                              {p.signal}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
