import sqlite3
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Veille Tech", layout="wide")

st.title("🧠 Veille Tech – Dashboard IA")

conn = sqlite3.connect("veille.db")
df = pd.read_sql_query("SELECT title, source_name, url, llm_score, category_key, published_ts FROM items", conn)
conn.close()

df["published"] = pd.to_datetime(df["published_ts"], unit="s")
df = df.sort_values("published", ascending=False)

score_min = st.slider("Filtrer par score minimum :", 0, 100, 70)
theme = st.multiselect("Thèmes :", sorted(df["category_key"].unique()), [])

filt = df[df["llm_score"] >= score_min]
if theme:
    filt = filt[filt["category_key"].isin(theme)]

st.write(f"Articles sélectionnés : {len(filt)}")

for _, row in filt.iterrows():
    st.markdown(f"### [{row['title']}]({row['url']})")
    st.caption(f"{row['source_name']} — {row['published'].strftime('%Y-%m-%d')} — score {row['llm_score']}")
    st.divider()