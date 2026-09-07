import streamlit as st
import pandas as pd
import pdfplumber
import re
from supabase import create_client, Client
from rapidfuzz import process, fuzz

st.set_page_config(page_title="Gestionale Ordini Cloud", layout="wide")

# ---------------------------------------------------------
# CONNESSIONE SUPABASE CLOUD
# ---------------------------------------------------------
SUPABASE_URL = "https://azmyqrcxfnimwrhpyhsv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF6bXlxcmN4Zm5pbXdyaHB5aHN2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1OTAxNjEsImV4cCI6MjEwNDE2NjE2MX0"

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

def carica_db_cloud():
    try:
        tutti_i_dati = []
        step = 1000
        inizio = 0
        while True:
            response = supabase.table("ordini").select("*").range(inizio, inizio + step - 1).execute()
            batch = response.data
            if not batch:
                break
            tutti_i_dati.extend(batch)
            if len(batch) < step:
                break
            inizio += step

        if tutti_i_dati:
            df = pd.DataFrame(tutti_i_dati)
            mappa_colonne = {
                'cliente': 'CLIENTE',
                'n_ordine': 'N. ORDINE',
                'articolo': 'ARTICOLO',
                'consegna': 'CONSEGNA',
                'quantita': 'QUANTITÀ',
                'prezzo': 'PREZZO'
            }
            df = df.rename(columns=mappa_colonne)
            cols_to_drop = [c for c in ['created_at'] if c in df.columns]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)

            colonne_standard = ["id", "CLIENTE", "N. ORDINE", "ARTICOLO", "CONSEGNA", "QUANTITÀ", "PREZZO"]
            for col in colonne_standard:
                if col not in df.columns:
                    df[col] = ""
            return df[colonne_standard].astype(str).fillna("")
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
    return pd.DataFrame(columns=["id", "CLIENTE", "N. ORDINE", "ARTICOLO", "CONSEGNA", "QUANTITÀ", "PREZZO"])

def rinomina_articolo_cloud(vecchio_nome, nuovo_nome):
    try:
        supabase.table("ordini").update({"articolo": nuovo_nome}).eq("articolo", vecchio_nome).execute()
        return True
    except Exception as e:
        st.error(f"Errore aggiornamento: {e}")
        return False

# ---------------------------------------------------------
# CARICAMENTO DATI
# ---------------------------------------------------------
if "db_ordini" not in st.session_state:
    st.session_state.db_ordini = carica_db_cloud()

st.title("📦 Gestionale Ordini - Dashboard Cloud")

tab_gestione, tab_fuzzy = st.tabs(["📋 Gestione Ordini", "🤖 Pulizia Smart (Fuzzy)"])

# ---------------------------------------------------------
# TAB 1: GESTIONE ORDINARIA
# ---------------------------------------------------------
with tab_gestione:
    df = st.session_state.db_ordini
    if not df.empty:
        st.subheader("1. Filtri & Database")
        col_c, col_a = st.columns(2)
        cli_sel = col_c.selectbox("Filtra per Cliente:", ["Tutti"] + sorted(list(df["CLIENTE"].unique())))
        
        df_filt = df.copy()
        if cli_sel != "Tutti":
            df_filt = df_filt[df_filt["CLIENTE"] == cli_sel]

        art_sel = col_a.selectbox("Filtra per Articolo:", ["Tutti"] + sorted(list(df_filt["ARTICOLO"].unique())))
        if art_sel != "Tutti":
            df_filt = df_filt[df_filt["ARTICOLO"] == art_sel]

        st.dataframe(df_filt, use_container_width=True)
        st.caption(f"Righe visibili: {len(df_filt)} su {len(df)}")
    else:
        st.info("Database vuoto o in fase di caricamento.")

# ---------------------------------------------------------
# TAB 2: PULIZIA SMART (FUZZY MATCHING)
# ---------------------------------------------------------
with tab_fuzzy:
    st.subheader("🤖 Rilevamento Automatico Duplicati e Varianti")
    st.markdown("Questa funzione confronta tutti gli articoli (per singolo cliente o su tutto il DB) e trova i nomi quasi identici.")

    df_fz = st.session_state.db_ordini
    if not df_fz.empty:
        col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
        
        list_cli = ["Tutti i Clienti"] + sorted([x for x in df_fz["CLIENTE"].unique() if str(x).strip()])
        target_cli = col_f1.selectbox("Seleziona Cliente da analizzare:", list_cli, key="fz_cli")
        soglia = col_f2.slider("Soglia di somiglianza (%):", min_value=70, max_value=98, value=85, step=1)
        
        if col_f3.button("🔄 Ricarica DB Cloud"):
            st.session_state.db_ordini = carica_db_cloud()
            st.rerun()

        # Filtra DF per il cliente scelto
        if target_cli != "Tutti i Clienti":
            df_work = df_fz[df_fz["CLIENTE"] == target_cli]
        else:
            df_work = df_fz

        articoli_unici = sorted([a for a in df_work["ARTICOLO"].unique() if str(a).strip()])
        st.info(f"Articoli distinti da analizzare: **{len(articoli_unici)}**")

        # Algoritmo di confronto vettoriale
        coppie_trovate = []
        processati = set()

        for idx, art_a in enumerate(articoli_unici):
            if art_a in processati:
                continue
            # Confronta art_a con tutti i successivi
            match = process.extract(
                art_a, 
                articoli_unici[idx+1:], 
                scorer=fuzz.token_sort_ratio, 
                score_cutoff=soglia
            )
            for art_b, score, _ in match:
                coppie_trovate.append({
                    "Articolo A": art_a,
                    "Articolo B": art_b,
                    "Somiglianza": f"{round(score)}%",
                    "Conteggio A": len(df_work[df_work["ARTICOLO"] == art_a]),
                    "Conteggio B": len(df_work[df_work["ARTICOLO"] == art_b])
                })
                processati.add(art_b)

        if coppie_trovate:
            st.write(f"🔍 Trovate **{len(coppie_trovate)}** potenziali corrispondenze:")
            st.divider()

            for i, c in enumerate(coppie_trovate):
                with st.container():
                    st.markdown(f"#### Coppia #{i+1} — Somiglianza: `{c['Somiglianza']}`")
                    col_left, col_right = st.columns(2)

                    with col_left:
                        st.markdown(f"**Opzione A** ({c['Conteggio A']} ordini):")
                        st.code(c['Articolo A'])
                        if st.button(f"👈 Unifica tutto sotto Opzione A", key=f"btn_a_{i}"):
                            if rinomina_articolo_cloud(c['Articolo B'], c['Articolo A']):
                                st.success(f"Unificato! '{c['Articolo B']}' convertito in '{c['Articolo A']}'")
                                st.session_state.db_ordini = carica_db_cloud()
                                st.rerun()

                    with col_right:
                        st.markdown(f"**Opzione B** ({c['Conteggio B']} ordini):")
                        st.code(c['Articolo B'])
                        if st.button(f"👉 Unifica tutto sotto Opzione B", key=f"btn_b_{i}"):
                            if rinomina_articolo_cloud(c['Articolo A'], c['Articolo B']):
                                st.success(f"Unificato! '{c['Articolo A']}' convertito in '{c['Articolo B']}'")
                                st.session_state.db_ordini = carica_db_cloud()
                                st.rerun()
                    st.divider()
        else:
            st.success("Nessun duplicato trovato con la percentuale di somiglianza impostata. Prova ad abbassare la percentuale dello slider.")
    else:
        st.warning("Database vuoto.")
