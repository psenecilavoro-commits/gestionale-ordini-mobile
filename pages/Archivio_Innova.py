"""Pagina di collaudo del bot Innova nel Gestionale Ordini principale.

Solo anteprima: nessuna API Drive di scrittura è chiamata da questa pagina.
"""

import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from innova_drive_preview import TEST_INBOX_ID, anteprima_test, carica_pdf_test
from innova_v4_cloud_preview import inspect_cloud, build_preview_plan


st.set_page_config(page_title="Archivio Innova · TEST", layout="wide")

if not st.session_state.get("autenticato", False):
    st.warning("Accedi prima al Gestionale Ordini principale.")
    if st.button("Vai al Gestionale Ordini"):
        st.switch_page("app_ordini.py")
    st.stop()

st.title("Archiviazione documenti · TEST")
st.info(
    "Collaudo in sola lettura nella cartella TEST BOT CLOUD. "
    "La logica V4 viene applicata soltanto per costruire un piano di anteprima: "
    "nessun PDF può essere rinominato, spostato o eliminato da questa pagina."
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


credenziali = _credenziali_drive()
if credenziali is None:
    st.warning(
        "Autorizzazione Drive non configurata nei Secrets di questa app di test."
    )
    st.stop()

if st.button("Analizza PDF di prova · anteprima V4", type="primary"):
    try:
        with st.spinner("Lettura dei documenti e costruzione anteprima V4…"):
            servizio = build("drive", "v3", credentials=credenziali, cache_discovery=False)

            # Diagnostica base: stessa lettura già collaudata.
            righe_base = anteprima_test(servizio)

            # Seconda lettura in memoria per applicare il parser V4 adattato.
            file_memoria = carica_pdf_test(servizio)
            docs = [inspect_cloud(info, contenuto) for info, contenuto in file_memoria]
            piano = build_preview_plan(docs)

        st.success(
            f"Documenti letti: {len(righe_base)}. Piano V4 generato in sola anteprima. "
            "Nessun file modificato."
        )

        st.subheader("Diagnostica lettura")
        st.dataframe(righe_base, use_container_width=True, hide_index=True)

        st.subheader("Piano di archiviazione V4 · SOLO ANTEPRIMA")
        st.dataframe(piano, use_container_width=True, hide_index=True)

        if piano and all(riga.get("Esito") == "ANTEPRIMA SPOSTA" for riga in piano):
            st.success(
                "La coppia di prova è stata riconosciuta come ordine + conferma "
                "Pastificio Mozzo e supera le verifiche V4 previste per questi due PDF."
            )
        elif piano:
            st.warning(
                "La V4 ha bloccato almeno un documento: nessuna operazione è stata eseguita."
            )
    except Exception:
        st.error(
            "Impossibile completare l'anteprima V4. Controllare autorizzazione, "
            "accesso Drive e formato dei PDF."
        )
