import streamlit as st
import pandas as pd
import re
import inspect
import importlib
import time
from rapidfuzz import process, fuzz

from pdf_import import (
    estrai_dati_pdf,
    valida_riga_importazione,
    classifica_righe_importazione,
)
import previsionale as previsionale_module

VERSIONE_MODULO_PREVISIONALE_ATTESA = "6H"

if getattr(previsionale_module, "VERSIONE_PREVISIONALE", None) != VERSIONE_MODULO_PREVISIONALE_ATTESA:
    previsionale_module = importlib.reload(previsionale_module)

calcola_previsionale = previsionale_module.calcola_previsionale

st.set_page_config(page_title="Gestionale Ordini Cloud", layout="wide")

# ---------------------------------------------------------
# SISTEMA DI AUTENTICAZIONE PASSWORD
# ---------------------------------------------------------
APP_PASSWORD = st.secrets["app"]["password"]

def verifica_password():
    if "autenticato" not in st.session_state:
        st.session_state.autenticato = False

    if not st.session_state.autenticato:
        st.title("🔒 Accesso Riservato")
        st.subheader("Gestionale Ordini & Monitoraggio Visite")
        
        pwd_input = st.text_input("Inserisci la password di accesso:", type="password", key="login_pwd_input")
        btn_login = st.button("Accedi", type="primary")

        if btn_login:
            if pwd_input == APP_PASSWORD:
                st.session_state.autenticato = True
                st.success("Accesso effettuato!")
                st.rerun()
            else:
                st.error("Password errata. Riprova.")
        return False
    return True

if not verifica_password():
    st.stop()

from database import (
    supabase,
    carica_db_cloud,
    inserisci_ordini_cloud,
    rinomina_articolo_cloud,
    carica_coppie_ignorate_cloud,
    aggiungi_coppia_ignorata_cloud,
    rimuovi_ultima_coppia_ignorata_cloud,
    svuota_coppie_ignorate_cloud,
    carica_mappatura_calendar_cloud,
    aggiungi_mappatura_calendar_cloud,
    rimuovi_mappatura_calendar_cloud,
    svuota_mappatura_calendar_cloud,
    carica_clienti_ignorati_visite_cloud,
    aggiungi_clienti_ignorati_visite_cloud,
    rimuovi_cliente_ignorato_visita_cloud,
    svuota_clienti_ignorati_visite_cloud,
    carica_articoli_ignorati_prev_cloud,
    aggiungi_articoli_ignorati_prev_cloud,
    rimuovi_articolo_ignorato_prev_cloud,
    svuota_articoli_ignorati_prev_cloud,
)

from calendar_service import ottieni_visite_calendar

# ---------------------------------------------------------
# DIAGNOSTICA PRESTAZIONI 5F
# ---------------------------------------------------------
_run_start_perf = time.perf_counter()

if "performance_metrics" not in st.session_state:
    st.session_state.performance_metrics = {}

def registra_tempo(nome, inizio):
    """Salva in millisecondi l'ultima durata misurata per un'operazione."""
    durata_ms = (time.perf_counter() - inizio) * 1000
    st.session_state.performance_metrics[nome] = round(durata_ms, 1)
    return durata_ms

# ---------------------------------------------------------
# CALCOLO FUZZY CON CACHE
# ---------------------------------------------------------
@st.cache_data(show_spinner=False)
def calcola_coppie_fuzzy_cached(articoli_con_conteggi, soglia):
    """
    Calcola le potenziali coppie fuzzy e memorizza il risultato.

    La cache dipende solo dagli articoli, dai relativi conteggi e dalla soglia.
    Le coppie ignorate vengono filtrate successivamente, così un semplice
    ignora/ripristina non costringe a rifare tutti i confronti.
    """
    articoli_unici = [articolo for articolo, _ in articoli_con_conteggi]
    conteggi = dict(articoli_con_conteggi)

    coppie_candidate = []
    processati = set()

    for idx, art_a in enumerate(articoli_unici):
        if art_a in processati:
            continue

        match = process.extract(
            art_a,
            articoli_unici[idx + 1:],
            scorer=fuzz.token_sort_ratio,
            score_cutoff=soglia
        )

        for art_b, score, _ in match:
            coppia_key = tuple(sorted([art_a, art_b]))
            coppie_candidate.append({
                "key": coppia_key,
                "Articolo A": art_a,
                "Articolo B": art_b,
                "Somiglianza": f"{round(score)}%",
                "Conteggio A": conteggi.get(art_a, 0),
                "Conteggio B": conteggi.get(art_b, 0)
            })
            processati.add(art_b)

    return coppie_candidate


# ---------------------------------------------------------
# PREVISIONALE CON CACHE
# ---------------------------------------------------------
VERSIONE_CACHE_PREVISIONALE = "6H"

@st.cache_data(show_spinner=False)
def calcola_previsionale_cached(df_ordini, giorno_cache, versione_cache):
    """
    Riutilizza il risultato finché database, giorno e versione del calcolo
    non cambiano.

    versione_cache evita che Streamlit possa riutilizzare un DataFrame
    calcolato con una versione precedente di previsionale.py.
    """
    _ = versione_cache
    return calcola_previsionale(df_ordini)


# ---------------------------------------------------------
# INTERFACCIA STREAMLIT A TABS (6 SCHEDE)
# ---------------------------------------------------------
col_h1, col_h2 = st.columns([5, 1])
with col_h1:
    st.title("📦 Gestionale Ordini PDF (Cloud Supabase)")
with col_h2:
    st.write("")
    if st.button("🔒 Disconnetti"):
        st.session_state.autenticato = False
        st.rerun()

if "db_ordini" not in st.session_state:
    _t_perf = time.perf_counter()
    st.session_state.db_ordini = carica_db_cloud()
    registra_tempo("Supabase · caricamento iniziale ordini", _t_perf)

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "dati_pdf_in_attesa" not in st.session_state:
    st.session_state.dati_pdf_in_attesa = []

if "select_all_state" not in st.session_state:
    st.session_state.select_all_state = False

if "select_all_visite_state" not in st.session_state:
    st.session_state.select_all_visite_state = False

