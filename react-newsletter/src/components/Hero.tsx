// src/components/Hero.tsx
// Header premium: marque, semaine, sous-titre, sélecteur.

import Chip from "./Chip";

export default function Hero({
  weekLabel,
  dateRange,
  weeks,
  onWeekChange,
}: {
  weekLabel: string;
  dateRange?: string;
  weeks: string[];
  onWeekChange: (w: string) => void;
}) {
  return (
    <header className="bg-white border-b">
      <div className="max-w-6xl mx-auto px-4 py-6 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="text-3xl font-serif tracking-wide">VEILLE</div>
          <Chip>MAG</Chip>
        </div>
        <div className="flex items-center gap-3">
          <label className="text-sm text-neutral-500">Semaine</label>
          <select
            className="border rounded-md px-3 py-2 text-sm bg-neutral-50"
            defaultValue={weekLabel}
            onChange={(e) => onWeekChange(e.target.value)}
          >
            {weeks.map((w) => (
              <option key={w} value={w}>{w}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="max-w-6xl mx-auto px-4 pb-6">
        <div className="bg-neutral-50 border rounded-2xl p-6">
          <div className="text-xs font-semibold tracking-widest">Semaine {weekLabel}</div>
          <h1 className="text-2xl md:text-3xl font-bold mt-2">
            Data • Analytics • ML — la semaine en un coup d’œil
          </h1>
          {dateRange && <p className="text-neutral-600 mt-2">{dateRange}</p>}
          <div className="h-1 bg-accent w-24 mt-4 rounded-full" />
        </div>
      </div>
    </header>
  );
}