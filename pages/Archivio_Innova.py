"""Pagina di collaudo del bot Innova, parte del Gestionale Ordini principale.

NON integra ancora la logica di archiviazione V4; nessuna scrittura su Drive.
Non usare in produzione prima di revisione, test e configurazione sicura.
"""

import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from innova_drive_preview import TEST_INBOX_ID, anteprima_test


st.set_page_config(page_title="Archivio Innova · TEST", layout="wide")

# Le pagine Streamlit hanno uno script proprio: non dare per scontato che
# il controllo password della pagina principale venga eseguito anche qui.
if not st.session_state.get("autenticato", False):
    st.warning("Accedi prima al Gestionale Ordini principale.")
    if st.button("Vai al Gestionale Ordini"):
        st.switch_page("app_ordini.py")
    st.stop()

st.title("Archiviazione documenti · TEST")
st.info(
    "Prima fase: sola lettura nella cartella TEST BOT CLOUD. "
    "Nessun PDF può essere rinominato, spostato o eliminato da questa pagina. "
    "La classificazione e gli abbinamenti del bot V4 non sono ancora integrati."
)
st.caption(f"Cartella di ingresso del collaudo: {TEST_INBOX_ID}")


def _credenziali_drive():
    """Usa un token OAuth già autorizzato, custodito soltanto nei Secrets.

    Non stampa, memorizza su GitHub o mostra al browser alcuna credenziale.
    La procedura sicura per ottenere il refresh token verrà definita e testata
    prima di rendere questa pagina utilizzabile.
    """
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
        "Autorizzazione Drive non ancora configurata nei Secrets di Streamlit. "
        "Il collaudo resta disabilitato; non inserire credenziali in chat o su GitHub."
    )
    st.stop()

if st.button("Analizza PDF di prova (sola lettura)", type="primary"):
    try:
        with st.spinner("Lettura dei documenti nella sola cartella TEST BOT CLOUD…"):
            servizio = build("drive", "v3", credentials=credenziali, cache_discovery=False)
            righe = anteprima_test(servizio)
        st.success(f"Documenti di prova letti: {len(righe)}. Nessun file modificato.")
        if righe:
            st.dataframe(righe, use_container_width=True, hide_index=True)
        else:
            st.info("Nessun PDF nella cartella di ingresso di prova.")
    except Exception:
        # Evita di rendere pubblici dati Drive o dettagli di autenticazione.
        st.error("Impossibile leggere la cartella TEST: controllare autorizzazione e accesso Drive.")