if "select_all_prev_state" not in st.session_state:
    st.session_state.select_all_prev_state = False

if "coppie_ignorate_list" not in st.session_state:
    _t_perf = time.perf_counter()
    st.session_state.coppie_ignorate_list = carica_coppie_ignorate_cloud()
    registra_tempo("Supabase · coppie ignorate Fuzzy", _t_perf)

if "clienti_ignorati_visite_list" not in st.session_state:
    _t_perf = time.perf_counter()
    st.session_state.clienti_ignorati_visite_list = carica_clienti_ignorati_visite_cloud()
    registra_tempo("Supabase · clienti esclusi Visite", _t_perf)

if "articoli_ignorati_prev_list" not in st.session_state:
    _t_perf = time.perf_counter()
    st.session_state.articoli_ignorati_prev_list = carica_articoli_ignorati_prev_cloud()
    registra_tempo("Supabase · esclusioni Previsionale", _t_perf)

if "mappa_custom_calendar" not in st.session_state:
    _t_perf = time.perf_counter()
    st.session_state.mappa_custom_calendar = carica_mappatura_calendar_cloud()
    registra_tempo("Supabase · mappatura Calendar", _t_perf)

etichette_tabs = [
    "📋 Database Ordini",
    "📈 Analisi & Grafici",
    "🏷️ Normalizzazione Cliente",
    "🤖 Pulizia Smart (Fuzzy)",
    "🔮 Previsionale Riordini",
    "📅 Monitoraggio Visite",
]

try:
    tabs_lazy_supportate = "on_change" in inspect.signature(st.tabs).parameters
except (TypeError, ValueError):
    tabs_lazy_supportate = False

if tabs_lazy_supportate:
    (
        tab_database,
        tab_grafici,
        tab_norm_cli,
        tab_fuzzy,
        tab_previsionale,
        tab_visite,
    ) = st.tabs(
        etichette_tabs,
        key="tabs_principali",
        on_change="rerun",
    )
else:
    # Compatibilità con versioni Streamlit precedenti alla 1.55.
    (
        tab_database,
        tab_grafici,
        tab_norm_cli,
        tab_fuzzy,
        tab_previsionale,
        tab_visite,
    ) = st.tabs(etichette_tabs)

