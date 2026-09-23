"""Pagina di collaudo del bot Innova nel Gestionale Ordini principale.

Anteprima e, solo dopo conferma esplicita, esecuzione limitata alla gerarchia
TEST BOT CLOUD hardcoded. Nessun ID dell'archivio reale è usato dal modulo di
esecuzione di test.
"""

import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from innova_drive_preview import TEST_INBOX_ID, anteprima_test, carica_pdf_test
from innova_v4_cloud_preview import inspect_cloud, build_preview_plan
from innova_drive_execute_test import (
    EsecuzioneTestBloccata,
    execute_test_pair,
    make_snapshot,
)


st.set_page_config(page_title="Archivio Innova · TEST", layout="wide")

if not st.session_state.get("autenticato", False):
    st.warning("Accedi prima al Gestionale Ordini principale.")
    if st.button("Vai al Gestionale Ordini"):
        st.switch_page("app_ordini.py")
    st.stop()

st.title("Archiviazione documenti · TEST")
st.info(
    "Collaudo limitato alla cartella TEST BOT CLOUD. "
    "Prima viene generata l'anteprima V4; l'esecuzione resta separata e richiede "
    "una conferma esplicita. Il modulo rifiuta cartelle diverse dalla gerarchia TEST."
)
st.caption(f"Cartella di ingresso del collaudo: {TEST_INBOX_ID}")


def _credenziali_drive():
    if "innova_drive_oauth" not in st.secrets:
        return None
    valori = st.secrets["innova_drive_oauth"]
    richiesti = ("client_id", "client_secret", "refresh_token")
    if any(not valori.get(chiave) for chiave in richiesti):
        return None
    return Credentials(
        token=None,
        refresh_token=valori["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=valori["client_id"],
        client_secret=valori["client_secret"],
        scopes=["https://www.googleapis.com/auth/drive"],
    )


def _servizio_drive():
    return build("drive", "v3", credentials=credenziali, cache_discovery=False)


credenziali = _credenziali_drive()
if credenziali is None:
    st.warning("Autorizzazione Drive non configurata nei Secrets di questa app di test.")
    st.stop()

if "innova_v4_preview_rows" not in st.session_state:
    st.session_state.innova_v4_preview_rows = None
if "innova_v4_base_rows" not in st.session_state:
    st.session_state.innova_v4_base_rows = None
if "innova_v4_snapshot" not in st.session_state:
    st.session_state.innova_v4_snapshot = None
if "innova_v4_last_execution" not in st.session_state:
    st.session_state.innova_v4_last_execution = None


if st.button("Analizza PDF di prova · anteprima V4", type="primary"):
    try:
        with st.spinner("Lettura dei documenti e costruzione anteprima V4…"):
            servizio = _servizio_drive()
            righe_base = anteprima_test(servizio)
            file_memoria = carica_pdf_test(servizio)
            docs = [inspect_cloud(info, contenuto) for info, contenuto in file_memoria]
            piano = build_preview_plan(docs)
            snapshot = make_snapshot(file_memoria, docs, piano)

        st.session_state.innova_v4_base_rows = righe_base
        st.session_state.innova_v4_preview_rows = piano
        st.session_state.innova_v4_snapshot = snapshot
        st.session_state.innova_v4_last_execution = None
    except Exception:
        st.session_state.innova_v4_base_rows = None
        st.session_state.innova_v4_preview_rows = None
        st.session_state.innova_v4_snapshot = None
        st.error(
            "Impossibile completare l'anteprima V4. Controllare autorizzazione, "
            "accesso Drive e formato dei PDF."
        )


righe_base = st.session_state.innova_v4_base_rows
piano = st.session_state.innova_v4_preview_rows
snapshot = st.session_state.innova_v4_snapshot

if righe_base is not None and piano is not None:
    st.success(
        f"Documenti letti: {len(righe_base)}. Piano V4 generato. "
        "Nessun file è stato modificato durante l'anteprima."
    )

    st.subheader("Diagnostica lettura")
    st.dataframe(righe_base, use_container_width=True, hide_index=True)

    st.subheader("Piano di archiviazione V4 · ANTEPRIMA")
    st.dataframe(piano, use_container_width=True, hide_index=True)

    piano_ok = bool(piano) and all(riga.get("Esito") == "ANTEPRIMA SPOSTA" for riga in piano)

    if piano_ok:
        st.success(
            "La coppia di prova è stata riconosciuta come ordine + conferma "
            "Pastificio Mozzo e supera le verifiche V4 previste per questi due PDF."
        )

        st.divider()
        st.subheader("Esecuzione di prova")
        st.warning(
            "Il pulsante seguente PUÒ modificare Google Drive, ma il codice è vincolato "
            "alla sola gerarchia TEST BOT CLOUD. Prima dello spostamento vengono riletti "
            "i PDF, confrontati metadati e SHA-256 e ricontrollate le collisioni."
        )

        conferma = st.checkbox(
            "Confermo che voglio eseguire lo spostamento esclusivamente nel TEST BOT CLOUD",
            key="innova_test_confirm_checkbox",
        )
        frase = st.text_input(
            'Per abilitare il pulsante scrivi esattamente: ESEGUI TEST',
            key="innova_test_confirm_text",
        )
        abilitato = conferma and frase.strip() == "ESEGUI TEST"

        if st.button(
            "ESEGUI SPOSTAMENTO NEL TEST",
            type="primary",
            disabled=not abilitato,
        ):
            try:
                with st.spinner("Rivalidazione e spostamento della coppia nel solo TEST…"):
                    servizio = _servizio_drive()
                    risultati = execute_test_pair(servizio, snapshot)
                st.session_state.innova_v4_last_execution = risultati
                st.session_state.innova_v4_base_rows = None
                st.session_state.innova_v4_preview_rows = None
                st.session_state.innova_v4_snapshot = None
                st.success(
                    "Test eseguito: la coppia è stata spostata nella cartella ORDINI/2026 "
                    "del cliente di prova. Nessun archivio reale è stato usato."
                )
                st.dataframe(risultati, use_container_width=True, hide_index=True)
            except EsecuzioneTestBloccata as exc:
                st.error(str(exc))
            except Exception:
                st.error(
                    "Errore inatteso durante l'esecuzione TEST. "
                    "Controllare manualmente la cartella di prova prima di riprovare."
                )
    else:
        st.warning(
            "La V4 ha bloccato almeno un documento: l'esecuzione resta disabilitata."
        )

if st.session_state.innova_v4_last_execution:
    st.subheader("Ultima esecuzione TEST")
    st.dataframe(
        st.session_state.innova_v4_last_execution,
        use_container_width=True,
        hide_index=True,
    )
