import streamlit as st
import pandas as pd
import pdfplumber
import re
from supabase import create_client, Client

st.set_page_config(page_title="Gestionale Ordini Cloud", layout="wide")

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
# CARICAMENTO / SALVATAGGIO DATABASE CLOUD (PAGINATO)
# ---------------------------------------------------------
def carica_db_cloud():
    try:
        tutti_i_dati = []
        step = 1000
        inizio = 0
        
        # Recupera tutti i dati a blocchi di 1000 righe per superare il limite standard
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
            
            # Normalizzazione dinamica dei nomi colonne (supporta sia maiuscolo che minuscolo)
            mappa_colonne = {
                'cliente': 'CLIENTE',
                'n_ordine': 'N. ORDINE',
                'articolo': 'ARTICOLO',
                'consegna': 'CONSEGNA',
                'quantita': 'QUANTITÀ',
                'prezzo': 'PREZZO'
            }
            df = df.rename(columns=mappa_colonne)
            
            # Rimuove colonne interne se presenti
            cols_to_drop = [c for c in ['created_at'] if c in df.columns]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)

            colonne_standard = ["id", "CLIENTE", "N. ORDINE", "ARTICOLO", "CONSEGNA", "QUANTITÀ", "PREZZO"]
            for col in colonne_standard:
                if col not in df.columns:
                    df[col] = ""
                    
            return df[colonne_standard].astype(str).fillna("")
    except Exception as e:
        st.error(f"Errore nel caricamento dal Cloud Supabase: {e}")
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
        st.error(f"Errore nel salvataggio sul Cloud: {e}")
        return False

# ---------------------------------------------------------
# FUNZIONE DI ESTRAZIONE A COORDINATE VISIVE
# ---------------------------------------------------------
def estrai_dati_pdf(pdf_file):
    righe_estratte = []
    
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        testo_layout = page.extract_text(layout=True) or ""
        testo_semplice = page.extract_text(layout=False) or ""

    # 1. CLIENTE (Spett.le)
    m_cliente = re.search(r"Spett\.le\s*\n\s*([^\n]+)", testo_semplice)
    cliente = m_cliente.group(1).strip() if m_cliente else ""

    # 2. N° ORDINE CLIENTE
    n_ordine = ""
    target_word = None
    for w in words:
        if "N°Ord" in w['text'] or "Cliente" in w['text']:
            if w['top'] < 300:
                target_word = w
                break
    
    if target_word:
        x0 = target_word['x0'] - 10
        x1 = target_word['x1'] + 60
        top = target_word['bottom']
        bottom = top + 45
        
        num_words = [
            w['text'].strip() for w in words 
            if x0 <= w['x0'] <= x1 and top <= w['top'] <= bottom
        ]
        
        for nw in num_words:
            clean_num = re.sub(r"\D", "", nw)
            if clean_num:
                n_ordine = clean_num
                break

    if not n_ordine:
        m_ord = re.search(r"N°Ord Cliente\s*[\n\r]*\s*(\d+)", testo_semplice)
        if m_ord:
            n_ordine = m_ord.group(1)

    # 3. ESTRAZIONE ARTICOLI, CONSEGNA, QUANTITÀ, PREZZO
    righe_raw = testo_layout.split("\n")
    
    for i, riga in enumerate(righe_raw):
        m_consegna = re.search(r"(\d{2}/\d{2}/\d{4})", riga)
        m_prezzo = re.search(r"€\s*([\d\.,]+)", riga)
        
        if m_consegna and m_prezzo:
            consegna = m_consegna.group(1)
            prezzo = f"€ {m_prezzo.group(1).strip()}"
            
            idx_date = riga.find(consegna)
            idx_price = riga.find("€")
            segmento_qta = riga[idx_date + len(consegna):idx_price]
            m_qta = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)", segmento_qta)
            qta = m_qta.group(1).strip() if m_qta else ""

            articolo = ""
            testo_prima_data = riga[:idx_date].strip()
            if len(testo_prima_data) > 2:
                articolo = testo_prima_data
            elif i > 0:
                riga_sopra = righe_raw[i-1].strip()
                riga_sopra_pulita = re.sub(r"Kg\s*[\d\.,]+", "", riga_sopra).strip()
                if riga_sopra_pulita and not "Descrizione" in riga_sopra_pulita:
                    articolo = riga_sopra_pulita

            if articolo:
                articolo = re.sub(r"^\s*\(\d+\)\s*", "", articolo)
                articolo = re.sub(r"Kg\s*[\d\.,]+", "", articolo)
                articolo = re.sub(r"\d+\s*x\s*\d+(\s*x\s*\d+)?", "", articolo, flags=re.IGNORECASE)
                articolo = re.sub(r"\s{2,}", " ", articolo).strip()

            if not articolo or len(articolo) < 2:
                m_code = re.findall(r"\b(IMSCA\d+|[A-Z0-9]{4,15})\b", testo_semplice)
                if m_code and len(righe_estratte) < len(m_code):
                    articolo = m_code[len(righe_estratte)]

            if articolo and consegna:
                righe_estratte.append({
                    "CLIENTE": cliente,
                    "N. ORDINE": n_ordine,
                    "ARTICOLO": articolo,
                    "CONSEGNA": consegna,
                    "QUANTITÀ": qta,
                    "PREZZO": prezzo
                })

    return righe_estratte