# =========================================================
# SCHEDA 1: DATABASE ORDINI & UPLOAD
# =========================================================
if not tabs_lazy_supportate or getattr(tab_database, "open", False):
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
                st.session_state.dati_pdf_in_attesa = []
                st.rerun()

        if btn_processa:
            if uploaded_files:
                nuovi_dati = []

                for pdf_file in uploaded_files:
                    dati = estrai_dati_pdf(pdf_file)

                    for riga in dati:
                        riga["FILE SORGENTE"] = pdf_file.name

                    nuovi_dati.extend(dati)

                if nuovi_dati:
                    st.session_state.dati_pdf_in_attesa = classifica_righe_importazione(
                        nuovi_dati,
                        st.session_state.db_ordini
                    )
                else:
                    st.session_state.dati_pdf_in_attesa = []
                    st.error("Impossibile estrarre dati validi dal PDF.")
            else:
                st.warning("Carica prima almeno un file PDF!")

        # ---------------------------------------------------------
        # ANTEPRIMA DATI ESTRATTI PRIMA DEL SALVATAGGIO
        # ---------------------------------------------------------
        if st.session_state.dati_pdf_in_attesa:
            st.subheader("🔍 Anteprima dati estratti")

            df_anteprima = pd.DataFrame(st.session_state.dati_pdf_in_attesa)

            colonne_prioritarie = [
                c for c in ["FILE SORGENTE", "STATO", "AVVISI"]
                if c in df_anteprima.columns
            ]
            altre_colonne = [
                c for c in df_anteprima.columns
                if c not in colonne_prioritarie
            ]
            df_anteprima = df_anteprima[colonne_prioritarie + altre_colonne]

            st.dataframe(
                df_anteprima,
                use_container_width=True,
                hide_index=True
            )

            conteggio_nuove = int((df_anteprima["STATO"] == "🟢 NUOVO").sum()) if "STATO" in df_anteprima.columns else len(df_anteprima)
            conteggio_presenti = int((df_anteprima["STATO"] == "🔴 GIÀ PRESENTE").sum()) if "STATO" in df_anteprima.columns else 0
            conteggio_verifica = int((df_anteprima["STATO"] == "🟡 DA VERIFICARE").sum()) if "STATO" in df_anteprima.columns else 0
            conteggio_avvisi = int((df_anteprima["AVVISI"] != "✅ OK").sum()) if "AVVISI" in df_anteprima.columns else 0

            st.info(
                f"Righe estratte: {len(df_anteprima)} | "
                f"🟢 Nuove: {conteggio_nuove} | "
                f"🔴 Già presenti: {conteggio_presenti} | "
                f"🟡 Da verificare: {conteggio_verifica} | "
                f"⚠️ Con avvisi: {conteggio_avvisi}"
            )

            if conteggio_avvisi > 0:
                st.warning(
                    "Alcune righe hanno campi mancanti o formati sospetti. "
                    "Gli avvisi sono solo informativi: nessuna riga viene bloccata automaticamente."
                )

            if conteggio_presenti > 0:
                st.warning(
                    "Le righe 🔴 GIÀ PRESENTE non verranno reinserite nel database."
                )

            if conteggio_verifica > 0:
                st.warning(
                    "Le righe 🟡 DA VERIFICARE hanno lo stesso cliente e numero ordine "
                    "di righe già presenti, ma dati differenti. Verranno salvate se confermi: "
                    "controllale prima di procedere."
                )

            righe_da_salvare = [
                riga for riga in st.session_state.dati_pdf_in_attesa
                if riga.get("STATO") != "🔴 GIÀ PRESENTE"
            ]

            if righe_da_salvare:
                if st.button("✅ Conferma e salva nel database", type="primary"):
                    if inserisci_ordini_cloud(righe_da_salvare):
                        st.session_state.db_ordini = carica_db_cloud()
                        st.session_state.dati_pdf_in_attesa = []
                        st.success(
                            f"Salvate {len(righe_da_salvare)} righe nel Cloud. "
                            f"Escluse {conteggio_presenti} righe già presenti."
                        )
                        st.rerun()
            else:
                st.success(
                    "Tutte le righe estratte risultano già presenti nel database. "
                    "Non c'è nulla da salvare."
                )

        st.divider()

        st.subheader("2. Tabella Ordini in Database Cloud")
        
        if st.button("🔄 Ricarica Dati dal Cloud"):
            _t_perf = time.perf_counter()
            st.session_state.db_ordini = carica_db_cloud()
            registra_tempo("Supabase · ricarica manuale ordini", _t_perf)
            st.rerun()

        df_attuale = st.session_state.db_ordini

        if not df_attuale.empty:
            _t_db_prep = time.perf_counter()
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

            # Manteniamo l'ID Supabase associato direttamente a ogni riga.
            # L'ID resta nascosto nell'interfaccia ma viene usato per
            # eliminazioni e aggiornamenti sicuri, indipendentemente da filtri
            # e ordinamenti.
            df_display = df_filtrato.copy()
            df_display.insert(0, "Seleziona", st.session_state.select_all_state)

            colonne_bloccate = [
                col for col in df_display.columns
                if col != "Seleziona"
            ]

            registra_tempo("Database · filtri, ordinamento e preparazione tabella", _t_db_prep)

            _t_editor = time.perf_counter()
            edited_df = st.data_editor(
                df_display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "id": None,
                    "Seleziona": st.column_config.CheckboxColumn(
                        "Seleziona",
                        help="Spunta le righe su cui vuoi eseguire un'operazione."
                    ),
                },
                disabled=colonne_bloccate,
                key="editor_ordini"
            )
            registra_tempo("Database · creazione data_editor (server)", _t_editor)

            col_sel_all, col_unsel_all, col_del, col_exp = st.columns([1.5, 1.5, 1.8, 1.8])
            
            with col_sel_all:
                if st.button("☑️ Seleziona Tutte"):
                    st.session_state.select_all_state = True
                    st.rerun()

            with col_unsel_all:
                if st.button("⬜ Deseleziona Tutte"):
                    st.session_state.select_all_state = False
                    st.rerun()

            with col_del:
                with st.popover("🗑️ Elimina Selezionate"):
                    righe_da_eliminare = edited_df[edited_df["Seleziona"] == True]
                    count_del = len(righe_da_eliminare)
                    if count_del > 0:
                        st.write("⚠️ **Conferma eliminazione**")
                        st.caption(f"Sei sicuro di voler eliminare **{count_del}** righe dal database Cloud?")
                        if st.button("Sì, elimina definitivamente", type="primary", key="btn_confirm_delete_rows"):
                            ids_da_eliminare = [
                                item_id
                                for item_id in righe_da_eliminare["id"].tolist()
                                if str(item_id).strip()
                            ]
                            if ids_da_eliminare:
                                supabase.table("ordini").delete().in_("id", ids_da_eliminare).execute()
                            st.session_state.db_ordini = carica_db_cloud()
                            st.session_state.select_all_state = False
                            st.success(f"Eliminate {len(ids_da_eliminare)} righe dal Cloud!")
                            st.rerun()
                    else:
                        st.info("Spunta prima la casella 'Seleziona' sulle righe da eliminare.")

            with col_exp:
                csv = df_filtrato.drop(columns=["id"], errors="ignore").to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Scarica CSV",
                    data=csv,
                    file_name='database_ordini_cloud.csv',
                    mime='text/csv',
                )

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
                    ids_da_aggiornare = [
                        item_id
                        for item_id in righe_selezionate["id"].tolist()
                        if str(item_id).strip()
                    ]
                    if ids_da_aggiornare:
                        supabase.table("ordini").update(
                            {"cliente": nome_finale}
                        ).in_("id", ids_da_aggiornare).execute()
                    st.session_state.db_ordini = carica_db_cloud()
                    st.session_state.select_all_state = False
                    st.success(f"Aggiornate {len(ids_da_aggiornare)} righe con la ragione sociale: '{nome_finale}'!")
                    st.rerun()

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
                    ids_da_aggiornare = [
                        item_id
                        for item_id in righe_selezionate["id"].tolist()
                        if str(item_id).strip()
                    ]
                    if ids_da_aggiornare:
                        supabase.table("ordini").update(
                            {"articolo": art_finale}
                        ).in_("id", ids_da_aggiornare).execute()
                    st.session_state.db_ordini = carica_db_cloud()
                    st.session_state.select_all_state = False
                    st.success(f"Aggiornate {len(ids_da_aggiornare)} righe con l'articolo: '{art_finale}'!")
                    st.rerun()

        else:
            st.info("Nessun ordine presente nel database Cloud. Carica dei PDF per iniziare.")
