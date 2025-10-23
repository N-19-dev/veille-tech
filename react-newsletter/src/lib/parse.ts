// src/lib/parse.ts
// Utilitaires de chargement + parsing de ai_summary.md (style magazine)

export type WeekMeta = {
  week: string;           // "2025w42" ou "latest"
  range?: string;         // "13 Oct 2025 → 19 Oct 2025"
  summary_md?: string;    // chemin du md (optionnel dans weeks.json)
};

export type TopItem = {
  title: string;
  url: string;
  source?: string;
  date?: string;
  score?: string | number;
};

export type SectionItem = {
  title: string;
  url: string;
  source?: string;
  score?: string | number;
};

export type SummarySection = {
  title: string;
  items: SectionItem[];
};

const TEXT_DECODER = new TextDecoder();

// ----- Gestion sûre du base path Vite -----
// Vite garantit BASE_URL (ex: "/", ou "/veille-tech/").
const VITE_BASE: string =
  (import.meta as any)?.env?.BASE_URL ??
  (typeof document !== "undefined" ? (document.querySelector("base")?.getAttribute("href") || "/") : "/");

// normalise: toujours commencer et finir par "/"
function normalizeBase(b: string): string {
  if (!b) return "/";
  let s = b;
  if (!s.startsWith("/")) s = "/" + s;
  if (!s.endsWith("/")) s = s + "/";
  return s;
}
const BASE = normalizeBase(VITE_BASE);

// Joindre BASE + chemin relatif sans utiliser new URL.
function withBase(p: string): string {
  const rel = p.startsWith("/") ? p.slice(1) : p;
  return BASE + rel;
}

/** Charge un fichier texte (fetch) et renvoie string. */
async function loadText(path: string): Promise<string> {
  // path doit être relatif au site (ex: "export/weeks.json" ou "/export/weeks.json")
  // on le passe toujours par withBase pour éviter les erreurs d’origine.
  const finalUrl = path.startsWith(BASE) ? path : withBase(path);
  const res = await fetch(finalUrl, { cache: "no-cache" });
  if (!res.ok) {
    throw new Error(`Impossible de charger ${finalUrl} (${res.status})`);
  }
  const buf = await res.arrayBuffer();
  return TEXT_DECODER.decode(buf);
}

/** Lit export/weeks.json ; secours: "latest". */
export async function loadWeeksIndex(): Promise<WeekMeta[]> {
  try {
    const txt = await loadText("export/weeks.json");
    const arr = JSON.parse(txt) as Array<{ week: string; range?: string; summary_md?: string }>;
    return (arr || []).sort((a, b) => (a.week < b.week ? 1 : -1));
  } catch {
    return [{ week: "latest", range: "" }];
  }
}

/** Construit le chemin du résumé md pour une semaine donnée. */
function summaryPath(meta: WeekMeta): string {
  if (meta.summary_md) return withBase(meta.summary_md.startsWith("/") ? meta.summary_md.slice(1) : meta.summary_md);
  if (meta.week === "latest") return withBase("export/latest/ai_summary.md");
  return withBase(`export/${meta.week}/ai_summary.md`);
}

// --------------------
// Parsing du Markdown
// --------------------

function parseTop3(md: string): TopItem[] {
  const out: TopItem[] = [];
  const topHeader = /(^|\n)##\s*🏆?\s*Top\s*3[^\n]*\n([\s\S]*?)(\n##\s|$)/i;
  const m = md.match(topHeader);
  if (!m) return out;

  const block = m[2];
  const itemRe =
    /^\s*[-–•]\s*(?:\*\*\d+\.\*\*\s*)?\[(.+?)\]\((https?:\/\/[^\s)]+)\)\s*—\s*([^·\n]+)?(?:\s*·\s*([\d-]{8,10}))?(?:\s*·\s*\*\*(\d+)\s*\/\s*100\*\*)?/gim;

  let mm: RegExpExecArray | null;
  while ((mm = itemRe.exec(block)) && out.length < 3) {
    out.push({
      title: mm[1]?.trim(),
      url: mm[2]?.trim(),
      source: mm[3]?.trim(),
      date: mm[4]?.trim(),
      score: mm[5]?.trim(),
    });
  }
  return out;
}

function parseSections(md: string): SummarySection[] {
  const sections: SummarySection[] = [];
  const h2Re = /(^|\n)##\s+([^\n]+)\n/gm;
  const indices: Array<{ title: string; start: number; end: number }> = [];

  let match: RegExpExecArray | null;
  while ((match = h2Re.exec(md))) {
    const title = match[2].trim();
    const start = match.index + match[0].length;
    indices.push({ title, start, end: md.length });
    if (indices.length > 1) indices[indices.length - 2].end = match.index;
  }

  for (const seg of indices) {
    const title = seg.title;
    const block = md.slice(seg.start, seg.end).trim();
    if (/aperçu général/i.test(title)) continue;

    const lineRe =
      /^\s*[-–•]\s*\[(.+?)\]\((https?:\/\/[^\s)]+)\)\s*(?:—\s*([^·\n]+))?(?:\s*·\s*([\d-]{8,10}))?(?:\s*·\s*\*\*(\d+)\s*\/\s*100\*\*)?/gim;

    const items: SectionItem[] = [];
    let lm: RegExpExecArray | null;
    while ((lm = lineRe.exec(block))) {
      items.push({
        title: lm[1]?.trim(),
        url: lm[2]?.trim(),
        source: lm[3]?.trim(),
        score: lm[5]?.trim(),
      });
    }
    if (items.length) sections.push({ title, items });
  }

  return sections;
}

// --------------------
// API principale
// --------------------

export async function loadWeekSummary(meta: WeekMeta): Promise<{ top3: TopItem[]; sections: SummarySection[] }> {
  const md = await loadText(summaryPath(meta));
  return { top3: parseTop3(md), sections: parseSections(md) };
}

// --------------------
// Utils visuels
// --------------------

export function getDomain(url?: string): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

export function faviconUrl(url?: string, size = 32): string {
  const dom = getDomain(url);
  if (!dom) return `https://via.placeholder.com/${size}`;
  return `https://www.google.com/s2/favicons?domain=${dom}&sz=${size}`;
}