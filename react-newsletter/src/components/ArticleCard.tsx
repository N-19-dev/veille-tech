// src/components/ArticleCard.tsx
// Carte article compacte, style magazine : favicon, source, titre clamp, barre d’accent.
// Compatible avec les bullets venant de ai_summary.md (title, url, source, score?, date?)

import React from "react";
import { faviconUrl, getDomain } from "../lib/parse";

type Props = {
  title: string;
  url?: string;
  source?: string;
  date?: string;
  score?: number | string;
};

export default function ArticleCard({ title, url, source, date, score }: Props) {
  const dom = getDomain(url ?? "");
  const displaySource = source || dom || "Source";

  // Affiche "NN/100" seulement si score ressemble à un entier 0–100
  const scoreText = React.useMemo(() => {
    if (typeof score === "number") return `${score}/100`;
    if (typeof score === "string" && /^\d{1,3}$/.test(score)) return `${score}/100`;
    return undefined;
  }, [score]);

  const CardShell: React.ElementType = url ? "a" : "div";
  const cardProps = url
    ? { href: url, target: "_blank", rel: "noreferrer" }
    : {};

  return (
    <CardShell
      {...cardProps}
      className="group block bg-white border rounded-2xl p-4 hover:shadow-lg transition-all"
      aria-label={title}
    >
      <div className="flex items-center gap-2 mb-3">
        {/* Favicon avec fallback silencieux si non dispo */}
        <img
          src={faviconUrl(url ?? "", 64)}
          alt=""
          className="h-5 w-5 rounded-sm border"
          loading="lazy"
          onError={(e) => {
            // masque l'img si le favicon 404
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
        <span className="text-[11px] tracking-widest font-semibold text-neutral-600 uppercase">
          {displaySource}
        </span>
        {date && <span className="text-[11px] text-neutral-400">· {date}</span>}
        {scoreText && (
          <span className="ml-auto text-[11px] font-semibold text-neutral-700">
            {scoreText}
          </span>
        )}
      </div>

      {/* Barre d’accent “magazine” */}
      <div className="h-1 bg-accent w-12 rounded-full mb-3" />

      <h4 className="font-semibold leading-snug line-clamp-3 group-hover:underline">
        {title}
      </h4>
    </CardShell>
  );
}