# ---------------------------------------------------------
# INTERFACCIA STREAMLIT A SCHEDE (TABS)
# ---------------------------------------------------------
st.title("📦 Gestionale Ordini PDF (Cloud Supabase)")

if "db_ordini" not in st.session_state:
    st.session_state.db_ordini = carica_db_cloud()

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "select_all_state" not in st.session_state:
    st.session_state.select_all_state = False

tab_database, tab_grafici = st.tabs(["📋 Database Ordini", "📈 Analisi & Grafici"])

# =========================================================
# SCHEDA 1: DATABASE ORDINI & UPLOAD
# =========================================================
with tab_database:
    st.subheader("1. Carica le Conferme d'Ordine")
    
    uploaded_files = st.file_uploader(
        "Trascina qui i file PDF degli ordini", 
        type=["pdf"], 
        accept_multiple_files=True,
        key=f"uploader_{st.session_state.uploader_key}"
    )

    col_proc, col_clear, _ = st.columns([1.5, 2, 4])
    
    with col_proc:
        btn_processa = st.button("⚙️ Processa PDF", type="primary")
        
    with col_clear:
        if st.button("🧹 Svuota PDF Caricati"):
            st.session_state.uploader_key += 1
            st.rerun()

    if btn_processa:
        if uploaded_files:
            nuovi_dati = []
            for pdf_file in uploaded_files:
                dati = estrai_dati_pdf(pdf_file)
                nuovi_dati.extend(dati)
            
            if nuovi_dati:
                if inserisci_ordini_cloud(nuovi_dati):
                    st.session_state.db_ordini = carica_db_cloud()
                    st.success(f"Elaborati {len(uploaded_files)} PDF e salvati nel Cloud con successo!")
                    st.rerun()
            else:
                st.error("Impossibile estrarre dati validi dal PDF.")
        else:
            st.warning("Carica prima almeno un file PDF!")

    st.divider()

    st.subheader("2. Tabella Ordini in Database Cloud")
    
    if st.button("🔄 Ricarica Dati dal Cloud"):
        st.session_state.db_ordini = carica_db_cloud()
        st.rerun()

    df_attuale = st.session_state.db_ordini

    if not df_attuale.empty:
        st.sidebar.header("🔍 Filtri Tabella")
        
        anni_disponibili = set()
        for data in df_attuale["CONSEGNA"].dropna():
            match_anno = re.search(r"\d{2}/\d{2}/(\d{4})", str(data))
            if match_anno:
                anni_disponibili.add(match_anno.group(1))
                
        lista_anni = ["Tutti"] + sorted(list(anni_disponibili), reverse=True)
        anno_selezionato = st.sidebar.selectbox("Filtra per ANNO CONSEGNA:", lista_anni, key="filter_anno")

        lista_clienti = ["Tutti"] + sorted([str(x) for x in df_attuale["CLIENTE"].unique() if str(x).strip()])
        cliente_selezionato = st.sidebar.selectbox("Filtra per CLIENTE:", lista_clienti, key="filter_cliente")
        
        lista_articoli = ["Tutti"] + sorted([str(x) for x in df_attuale["ARTICOLO"].unique() if str(x).strip()])
        articolo_selezionato = st.sidebar.selectbox("Filtra per ARTICOLO:", lista_articoli, key="filter_art")
        
        st.sidebar.divider()
        st.sidebar.header("🔀 Ordinamento Tabella")
        colonna_ordinamento = st.sidebar.selectbox(
            "Ordina per:",
            ["Nessuno", "CONSEGNA", "CLIENTE", "ARTICOLO", "N. ORDINE", "QUANTITÀ", "PREZZO"],
            key="sort_col"
        )
        ordine_direzione = st.sidebar.radio(
            "Ordine:",
            ["Crescente (A-Z / 0-9)", "Decrescente (Z-A / 9-0)"],
            key="sort_dir"
        )

        df_filtrato = df_attuale.copy()

        if anno_selezionato != "Tutti":
            df_filtrato = df_filtrato[df_filtrato["CONSEGNA"].astype(str).str.endswith(f"/{anno_selezionato}")]

        if cliente_selezionato != "Tutti":
            df_filtrato = df_filtrato[df_filtrato["CLIENTE"] == cliente_selezionato]

        if articolo_selezionato != "Tutti":
            df_filtrato = df_filtrato[df_filtrato["ARTICOLO"] == articolo_selezionato]

        if colonna_ordinamento != "Nessuno":
            ascending = (ordine_direzione == "Crescente (A-Z / 0-9)")
            if colonna_ordinamento == "CONSEGNA":
                df_filtrato["_sort_dt"] = pd.to_datetime(df_filtrato["CONSEGNA"], format="%d/%m/%Y", errors="coerce")
                df_filtrato = df_filtrato.sort_values("_sort_dt", ascending=ascending).drop(columns=["_sort_dt"])
            elif colonna_ordinamento in ["QUANTITÀ", "PREZZO"]:
                df_filtrato["_sort_num"] = df_filtrato[colonna_ordinamento].astype(str).str.replace(".", "", regex=False).str.replace("€", "", regex=False).str.replace(",", ".", regex=False)
                df_filtrato["_sort_num"] = pd.to_numeric(df_filtrato["_sort_num"], errors="coerce")
                df_filtrato = df_filtrato.sort_values("_sort_num", ascending=ascending).drop(columns=["_sort_num"])
            else:
                df_filtrato = df_filtrato.sort_values(colonna_ordinamento, ascending=ascending)

        c1, c2, c3 = st.columns(3)
        c1.metric("Righe Visibili", len(df_filtrato))
        c2.metric("Clienti Distinti", df_filtrato["CLIENTE"].nunique())
        c3.metric("Articoli Distinti", df_filtrato["ARTICOLO"].nunique())

        # Rimuove la colonna id per la visualizzazione pulita in tabella
        df_display = df_filtrato.drop(columns=["id"], errors="ignore").copy()
        df_display.insert(0, "Seleziona", st.session_state.select_all_state)

        edited_df = st.data_editor(
            df_display, 
            use_container_width=True, 
            num_rows="dynamic",
            key="editor_ordini"
        )

        col_sel_all, col_del, col_exp = st.columns([1.5, 1.5, 2])
        
        with col_sel_all:
            if st.button("☑️ Seleziona Tutte le Righe"):
                st.session_state.select_all_state = True
                st.rerun()

        with col_del:
            if st.button("🗑️ Elimina Righe Selezionate"):
                righe_da_eliminare = edited_df[edited_df["Seleziona"] == True]
                if not righe_da_eliminare.empty:
                    indici_visibili = righe_da_eliminare.index
                    ids_da_eliminare = df_filtrato.loc[indici_visibili, "id"].tolist()
                    for item_id in ids_da_eliminare:
                        if item_id:
                            supabase.table("ordini").delete().eq("id", item_id).execute()
                    st.session_state.db_ordini = carica_db_cloud()
                    st.session_state.select_all_state = False
                    st.success(f"Eliminate {len(ids_da_eliminare)} righe dal Cloud!")
                    st.rerun()
                else:
                    st.warning("Seleziona prima le righe da eliminare.")

        with col_exp:
            csv = df_filtrato.drop(columns=["id"], errors="ignore").to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Scarica Tabella (CSV)",
                data=csv,
                file_name='database_ordini_cloud.csv',
                mime='text/csv',
            )

        # ---------------------------------------------------------
        # MODIFICA / UNIFICA RAGIONE SOCIALE
        # ---------------------------------------------------------
        st.divider()
        st.subheader("✏️ Modifica / Unifica Ragione Sociale")
        st.caption("Seleziona una o più righe dalla tabella in alto spuntando la casella 'Seleziona', poi imposta la nuova ragione sociale qui sotto.")

        col_rename_1, col_rename_2, col_btn = st.columns([2, 2, 1.5])

        with col_rename_1:
            clienti_esistenti = sorted([str(x) for x in st.session_state.db_ordini["CLIENTE"].unique() if str(x).strip()])
            cliente_scelto = st.selectbox("Scegli tra i clienti in database:", ["-- Seleziona o scrivi a destra --"] + clienti_esistenti, key="sel_cli_rename")

        with col_rename_2:
            nuovo_nome_input = st.text_input("Oppure digita una nuova ragione sociale:", placeholder="Es. CASEIFICIO F.LLI MARTIGNONI MARIO E", key="txt_cli_rename")

        with col_btn:
            st.write("")
            st.write("")
            btn_unifica = st.button("🔄 Aggiorna Cliente", type="primary", key="btn_cli_rename")

        if btn_unifica:
            righe_selezionate = edited_df[edited_df["Seleziona"] == True]
            nome_finale = nuovo_nome_input.strip()
            if not nome_finale and cliente_scelto != "-- Seleziona o scrivi a destra --":
                nome_finale = cliente_scelto

            if righe_selezionate.empty:
                st.warning("Seleziona almeno una riga spuntando la casella 'Seleziona' nella tabella sopra!")
            elif not nome_finale:
                st.warning("Inserisci o seleziona una ragione sociale valida.")
            else:
                indici_visibili = righe_selezionate.index
                ids_da_aggiornare = df_filtrato.loc[indici_visibili, "id"].tolist()
                for item_id in ids_da_aggiornare:
                    if item_id:
                        supabase.table("ordini").update({"cliente": nome_finale}).eq("id", item_id).execute()
                st.session_state.db_ordini = carica_db_cloud()
                st.session_state.select_all_state = False
                st.success(f"Aggiornate {len(ids_da_aggiornare)} righe con la ragione sociale: '{nome_finale}'!")
                st.rerun()

        # ---------------------------------------------------------
        # MODIFICA / UNIFICA NOME ARTICOLO
        # ---------------------------------------------------------
        st.subheader("🏷️ Modifica / Unifica Nome Articolo")
        st.caption("Seleziona una o più righe dalla tabella in alto spuntando la casella 'Seleziona', poi imposta il nuovo nome articolo qui sotto.")

        col_art_1, col_art_2, col_art_btn = st.columns([2, 2, 1.5])

        with col_art_1:
            articoli_esistenti = sorted([str(x) for x in st.session_state.db_ordini["ARTICOLO"].unique() if str(x).strip()])
            articolo_scelto = st.selectbox("Scegli tra gli articoli in database:", ["-- Seleziona o scrivi a destra --"] + articoli_esistenti, key="sel_art_rename")

        with col_art_2:
            nuovo_articolo_input = st.text_input("Oppure digita un nuovo nome articolo:", placeholder="Es. RIF.RICOTTA KBMK363 C", key="txt_art_rename")

        with col_art_btn:
            st.write("")
            st.write("")
            btn_unifica_art = st.button("🔄 Aggiorna Articolo", type="primary", key="btn_art_rename")

        if btn_unifica_art:
            righe_selezionate = edited_df[edited_df["Seleziona"] == True]
            art_finale = nuovo_articolo_input.strip()
            if not art_finale and articolo_scelto != "-- Seleziona o scrivi a destra --":
                art_finale = articolo_scelto

            if righe_selezionate.empty:
                st.warning("Seleziona almeno una riga spuntando la casella 'Seleziona' nella tabella sopra!")
            elif not art_finale:
                st.warning("Inserisci o seleziona un nome articolo valido.")
            else:
                indici_visibili = righe_selezionate.index
                ids_da_aggiornare = df_filtrato.loc[indici_visibili, "id"].tolist()
                for item_id in ids_da_aggiornare:
                    if item_id:
                        supabase.table("ordini").update({"articolo": art_finale}).eq("id", item_id).execute()
                st.session_state.db_ordini = carica_db_cloud()
                st.session_state.select_all_state = False
                st.success(f"Aggiornate {len(ids_da_aggiornare)} righe con l'articolo: '{art_finale}'!")
                st.rerun()

    else:
        st.info("Nessun ordine presente nel database Cloud. Carica dei PDF per iniziare.")

