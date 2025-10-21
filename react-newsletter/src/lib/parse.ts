// src/lib/parse.ts
// Utilitaires de chargement + parsing de ai_summary.md (style magazine)

export type WeekMeta = {
  week: string;           // "2025w42" ou "latest"
  range?: string;         // "13 Oct 2025 → 19 Oct 2025" si présent
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

/** Charge un fichier texte (fetch) et renvoie string. */
async function loadText(path: string): Promise<string> {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) {
    throw new Error(`Impossible de charger ${path} (${res.status})`);
  }
  const buf = await res.arrayBuffer();
  return TEXT_DECODER.decode(buf);
}

/** Lit export/weeks.json ; en secours, retourne un index minimal sur "latest". */
export async function loadWeeksIndex(): Promise<WeekMeta[]> {
  try {
    const txt = await loadText("/export/weeks.json");
    const arr = JSON.parse(txt) as Array<{
      week: string;
      range?: string;
      summary_md?: string;
    }>;
    // Tri décroissant au cas où
    return (arr || []).sort((a, b) => (a.week < b.week ? 1 : -1));
  } catch {
    // Secours : si weeks.json n’existe pas, propose juste "latest"
    return [{ week: "latest", range: "" }];
  }
}

/** Construit le chemin du résumé md pour une semaine donnée. */
function summaryPath(meta: WeekMeta): string {
  if (meta.summary_md) return `/${meta.summary_md}`;
  if (meta.week === "latest") return "/export/latest/ai_summary.md";
  return `/export/${meta.week}/ai_summary.md`;
}

// --------------------
// Parsing du Markdown
// --------------------

/**
 * Extrait le Top 3 depuis le markdown.
 * On vise des lignes du type:
 *  - **1.** [Titre](URL) — Source · 2025-10-14 · **90/100**
 */
function parseTop3(md: string): TopItem[] {
  const out: TopItem[] = [];
  // Cherche le bloc commençant par "## 🏆 Top 3" (tolérant aux variations)
  const topHeader = /(^|\n)##\s*🏆?\s*Top\s*3[^\n]*\n([\s\S]*?)(\n##\s|$)/i;
  const m = md.match(topHeader);
  if (!m) return out;

  const block = m[2];

  // Ligne d’item
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

/**
 * Extrait les sections H2 + leurs listes d’items (liens) depuis le markdown.
 * Ignore l'aperçu général ; transforme les puces en cartes.
 */
function parseSections(md: string): SummarySection[] {
  const sections: SummarySection[] = [];

  // Sépare par titres H2 ("## Titre")
  const h2Re = /(^|\n)##\s+([^\n]+)\n/gm;
  const indices: Array<{ title: string; start: number; end: number }> = [];

  let match: RegExpExecArray | null;
  while ((match = h2Re.exec(md))) {
    const title = match[2].trim();
    const start = match.index + match[0].length;
    indices.push({ title, start, end: md.length });
    // Mettra l'end au passage suivant
    if (indices.length > 1) {
      indices[indices.length - 2].end = match.index;
    }
  }

  for (const seg of indices) {
    const title = seg.title;
    const block = md.slice(seg.start, seg.end).trim();

    // On ignore l'Aperçu général (souvent des paragraphes sans puces)
    if (/aperçu général/i.test(title)) continue;

    // On extrait les items sous forme de puces Markdown avec lien
    // Formats possibles :
    //  - [Titre](URL) — Source · date · **score/100**
    //  - [Titre](URL)
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

    // Si pas d’items extraits, on n’ajoute pas la section (évite des cartes vides)
    if (items.length) {
      sections.push({ title, items });
    }
  }

  return sections;
}

// --------------------
// API principale
// --------------------

/** Charge et parse ai_summary.md pour une semaine donnée. */
export async function loadWeekSummary(meta: WeekMeta): Promise<{
  top3: TopItem[];
  sections: SummarySection[];
}> {
  const path = summaryPath(meta);
  const md = await loadText(path);

  const top3 = parseTop3(md);
  const sections = parseSections(md);

  return { top3, sections };
}

// --------------------
// Utils visuels (favicon / domaine)
// --------------------

/** Extrait le domaine (ex: "huggingface.co") d'une URL. */
export function getDomain(url?: string): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/** Construit une URL de favicon (Google ou DuckDuckGo). */
export function faviconUrl(url?: string, size = 32): string {
  const dom = getDomain(url);
  if (!dom) return `https://via.placeholder.com/${size}`;
  // Google S2 API : stable, rapide, sans clé
  return `https://www.google.com/s2/favicons?domain=${dom}&sz=${size}`;
}