# =========================================================
# SCHEDA 2: ANALISI PREZZO NEL TEMPO
# =========================================================
if not tabs_lazy_supportate or getattr(tab_grafici, "open", False):
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
# =========================================================
# SCHEDA 3: NORMALIZZAZIONE VELOCE PER CLIENTE
# =========================================================
if not tabs_lazy_supportate or getattr(tab_norm_cli, "open", False):
    with tab_norm_cli:
        st.subheader("🏷️ Normalizzazione Veloce Articoli per Cliente")
        st.markdown("Seleziona un cliente per visualizzare l'elenco dei suoi articoli in database, vedere quante volte compaiono e unificare le varianti obsolete in un solo clic.")

        df_nc = st.session_state.db_ordini
        if not df_nc.empty:
            list_clienti_nc = sorted([x for x in df_nc["CLIENTE"].unique() if str(x).strip()])
            sel_cli_nc = st.selectbox("👤 Seleziona Cliente:", ["-- Seleziona un cliente --"] + list_clienti_nc, key="nc_cli")

            if sel_cli_nc != "-- Seleziona un cliente --":
                df_cli_nc = df_nc[df_nc["CLIENTE"] == sel_cli_nc]
                
                art_counts = df_cli_nc["ARTICOLO"].value_counts().reset_index()
                art_counts.columns = ["ARTICOLO", "N° ORDINI"]

                col_list, col_action = st.columns([3, 2])

                with col_list:
                    st.markdown(f"### Articoli trovati per **{sel_cli_nc}** ({len(art_counts)} distinti)")
                    st.dataframe(art_counts, use_container_width=True)

                with col_action:
                    st.markdown("### 🔄 Unifica due articoli")
                    st.caption("Seleziona l'articolo da sostituire e quello definitivo da mantenere.")

                    articoli_cli_list = sorted(art_counts["ARTICOLO"].tolist())
                    
                    art_da_cambiare = st.selectbox("❌ Articolo da SOSTITUIRE (obsoleto/errato):", ["-- Seleziona --"] + articoli_cli_list, key="nc_from")
                    
                    articoli_dest_list = [a for a in articoli_cli_list if a != art_da_cambiare]
                    art_destinazione = st.selectbox("✅ Nuovo nome CORRETTO (da applicare):", ["-- Seleziona o scrivi sotto --"] + articoli_dest_list, key="nc_to_sel")
                    
                    art_dest_custom = st.text_input("Oppure digita un nuovo nome valido:", placeholder="Digita qui...", key="nc_to_txt")

                    nome_definitivo = art_dest_custom.strip() if art_dest_custom.strip() else (art_destinazione if art_destinazione != "-- Seleziona o scrivi sotto --" else "")

                    if st.button("🚀 Unifica per questo Cliente", type="primary", key="btn_nc_apply"):
                        if art_da_cambiare == "-- Seleziona --":
                            st.warning("Seleziona prima l'articolo da sostituire.")
                        elif not nome_definitivo:
                            st.warning("Seleziona o digita il nome dell'articolo corretto.")
                        else:
                            if rinomina_articolo_cloud(art_da_cambiare, nome_definitivo, cliente=sel_cli_nc):
                                st.success(f"Tutti gli ordini di '{art_da_cambiare}' per {sel_cli_nc} sono stati rinominati in '{nome_definitivo}'!")
                                st.session_state.db_ordini = carica_db_cloud()
                                st.rerun()
        else:
            st.warning("Database vuoto o in fase di caricamento.")
# =========================================================
# SCHEDA 4: PULIZIA SMART (FUZZY MATCHING CON PERSISTENZA CLOUD)
# =========================================================
if not tabs_lazy_supportate or getattr(tab_fuzzy, "open", False):
    with tab_fuzzy:
        st.subheader("🤖 Rilevamento Automatico Duplicati e Varianti")
        st.markdown("Questa funzione confronta gli articoli in database e trova le varianti quasi identiche per unificarle con un clic.")

        df_fz = st.session_state.db_ordini
        if not df_fz.empty:
            col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
            
            list_cli = ["Tutti i Clienti"] + sorted([x for x in df_fz["CLIENTE"].unique() if str(x).strip()])
            target_cli = col_f1.selectbox("Seleziona Cliente da analizzare:", list_cli, key="fz_cli")
            soglia = col_f2.slider("Soglia di somiglianza (%):", min_value=70, max_value=98, value=85, step=1)
            
            if col_f3.button("🔄 Ricarica DB Cloud", key="btn_fz_reload"):
                st.session_state.db_ordini = carica_db_cloud()
                st.session_state.coppie_ignorate_list = carica_coppie_ignorate_cloud()
                st.rerun()

            if target_cli != "Tutti i Clienti":
                df_work = df_fz[df_fz["CLIENTE"] == target_cli]
            else:
                df_work = df_fz

            articoli_unici = sorted([a for a in df_work["ARTICOLO"].unique() if str(a).strip()])
            st.info(f"Articoli distinti da analizzare: **{len(articoli_unici)}**")

            # Prepariamo una firma compatta dei dati rilevanti.
            # Se articoli, conteggi e soglia non cambiano, Streamlit riutilizza
            # il risultato fuzzy già calcolato invece di rifare tutti i confronti.
            conteggi_articoli = df_work["ARTICOLO"].value_counts()
            articoli_con_conteggi = tuple(
                (articolo, int(conteggi_articoli.get(articolo, 0)))
                for articolo in articoli_unici
            )

            _t_fuzzy = time.perf_counter()
            coppie_candidate = calcola_coppie_fuzzy_cached(
                articoli_con_conteggi,
                soglia
            )
            registra_tempo("Fuzzy · calcolo/copia da cache", _t_fuzzy)

            set_ignorate = set(st.session_state.coppie_ignorate_list)
            coppie_trovate = [
                coppia
                for coppia in coppie_candidate
                if coppia["key"] not in set_ignorate
            ]

            col_bar1, col_bar2, col_bar3 = st.columns([1.8, 1.8, 2.2])

            if st.session_state.coppie_ignorate_list:
                with col_bar1:
                    with st.popover(f"👁️ Ripristina {len(st.session_state.coppie_ignorate_list)} ignorate"):
                        st.write("⚠️ **Conferma ripristino**")
                        st.caption("Vuoi far ricomparire tutte le coppie precedentemente ignorate?")
                        if st.button("Sì, ripristina tutte", type="primary", key="btn_confirm_all_restore"):
                            if svuota_coppie_ignorate_cloud():
                                st.session_state.coppie_ignorate_list = []
                                st.rerun()

                with col_bar2:
                    if st.button("↩️ Ripristina ultima ignorata", key="btn_undo_last"):
                        if rimuovi_ultima_coppia_ignorata_cloud():
                            st.session_state.coppie_ignorate_list = carica_coppie_ignorate_cloud()
                            st.rerun()

            if coppie_trovate:
                with col_bar3:
                    with st.popover(f"❌ Ignora tutte le {len(coppie_trovate)} coppie visibili"):
                        st.write("⚠️ **Conferma operazione**")
                        st.caption(f"Vuoi nascondere tutte le {len(coppie_trovate)} coppie attualmente in elenco?")
                        if st.button("Sì, ignora tutte", type="primary", key="btn_confirm_all_ignore"):
                            for c in coppie_trovate:
                                if c['key'] not in set_ignorate:
                                    aggiungi_coppia_ignorata_cloud(c['key'][0], c['key'][1])
                            st.session_state.coppie_ignorate_list = carica_coppie_ignorate_cloud()
                            st.rerun()

            st.divider()

            if coppie_trovate:
                st.write(f"🔍 Trovate **{len(coppie_trovate)}** potenziali corrispondenze:")
                st.divider()

                for i, c in enumerate(coppie_trovate):
                    with st.container():
                        col_head_left, col_head_right = st.columns([4, 1])
                        col_head_left.markdown(f"#### Coppia #{i+1} — Somiglianza: `{c['Somiglianza']}`")
                        
                        if col_head_right.button("❌ Ignora coppia", key=f"btn_ignore_{i}"):
                            if aggiungi_coppia_ignorata_cloud(c['key'][0], c['key'][1]):
                                st.session_state.coppie_ignorate_list = carica_coppie_ignorate_cloud()
                                st.rerun()

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
                st.success("Nessun duplicato trovato con la percentuale di somiglianza impostata.")
        else:
            st.warning("Database vuoto.")
