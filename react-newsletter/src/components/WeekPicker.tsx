import React from "react";
import type { WeekMeta } from "../lib/parse";

export default function WeekPicker({
  weeks,
  value,
  onChange,
}: {
  weeks: WeekMeta[];
  value?: string;
  onChange: (week: string) => void;
}) {
  return (
    <div className="flex flex-col text-sm">
      <label className="font-medium text-slate-600">Semaine</label>
      <select
        className="mt-1 rounded-md border border-slate-300 bg-white px-3 py-2 shadow-sm hover:border-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {weeks.map((w) => (
          <option key={w.week} value={w.week}>
            {w.week} {w.range ? `— ${w.range}` : ""}
          </option>
        ))}
      </select>
    </div>
  );
}