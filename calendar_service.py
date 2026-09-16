import streamlit as st
import pandas as pd
import re
import unicodedata
import hashlib
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo
from rapidfuzz import fuzz
from google.oauth2 import service_account
from googleapiclient.discovery import build


# ---------------------------------------------------------
# CONNESSIONE GOOGLE CALENDAR API (VIA SERVICE ACCOUNT)
# ---------------------------------------------------------
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Il gestionale lavora con clienti e visite in Italia.
# Tutti i confronti "oggi / passato / futuro" vengono quindi eseguiti
# nel fuso Europe/Rome, mentre le query Google Calendar vengono inviate
# in UTC con timestamp RFC3339 terminante in Z.
CALENDAR_TIMEZONE = ZoneInfo("Europe/Rome")

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
# GESTIONE DATA / ORA E TIMEZONE
# ---------------------------------------------------------
def _to_rfc3339_utc(dt_locale):
    """
    Converte un datetime timezone-aware in UTC RFC3339 per Google Calendar.
    Esempio: 2026-09-15T10:00:00+02:00 -> 2026-09-15T08:00:00Z
    """
    if dt_locale.tzinfo is None:
        raise ValueError("Il datetime deve essere timezone-aware.")

    return (
        dt_locale
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _data_locale_evento(start_evento):
    """
    Restituisce la data dell'evento nel fuso Europe/Rome.

    - eventi con dateTime: interpreta correttamente offset / UTC e converte
      nel fuso locale prima di ricavare il giorno;
    - eventi all-day con date: mantiene direttamente la data di calendario.
    """
    if not start_evento:
        return None

    data_ora = start_evento.get("dateTime")
    if data_ora:
        try:
            dt_evento = datetime.fromisoformat(data_ora.replace("Z", "+00:00"))

            # Google normalmente fornisce un offset. Il fallback evita comunque
            # confronti naive/aware in caso di dati anomali.
            if dt_evento.tzinfo is None:
                dt_evento = dt_evento.replace(tzinfo=CALENDAR_TIMEZONE)

            return dt_evento.astimezone(CALENDAR_TIMEZONE).date()
        except (TypeError, ValueError):
            return None

    data_intera = start_evento.get("date")
    if data_intera:
        try:
            return datetime.strptime(data_intera, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

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
# MATCHING ROBUSTO EVENTO CALENDAR -> CLIENTE
# ---------------------------------------------------------
_PAROLE_DA_IGNORARE_CLIENTE = {
    "spa", "srl", "srls", "snc", "sas", "ss", "inc", "ltd",
    "soc", "societa", "cooperativa", "coop", "agricola", "agr",
    "unipersonale", "di", "del", "della", "delle", "dei", "degli",
    "il", "lo", "la", "le", "e"
}


def _pulisci_testo_calendar(testo):
    """
    Normalizzazione condivisa per titoli Calendar e ragioni sociali.
    """
    if testo is None:
        return ""

    testo = str(testo).strip()
    if not testo:
        return ""

    testo = (
        unicodedata
        .normalize("NFKD", testo)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    testo = re.sub(r"[^a-z0-9]+", " ", testo)

    tokens = [
        token
        for token in testo.split()
        if len(token) > 1 and token not in _PAROLE_DA_IGNORARE_CLIENTE
    ]

    return " ".join(tokens)


def _acronimo_cliente_corto(cliente_originale, cliente_clean):
    """
    Consente acronimi reali corti (es. WFT, CPM) senza rendere
    permissivi tutti i token brevi.
    """
    tokens_clean = cliente_clean.split()
    if len(tokens_clean) != 1:
        return False

    token = tokens_clean[0]
    if len(token) > 4:
        return False

    primo_token_originale = re.split(
        r"[^A-Za-z0-9]+",
        str(cliente_originale).strip()
    )[0]

    return (
        primo_token_originale.upper() == primo_token_originale
        and primo_token_originale.lower() == token
        and len(primo_token_originale) >= 2
    )


def _abbina_cliente_automatico(summary, clienti_db_clean):
    """
    Matching automatico prudente:
    1) match esatto normalizzato;
    2) contenimento a parole scegliendo il candidato più specifico;
    3) fuzzy globale: soglia >= 90 e vantaggio >= 8 sul secondo.

    Se il risultato è ambiguo restituisce None.
    """
    summary_clean = _pulisci_testo_calendar(summary)
    if not summary_clean:
        return None

    summary_tokens = set(summary_clean.split())

    candidati = [
        (cliente_orig, cliente_clean)
        for cliente_orig, cliente_clean in clienti_db_clean.items()
        if cliente_clean
    ]
    if not candidati:
        return None

    match_esatti = [
        cliente_orig
        for cliente_orig, cliente_clean in candidati
        if summary_clean == cliente_clean
    ]

    if len(match_esatti) == 1:
        return match_esatti[0]
    if len(match_esatti) > 1:
        return None

    candidati_contenuti = []

    for cliente_orig, cliente_clean in candidati:
        cliente_tokens = set(cliente_clean.split())
        if not cliente_tokens:
            continue

        if cliente_tokens.issubset(summary_tokens):
            if len(cliente_tokens) == 1:
                token = next(iter(cliente_tokens))
                if len(token) < 5 and not _acronimo_cliente_corto(
                    cliente_orig,
                    cliente_clean
                ):
                    continue

            specificita = (
                len(cliente_tokens),
                len(cliente_clean),
            )
            candidati_contenuti.append((specificita, cliente_orig))

    if candidati_contenuti:
        candidati_contenuti.sort(reverse=True)
        migliore_specificita = candidati_contenuti[0][0]

        migliori = [
            cliente
            for specificita, cliente in candidati_contenuti
            if specificita == migliore_specificita
        ]

        if len(migliori) == 1:
            return migliori[0]

        return None

    risultati_fuzzy = []

    for cliente_orig, cliente_clean in candidati:
        ratio = fuzz.ratio(summary_clean, cliente_clean)
        token_set = fuzz.token_set_ratio(summary_clean, cliente_clean)
        punteggio = max(ratio, token_set)

        if len(summary_clean) >= 6 and len(cliente_clean) >= 6:
            punteggio = max(
                punteggio,
                fuzz.partial_ratio(summary_clean, cliente_clean)
            )

        risultati_fuzzy.append((float(punteggio), cliente_orig))

    risultati_fuzzy.sort(key=lambda x: x[0], reverse=True)

    best_score, best_cliente = risultati_fuzzy[0]
    second_score = (
        risultati_fuzzy[1][0]
        if len(risultati_fuzzy) > 1
        else 0.0
    )

    if best_score >= 90 and (best_score - second_score) >= 8:
        return best_cliente

    return None


def _abbina_cliente_calendar(summary, clienti_db_clean, mappa_custom=None):
    """
    Le regole manuali mantengono sempre la priorità.
    """
    if mappa_custom is None:
        mappa_custom = {}

    summary_casefold = str(summary or "").casefold()

    for parola_chiave, cliente_reale in mappa_custom.items():
        parola = str(parola_chiave or "").strip()
        if parola and parola.casefold() in summary_casefold:
            return cliente_reale

    return _abbina_cliente_automatico(summary, clienti_db_clean)


# ---------------------------------------------------------
# EVENTI NON ABBINATI E DECISIONI MANUALI (STEP 8C)
# ---------------------------------------------------------
def _motivo_non_abbinamento(titolo, clienti_db_clean):
    """Segnala un'eventuale ambiguità, senza forzare l'abbinamento."""
    parole_titolo = {
        t for t in _pulisci_testo_calendar(titolo).split() if len(t) >= 4
    }
    candidati = [
        nome for nome, pulito in clienti_db_clean.items()
        if parole_titolo.intersection(pulito.split())
    ]
    if len(candidati) >= 2:
        return "Possibile ambiguità tra più clienti"
    return "Nessuna corrispondenza sufficientemente sicura"


def elabora_eventi_calendar(
    eventi, lista_clienti_db, mappa_custom=None,
    decisioni_eventi=None, clienti_da_monitorare=None, oggi=None
):
    """Elabora gli eventi gia' letti, senza richiamare Google Calendar.

    Le decisioni sono indicizzate da (calendar_id, event_id), non dal titolo:
    una regola 'ignora' o 'associa' riguarda SOLO quell'occorrenza.
    Gli ignorati si vedono fino al giorno dell'evento incluso.
    """
    if mappa_custom is None:
        mappa_custom = {}
    if decisioni_eventi is None:
        decisioni_eventi = {}
    if oggi is None:
        oggi = datetime.now(CALENDAR_TIMEZONE).date()
    if clienti_da_monitorare is None:
        clienti_da_monitorare = lista_clienti_db

    clienti_validi = set(lista_clienti_db)
    clienti_monitorati = set(clienti_da_monitorare)
    clienti_db_clean = {
        cliente: _pulisci_testo_calendar(cliente)
        for cliente in lista_clienti_db if str(cliente).strip()
    }
    visite_passate = {}
    visite_future = {}
    da_verificare = []
    ignorati = []

    for evento in eventi:
        try:
            data_evento = date.fromisoformat(evento["data_evento"])
        except (ValueError, TypeError, KeyError):
            continue

        chiave = (evento.get("calendar_id", ""), evento.get("event_id", ""))
        decisione = decisioni_eventi.get(chiave, {})
        stato = decisione.get("stato")

        if stato == "ignorato":
            if data_evento >= oggi:
                ignorati.append(evento)
            # Ignorare significa non considerare l'evento nemmeno nello storico.
            continue

        cliente_assegnato = decisione.get("cliente") if stato == "associato" else None
        if cliente_assegnato and cliente_assegnato in clienti_validi:
            cliente_abbinato = cliente_assegnato
        else:
            cliente_abbinato = _abbina_cliente_calendar(
                evento.get("titolo", ""), clienti_db_clean, mappa_custom
            )

        if cliente_abbinato in clienti_validi:
            if cliente_abbinato not in clienti_monitorati:
                # I clienti esclusi dal monitoraggio non sono anomalie.
                continue
            if data_evento >= oggi:
                if (cliente_abbinato not in visite_future
                        or data_evento < visite_future[cliente_abbinato]):
                    visite_future[cliente_abbinato] = data_evento
            else:
                if (cliente_abbinato not in visite_passate
                        or data_evento > visite_passate[cliente_abbinato]):
                    visite_passate[cliente_abbinato] = data_evento
        elif data_evento >= oggi and chiave[0] and chiave[1]:
            # Appuntamenti passati non abbinati non entrano nelle anomalie.
            da_verificare.append({
                **evento,
                "motivo": _motivo_non_abbinamento(
                    evento.get("titolo", ""), clienti_db_clean
                ),
            })

    risultati = []
    for cliente in clienti_da_monitorare:
        if cliente in visite_future:
            visita = visite_future[cliente]
            giorni = (visita - oggi).days
            str_visita = visita.strftime("%d/%m/%Y")
            str_gg = f"-{giorni}"
            stato_visita = "🔵 Programmata"
        elif cliente in visite_passate:
            visita = visite_passate[cliente]
            giorni = (oggi - visita).days
            str_visita = visita.strftime("%d/%m/%Y")
            str_gg = str(giorni)
            if giorni < 60:
                stato_visita = "🟢 Recente (< 60 gg)"
            elif giorni <= 90:
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
            "STATO VISITA": stato_visita,
        })

    df_res = pd.DataFrame(risultati)
    if not df_res.empty:
        df_res = df_res.sort_values(by=["STATO VISITA", "CLIENTE"])

    da_verificare.sort(key=lambda item: (item["data_evento"], item["titolo"]))
    ignorati.sort(key=lambda item: (item["data_evento"], item["titolo"]))
    return df_res, da_verificare, ignorati


# ---------------------------------------------------------
# ESTRAZIONE EVENTI GOOGLE CALENDAR (VERSIONE DEBUG & AUTO-DISCOVERY)
# ---------------------------------------------------------
def ottieni_visite_calendar(
    lista_clienti_db, mappa_custom=None, restituisci_eventi=False,
    decisioni_eventi=None, clienti_da_monitorare=None
):
    if mappa_custom is None:
        mappa_custom = {}

    service = get_calendar_service()
    if not service:
        st.error("Servizio Google Calendar non inizializzato. Controlla i Secrets 'gcp_service_account'.")
        return (None, []) if restituisci_eventi else pd.DataFrame()

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

        ora_locale = datetime.now(CALENDAR_TIMEZONE)
        oggi = ora_locale.date()

        time_min = _to_rfc3339_utc(
            ora_locale - timedelta(days=365)
        )
        time_max = _to_rfc3339_utc(
            ora_locale + timedelta(days=90)
        )
        
        eventi_letti_debug = []
        eventi_minimi = []
        calendari_letti = 0

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

            calendari_letti += 1
            for event in events:
                summary = event.get('summary', '')
                if not summary:
                    continue

                data_evento = _data_locale_evento(event.get("start", {}))
                if data_evento is None:
                    continue

                eventi_letti_debug.append(f"[{cal_id[:15]}...] {data_evento.strftime('%d/%m/%Y')} - {summary}")

                # Conserviamo solo ID, titolo e giorno: niente descrizioni,
                # partecipanti o dettagli privati degli eventi in sessione.
                event_id = event.get("id")
                if not event_id:
                    # ID Google normalmente presente. Fallback deterministico
                    # per non perdere un evento privo di ID API.
                    identita = (
                        str(cal_id) + "|" + str(event.get("iCalUID", ""))
                        + "|" + str(event.get("start", {})) + "|" + summary
                    )
                    event_id = "fallback_" + hashlib.sha256(
                        identita.encode("utf-8")
                    ).hexdigest()
                eventi_minimi.append({
                    "calendar_id": str(cal_id),
                    "event_id": str(event_id),
                    "titolo": summary,
                    "data_evento": data_evento.isoformat(),
                })

        if calendari_letti == 0:
            st.warning("Nessun calendario è stato letto: riprova la scansione.")
            return (None, []) if restituisci_eventi else pd.DataFrame()

        with st.expander("🔍 Log Debug: Eventi letti"):
            st.write(f"Totale eventi analizzati: {len(eventi_letti_debug)}")
            if eventi_letti_debug:
                st.caption("Ultimi eventi letti:")
                st.code("\n".join(eventi_letti_debug[-30:]))
            else:
                st.info("Nessun evento estratto dai calendari specificati.")

        df_res, _, _ = elabora_eventi_calendar(
            eventi_minimi,
            lista_clienti_db,
            mappa_custom,
            decisioni_eventi=decisioni_eventi,
            clienti_da_monitorare=clienti_da_monitorare,
            oggi=oggi,
        )
        if restituisci_eventi:
            return df_res, eventi_minimi
        return df_res

    except Exception as e:
        st.error(f"Errore nella lettura del Google Calendar: {e}")
        return (None, []) if restituisci_eventi else pd.DataFrame()