# =========================================================
# SCHEDA 2: ANALISI PREZZO NEL TEMPO
# =========================================================
with tab_grafici:
    st.subheader("📊 Andamento Prezzo per Articolo (Mese/Anno)")
    
    df_chart = st.session_state.db_ordini.copy()
    
    if not df_chart.empty:
        col_f1, col_f2 = st.columns(2)
        
        clienti_g = sorted([str(x) for x in df_chart["CLIENTE"].unique() if str(x).strip()])
        sel_cliente_g = col_f1.selectbox("Seleziona CLIENTE:", ["Tutti"] + clienti_g, key="g_cliente")
        
        if sel_cliente_g != "Tutti":
            df_chart = df_chart[df_chart["CLIENTE"] == sel_cliente_g]
            
        articoli_g = sorted([str(x) for x in df_chart["ARTICOLO"].unique() if str(x).strip()])
        sel_art_g = col_f2.selectbox("Seleziona ARTICOLO:", articoli_g, key="g_articolo") if articoli_g else None

        if sel_art_g:
            df_art = df_chart[df_chart["ARTICOLO"] == sel_art_g].copy()
            
            df_art["DATA_DT"] = pd.to_datetime(df_art["CONSEGNA"], format="%d/%m/%Y", errors="coerce")
            df_art = df_art.dropna(subset=["DATA_DT"]).sort_values("DATA_DT")
            df_art["ANNO_MESE"] = df_art["DATA_DT"].dt.strftime("%Y-%m")

            def converti_prezzo(val):
                val_str = str(val).replace("€", "").strip().replace(",", ".")
                try:
                    return float(val_str)
                except ValueError:
                    return None

            df_art["PREZZO_NUM"] = df_art["PREZZO"].apply(converti_prezzo)
            df_art = df_art.dropna(subset=["PREZZO_NUM"])

            if not df_art.empty:
                df_grouped = df_art.groupby("ANNO_MESE")["PREZZO_NUM"].mean().reset_index()
                df_grouped.set_index("ANNO_MESE", inplace=True)
                df_grouped.rename(columns={"PREZZO_NUM": f"Prezzo Medio Unitario € ({sel_art_g})"}, inplace=True)

                st.line_chart(df_grouped)

                st.write("📋 Dettaglio ordini e prezzi trovati:")
                st.dataframe(
                    df_art[["CLIENTE", "N. ORDINE", "CONSEGNA", "QUANTITÀ", "PREZZO"]], 
                    use_container_width=True
                )
            else:
                st.warning("Nessun prezzo valido trovato per l'articolo selezionato.")
    else:
        st.info("Carica dei file PDF nella prima scheda per generare i grafici.")
