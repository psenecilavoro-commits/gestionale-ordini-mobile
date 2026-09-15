import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta
from rapidfuzz import fuzz
from google.oauth2 import service_account
from googleapiclient.discovery import build


# ---------------------------------------------------------
# CONNESSIONE GOOGLE CALENDAR API (VIA SERVICE ACCOUNT)
# ---------------------------------------------------------
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

@st.cache_resource
def get_calendar_service():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            # Normalizzazione automatica dei ritorni a capo per evitare Invalid JWT Signature
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            
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
# PAGINAZIONE GOOGLE CALENDAR
# ---------------------------------------------------------
def _elenca_calendari_accessibili(service):
    """
    Recupera tutti i calendari accessibili al Service Account,
    seguendo eventuali nextPageToken.
    """
    calendar_ids = []
    page_token = None

    while True:
        richiesta = service.calendarList().list(pageToken=page_token)
        risposta = richiesta.execute()

        for calendario in risposta.get("items", []):
            calendar_id = calendario.get("id")
            if calendar_id:
                calendar_ids.append(calendar_id)

        page_token = risposta.get("nextPageToken")
        if not page_token:
            break

    return calendar_ids


def _elenca_eventi_calendar(service, calendar_id, time_min, time_max):
    """
    Recupera tutti gli eventi del calendario nel periodo richiesto.

    Google Calendar può restituire più pagine anche con maxResults=2500:
    il ciclo segue nextPageToken finché non esistono altre pagine.
    """
    eventi = []
    page_token = None

    while True:
        richiesta = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=2500,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        )
        risposta = richiesta.execute()
        eventi.extend(risposta.get("items", []))

        page_token = risposta.get("nextPageToken")
        if not page_token:
            break

    return eventi


# ---------------------------------------------------------
# ESTRAZIONE EVENTI GOOGLE CALENDAR (VERSIONE DEBUG & AUTO-DISCOVERY)
# ---------------------------------------------------------
def ottieni_visite_calendar(lista_clienti_db, mappa_custom={}):
    service = get_calendar_service()
    if not service:
        st.error("Servizio Google Calendar non inizializzato. Controlla i Secrets 'gcp_service_account'.")
        return pd.DataFrame()

    try:
        # Recupera automaticamente tutti i calendari accessibili al Service Account
        CALENDAR_IDS = []
        try:
            CALENDAR_IDS = _elenca_calendari_accessibili(service)
        except Exception as e:
            st.warning(f"Impossibile elencare i calendari in automatico: {e}")

        # Fallback agli ID manuali se l'elenco automatico è vuoto
        if not CALENDAR_IDS:
            CALENDAR_IDS = ['primary', 'pseneci.lavoro@gmail.com']

        st.caption(f"Calendari identificati per la scansione: {CALENDAR_IDS}")

        oggi = datetime.now()
        time_min = (oggi - timedelta(days=365)).isoformat() + 'Z'
        time_max = (oggi + timedelta(days=90)).isoformat() + 'Z'
        
        visite_passate = {}
        visite_future = {}
        eventi_letti_debug = []

        def pulisci_testo(t):
            if not t:
                return ""
            t = re.sub(r"\b(SPA|SRL|S\.P\.A\.|S\.R\.L\.|SS|S\.S\.|INC|LTD)\b", "", t, flags=re.IGNORECASE)
            t = re.sub(r"[^\w\s]", " ", t)
            return re.sub(r"\s+", " ", t).strip().lower()

        clienti_db_clean = {c: pulisci_testo(c) for c in lista_clienti_db if str(c).strip()}

        for cal_id in CALENDAR_IDS:
            try:
                events = _elenca_eventi_calendar(
                    service,
                    cal_id,
                    time_min,
                    time_max
                )
            except Exception as err_cal:
                st.error(f"Errore nella lettura del calendario '{cal_id}': {err_cal}")
                continue

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

                eventi_letti_debug.append(f"[{cal_id[:15]}...] {data_evento.strftime('%d/%m/%Y')} - {summary}")

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
                            elif fuzz.partial_ratio(summary_clean, cliente_clean) >= 85:
                                cliente_abbinato = cliente_orig
                                break

                if cliente_abbinato:
                    if data_evento >= oggi.replace(hour=0, minute=0, second=0, microsecond=0):
                        if cliente_abbinato not in visite_future or data_evento < visite_future[cliente_abbinato]:
                            visite_future[cliente_abbinato] = data_evento
                    else:
                        if cliente_abbinato not in visite_passate or data_evento > visite_passate[cliente_abbinato]:
                            visite_passate[cliente_abbinato] = data_evento

        with st.expander("🔍 Log Debug: Eventi letti"):
            st.write(f"Totale eventi analizzati: {len(eventi_letti_debug)}")
            if eventi_letti_debug:
                st.caption("Ultimi eventi letti:")
                st.code("\n".join(eventi_letti_debug[-30:]))
            else:
                st.info("Nessun evento estratto dai calendari specificati.")

        risultati = []
        for cliente in lista_clienti_db:
            ha_futura = cliente in visite_future
            ha_passata = cliente in visite_passate

            if ha_futura:
                u_visita = visite_future[cliente]
                gg_futuri = (u_visita - oggi).days + 1
                str_visita = u_visita.strftime("%d/%m/%Y")
                str_gg = f"-{gg_futuri}"
                stato_visita = "🔵 Programmata"
            elif ha_passata:
                u_visita = visite_passate[cliente]
                gg_trascorsi = (oggi - u_visita).days
                str_visita = u_visita.strftime("%d/%m/%Y")
                str_gg = str(gg_trascorsi)
                
                if gg_trascorsi < 60:
                    stato_visita = "🟢 Recente (< 60 gg)"
                elif gg_trascorsi <= 90:
                    stato_visita = "🟡 Programmare (60-90 gg)"
                else:
                    stato_visita = "🔴 Urgente (> 90 gg)"
            else:
                str_visita = "Mai trovata"
                str_gg = "N/D"
                stato_visita = "⚪ Nessuna Visita a Calendario"

            risultati.append({
                "CLIENTE": cliente,
                "DATA ULTIMA VISITA": str_visita,
                "GG DALL'ULTIMA VISITA": str_gg,
                "STATO VISITA": stato_visita
            })

        df_res = pd.DataFrame(risultati)
        if not df_res.empty:
            df_res = df_res.sort_values(by=["STATO VISITA", "CLIENTE"])
        return df_res

    except Exception as e:
        st.error(f"Errore nella lettura del Google Calendar: {e}")
        return pd.DataFrame()
