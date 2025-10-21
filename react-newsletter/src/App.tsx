import React from "react";
import Hero from "./components/Hero";
import Top3 from "./components/Top3";
import SectionCard from "./components/SectionCard";
import { loadWeeksIndex, loadWeekSummary } from "./lib/parse";
import type { WeekMeta } from "./lib/parse";

export default function App() {
  const [weeks, setWeeks] = React.useState<WeekMeta[]>([]);
  const [currentWeek, setCurrentWeek] = React.useState<WeekMeta | null>(null);
  const [data, setData] = React.useState<{ top3: any[]; sections: any[] } | null>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    (async () => {
      try {
        const ws = await loadWeeksIndex();
        if (!ws?.length) throw new Error("weeks.json vide ou introuvable");
        setWeeks(ws);
        const latest = ws[0];
        setCurrentWeek(latest);
        setData(await loadWeekSummary(latest)); // { top3, sections }
      } catch (e: any) {
        setError(e.message ?? String(e));
      }
    })();
  }, []);

  if (error) return <div className="p-6 text-red-600">{error}</div>;
  if (!data || !currentWeek) return <div className="p-6">Chargement…</div>;

  // top3 vient déjà parsé depuis ai_summary.md
  const top3 = data.top3.map((t) => ({
    title: t.title,
    url: t.url,
    source: t.source,
    date: t.date,
    score: t.score,
  }));

  return (
    <div className="min-h-screen bg-neutral-50">
      <Hero
        weekLabel={currentWeek.week}
        dateRange={currentWeek.range || ""}
        weeks={weeks.map((w) => w.week)}
        onWeekChange={async (weekId) => {
          try {
            const w = weeks.find((x) => x.week === weekId)!;
            setCurrentWeek(w);
            setData(await loadWeekSummary(w)); // recharge le md pour la semaine choisie
          } catch (e: any) {
            setError(e.message ?? String(e));
          }
        }}
      />

      <main className="max-w-6xl mx-auto px-4 py-8 space-y-8">
        <Top3 items={top3} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {data.sections.map((sec: any) => (
            <SectionCard
              key={sec.title}
              title={sec.title}
              // ✅ SectionCard attend "bullets", pas "items"
              bullets={sec.items.map((it: any) => ({
                title: it.title,
                url: it.url,
                source: it.source,
                score: it.score,
              }))}
            />
          ))}
        </div>
      </main>
    </div>
  );
}