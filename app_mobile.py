import streamlit as st
import pandas as pd
import pdfplumber
import re
from supabase import create_client, Client

st.set_page_config(
    page_title="Ordini Mobile", 
    layout="wide", 
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# CONNESSIONE SUPABASE CLOUD
# ---------------------------------------------------------
SUPABASE_URL = "https://azmyqrcxfnimwrhpyhsv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImF6bXlxcmN4Zm5pbXdyaHB5aHN2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg1OTAxNjEsImV4cCI6MjEwNDE2NjE2MX0.sFf3_axQg6uOqWCQJcfvWGbebDwrVGngIyA0jPZqjz4"

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

def inserisci_ordini_cloud(nuovi_dati):
    try:
        dati_db = []
        for d in nuovi_dati:
            dati_db.append({
                "cliente": d.get("CLIENTE", ""),
                "n_ordine": d.get("N. ORDINE", ""),
                "articolo": d.get("ARTICOLO", ""),
                "consegna": d.get("CONSEGNA", ""),
                "quantita": d.get("QUANTITÀ", ""),
                "prezzo": d.get("PREZZO", "")
            })
        supabase.table("ordini").insert(dati_db).execute()
        return True
    except Exception as e:
        st.error(f"Errore salvataggio: {e}")
        return False

def estrai_dati_pdf(pdf_file):
    righe_estratte = []
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        testo_layout = page.extract_text(layout=True) or ""
        testo_semplice = page.extract_text(layout=False) or ""

    m_cliente = re.search(r"Spett\.le\s*\n\s*([^\n]+)", testo_semplice)
    cliente = m_cliente.group(1).strip() if m_cliente else ""

    n_ordine = ""
    target_word = None
    for w in words:
        if "N°Ord" in w['text'] or "Cliente" in w['text']:
            if w['top'] < 300:
                target_word = w
                break
    
    if target_word:
        x0, x1 = target_word['x0'] - 10, target_word['x1'] + 60
        top, bottom = target_word['bottom'], target_word['bottom'] + 45
        num_words = [w['text'].strip() for w in words if x0 <= w['x0'] <= x1 and top <= w['top'] <= bottom]
        for nw in num_words:
            clean_num = re.sub(r"\D", "", nw)
            if clean_num:
                n_ordine = clean_num
                break

    if not n_ordine:
        m_ord = re.search(r"N°Ord Cliente\s*[\n\r]*\s*(\d+)", testo_semplice)
        if m_ord: n_ordine = m_ord.group(1)

    righe_raw = testo_layout.split("\n")
    for i, riga in enumerate(righe_raw):
        m_consegna = re.search(r"(\d{2}/\d{2}/\d{4})", riga)
        m_prezzo = re.search(r"€\s*([\d\.,]+)", riga)
        if m_consegna and m_prezzo:
            consegna = m_consegna.group(1)
            prezzo = f"€ {m_prezzo.group(1).strip()}"
            idx_date, idx_price = riga.find(consegna), riga.find("€")
            segmento_qta = riga[idx_date + len(consegna):idx_price]
            m_qta = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)", segmento_qta)
            qta = m_qta.group(1).strip() if m_qta else ""
            articolo = riga[:idx_date].strip()
            if articolo and consegna:
                righe_estratte.append({
                    "CLIENTE": cliente, "N. ORDINE": n_ordine,
                    "ARTICOLO": articolo, "CONSEGNA": consegna,
                    "QUANTITÀ": qta, "PREZZO": prezzo
                })
    return righe_estratte

# ---------------------------------------------------------
# INTERFACCIA MOBILE DENSE & COMPACT
# ---------------------------------------------------------
st.markdown("### 📱 Consulta & Compara Ordini")

if "db_ordini" not in st.session_state or st.session_state.db_ordini.empty:
    st.session_state.db_ordini = carica_db_cloud()

tab_ricerca, tab_carica = st.tabs(["🔍 Comparativa Articoli", "📄 Carica PDF"])

with tab_ricerca:
    df_m = st.session_state.db_ordini
    
    if not df_m.empty:
        # Sezione Filtri Compatta
        col_cli, col_art = st.columns(2)
        
        list_clienti = ["Tutti"] + sorted([x for x in df_m["CLIENTE"].unique() if str(x).strip()])
        sel_cliente = col_cli.selectbox("👤 Cliente:", list_clienti, key="m_cli")
        
        # Filtra gli articoli in base al cliente selezionato se presente
        if sel_cliente != "Tutti":
            df_m_art = df_m[df_m["CLIENTE"] == sel_cliente]
        else:
            df_m_art = df_m

        list_articoli = ["Tutti"] + sorted([x for x in df_m_art["ARTICOLO"].unique() if str(x).strip()])
        sel_articolo = col_art.selectbox("🏷️ Articolo:", list_articoli, key="m_art")

        # Applicazione Filtri
        df_filtrato = df_m.copy()
        if sel_cliente != "Tutti":
            df_filtrato = df_filtrato[df_filtrato["CLIENTE"] == sel_cliente]
        if sel_articolo != "Tutti":
            df_filtrato = df_filtrato[df_filtrato["ARTICOLO"] == sel_articolo]

        # Conversione e ordinamento per Data Consegna (più recenti prima)
        df_filtrato["_dt"] = pd.to_datetime(df_filtrato["CONSEGNA"], format="%d/%m/%Y", errors="coerce")
        df_filtrato = df_filtrato.sort_values("_dt", ascending=False).drop(columns=["_dt"])

        # Intestazione conteggio e reset
        c_left, c_right = st.columns([2, 1])
        c_left.caption(f"📊 Ordini trovati: **{len(df_filtrato)}**")
        if c_right.button("🔄 Reset", key="btn_m_reset"):
            st.session_state.db_ordini = carica_db_cloud()
            st.rerun()

        st.divider()

        # Visualizzazione Densa e Strutturata
        if not df_filtrato.empty:
            for _, r in df_filtrato.iterrows():
                # Card ad alta densità per schermo verticale
                with st.container():
                    st.markdown(f"**{r['CLIENTE']}**")
                    if sel_articolo == "Tutti":
                        st.markdown(f"🏷️ `{r['ARTICOLO']}`")
                    
                    # Griglia dati a 3 colonne per confronto immediato
                    c1, c2, c3 = st.columns([1.2, 1, 1])
                    c1.markdown(f"📅 **{r['CONSEGNA']}**")
                    c2.markdown(f"📦 **{r['QUANTITÀ']}**")
                    c3.markdown(f"💶 **{r['PREZZO']}**")
                    
                    st.caption(f"N° Ordine: {r['N. ORDINE']}")
                    st.markdown("---")
        else:
            st.warning("Nessun ordine trovato con i filtri inseriti.")
    else:
        st.info("Database vuoto o in fase di caricamento.")

with tab_carica:
    st.subheader("Carica PDF dal cellulare")
    up_f = st.file_uploader("Seleziona il PDF dell'ordine", type=["pdf"])
    if st.button("⚙️ Salva nel Cloud", type="primary"):
        if up_f:
            dati = estrai_dati_pdf(up_f)
            if dati and inserisci_ordini_cloud(dati):
                st.session_state.db_ordini = carica_db_cloud()
                st.success("Ordine salvato ed in linea sul Cloud!")
                st.rerun()
