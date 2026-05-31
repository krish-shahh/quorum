import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchSectors, fetchInsiders, fetchCongress } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tab = "sectors" | "insiders" | "congress";

export default function ScansPanel() {
  const [tab, setTab] = useState<Tab>("sectors");

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center gap-1 mb-3">
        {(["sectors", "insiders", "congress"] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={cn(
              "text-xs font-medium px-3 py-1 rounded",
              tab === t ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"
            )}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === "sectors" && <SectorsContent />}
      {tab === "insiders" && <InsidersContent />}
      {tab === "congress" && <CongressContent />}
    </div>
  );
}

function SectorsContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["scans", "sectors"],
    queryFn: fetchSectors,
    staleTime: 120_000,
  });

  if (isLoading) return <Loading />;
  if (!data?.sectors?.length) return <Empty msg="No sector data" />;

  return (
    <div>
      <p className="text-xs text-muted-foreground mb-2">
        Rotation: <span className="font-medium">{(data as any).direction}</span>
      </p>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b">
            <th className="text-left py-1 font-medium text-muted-foreground">Sector</th>
            <th className="text-left py-1 font-medium text-muted-foreground">ETF</th>
            <th className="text-right py-1 font-medium text-muted-foreground">1M Return</th>
            <th className="text-right py-1 font-medium text-muted-foreground">Rel. Strength</th>
          </tr>
        </thead>
        <tbody>
          {(data.sectors as any[]).map((s: any) => (
            <tr key={s.name} className="border-b last:border-0">
              <td className="py-1.5">{s.name}</td>
              <td className="py-1.5 font-mono">{s.etf}</td>
              <td className={cn("text-right py-1.5 font-mono", s.return_1m >= 0 ? "text-green-600" : "text-red-600")}>
                {s.return_1m > 0 ? "+" : ""}{s.return_1m}%
              </td>
              <td className={cn("text-right py-1.5 font-mono", s.relative_1m >= 0 ? "text-green-600" : "text-red-600")}>
                {s.relative_1m > 0 ? "+" : ""}{s.relative_1m}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InsidersContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["scans", "insiders"],
    queryFn: fetchInsiders,
    staleTime: 120_000,
  });

  if (isLoading) return <Loading />;
  if (!data?.clusters?.length) return <Empty msg="No insider clusters detected" />;

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b">
          <th className="text-left py-1 font-medium text-muted-foreground">Ticker</th>
          <th className="text-left py-1 font-medium text-muted-foreground">Direction</th>
          <th className="text-right py-1 font-medium text-muted-foreground">Insiders</th>
          <th className="text-left py-1 font-medium text-muted-foreground">Window</th>
        </tr>
      </thead>
      <tbody>
        {(data.clusters as any[]).map((c: any) => (
          <tr key={c.ticker} className="border-b last:border-0">
            <td className="py-1.5 font-mono font-medium">{c.ticker}</td>
            <td className="py-1.5">
              <span className={cn("px-1.5 py-0.5 rounded-full text-[10px]",
                c.direction === "buy" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
              )}>
                {c.direction}
              </span>
            </td>
            <td className="text-right py-1.5">{c.insider_count}</td>
            <td className="py-1.5 text-muted-foreground">{c.window}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CongressContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["scans", "congress"],
    queryFn: fetchCongress,
    staleTime: 120_000,
  });

  if (isLoading) return <Loading />;
  if (!data?.trades?.length) return <Empty msg="No recent congressional trades" />;

  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="border-b">
          <th className="text-left py-1 font-medium text-muted-foreground">Date</th>
          <th className="text-left py-1 font-medium text-muted-foreground">Member</th>
          <th className="text-left py-1 font-medium text-muted-foreground">Ticker</th>
          <th className="text-left py-1 font-medium text-muted-foreground">Type</th>
          <th className="text-left py-1 font-medium text-muted-foreground">Amount</th>
        </tr>
      </thead>
      <tbody>
        {(data.trades as any[]).slice(0, 15).map((t: any, i: number) => (
          <tr key={i} className="border-b last:border-0">
            <td className="py-1.5 text-muted-foreground">{t.date}</td>
            <td className="py-1.5">{t.member}</td>
            <td className="py-1.5 font-mono font-medium">{t.ticker}</td>
            <td className="py-1.5">
              <span className={cn("px-1.5 py-0.5 rounded-full text-[10px]",
                t.type?.toLowerCase() === "purchase" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
              )}>
                {t.type}
              </span>
            </td>
            <td className="py-1.5 text-muted-foreground">{t.amount}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Loading() {
  return <p className="text-xs text-muted-foreground py-4">Loading...</p>;
}

function Empty({ msg }: { msg: string }) {
  return <p className="text-xs text-muted-foreground py-4">{msg}</p>;
}
