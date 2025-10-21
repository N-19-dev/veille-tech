// src/components/SectionCard.tsx
// Rubrique (ex: "🔢 Bases de données & OLAP") avec cartouches articles.

import ArticleCard from "./ArticleCard";

export default function SectionCard({
  title,
  bullets,
}: {
  title: string;
  bullets: { title: string; url?: string; source?: string; date?: string; score?: number | string }[];
}) {
  if (!bullets?.length) return null;

  // on met un "lead" et des secondaires, comme un magazine
  const [lead, ...rest] = bullets;

  return (
    <section className="bg-white border rounded-2xl p-5">
      <div className="mb-4">
        <h3 className="text-xl font-bold">{title}</h3>
        <div className="h-1 bg-accent w-20 mt-2 rounded-full" />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Lead plus large */}
        <div className="md:col-span-2">
          <ArticleCard {...lead} />
        </div>

        {/* Secondaires */}
        {rest.slice(0, 6).map((b, i) => (
          <ArticleCard key={i} {...b} />
        ))}
      </div>
    </section>
  );
}