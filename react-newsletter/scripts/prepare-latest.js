// scripts/prepare-latest.js
import { readFileSync, rmSync, cpSync, mkdirSync, existsSync } from "node:fs";
import { dirname } from "node:path";

const weeksPath = "public/export/weeks.json";
const latestDir = "public/export/latest";

function pickTarget() {
  let target = "public/export/2025w42";
  try {
    const weeks = JSON.parse(readFileSync(weeksPath, "utf8"));
    const latest = weeks.find(w => w.week === "latest");
    if (latest?.summary_md) return "public/" + dirname(latest.summary_md);
    if (latest?.week) return `public/export/${latest.week}`;
    if (weeks[0]?.summary_md) return "public/" + dirname(weeks[0].summary_md);
    if (weeks[0]?.week) return `public/export/${weeks[0].week}`;
  } catch {}
  return target;
}

const target = pickTarget();
if (!existsSync(target)) {
  console.error(`[prepare-latest] Missing target: ${target}`);
  mkdirSync(latestDir, { recursive: true });
  process.exit(0);
}

rmSync(latestDir, { recursive: true, force: true });
cpSync(target, latestDir, { recursive: true });
console.log(`[prepare-latest] Copied ${target} -> ${latestDir}`);