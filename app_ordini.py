import streamlit as st
import pandas as pd
import pdfplumber
import re
from datetime import datetime, timedelta
from supabase import create_client, Client
from rapidfuzz import process, fuzz
from google.oauth2 import service_account
from googleapiclient.discovery import build

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
# CONNESSIONE GOOGLE CALENDAR API (VIA SERVICE ACCOUNT)
# ---------------------------------------------------------
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

@st.cache_resource
def get_calendar_service():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
            service = build('calendar', 'v3', credentials=creds)
            return service
        else:
            st.warning("Credenziali 'gcp_service_account' non trovate nei Secrets di Streamlit.")
            return None
    except Exception as e:
        st.error(f"Errore di connessione a Google Calendar API: {e}")
        return None

# ---------------------------------------------------------
# CARICAMENTO / SALVATAGGIO DATABASE CLOUD (PAGINATO)
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

def rinomina_articolo_cloud(vecchio_nome, nuovo_nome, cliente=None):
    try:
        query = supabase.table("ordini").update({"articolo": nuovo_nome}).eq("articolo", vecchio_nome)
        if cliente:
            query = query.eq("cliente", cliente)
        query.execute()
        return True
    except Exception as e:
        st.error(f"Errore nell'aggiornamento dell'articolo sul Cloud: {e}")
        return False

# ---------------------------------------------------------
# GESTIONE PERMANENTE COPPIE IGNORATE SU CLOUD
# ---------------------------------------------------------
def carica_coppie_ignorate_cloud():
    try:
        res = supabase.table("coppie_ignorate").select("articolo_a, articolo_b").execute()
        coppie = []
        for r in res.data:
            coppie.append(tuple(sorted([r["articolo_a"], r["articolo_b"]])))
        return coppie
    except Exception as e:
        st.error(f"Errore nel caricamento delle coppie ignorate: {e}")
        return []

def aggiungi_coppia_ignorata_cloud(art_a, art_b):
    try:
        a, b = sorted([art_a, art_b])
        supabase.table("coppie_ignorate").insert({"articolo_a": a, "articolo_b": b}).execute()
        return True
    except Exception as e:
        st.error(f"Errore nel salvataggio coppia ignorata: {e}")
        return False

def rimuovi_ultima_coppia_ignorata_cloud():
    try:
        res = supabase.table("coppie_ignorate").select("id").order("id", desc=True).limit(1).execute()
        if res.data:
            last_id = res.data[0]["id"]
            supabase.table("coppie_ignorate").delete().eq("id", last_id).execute()
        return True
    except Exception as e:
        st.error(f"Errore nella rimozione dell'ultima coppia ignorata: {e}")
        return False

