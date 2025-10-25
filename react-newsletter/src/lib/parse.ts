// src/lib/parse.ts
// Utilitaires de chargement + parsing de ai_summary.md (style magazine)

export type WeekMeta = {
  week: string;           // "2025w42" ou "latest"
  range?: string;         // "13 Oct 2025 → 19 Oct 2025"
  summary_md?: string;    // chemin du md (optionnel dans weeks.json)
  selection_blogs?: string;  // ✅ Nouveau
  selection_hands?: string;  // ✅ Nouveau
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

// ✅ Fonction de chargement simplifiée qui utilise document.baseURI
async function loadText(relativePath: string): Promise<string> {
  // relativePath doit être SANS "/" au début (ex: "export/weeks.json")
  const cleanPath = relativePath.startsWith("/") ? relativePath.slice(1) : relativePath;
  
  // document.baseURI contient déjà le bon préfixe (ex: https://n-19-dev.github.io/veille-tech/)
  const base = typeof document !== "undefined" ? document.baseURI : "/";
  const finalUrl = new URL(cleanPath, base).toString();
  
  const res = await fetch(finalUrl, { cache: "no-store" });
  if (!res.ok) throw new Error(`Impossible de charger ${finalUrl} (${res.status})`);
  
  return new TextDecoder().decode(await res.arrayBuffer());
}

export async function loadWeeksIndex(): Promise<WeekMeta[]> {
  try {
    const txt = await loadText("export/weeks.json");
    const arr = JSON.parse(txt) as WeekMeta[];
    return (arr || []).sort((a, b) => (a.week < b.week ? 1 : -1));
  } catch (e) {
    console.error("Erreur chargement weeks.json:", e);
    return [{ week: "latest", range: "" }];
  }
}

// ✅ Retourne un chemin RELATIF (sans BASE_URL)
function summaryPath(meta: { week: string; summary_md?: string }): string {
  if (meta.summary_md) {
    return meta.summary_md.replace(/^export\//, "export/");
  }
  if (meta.week === "latest") {
    return "export/latest/ai_summary.md";
  }
  return `export/${meta.week}/ai_summary.md`;
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
  try {
    const md = await loadText(summaryPath(meta));
    return { top3: parseTop3(md), sections: parseSections(md) };
  } catch (e) {
    console.error("Erreur chargement summary:", e);
    return { top3: [], sections: [] };
  }
}

export async function loadWeekSelection(
  meta: WeekMeta,
  kind: "blogs" | "hands"
): Promise<Record<string, Array<{ title: string; url: string; source_name?: string; published_ts?: number; llm_score?: number; score?: number }>>> {
  const week = meta.week || "latest";
  
  // ✅ Utilise les chemins depuis weeks.json si disponibles
  const metaPath = kind === "blogs"
    ? meta.selection_blogs
    : meta.selection_hands;
  
  // ✅ Fallback sur le nom de fichier standard
  const filename = kind === "blogs" 
    ? "ai_selection_blogs.json" 
    : "ai_selection_hands.json";
  
  const rel = metaPath 
    ? metaPath.replace(/^\/+/, "")
    : `export/${week}/${filename}`;

  try {
    const txt = await loadText(rel);
    return JSON.parse(txt);
  } catch (e: any) {
    console.error(`Erreur chargement ${rel}:`, e.message);
    return {}; // Retourne vide au lieu de crasher
  }
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