import React from "react";
import { Routes, Route, Link, useLocation, useNavigate } from "react-router-dom";
import Hero from "./components/Hero";
import Top3 from "./components/Top3";
import SectionCard from "./components/SectionCard";
import { loadWeeksIndex, loadWeekSelection, loadWeekSummary } from "./lib/parse";
import type { WeekMeta } from "./lib/parse";

function Page({ kind }: { kind: "blogs" | "hands" }) {
  const [weeks, setWeeks] = React.useState<WeekMeta[]>([]);
  const [currentWeek, setCurrentWeek] = React.useState<WeekMeta | null>(null);
  const [selection, setSelection] = React.useState<any>(null);
  const [top3, setTop3] = React.useState<any[]>([]);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    (async () => {
      try {
        const ws = await loadWeeksIndex();
        if (!ws?.length) throw new Error("weeks.json vide ou introuvable");
        setWeeks(ws);
        const latest = ws[0];
        setCurrentWeek(latest);

        // charge sélection + top3 extrait du summary (optionnel)
        const sel = await loadWeekSelection(latest, kind);
        setSelection(sel);

        const { top3 } = await loadWeekSummary(latest);
        setTop3(top3);
      } catch (e: any) {
        setError(e.message);
      }
    })();
  }, [kind]);

  if (error) return <div className="p-6 text-red-600">{error}</div>;
  if (!selection || !currentWeek) return <div className="p-6">Chargement…</div>;

  // Construire un top3 fallback depuis la sélection si besoin
  const all = Object.values(selection).flat() as any[];
  const fallbackTop3 = all
    .slice()
    .sort((a, b) => (b.llm_score ?? b.score ?? 0) - (a.llm_score ?? a.score ?? 0))
    .slice(0, 3)
    .map((it) => ({
      title: it.title,
      url: it.url,
      source: it.source_name,
      date: it.published_ts ? new Date(it.published_ts * 1000).toISOString().slice(0, 10) : undefined,
      score: it.llm_score ?? it.score ?? "?"
    }));

  return (
    <div className="min-h-screen bg-neutral-50">
      <SiteTabs />

      <Hero
        weekLabel={currentWeek.week}
        dateRange={currentWeek.range || ""}
        weeks={weeks.map((w) => w.week)}
        onWeekChange={async (weekId) => {
          const w = weeks.find((x) => x.week === weekId)!;
          setCurrentWeek(w);
          const sel = await loadWeekSelection(w, kind);
          setSelection(sel);
          try {
            const { top3 } = await loadWeekSummary(w);
            setTop3(top3);
          } catch {
            setTop3([]);
          }
        }}
      />

      <main className="max-w-6xl mx-auto px-4 py-8 space-y-8">
        <Top3 items={top3.length ? top3 : fallbackTop3} />

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {Object.entries(selection).map(([cat, items]: any) => (
            <SectionCard
              key={cat}
              title={cat}
              bullets={(items || []).map((it: any) => ({
                title: it.title,
                url: it.url,
                source: it.source_name,
                score: it.llm_score ?? it.score ?? "?"
              }))}
            />
          ))}
        </div>
      </main>
    </div>
  );
}

function SiteTabs() {
  const loc = useLocation();
  const isHands = loc.pathname.includes("hands");

  return (
    <div className="w-full border-b bg-white">
      <div className="max-w-6xl mx-auto px-4 flex gap-6">
        <Link
          to="/"
          className={`py-3 text-sm font-semibold ${!isHands ? "border-b-2 border-black" : "text-neutral-500 hover:text-black"}`}
        >
          Blogs
        </Link>
        <Link
          to="/hands-on"
          className={`py-3 text-sm font-semibold ${isHands ? "border-b-2 border-black" : "text-neutral-500 hover:text-black"}`}
        >
          Hands-on / REX
        </Link>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Page kind="blogs" />} />
      <Route path="/hands-on" element={<Page kind="hands" />} />
    </Routes>
  );
}