# =========================================================
# SCHEDA 5: PREVISIONALE RIORDINI
# =========================================================
if not tabs_lazy_supportate or getattr(tab_previsionale, "open", False):
    with tab_previsionale:
        st.subheader("🔮 Previsionale Riordini (Mese Corrente & Successivo)")
        st.markdown("L'algoritmo separa le **consegne storiche** dagli **ordini futuri** e usa date storiche distinte per media, mediana e regolarità. La nuova **PRIORITÀ SOLLECITO** distingue i ritardi più credibili dalle segnalazioni che, con uno storico debole, è meglio verificare.")

        df_prev_base = st.session_state.db_ordini

        if not df_prev_base.empty:
            giorno_cache_previsionale = pd.Timestamp.now().strftime("%Y-%m-%d")
            _t_prev = time.perf_counter()
            df_prev_res = calcola_previsionale_cached(
                df_prev_base,
                giorno_cache_previsionale,
                VERSIONE_CACHE_PREVISIONALE
            )
            registra_tempo("Previsionale · calcolo/copia da cache", _t_prev)

            colonne_6h_richieste = {
                "REGOLARITÀ",
                "AFFIDABILITÀ",
                "N. STORICO",
                "FREQ. MEDIANA (GG)",
                "SCOST. MEDIA/MEDIANA",
                "PRIORITÀ SOLLECITO",
                "RITARDO STIMATO (GG)",
            }
            if not df_prev_res.empty and not colonne_6h_richieste.issubset(df_prev_res.columns):
                calcola_previsionale_cached.clear()
                df_prev_res = calcola_previsionale_cached(
                    df_prev_base,
                    giorno_cache_previsionale,
                    VERSIONE_CACHE_PREVISIONALE
                )

            if not df_prev_res.empty:
                set_prev_ignorati = set(st.session_state.articoli_ignorati_prev_list)
                if set_prev_ignorati:
                    df_prev_res["_key"] = list(zip(df_prev_res["CLIENTE"], df_prev_res["ARTICOLO"]))
                    df_prev_res = df_prev_res[~df_prev_res["_key"].isin(set_prev_ignorati)].drop(columns=["_key"])

                n_ritardo = len(df_prev_res[df_prev_res["STATO"].str.contains("Ritardo")])
                n_corr = len(df_prev_res[df_prev_res["STATO"].str.contains("Mese Corrente")])
                n_prox = len(df_prev_res[df_prev_res["STATO"].str.contains("Mese Successivo")])

                m1, m2, m3 = st.columns(3)
                m1.metric("🔴 In Ritardo (Da Sollecitare)", n_ritardo)
                m2.metric("🟡 Previsti Questo Mese", n_corr)
                m3.metric("🔵 Previsti Mese Successivo", n_prox)

                st.divider()

                col_pf1, col_pf2, col_pf3, col_pf4, col_pf5 = st.columns(
                    [1.15, 1.15, 1.05, 1.15, 0.95]
                )

                mostra_declassati = col_pf5.checkbox(
                    "Includi '⚪ Articolo Declassato'",
                    value=False,
                    key="chk_show_decl"
                )

                if not mostra_declassati:
                    df_prev_res_filtered = df_prev_res[
                        ~df_prev_res["STATO"].str.contains("Declassato")
                    ].copy()
                else:
                    df_prev_res_filtered = df_prev_res.copy()

                stati_disponibili = ["Tutti"] + sorted(
                    list(df_prev_res_filtered["STATO"].unique())
                )
                sel_stato = col_pf1.selectbox(
                    "Filtra per STATO:",
                    stati_disponibili,
                    key="prev_stato_filter"
                )

                clienti_prev = ["Tutti"] + sorted(
                    list(df_prev_res_filtered["CLIENTE"].unique())
                )
                sel_cli_p = col_pf2.selectbox(
                    "Filtra per CLIENTE:",
                    clienti_prev,
                    key="prev_cli_filter"
                )

                if "AFFIDABILITÀ" in df_prev_res_filtered.columns:
                    affidabilita_disponibili = ["Tutte"] + [
                        valore
                        for valore in ["🟢 Alta", "🟡 Media", "🔴 Bassa"]
                        if valore in set(df_prev_res_filtered["AFFIDABILITÀ"])
                    ]
                    sel_affidabilita = col_pf3.selectbox(
                        "Filtra AFFIDABILITÀ:",
                        affidabilita_disponibili,
                        key="prev_affidabilita_filter"
                    )
                else:
                    sel_affidabilita = "Tutte"
                    col_pf3.caption("⚠️ Affidabilità in aggiornamento")

                if "PRIORITÀ SOLLECITO" in df_prev_res_filtered.columns:
                    priorita_disponibili = ["Tutte"] + [
                        valore
                        for valore in ["🔴 Alta", "🟠 Media", "⚪ Da verificare"]
                        if valore in set(df_prev_res_filtered["PRIORITÀ SOLLECITO"])
                    ]
                    sel_priorita = col_pf4.selectbox(
                        "Filtra PRIORITÀ:",
                        priorita_disponibili,
                        key="prev_priorita_filter"
                    )
                else:
                    sel_priorita = "Tutte"
                    col_pf4.caption("⚠️ Priorità in aggiornamento")

                df_prev_disp = df_prev_res_filtered.copy()

                if sel_stato != "Tutti":
                    df_prev_disp = df_prev_disp[df_prev_disp["STATO"] == sel_stato]

                if sel_cli_p != "Tutti":
                    df_prev_disp = df_prev_disp[df_prev_disp["CLIENTE"] == sel_cli_p]

                if sel_affidabilita != "Tutte" and "AFFIDABILITÀ" in df_prev_disp.columns:
                    df_prev_disp = df_prev_disp[
                        df_prev_disp["AFFIDABILITÀ"] == sel_affidabilita
                    ]

                if sel_priorita != "Tutte" and "PRIORITÀ SOLLECITO" in df_prev_disp.columns:
                    df_prev_disp = df_prev_disp[
                        df_prev_disp["PRIORITÀ SOLLECITO"] == sel_priorita
                    ]

                # 8B: ordinamento esclusivamente VISIVO, dopo tutti i filtri.
                # Manteniamo l'ordine preesistente per le righe non in ritardo
                # e, a parità di priorità/giorni, anche per quelle in ritardo.
                if "PRIORITÀ SOLLECITO" in df_prev_disp.columns and "RITARDO STIMATO (GG)" in df_prev_disp.columns:
                    ordine_priorita = {
                        "🔴 Alta": 0,
                        "🟠 Media": 1,
                        "⚪ Da verificare": 2,
                    }
                    df_prev_disp = df_prev_disp.copy()
                    df_prev_disp["_ordine_priorita_ui"] = (
                        df_prev_disp["PRIORITÀ SOLLECITO"]
                        .map(ordine_priorita)
                        .fillna(3)
                        .astype(int)
                    )
                    df_prev_disp["_ritardo_ui"] = (
                        pd.to_numeric(
                            df_prev_disp["RITARDO STIMATO (GG)"],
                            errors="coerce",
                        )
                        .fillna(-1)
                    )
                    df_prev_disp = (
                        df_prev_disp
                        .sort_values(
                            by=["_ordine_priorita_ui", "_ritardo_ui"],
                            ascending=[True, False],
                            kind="mergesort",
                        )
                        .drop(columns=["_ordine_priorita_ui", "_ritardo_ui"])
                        .reset_index(drop=True)
                    )

                st.caption(f"Righe trovate: **{len(df_prev_disp)}**")
                st.caption(
                    "☎️ **PRIORITÀ SOLLECITO**: 🔴 Alta = affidabilità Alta, oppure Media con ≥30 gg di ritardo · "
                    "🟠 Media = affidabilità Media con <30 gg di ritardo · "
                    "⚪ Da verificare = affidabilità Bassa · "
                    "**RITARDO STIMATO (GG)** = giorni trascorsi dalla STIMA DA STORICO. "
                    "La priorità non modifica la previsione."
                )

                df_prev_edit = df_prev_disp.copy()
                df_prev_edit.insert(0, "Seleziona", st.session_state.select_all_prev_state)

                edited_prev_df = st.data_editor(
                    df_prev_edit,
                    use_container_width=True,
                    hide_index=True,
                    key="editor_previsionale"
                )

                col_p_sel1, col_p_sel2, col_p_ign = st.columns([1.5, 1.5, 3])

                with col_p_sel1:
                    if st.button("☑️ Seleziona Tutte", key="btn_sel_all_prev"):
                        st.session_state.select_all_prev_state = True
                        st.rerun()

                with col_p_sel2:
                    if st.button("⬜ Deseleziona Tutte", key="btn_unsel_all_prev"):
                        st.session_state.select_all_prev_state = False
                        st.rerun()

                with col_p_ign:
                    righe_selezionate_prev = edited_prev_df[edited_prev_df["Seleziona"] == True]
                    count_prev_sel = len(righe_selezionate_prev)
                    
                    if st.button(f"🚫 Escludi Selezionati ({count_prev_sel})", type="primary", key="btn_ign_selected_prev"):
                        if count_prev_sel > 0:
                            coppie_da_escludere = list(zip(righe_selezionate_prev["CLIENTE"], righe_selezionate_prev["ARTICOLO"]))
                            if aggiungi_articoli_ignorati_prev_cloud(coppie_da_escludere):
                                st.session_state.articoli_ignorati_prev_list = carica_articoli_ignorati_prev_cloud()
                                st.session_state.select_all_prev_state = False
                                st.success(f"Esclusi {count_prev_sel} articoli dal previsionale!")
                                st.rerun()
                        else:
                            st.warning("Spunta almeno una riga dalla tabella tramite la casella 'Seleziona'.")

                st.divider()

                if st.session_state.articoli_ignorati_prev_list:
                    with st.expander(f"👁️ Gestisci Articoli Esclusi dal Previsionale ({len(st.session_state.articoli_ignorati_prev_list)})"):
                        st.caption("Elenco delle coppie Cliente - Articolo attualmente escluse dal previsionale:")
                        
                        opzioni_ripristino_prev = [f"{c} ➔ {a}" for c, a in st.session_state.articoli_ignorati_prev_list]
                        
                        c_prst1, c_prst2 = st.columns([3, 1])
                        scelta_rst_prev = c_prst1.selectbox("Seleziona una voce da ripristinare:", ["-- Seleziona --"] + sorted(opzioni_ripristino_prev), key="sel_prev_rst")
                        
                        if c_prst2.button("↩️ Ripristina Selezionato", key="btn_rst_single_prev"):
                            if scelta_rst_prev != "-- Seleziona --":
                                cli_rst, art_rst = scelta_rst_prev.split(" ➔ ", 1)
                                if rimuovi_articolo_ignorato_prev_cloud(cli_rst, art_rst):
                                    st.session_state.articoli_ignorati_prev_list = carica_articoli_ignorati_prev_cloud()
                                    st.success(f"Ripristinato: {scelta_rst_prev}")
                                    st.rerun()

                        if st.button("🔄 Ripristina TUTTI gli articoli esclusi", type="primary", key="btn_rst_all_prev"):
                            if svuota_articoli_ignorati_prev_cloud():
                                st.session_state.articoli_ignorati_prev_list = []
                                st.success("Tutti gli articoli del previsionale sono stati ripristinati!")
                                st.rerun()
            else:
                st.info("Nessuna previsione di riordine calcolata per il periodo attuale.")
        else:
            st.warning("Database vuoto. Carica dei PDF per generare il previsionale.")
