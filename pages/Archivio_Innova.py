"""Pagina di collaudo del bot Innova nel Gestionale Ordini principale.

Anteprima V4 generica sul solo TEST BOT CLOUD. L'esecuzione reale resta
volutamente limitata alla coppia Mozzo già collaudata.
"""

import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from innova_drive_preview import (
    TEST_INBOX_ID,
    anteprima_test,
    carica_pdf_test,
    mappa_archivio_test,
)
from innova_v4_cloud_full import inspect_cloud, build_preview_plan
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
    "La lettura e l'anteprima usano ora la logica V4 estesa sul solo TEST BOT CLOUD. "
    "Il pulsante di esecuzione resta disponibile soltanto per la coppia Mozzo già "
    "collaudata: per tutti gli altri documenti questa pagina è ancora sola anteprima."
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


def _alias_clienti():
    if "innova_drive_aliases" not in st.secrets:
        return {}
    raw = st.secrets["innova_drive_aliases"]
    aliases = {}
    for nome, valori in raw.items():
        if isinstance(valori, str):
            aliases[nome] = [valori]
        else:
            aliases[nome] = list(valori)
    return aliases


credenziali = _credenziali_drive()
if credenziali is None:
    st.warning("Autorizzazione Drive non configurata nei Secrets di questa app di test.")
    st.stop()

for key in (
    "innova_v4_preview_rows",
    "innova_v4_base_rows",
    "innova_v4_snapshot",
    "innova_v4_last_execution",
    "innova_v4_client_count",
):
    if key not in st.session_state:
        st.session_state[key] = None


if st.button("Analizza PDF di prova · anteprima V4 completa", type="primary"):
    try:
        with st.spinner("Lettura struttura TEST, documenti e costruzione piano V4…"):
            servizio = _servizio_drive()
            archivio = mappa_archivio_test(servizio)
            client_names = sorted(archivio.keys())
            righe_base = anteprima_test(servizio)
            file_memoria = carica_pdf_test(servizio)
            aliases = _alias_clienti()
            docs = [
                inspect_cloud(info, contenuto, client_names, aliases)
                for info, contenuto in file_memoria
            ]
            piano = build_preview_plan(
                docs,
                archivio,
                "TEST BOT CLOUD / 01 ORDINI SENZA CO",
            )
            snapshot = make_snapshot(file_memoria, docs, piano) if file_memoria else []

        st.session_state.innova_v4_base_rows = righe_base
        st.session_state.innova_v4_preview_rows = piano
        st.session_state.innova_v4_snapshot = snapshot
        st.session_state.innova_v4_client_count = len(client_names)
        st.session_state.innova_v4_last_execution = None
    except Exception:
        st.session_state.innova_v4_base_rows = None
        st.session_state.innova_v4_preview_rows = None
        st.session_state.innova_v4_snapshot = None
        st.session_state.innova_v4_client_count = None
        st.error(
            "Impossibile completare l'anteprima V4 completa. "
            "Nessun file è stato modificato."
        )


righe_base = st.session_state.innova_v4_base_rows
piano = st.session_state.innova_v4_preview_rows
snapshot = st.session_state.innova_v4_snapshot
client_count = st.session_state.innova_v4_client_count

if righe_base is not None and piano is not None:
    st.success(
        f"Clienti TEST rilevati: {client_count or 0} · PDF in ingresso: {len(righe_base)}. "
        "Piano V4 generato senza modificare file."
    )

    if righe_base:
        st.subheader("Diagnostica lettura")
        st.dataframe(righe_base, use_container_width=True, hide_index=True)

    st.subheader("Piano di archiviazione V4 · ANTEPRIMA")
    if piano:
        st.dataframe(piano, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun PDF da elaborare nella cartella di ingresso TEST.")

    anomalie = [r for r in piano if r.get("Esito") == "ANOMALIA"]
    if anomalie:
        st.warning(
            f"Documenti bloccati dalla V4: {len(anomalie)}. "
            "Nessuna esecuzione generica è abilitata."
        )

    eligible_mozzo = (
        len(piano) == 2
        and {r.get("Tipo") for r in piano} == {"ordine", "conferma"}
        and {r.get("Cliente") for r in piano} == {"PASTIFICIO MOZZO SRL"}
        and all(r.get("Esito") == "ANTEPRIMA SPOSTA" for r in piano)
        and all("Coppia ordine-conferma" in r.get("Motivo", "") for r in piano)
    )

    if eligible_mozzo:
        st.success(
            "Questa è la coppia Mozzo già collaudata: è disponibile anche "
            "l'esecuzione controllata nel solo TEST BOT CLOUD."
        )

        st.divider()
        st.subheader("Esecuzione di prova · solo coppia Mozzo")
        st.warning(
            "Il pulsante seguente PUÒ modificare Google Drive, ma il modulo di esecuzione "
            "è ancora hardcoded sulla sola gerarchia TEST e rivalida file, metadati e SHA-256."
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
                    "Test eseguito nel solo TEST BOT CLOUD. "
                    "Nessun archivio reale è stato usato."
                )
                st.dataframe(risultati, use_container_width=True, hide_index=True)
            except EsecuzioneTestBloccata as exc:
                st.error(str(exc))
            except Exception:
                st.error(
                    "Errore inatteso durante l'esecuzione TEST. "
                    "Controllare manualmente la cartella di prova prima di riprovare."
                )

if st.session_state.innova_v4_last_execution:
    st.subheader("Ultima esecuzione TEST")
    st.dataframe(
        st.session_state.innova_v4_last_execution,
        use_container_width=True,
        hide_index=True,
    )
