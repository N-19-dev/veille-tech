# main.py
# Lance toute la pipeline : crawl -> analyse IA (Groq) -> exports/summary
# Compatible Python 3.8+ (utilise asyncio.run si dispo)

import os
import sys
import time
import argparse
import asyncio
from pathlib import Path

# --- Utils ---
def banner(msg: str):
    print("\n" + "=" * 80)
    print(msg)
    print("=" * 80 + "\n")

def ensure_env(var: str):
    val = os.getenv(var)
    if not val:
        raise RuntimeError(
            f"Variable d'environnement manquante: {var}\n"
            f"Exemple: export {var}='sk_groq_XXXX' (ou adapte ton provider dans config.yaml)"
        )
    return val

def import_or_die(modpath: str, hint: str = ""):
    try:
        return __import__(modpath, fromlist=['*'])
    except Exception as e:
        raise RuntimeError(f"Impossible d'importer {modpath}: {e}\n{hint}")

def seconds_to_mmss(s: float) -> str:
    m = int(s // 60)
    ss = int(s % 60)
    return f"{m:02d}:{ss:02d}"

# --- Runner ---
def run_all(config_path: str, skip_crawl: bool, skip_analyze: bool, analyze_limit: int = None):
    t0 = time.time()
    cfg_path = Path(config_path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config introuvable: {cfg_path.resolve()}")

    # 1) Crawl
    if not skip_crawl:
        banner("1) CRAWL — collecte des articles/blogs (fenêtre lookback_days)")
        veille = import_or_die(
            "veille_tech",
            hint="Vérifie que 'veille_tech.py' est au même niveau que main.py."
        )
        # veille.run est async -> on utilise asyncio.run
        asyncio.run(veille.run(config_path))
    else:
        print("⏭️  Crawl skipped (--skip-crawl).")

    # 2) Analyse IA (Groq / OpenAI-compatible)
    if not skip_analyze:
        banner("2) ANALYSE IA — scoring + labels + résumé hebdo (selon config)")
        # On vérifie la clé seulement si provider == openai_compat (Groq)
        # On lit vite fait le config pour savoir.
        import yaml
        cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        provider = cfg.get("llm", {}).get("provider", "")
        if provider == "openai_compat":
            ensure_env(cfg.get("llm", {}).get("api_key_env", "GROQ_API_KEY"))

        analyzer = import_or_die(
            "analyze_llm",
            hint="Vérifie que 'analyze_llm.py' est au même niveau que main.py."
        )
        # analyze_llm.main est async -> on utilise asyncio.run
        asyncio.run(analyzer.main(config_path, limit=analyze_limit))
    else:
        print("⏭️  Analyse IA skipped (--skip-analyze).")

    banner(f"✅ Terminé en {seconds_to_mmss(time.time()-t0)}")

# --- CLI ---
if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Orchestrateur veille: crawl -> analyse IA -> export")
    p.add_argument("--config", default="config.yaml", help="Chemin vers le config.yaml")
    p.add_argument("--skip-crawl", action="store_true", help="Ne pas lancer le crawler")
    p.add_argument("--skip-analyze", action="store_true", help="Ne pas lancer l'analyse IA")
    p.add_argument("--limit", type=int, default=None, help="Limiter le nombre d'items à scorer (debug)")
    args = p.parse_args()

    try:
        run_all(args.config, args.skip_crawl, args.skip_analyze, analyze_limit=args.limit)
    except Exception as e:
        print(f"\n❌ Erreur: {e}\n", file=sys.stderr)
        sys.exit(1)