# main.py
# Orchestration : crawl (semaine) -> analyse LLM (semaine) -> (option) build site

import os
import sys
import subprocess

def run(cmd: list[str]):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)

def main():
    config = "config.yaml"
    week_offset = os.getenv("WEEK_OFFSET", "0")  # export WEEK_OFFSET=-1 pour semaine dernière

    # 1) Crawl sur la semaine
    run([sys.executable, "veille_tech.py", "--config", config, "--week-offset", week_offset])

    # 2) Analyse LLM (scoring + sélection + summary) sur la même semaine
    run([sys.executable, "analyze_llm.py", "--config", config, "--week-offset", week_offset])

    # 3) (option) Site statique
    if os.path.exists("build_site.py"):
        run([sys.executable, "build_site.py"])
        # déploiement MkDocs éventuel :
        # run(["mkdocs", "gh-deploy"])

if __name__ == "__main__":
    main()