def svuota_coppie_ignorate_cloud():
    try:
        supabase.table("coppie_ignorate").delete().neq("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"Errore nello svuotamento delle coppie ignorate: {e}")
        return False

# ---------------------------------------------------------
# FUNZIONE DI ESTRAZIONE MULTI-LAYOUT (VECCHIO + NUOVO)
# ---------------------------------------------------------
def estrai_dati_pdf(pdf_file):
    righe_estratte = []
    
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        testo_layout = page.extract_text(layout=True) or ""
        testo_semplice = page.extract_text(layout=False) or ""

    if "BORGO SAN GIACOMO" in testo_semplice or "N° Ord. Cliente" in testo_semplice or "N Ord. Cliente" in testo_semplice:
        m_cli = re.search(r"Spett\.le\s*\n\s*([^\n]+)", testo_semplice)
        cliente = m_cli.group(1).strip() if m_cli else ""

        n_ordine = ""
        target_word = None
        for w in words:
            if "Cliente" in w['text'] and w['top'] < 300:
                target_word = w
                break
        
        if target_word:
            x0 = target_word['x0'] - 30
            x1 = target_word['x1'] + 60
            top = target_word['bottom']
            bottom = top + 35
            
            num_words = [
                w['text'].strip() for w in words 
                if x0 <= w['x0'] <= x1 and top <= w['top'] <= bottom
            ]
            for nw in num_words:
                if re.search(r"\d", nw) and "Causale" not in nw:
                    n_ordine = nw
                    break

        if not n_ordine:
            m_ord = re.search(r"N°?\s*Ord\.?\s*Cliente\s*[\n\r]*\s*([A-Z0-9/\-_]+)", testo_semplice, re.IGNORECASE)
            if m_ord:
                n_ordine = m_ord.group(1).strip()

        righe_raw = testo_layout.split("\n")
        
        idx_inizio = 0
        for i, riga in enumerate(righe_raw):
            if "Descrizione" in riga and "Quantità" in riga:
                idx_inizio = i
                break

        for i in range(idx_inizio + 1, len(righe_raw)):
            riga = righe_raw[i]
            
            m_consegna = re.search(r"(\d{2}\.\d{2}\.\d{4})", riga)
            if m_consegna:
                idx_date = riga.find(m_consegna.group(1))
                testo_dopo_data = riga[idx_date + len(m_consegna.group(1)):].strip()
                numeri_destra = re.findall(r"\b\d{1,3}(?:\.\d{3})*(?:,\d+)?\b", testo_dopo_data)
                
                if len(numeri_destra) < 2:
                    continue

                consegna = m_consegna.group(1).replace(".", "/")
                qta = numeri_destra[0]
                prezzo = f"€ {numeri_destra[1]}"

                descrizione = riga[:idx_date].strip()
                if i > 0 and (len(descrizione) < 3 or re.match(r"^[\d\s x X \.-]+$", descrizione)):
                    riga_sopra = righe_raw[i-1].strip()
                    if "Descrizione" not in riga_sopra:
                        descrizione = riga_sopra

                descrizione = re.sub(r"Kg\s*[\d\.,]+", "", descrizione, flags=re.IGNORECASE).strip()

                cartone = ""
                m_cartone = re.search(r"\b([A-Z]{2,4}\d{2,4}\s*[A-Z0-9]*)\b", riga[idx_date:])
                if not m_cartone and i + 1 < len(righe_raw):
                    m_cartone = re.search(r"\b([A-Z]{2,4}\d{2,4}\s*[A-Z0-9]*)\b", righe_raw[i+1])
                
                if m_cartone:
                    cartone = m_cartone.group(1).strip()

                if cartone and cartone not in descrizione:
                    articolo_completo = f"{descrizione} {cartone}".strip()
                else:
                    articolo_completo = descrizione

                if articolo_completo and consegna:
                    righe_estratte.append({
                        "CLIENTE": cliente,
                        "N. ORDINE": n_ordine,
                        "ARTICOLO": articolo_completo,
                        "CONSEGNA": consegna,
                        "QUANTITÀ": qta,
                        "PREZZO": prezzo
                    })

    else:
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
# CALCOLO ALGORITMO PREVISIONALE RIORDINI
# ---------------------------------------------------------
def calcola_previsionale(df_ordini):
    if df_ordini.empty:
        return pd.DataFrame()

    df = df_ordini.copy()
    df["DATA_DT"] = pd.to_datetime(df["CONSEGNA"], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=["DATA_DT"]).sort_values(["CLIENTE", "ARTICOLO", "DATA_DT"])

    oggi = datetime.now()
    mese_corrente = oggi.month
    anno_corrente = oggi.year
    
    prossimo_mese_dt = (oggi.replace(day=1) + timedelta(days=32)).replace(day=1)
    mese_prossimo = prossimo_mese_dt.month
    anno_prossimo = prossimo_mese_dt.year

    previsioni = []

    gruppi = df.groupby(["CLIENTE", "ARTICOLO"])

    for (cliente, articolo), g in gruppi:
        if len(g) == 0:
            continue

        date_consegne = g["DATA_DT"].tolist()
        ultima_data = date_consegne[-1]
        ultima_qta = g["QUANTITÀ"].iloc[-1]
        ultimo_prezzo = g["PREZZO"].iloc[-1]

        gg_trascorsi = (oggi - ultima_data).days

        if len(date_consegne) > 1:
            diffs = [(date_consegne[k] - date_consegne[k-1]).days for k in range(1, len(date_consegne))]
            intervallo_medio = sum(diffs) / len(diffs)
            intervallo_medio = max(intervallo_medio, 15)
        else:
            intervallo_medio = 60

        data_stimata = ultima_data + timedelta(days=int(intervallo_medio))
        ha_ordine_futuro = any(d >= oggi.replace(day=1) for d in date_consegne)

        stesso_mese_corr = (data_stimata.month == mese_corrente and data_stimata.year == anno_corrente)
        stesso_mese_prox = (data_stimata.month == mese_prossimo and data_stimata.year == anno_prossimo)
        in_ritardo = (data_stimata < oggi and not ha_ordine_futuro)

        if gg_trascorsi > 365:
            stato = "⚪ Articolo Declassato"
            periodo_rif = "Inattivo (> 1 anno)"
            previsioni.append({
                "CLIENTE": cliente,
                "ARTICOLO": articolo,
                "STATO": stato,
                "PERIODO ATTESO": periodo_rif,
                "GG TRASCORSI": gg_trascorsi,
                "DATA STIMATA RIORDINO": data_stimata.strftime("%d/%m/%Y"),
                "FREQ. MEDIA (GG)": int(intervallo_medio),
                "ULTIMA CONSEGNA": ultima_data.strftime("%d/%m/%Y"),
                "ULTIMA Q.TÀ": ultima_qta,
                "ULTIMO PREZZO": ultimo_prezzo
            })
        elif stesso_mese_corr or stesso_mese_prox or in_ritardo:
            if in_ritardo:
                stato = "🔴 In Ritardo / Da Sollecitare"
                periodo_rif = "Scaduto"
            elif stesso_mese_corr:
                stato = "🟢 Già Ordinato" if ha_ordine_futuro else "🟡 Mese Corrente"
                periodo_rif = "Mese Corrente"
            else:
                stato = "🟢 Già Ordinato" if ha_ordine_futuro else "🔵 Mese Successivo"
                periodo_rif = "Mese Successivo"

            previsioni.append({
                "CLIENTE": cliente,
                "ARTICOLO": articolo,
                "STATO": stato,
                "PERIODO ATTESO": periodo_rif,
                "GG TRASCORSI": gg_trascorsi,
                "DATA STIMATA RIORDINO": data_stimata.strftime("%d/%m/%Y"),
                "FREQ. MEDIA (GG)": int(intervallo_medio),
                "ULTIMA CONSEGNA": ultima_data.strftime("%d/%m/%Y"),
                "ULTIMA Q.TÀ": ultima_qta,
                "ULTIMO PREZZO": ultimo_prezzo
            })

    df_prev = pd.DataFrame(previsioni)
    if not df_prev.empty:
        df_prev = df_prev.sort_values(by=["STATO", "DATA STIMATA RIORDINO"])
    return df_prev

# ---------------------------------------------------------
# ESTRAZIONE EVENTI GOOGLE CALENDAR MULTI-CALENDARIO
# ---------------------------------------------------------
def ottieni_visite_calendar(lista_clienti_db, mappa_custom={}):
    service = get_calendar_service()
    if not service:
        return pd.DataFrame()

    try:
        calendar_list = service.calendarList().list().execute().get('items', [])
        
        if not calendar_list:
            st.warning("⚠️ La Service Account non legge nessun calendario. Condividi il calendario 'Innova Group' o 'Emilabel' con l'email del bot.")
            return pd.DataFrame()

        oggi = datetime.now()
        time_min = (oggi - timedelta(days=365)).isoformat() + 'Z'
        visite_cliente = {}

        def pulisci_testo(t):
            if not t:
                return ""
            t = re.sub(r"\b(SPA|SRL|S\.P\.A\.|S\.R\.L\.|SS|S\.S\.|INC|LTD)\b", "", t, flags=re.IGNORECASE)
            t = re.sub(r"[^\w\s]", " ", t)
            return re.sub(r"\s+", " ", t).strip().lower()

        clienti_db_clean = {c: pulisci_testo(c) for c in lista_clienti_db if str(c).strip()}
        eventi_letti_debug = []

        for cal in calendar_list:
            cal_id = cal['id']
            cal_summary = cal.get('summary', 'Senza nome')

            events_result = service.events().list(
                calendarId=cal_id, 
                timeMin=time_min,
                maxResults=2500, 
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

            for event in events:
                summary = event.get('summary', '')
                if not summary:
                    continue

                start = event['start'].get('dateTime', event['start'].get('date'))
                try:
                    str_date = start.split('T')[0]
                    data_evento = datetime.strptime(str_date, "%Y-%m-%d")
                except Exception:
                    continue

                if data_evento > oggi:
                    continue

                eventi_letti_debug.append(f"[{cal_summary}] {data_evento.strftime('%d/%m/%Y')} - {summary}")

                cliente_abbinato = None

                # 1. Regole manuali
                for parola_chiave, cliente_reale in mappa_custom.items():
                    if parola_chiave.lower() in summary.lower():
                        cliente_abbinato = cliente_reale
                        break

                # 2. Match automatico
                if not cliente_abbinato:
                    summary_clean = pulisci_testo(summary)
                    for cliente_orig, cliente_clean in clienti_db_clean.items():
                        if len(cliente_clean) >= 2:
                            parole_summary = set(summary_clean.split())
                            parole_cliente = set(cliente_clean.split())
                            
                            if parole_summary and (parole_summary.issubset(parole_cliente) or parole_cliente.issubset(parole_summary)):
                                cliente_abbinato = cliente_orig
                                break
                            elif fuzz.partial_ratio(summary_clean, cliente_clean) >= 70:
                                cliente_abbinato = cliente_orig
                                break

                if cliente_abbinato:
                    if cliente_abbinato not in visite_cliente or data_evento > visite_cliente[cliente_abbinato]:
                        visite_cliente[cliente_abbinato] = data_evento

        with st.expander("🔍 Log Debug: Calendari ed Eventi letti"):
            st.write(f"Calendari trovati ({len(calendar_list)}):", [c.get('summary') for c in calendar_list])
            st.write(f"Totale eventi analizzati: {len(eventi_letti_debug)}")
            st.caption("Ultimi 20 eventi letti:")
            st.code("\n".join(eventi_letti_debug[-20:]))

        risultati = []
        for cliente in lista_clienti_db:
            if cliente in visite_cliente:
                u_visita = visite_cliente[cliente]
                gg_trascorsi = (oggi - u_visita).days
                str_visita = u_visita.strftime("%d/%m/%Y")
            else:
                gg_trascorsi = 999
                str_visita = "Mai trovata"

            if gg_trascorsi <= 30:
                stato_visita = "🟢 Recente (< 30 gg)"
            elif gg_trascorsi <= 60:
                stato_visita = "🟡 Programmare (30-60 gg)"
            elif gg_trascorsi < 999:
                stato_visita = "🔴 Urgente (> 60 gg)"
            else:
                stato_visita = "⚪ Nessuna Visita a Calendario"

            risultati.append({
                "CLIENTE": cliente,
                "DATA ULTIMA VISITA": str_visita,
                "GG DALL'ULTIMA VISITA": gg_trascorsi if gg_trascorsi != 999 else "N/D",
                "STATO VISITA": stato_visita
            })

        df_res = pd.DataFrame(risultati)
        if not df_res.empty:
            df_res = df_res.sort_values(by=["STATO VISITA", "CLIENTE"])
        return df_res

    except Exception as e:
        st.error(f"Errore nella lettura del Google Calendar: {e}")
        return pd.DataFrame()

# ---------------------------------------------------------
# INTERFACCIA STREAMLIT A TABS (6 SCHEDE)
# ---------------------------------------------------------
st.title("📦 Gestionale Ordini PDF (Cloud Supabase)")

if "db_ordini" not in st.session_state:
    st.session_state.db_ordini = carica_db_cloud()

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if "select_all_state" not in st.session_state:
    st.session_state.select_all_state = False

if "coppie_ignorate_list" not in st.session_state:
    st.session_state.coppie_ignorate_list = carica_coppie_ignorate_cloud()

if "mappa_custom_calendar" not in st.session_state:
    st.session_state.mappa_custom_calendar = {}

tab_database, tab_grafici, tab_norm_cli, tab_fuzzy, tab_previsionale, tab_visite = st.tabs([
    "📋 Database Ordini", 
    "📈 Analisi & Grafici", 
    "🏷️ Normalizzazione Cliente",
    "🤖 Pulizia Smart (Fuzzy)",
    "🔮 Previsionale Riordini",
    "📅 Monitoraggio Visite"
])

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

        df_display = df_filtrato.drop(columns=["id"], errors="ignore").copy()
        df_display.insert(0, "Seleziona", st.session_state.select_all_state)

        edited_df = st.data_editor(
            df_display, 
            use_container_width=True, 
            num_rows="dynamic",
            key="editor_ordini"
        )

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
                indici_visibili = righe_selezionate.index
                ids_da_aggiornare = df_filtrato.loc[indici_visibili, "id"].tolist()
                for item_id in ids_da_aggiornare:
                    if item_id:
                        supabase.table("ordini").update({"cliente": nome_finale}).eq("id", item_id).execute()
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

# =========================================================
# SCHEDA 3: NORMALIZZAZIONE VELOCE PER CLIENTE
# =========================================================
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

        coppie_trovate = []
        processati = set()
        set_ignorate = set(st.session_state.coppie_ignorate_list)

        for idx, art_a in enumerate(articoli_unici):
            if art_a in processati:
                continue
            match = process.extract(
                art_a, 
                articoli_unici[idx+1:], 
                scorer=fuzz.token_sort_ratio, 
                score_cutoff=soglia
            )
            for art_b, score, _ in match:
                coppia_key = tuple(sorted([art_a, art_b]))
                
                if coppia_key not in set_ignorate:
                    coppie_trovate.append({
                        "key": coppia_key,
                        "Articolo A": art_a,
                        "Articolo B": art_b,
                        "Somiglianza": f"{round(score)}%",
                        "Conteggio A": len(df_work[df_work["ARTICOLO"] == art_a]),
                        "Conteggio B": len(df_work[df_work["ARTICOLO"] == art_b])
                    })
                processati.add(art_b)

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
with tab_previsionale:
    st.subheader("🔮 Previsionale Riordini (Mese Corrente & Successivo)")
    st.markdown("L'algoritmo analizza la frequenza storica di riordine per ogni coppia **Cliente-Articolo**, i giorni trascorsi dall'ultimo ordine e ti segnala le commesse attese o in ritardo.")

    df_prev_base = st.session_state.db_ordini

    if not df_prev_base.empty:
        df_prev_res = calcola_previsionale(df_prev_base)

        if not df_prev_res.empty:
            n_ritardo = len(df_prev_res[df_prev_res["STATO"].str.contains("Ritardo")])
            n_corr = len(df_prev_res[df_prev_res["STATO"].str.contains("Mese Corrente")])
            n_prox = len(df_prev_res[df_prev_res["STATO"].str.contains("Mese Successivo")])

            m1, m2, m3 = st.columns(3)
            m1.metric("🔴 In Ritardo (Da Sollecitare)", n_ritardo)
            m2.metric("🟡 Previsti Questo Mese", n_corr)
            m3.metric("🔵 Previsti Mese Successivo", n_prox)

            st.divider()

            col_pf1, col_pf2, col_pf3 = st.columns([1.5, 1.5, 1])

            mostra_declassati = col_pf3.checkbox("Includi '⚪ Articolo Declassato'", value=False, key="chk_show_decl")

            if not mostra_declassati:
                df_prev_res_filtered = df_prev_res[~df_prev_res["STATO"].str.contains("Declassato")].copy()
            else:
                df_prev_res_filtered = df_prev_res.copy()

            stati_disponibili = ["Tutti"] + sorted(list(df_prev_res_filtered["STATO"].unique()))
            sel_stato = col_pf1.selectbox("Filtra per STATO:", stati_disponibili, key="prev_stato_filter")

            clienti_prev = ["Tutti"] + sorted(list(df_prev_res_filtered["CLIENTE"].unique()))
            sel_cli_p = col_pf2.selectbox("Filtra per CLIENTE:", clienti_prev, key="prev_cli_filter")

            df_prev_disp = df_prev_res_filtered.copy()

            if sel_stato != "Tutti":
                df_prev_disp = df_prev_disp[df_prev_disp["STATO"] == sel_stato]

            if sel_cli_p != "Tutti":
                df_prev_disp = df_prev_disp[df_prev_disp["CLIENTE"] == sel_cli_p]

            st.caption(f"Righe trovate: **{len(df_prev_disp)}**")

            st.dataframe(
                df_prev_disp,
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nessuna previsione di riordine calcolata per il periodo attuale.")
    else:
        st.warning("Database vuoto. Carica dei PDF per generare il previsionale.")

# =========================================================
# SCHEDA 6: MONITORAGGIO VISITE GOOGLE CALENDAR
# =========================================================
with tab_visite:
    st.subheader("📅 Monitoraggio Visite Clienti (Google Calendar)")
    st.markdown("Il sistema scansiona in sola lettura il tuo **Google Calendar**, riconosce i titoli degli eventi associandoli ai clienti del database e calcola da quanti giorni non li visiti.")

    df_vis_base = st.session_state.db_ordini

    if not df_vis_base.empty:
        list_cli_db = sorted([x for x in df_vis_base["CLIENTE"].unique() if str(x).strip()])

        col_v1, col_v2 = st.columns([3, 1])

        with col_v2:
            st.write("")
            btn_scan_cal = st.button("🔄 Scansiona Google Calendar", type="primary", key="btn_scan_cal")

        if btn_scan_cal or "df_visite_cache" not in st.session_state:
            with st.spinner("Scansione di Google Calendar in corso..."):
                df_vis_res = ottieni_visite_calendar(list_cli_db, st.session_state.mappa_custom_calendar)
                st.session_state.df_visite_cache = df_vis_res

        df_vis_display = st.session_state.get("df_visite_cache", pd.DataFrame())

        if not df_vis_display.empty:
            n_rec = len(df_vis_display[df_vis_display["STATO VISITA"].str.contains("Recente")])
            n_prog = len(df_vis_display[df_vis_display["STATO VISITA"].str.contains("Programmare")])
            n_urg = len(df_vis_display[df_vis_display["STATO VISITA"].str.contains("Urgente")])

            v_m1, v_m2, v_m3 = st.columns(3)
            v_m1.metric("🟢 Visitati (< 30 gg)", n_rec)
            v_m2.metric("🟡 Da Programmare (30-60 gg)", n_prog)
            v_m3.metric("🔴 Visita Urgente (> 60 gg)", n_urg)

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

            st.dataframe(
                df_vis_filt,
                use_container_width=True,
                hide_index=True
            )

            st.divider()

            with st.expander("🔗 Mappatura Manuale / Sinonimi Titoli Calendar"):
                st.caption("Se su Google Calendar scrivi nomi abbreviati (es. 'MARTIGNONI' invece del nome completo), puoi associare qui la parola chiave alla ragione sociale esatta.")
                
                c_map1, c_map2, c_map3 = st.columns([2, 2, 1])
                txt_keyword = c_map1.text_input("Parola chiave in Calendar (es. MARTIGNONI):", key="txt_kw_cal")
                sel_cli_map = c_map2.selectbox("Cliente Corrispondente nel DB:", ["-- Seleziona --"] + list_cli_db, key="sel_cli_map")

                if c_map3.button("➕ Aggiungi Regola", key="btn_add_map"):
                    if txt_keyword.strip() and sel_cli_map != "-- Seleziona --":
                        st.session_state.mappa_custom_calendar[txt_keyword.strip()] = sel_cli_map
                        st.success(f"Regola aggiunta: '{txt_keyword.strip()}' -> '{sel_cli_map}'")
                        st.rerun()

                if st.session_state.mappa_custom_calendar:
                    st.write("📋 Regole di abbinamento attive:")
                    for kw, cl in list(st.session_state.mappa_custom_calendar.items()):
                        st.text(f"• '{kw}' ➔ '{cl}'")
        else:
            st.info("Fai clic su 'Scansiona Google Calendar' per caricare i dati delle visite.")
    else:
        st.warning("Database vuoto. Carica dei PDF per sincronizzare le visite.")
