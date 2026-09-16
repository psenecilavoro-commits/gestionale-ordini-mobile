import streamlit as st
import pandas as pd
from supabase import create_client, Client


# ---------------------------------------------------------
# CONFIGURAZIONE CONNESSIONE SUPABASE CLOUD (AGGIORNATA)
# ---------------------------------------------------------
@st.cache_resource
def init_supabase() -> Client:
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]

        # Le nuove chiavi sb_secret_ vanno usate come API key.
        # Non devono essere inviate come Bearer token JWT.
        client = create_client(url, key)
        return client
    except Exception as e:
        st.error(f"Errore di connessione a Supabase: {e}")
        return None

supabase = init_supabase()

# ---------------------------------------------------------
# CARICAMENTO / SALVATAGGIO DATABASE CLOUD (PAGINATO)
# ---------------------------------------------------------
def carica_db_cloud():
    try:
        tutti_i_dati = []
        step = 1000
        inizio = 0
        
        while True:
            response = supabase.table("ordini").select("*").order("id").range(inizio, inizio + step - 1).execute()
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
                    
            return df[colonne_standard].fillna("").astype(str)
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
# GESTIONE PERMANENTE MAPPATURA CALENDAR SU CLOUD
# ---------------------------------------------------------
def carica_mappatura_calendar_cloud():
    try:
        res = supabase.table("mappatura_calendar").select("parola_chiave, cliente").execute()
        return {r["parola_chiave"]: r["cliente"] for r in res.data}
    except Exception as e:
        return {}

def aggiungi_mappatura_calendar_cloud(parola_chiave, cliente):
    try:
        supabase.table("mappatura_calendar").upsert({
            "parola_chiave": parola_chiave,
            "cliente": cliente
        }, on_conflict="parola_chiave").execute()
        return True
    except Exception as e:
        st.error(f"Errore nel salvataggio della regola: {e}")
        return False

def rimuovi_mappatura_calendar_cloud(parola_chiave):
    try:
        supabase.table("mappatura_calendar").delete().eq("parola_chiave", parola_chiave).execute()
        return True
    except Exception as e:
        st.error(f"Errore nella rimozione della regola: {e}")
        return False

