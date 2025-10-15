# 🧠 Veille Tech — Data, BI, Cloud & AI

Automatise ta **veille technologique** avec Python :
- 📰 **Crawl** des blogs officiels, articles techniques et sources data/BI/ML.
- 🤖 **Analyse IA** (via **Groq** / Llama 3.1) pour trier les contenus utiles.
- 🧾 **Exports** JSON & Markdown.
- 🗞️ **Résumé hebdomadaire IA** clair et synthétique avec liens à creuser.

---

## 🚀 Fonctionnalités

| Étape | Description |
|--------|--------------|
| **Crawl** | Récupère automatiquement les articles récents des blogs techniques (RSS/HTML auto). |
| **Filtrage** | Ignore les sources non éditoriales (forums, jobs, release notes, etc.). |
| **Classification** | Trie par thème : bases de données, orchestration, BI, ML, Cloud... |
| **Analyse IA** | Score la pertinence de chaque article (0–100) via LLM. |
| **Résumé IA** | Génère un résumé hebdomadaire par thèmes avec les liens principaux. |
| **Export Markdown/JSON** | Sortie prête à lire ou à publier (Notion, Slack, newsletter…). |

---

## 🧩 Structure du projet

veille-tech/
├── main.py              # Orchestrateur global (crawl + analyse + export)
├── veille_tech.py       # Crawler / parser RSS + HTML
├── analyze_llm.py       # Analyse IA + résumé
├── config.yaml          # Configuration principale
├── veille.db            # Base SQLite (articles)
└── export/
├── digest_YYYYMMDD.md
├── ai_selection_YYYYMMDD.md
└── ai_summary_YYYYMMDD.md

---

## ⚙️ Installation

### 1️⃣ Crée ton environnement

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

Exemple minimal de requirements.txt :

aiohttp
aiolimiter
feedparser
beautifulsoup4
html5lib
lxml
python-slugify
pydantic
readability-lxml
tqdm
pyyaml
openai==1.50.2
httpx==0.27.2


⸻

2️⃣ Configure ton config.yaml

Tous les paramètres sont centralisés ici :
	•	crawl : vitesse, timeout, filtres de domaines (whitelist/blacklist).
	•	sources : flux RSS ou blogs à suivre.
	•	llm : paramètres du modèle d’analyse IA.
	•	summary : options du résumé hebdomadaire.

Exemple :

llm:
  provider: "openai_compat"
  base_url: "https://api.groq.com/openai/v1"
  api_key_env: "GROQ_API_KEY"
  model: "llama-3.1-8b-instant"
  temperature: 0.2
  max_tokens: 400
  concurrent: 1
  score_threshold: 60


⸻

3️⃣ Configure ta clé API Groq

Crée ton token ici → https://console.groq.com/

export GROQ_API_KEY="sk_groq_xxxxxxxxxxxxxx"


⸻

▶️ Exécution

Tout lancer d’un coup :

python main.py --config config.yaml

Options disponibles :

--skip-crawl       # saute la phase de crawling
--skip-analyze     # saute l’analyse IA
--limit 10         # ne traite que 10 items (debug)

Exemples :

# Crawler uniquement
python main.py --skip-analyze

# Relancer uniquement l’analyse IA
python main.py --skip-crawl


⸻

📊 Résultats

Les exports sont dans export/ :
	•	digest_YYYYMMDD.md → liste d’articles par thème
	•	ai_selection_YYYYMMDD.md → items filtrés par l’IA (score ≥ threshold)
	•	ai_summary_YYYYMMDD.md → résumé hebdomadaire IA

Exemple de résumé :

# 🧠 Veille Tech – Semaine du 14 octobre 2025

## 🔢 Bases de données
- Snowflake GA sur Dynamic Tables 2.0 – gains de performance notables.
- Databricks améliore Photon SQL (+30% sur benchmarks).

**À creuser :**
- https://www.snowflake.com/blog/dynamic-tables-2-0/
- https://www.databricks.com/blog/photon-updates


⸻

🧹 Purge (optionnelle)

Tu peux activer la purge automatique pour ne garder que la fenêtre de veille (7 jours par défaut) :

with db_conn(cfg.storage.sqlite_path) as conn:
    conn.execute("DELETE FROM items WHERE published_ts < ?", (window_start_ts,))


⸻

🛠️ Personnalisation
	•	🧾 Ajouter une source :
→ Ajoute un bloc dans config.yaml > sources
Exemple :

- name: "Datafold Blog"
  url: "https://datafold.com/blog"


	•	🎯 Modifier les thèmes :
→ Mets à jour categories (mots-clés et titres).
	•	🧠 Changer de modèle IA :
→ Utilise model: llama-3.1-70b-versatile (plus précis mais plus lent).

⸻

🧵 Automatisation

Tu peux planifier l’exécution avec cron (Linux/macOS) :

0 9 * * 1 cd /path/to/veille-tech && /usr/bin/python3 main.py --config config.yaml >> veille.log 2>&1

→ Lance la veille tous les lundis à 9h.

⸻

💡 Astuces
	•	Vérifie la qualité des sources :

sqlite3 veille.db "SELECT source_name, COUNT(*) FROM items GROUP BY source_name ORDER BY 2 DESC;"


	•	Pour relire les articles scorés :

sqlite3 veille.db "SELECT title, llm_score, url FROM items WHERE llm_score >= 70 ORDER BY published_ts DESC;"



⸻

🧑‍💻 Auteur

Projet conçu par Nathan Sornet
avec ❤️ et Groq + Llama 3.1 pour booster la veille data/tech.

⸻

🪪 Licence

MIT — libre d’usage et de modification.
Si tu l’adaptes, pense à citer la source 🙏

---

Souhaites-tu que je te fasse aussi un **`requirements.txt` complet et figé** (versions exactes testées avec ton pipeline Groq + crawler) à mettre à côté du README ?