# =========================================================
# SCHEDA 6: MONITORAGGIO VISITE GOOGLE CALENDAR
# =========================================================
if not tabs_lazy_supportate or getattr(tab_visite, "open", False):
    with tab_visite:
        st.subheader("📅 Monitoraggio Visite Clienti (Google Calendar)")
        st.markdown("Il sistema scansiona in sola lettura il tuo **Google Calendar**, riconosce i titoli degli eventi associandoli ai clienti del database e calcola da quanti giorni non li visiti.")

        df_vis_base = st.session_state.db_ordini

        if not df_vis_base.empty:
            list_cli_db_tutti = sorted([x for x in df_vis_base["CLIENTE"].unique() if str(x).strip()])
            set_cli_ignorati = set(st.session_state.clienti_ignorati_visite_list)
            
            list_cli_db = [c for c in list_cli_db_tutti if c not in set_cli_ignorati]

            col_v1, col_v2 = st.columns([3, 1])

            with col_v2:
                st.write("")
                btn_scan_cal = st.button("🔄 Scansiona Google Calendar", type="primary", key="btn_scan_cal")

            # La scansione di Google Calendar parte solo su richiesta esplicita.
            # Evitiamo così una chiamata API automatica all'avvio della sessione
            # o durante rerun causati da interazioni nelle altre schede.
            if btn_scan_cal:
                _t_calendar = time.perf_counter()
                with st.spinner("Scansione di Google Calendar in corso..."):
                    df_vis_res = ottieni_visite_calendar(list_cli_db, st.session_state.mappa_custom_calendar)
                    st.session_state.df_visite_cache = df_vis_res
                registra_tempo("Calendar · scansione completa", _t_calendar)

            df_vis_display = st.session_state.get("df_visite_cache", pd.DataFrame())

            if not df_vis_display.empty:
                df_vis_display = df_vis_display[~df_vis_display["CLIENTE"].isin(set_cli_ignorati)]

                n_prog = len(df_vis_display[df_vis_display["STATO VISITA"] == "🔵 Programmata"])
                n_rec = len(df_vis_display[df_vis_display["STATO VISITA"].str.contains("Recente")])
                n_prog_std = len(df_vis_display[df_vis_display["STATO VISITA"].str.contains("Programmare")])
                n_urg = len(df_vis_display[df_vis_display["STATO VISITA"].str.contains("Urgente")])

                v_m0, v_m1, v_m2, v_m3 = st.columns(4)
                v_m0.metric("🔵 Visita Programmata", n_prog)
                v_m1.metric("🟢 Visitati (< 60 gg)", n_rec)
                v_m2.metric("🟡 Da Programmare (60-90 gg)", n_prog_std)
                v_m3.metric("🔴 Visita Urgente (> 90 gg)", n_urg)

                st.divider()

                col_vf1, col_vf2 = st.columns(2)
                stati_v = ["Tutti"] + sorted(list(df_vis_display["STATO VISITA"].unique()))
                sel_st_v = col_vf1.selectbox("Filtra per STATO VISITA:", stati_v, key="vf_stato")
                
                sel_cli_v = col_vf2.selectbox("Filtra per CLIENTE:", ["Tutti"] + list_cli_db, key="vf_cli")

                df_vis_filt = df_vis_display.copy()
                if sel_st_v != "Tutti":
                    df_vis_filt = df_vis_filt[df_vis_filt["STATO VISITA"] == sel_st_v]
                if sel_cli_v != "Tutti":
                    df_vis_filt = df_vis_filt[df_vis_filt["CLIENTE"] == sel_cli_v]

                df_vis_edit = df_vis_filt.copy()
                df_vis_edit.insert(0, "Seleziona", st.session_state.select_all_visite_state)

                edited_vis_df = st.data_editor(
                    df_vis_edit,
                    use_container_width=True,
                    num_rows="dynamic",
                    key="editor_visite"
                )

                col_v_sel1, col_v_sel2, col_v_ign = st.columns([1.5, 1.5, 3])

                with col_v_sel1:
                    if st.button("☑️ Seleziona Tutte", key="btn_sel_all_vis"):
                        st.session_state.select_all_visite_state = True
                        st.rerun()

                with col_v_sel2:
                    if st.button("⬜ Deseleziona Tutte", key="btn_unsel_all_vis"):
                        st.session_state.select_all_visite_state = False
                        st.rerun()

                with col_v_ign:
                    clienti_selezionati_vis = edited_vis_df[edited_vis_df["Seleziona"] == True]["CLIENTE"].tolist()
                    count_vis_sel = len(clienti_selezionati_vis)
                    
                    if st.button(f"🚫 Escludi Selezionati ({count_vis_sel})", type="primary", key="btn_ign_selected_vis"):
                        if count_vis_sel > 0:
                            if aggiungi_clienti_ignorati_visite_cloud(clienti_selezionati_vis):
                                st.session_state.clienti_ignorati_visite_list = carica_clienti_ignorati_visite_cloud()
                                st.session_state.df_visite_cache = pd.DataFrame()
                                st.session_state.select_all_visite_state = False
                                st.success(f"Esclusi {count_vis_sel} clienti con successo!")
                                st.rerun()
                        else:
                            st.warning("Spunta almeno un cliente dalla tabella tramite la casella 'Seleziona'.")

                st.divider()

                if st.session_state.clienti_ignorati_visite_list:
                    with st.expander(f"👁️ Gestisci Clienti Esclusi ({len(st.session_state.clienti_ignorati_visite_list)})"):
                        st.caption("Elenco dei clienti attualmente esclusi dal monitoraggio delle visite:")
                        
                        c_rst1, c_rst2 = st.columns([3, 1])
                        cli_da_ripristinare = c_rst1.selectbox("Seleziona un cliente da ripristinare:", ["-- Seleziona --"] + sorted(st.session_state.clienti_ignorati_visite_list), key="sel_cli_rst_vis")
                        
                        if c_rst2.button("↩️ Ripristina Selezionato", key="btn_rst_single_cli"):
                            if cli_da_ripristinare != "-- Seleziona --":
                                if rimuovi_cliente_ignorato_visita_cloud(cli_da_ripristinare):
                                    st.session_state.clienti_ignorati_visite_list = carica_clienti_ignorati_visite_cloud()
                                    st.session_state.df_visite_cache = pd.DataFrame()
                                    st.success(f"Cliente '{cli_da_ripristinare}' ripristinato!")
                                    st.rerun()

                        if st.button("🔄 Ripristina TUTTI i clienti esclusi", type="primary", key="btn_rst_all_cli"):
                            if svuota_clienti_ignorati_visite_cloud():
                                st.session_state.clienti_ignorati_visite_list = []
                                st.session_state.df_visite_cache = pd.DataFrame()
                                st.success("Tutti i clienti sono stati ripristinati con successo!")
                                st.rerun()

                with st.expander("🔗 Mappatura Manuale / Sinonimi Titoli Calendar"):
                    st.caption("Se su Google Calendar scrivi nomi abbreviati (es. 'MARTIGNONI' invece del nome completo), puoi associare qui la parola chiave alla ragione sociale esatta.")
                    
                    # Aggiunta nuova regola
                    c_map1, c_map2, c_map3 = st.columns([2, 2, 1])
                    txt_keyword = c_map1.text_input("Parola chiave in Calendar (es. MARTIGNONI):", key="txt_kw_cal")
                    sel_cli_map = c_map2.selectbox("Cliente Corrispondente nel DB:", ["-- Seleziona --"] + list_cli_db, key="sel_cli_map")

                    with c_map3:
                        st.write("")
                        st.write("")
                        btn_add_rule = st.button("➕ Aggiungi Regola", key="btn_add_map")

                    if btn_add_rule:
                        kw_clean = txt_keyword.strip()
                        if kw_clean and sel_cli_map != "-- Seleziona --":
                            if aggiungi_mappatura_calendar_cloud(kw_clean, sel_cli_map):
                                st.session_state.mappa_custom_calendar = carica_mappatura_calendar_cloud()
                                st.session_state.df_visite_cache = pd.DataFrame()
                                st.success(f"Regola salvata nel Cloud: '{kw_clean}' ➔ '{sel_cli_map}'")
                                st.rerun()
                        else:
                            st.warning("Inserisci sia la parola chiave che il cliente da abbinare.")

                    st.divider()

                    # Gestione e Rimozione Regole Esistenti
                    st.subheader("📋 Regole di Abbinamento Salvate nel Cloud")
                    if st.session_state.mappa_custom_calendar:
                        opzioni_regole = [f"'{kw}' ➔ '{cl}'" for kw, cl in st.session_state.mappa_custom_calendar.items()]
                        
                        c_del1, c_del2 = st.columns([3, 1])
                        regola_da_rimuovere = c_del1.selectbox(
                            "Seleziona una regola da eliminare:", 
                            ["-- Seleziona regola --"] + sorted(opzioni_regole), 
                            key="sel_rule_to_delete"
                        )

                        with c_del2:
                            st.write("")
                            st.write("")
                            btn_del_single_rule = st.button("🗑️ Rimuovi Regola", key="btn_del_rule")

                        if btn_del_single_rule:
                            if regola_da_rimuovere != "-- Seleziona regola --":
                                kw_target = regola_da_rimuovere.split(" ➔ ")[0].strip("'")
                                if rimuovi_mappatura_calendar_cloud(kw_target):
                                    st.session_state.mappa_custom_calendar = carica_mappatura_calendar_cloud()
                                    st.session_state.df_visite_cache = pd.DataFrame()
                                    st.success(f"Regola per '{kw_target}' eliminata!")
                                    st.rerun()

                        st.write("")
                        if st.button("🧹 Svuota TUTTE le regole di mappatura", key="btn_clear_all_rules"):
                            if svuota_mappatura_calendar_cloud():
                                st.session_state.mappa_custom_calendar = {}
                                st.session_state.df_visite_cache = pd.DataFrame()
                                st.success("Tutte le regole di mappatura sono state eliminate dal Cloud!")
                                st.rerun()
                    else:
                        st.info("Nessuna regola manuale salvata nel Cloud al momento.")