def svuota_mappatura_calendar_cloud():
    try:
        supabase.table("mappatura_calendar").delete().neq("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"Errore nello svuotamento delle regole: {e}")
        return False
        
# ---------------------------------------------------------
# GESTIONE PERMANENTE CLIENTE IGNORATI VISITE SU CLOUD
# ---------------------------------------------------------
def carica_clienti_ignorati_visite_cloud():
    try:
        res = supabase.table("clienti_ignorati_visite").select("cliente").execute()
        return [r["cliente"] for r in res.data]
    except Exception as e:
        return []

def aggiungi_clienti_ignorati_visite_cloud(lista_clienti_nomi):
    try:
        dati_db = [{"cliente": nome} for nome in lista_clienti_nomi if nome]
        if dati_db:
            supabase.table("clienti_ignorati_visite").insert(dati_db).execute()
        return True
    except Exception as e:
        st.error(f"Errore nell'esclusione dei clienti: {e}")
        return False

def rimuovi_cliente_ignorato_visita_cloud(cliente_nome):
    try:
        supabase.table("clienti_ignorati_visite").delete().eq("cliente", cliente_nome).execute()
        return True
    except Exception as e:
        st.error(f"Errore nel ripristino del cliente: {e}")
        return False

def svuota_clienti_ignorati_visite_cloud():
    try:
        supabase.table("clienti_ignorati_visite").delete().neq("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"Errore nel ripristino dei clienti: {e}")
        return False

# ---------------------------------------------------------
# GESTIONE PERMANENTE PREVISIONALE IGNORATO SU CLOUD
# ---------------------------------------------------------
def carica_articoli_ignorati_prev_cloud():
    try:
        res = supabase.table("articoli_ignorati_previsionale").select("cliente, articolo").execute()
        return [(r["cliente"], r["articolo"]) for r in res.data]
    except Exception as e:
        return []

def aggiungi_articoli_ignorati_prev_cloud(lista_coppie):
    try:
        dati_db = [{"cliente": c, "articolo": a} for c, a in lista_coppie if c and a]
        if dati_db:
            supabase.table("articoli_ignorati_previsionale").insert(dati_db).execute()
        return True
    except Exception as e:
        st.error(f"Errore nell'esclusione dal previsionale: {e}")
        return False

def rimuovi_articolo_ignorato_prev_cloud(cliente, articolo):
    try:
        supabase.table("articoli_ignorati_previsionale").delete().eq("cliente", cliente).eq("articolo", articolo).execute()
        return True
    except Exception as e:
        st.error(f"Errore nel ripristino dal previsionale: {e}")
        return False

def svuota_articoli_ignorati_prev_cloud():
    try:
        supabase.table("articoli_ignorati_previsionale").delete().neq("id", 0).execute()
        return True
    except Exception as e:
        st.error(f"Errore nel ripristino totale del previsionale: {e}")
        return False


# ---------------------------------------------------------
# EVENTI GOOGLE CALENDAR GESTITI (STEP 8C)
# La tabella calendar_eventi_gestiti va creata con lo script SQL nel pacchetto.
# Le letture avvengono SOLO durante la scansione manuale.
# ---------------------------------------------------------
def carica_decisioni_eventi_calendar_cloud():
    """Restituisce {(calendar_id, event_id): record}; None se DB non pronto."""
    if supabase is None:
        st.error("Supabase non disponibile: gestione eventi Calendar disabilitata.")
        return None
    try:
        dati = []
        inizio = 0
        step = 1000
        while True:
            res = (supabase.table("calendar_eventi_gestiti")
                   .select("calendar_id,event_id,stato,cliente,data_evento")
                   .order("calendar_id").order("event_id")
                   .range(inizio, inizio + step - 1).execute())
            batch = res.data or []
            dati.extend(batch)
            if len(batch) < step:
                break
            inizio += step
        return {
            (str(r["calendar_id"]), str(r["event_id"])): r
            for r in dati
        }
    except Exception as e:
        st.error(
            "Impossibile leggere gli eventi gestiti da Supabase. "
            "Verifica di aver eseguito lo script SQL dello Step 8C. "
            f"Dettagli: {e}"
        )
        return None


def salva_decisione_evento_calendar_cloud(evento, stato, cliente=None):
    """Salva la decisione solo per la specifica occorrenza Calendar."""
    if supabase is None:
        return False
    if stato not in {"ignorato", "associato"}:
        st.error("Stato evento non valido.")
        return False
    cliente = str(cliente).strip() if cliente is not None else None
    if stato == "associato" and not cliente:
        st.warning("Seleziona il cliente da associare.")
        return False
    payload = {
        "calendar_id": str(evento["calendar_id"]),
        "event_id": str(evento["event_id"]),
        "data_evento": str(evento["data_evento"]),
        "stato": stato,
        "cliente": cliente if stato == "associato" else None,
    }
    try:
        supabase.table("calendar_eventi_gestiti").upsert(
            payload, on_conflict="calendar_id,event_id"
        ).execute()
        return True
    except Exception as e:
        st.error(f"Errore nel salvataggio della decisione Calendar: {e}")
        return False


def ripristina_evento_ignorato_calendar_cloud(evento):
    """Rimuove solo una decisione 'ignorato', non le associazioni."""
    if supabase is None:
        return False
    try:
        (supabase.table("calendar_eventi_gestiti").delete()
         .eq("calendar_id", str(evento["calendar_id"]))
         .eq("event_id", str(evento["event_id"]))
         .eq("stato", "ignorato")
         .execute())
        return True
    except Exception as e:
        st.error(f"Errore nel ripristino dell'evento: {e}")
        return False
