// src/components/Top3.tsx
// Les trois "unes" de la semaine: gros titre, ruban jaune, grille responsive.

export default function Top3({
  items,
}: { items: { title: string; url?: string; source?: string; score?: number | string }[] }) {
  if (!items || !items.length) return null;
  return (
    <section aria-labelledby="top3" className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="h-2 w-8 bg-accent rounded-full" />
        <h2 id="top3" className="text-sm font-semibold tracking-widest">À LA UNE</h2>
      </div>

      <div className="grid md:grid-cols-3 gap-5">
        {items.slice(0, 3).map((it, i) => (
          <a
            key={i}
            href={it.url}
            target="_blank"
            rel="noreferrer"
            className="group bg-white border rounded-2xl p-6 hover:shadow-xl transition-shadow"
          >
            <p className="text-[11px] tracking-widest font-semibold text-neutral-600 uppercase">
              {it.source || "Source"}{typeof it.score !== "undefined" ? ` · ${it.score}/100` : ""}
            </p>
            <h3 className="mt-2 text-xl font-bold leading-tight group-hover:underline">
              {it.title}
            </h3>
            <div className="mt-4 h-1 w-16 bg-accent rounded-full" />
          </a>
        ))}
      </div>
    </section>
  );
}