# ---------------------------------------------------------
# PANNELLO DIAGNOSTICA PRESTAZIONI NELLA SIDEBAR
# ---------------------------------------------------------
registra_tempo("Rerun · tempo Python totale", _run_start_perf)

# La diagnostica compare nella colonna laterale solo quando è attiva
# la scheda Database Ordini, sotto i filtri e l'ordinamento esistenti.
if not tabs_lazy_supportate or getattr(tab_database, "open", False):
    st.sidebar.divider()

    with st.sidebar.expander("⚙️ Diagnostica prestazioni", expanded=False):
        st.caption(
            "Misure server-side dell'ultimo passaggio eseguito. "
            "Non includono il tempo di rendering del browser o la latenza visiva della rete."
        )

        metriche_perf = st.session_state.get("performance_metrics", {})

        if metriche_perf:
            righe_perf = []
            for nome, durata_ms in metriche_perf.items():
                if durata_ms < 50:
                    stato = "🟢"
                elif durata_ms < 300:
                    stato = "🟡"
                else:
                    stato = "🔴"

                righe_perf.append({
                    "STATO": stato,
                    "OPERAZIONE": nome,
                    "TEMPO (ms)": durata_ms,
                })

            df_perf = pd.DataFrame(righe_perf).sort_values(
                "TEMPO (ms)",
                ascending=False
            )

            st.dataframe(
                df_perf,
                use_container_width=True,
                hide_index=True
            )

            st.caption(
                "Indicazione rapida: 🟢 < 50 ms · 🟡 50–299 ms · 🔴 ≥ 300 ms. "
                "Per chiamate esterne come Supabase e Google Calendar tempi più alti possono essere normali."
            )

            if st.button("🧹 Azzera misure diagnostiche", key="btn_reset_perf"):
                st.session_state.performance_metrics = {}
                st.rerun()
        else:
            st.info("Nessuna misura disponibile in questa sessione.")

