import streamlit as st
import pandas as pd
import re
from supabase import create_client, Client

st.set_page_config(page_title="Ordini Mobile", layout="wide")

# ---------------------------------------------------------
# CONFIGURAZIONE CONNESSIONE SUPABASE CLOUD
# ---------------------------------------------------------
SUPABASE_URL = "https://azmyqrcxfnimwrhpyhsv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF6bXlxcmN4Zm5pbXdyaHB5aHN2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1OTAxNjEsImV4cCI6MjEwNDE2NjE2MX0.sFf3_axQg6uOqWCQJcfvWGbebDwrVGngIyA0jPZqjz4"

@st.cache_resource
def init_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = init_supabase()

# ---------------------------------------------------------
# CARICAMENTO DATABASE CLOUD (PAGINATO)
# ---------------------------------------------------------
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
            cols_to_drop = [c for c in ['created_at', 'id'] if c in df.columns]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)

            colonne_standard = ["CLIENTE", "N. ORDINE", "ARTICOLO", "CONSEGNA", "QUANTITÀ", "PREZZO"]
            for col in colonne_standard:
                if col not in df.columns:
                    df[col] = ""
            return df[colonne_standard].astype(str).fillna("")
    except Exception as e:
        st.error(f"Errore caricamento: {e}")
    return pd.DataFrame(columns=["CLIENTE", "N. ORDINE", "ARTICOLO", "CONSEGNA", "QUANTITÀ", "PREZZO"])

# ---------------------------------------------------------
# INTERFACCIA MOBILE (CONSULTAZIONE & COMPARATIVA)
# ---------------------------------------------------------
st.title("📱 Consulta & Compara Ordini")

if "db_ordini" not in st.session_state:
    st.session_state.db_ordini = carica_db_cloud()

if st.button("🔄 Aggiorna Dati"):
    st.session_state.db_ordini = carica_db_cloud()
    st.rerun()

df = st.session_state.db_ordini

if not df.empty:
    col_c, col_a = st.columns(2)
    
    list_clienti = ["Tutti"] + sorted([x for x in df["CLIENTE"].unique() if str(x).strip()])
    cli_sel = col_c.selectbox("Cliente:", list_clienti, key="mob_cli")
    
    df_filt = df.copy()
    if cli_sel != "Tutti":
        df_filt = df_filt[df_filt["CLIENTE"] == cli_sel]

    list_articoli = ["Tutti"] + sorted([x for x in df_filt["ARTICOLO"].unique() if str(x).strip()])
    art_sel = col_a.selectbox("Articolo:", list_articoli, key="mob_art")
    
    if art_sel != "Tutti":
        df_filt = df_filt[df_filt["ARTICOLO"] == art_sel]

    st.caption(f"Ordini trovati: **{len(df_filt)}**")
    
    # Visualizzazione tabella ottimizzata per schermi smartphone
    st.dataframe(
        df_filt, 
        use_container_width=True, 
        hide_index=True
    )
else:
    st.info("Database vuoto o in fase di caricamento.")
