import hmac

import pandas as pd
import streamlit as st
from supabase import Client, create_client


st.set_page_config(
    page_title="Ordini Mobile",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# L'app mobile non usa una barra laterale: nascondiamola anche quando
# il browser cambia orientamento o ricorda uno stato precedente.
st.markdown(
    """
    <style>
    section[data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"] {
        display: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# ACCESSO CON PASSWORD (PRIMA DI LEGGERE I DATI)
# ---------------------------------------------------------
def verifica_password():
    try:
        password_configurata = st.secrets["app"]["password"]
    except (KeyError, FileNotFoundError):
        st.error("Password non configurata. Controlla la sezione [app] nei Secrets dell'app mobile.")
        st.stop()

    if not password_configurata:
        st.error("Password non configurata. Controlla i Secrets dell'app mobile.")
        st.stop()

    if st.session_state.get("autenticato_mobile", False):
        return

    st.title("🔒 Accesso riservato — Ordini Mobile")
    password_inserita = st.text_input("Password di accesso", type="password")
    if st.button("Accedi", type="primary"):
        if hmac.compare_digest(str(password_inserita), str(password_configurata)):
            st.session_state.autenticato_mobile = True
            st.rerun()
        else:
            st.error("Password errata.")
    st.stop()


verifica_password()

# ---------------------------------------------------------
# CONNESSIONE SUPABASE: CREDENZIALI SOLO NEI SECRETS
# ---------------------------------------------------------
@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)


try:
    supabase = init_supabase()
except Exception:
    st.error("Connessione a Supabase non configurata. Verifica [supabase] nei Secrets dell'app mobile.")
    st.stop()

# ---------------------------------------------------------
# CARICAMENTO ORDINI (SOLA LETTURA, PAGINATO)
# ---------------------------------------------------------
def carica_db_cloud():
    try:
        tutti_i_dati = []
        step = 1000
        inizio = 0
        while True:
            risposta = (
                supabase.table("ordini")
                .select("*")
                .order("id")
                .range(inizio, inizio + step - 1)
                .execute()
            )
            batch = risposta.data or []
            tutti_i_dati.extend(batch)
            if len(batch) < step:
                break
            inizio += step

        colonne_standard = [
            "CLIENTE", "N. ORDINE", "ARTICOLO",
            "CONSEGNA", "QUANTITÀ", "PREZZO",
        ]
        if not tutti_i_dati:
            return pd.DataFrame(columns=colonne_standard)

        df = pd.DataFrame(tutti_i_dati).rename(columns={
            "cliente": "CLIENTE",
            "n_ordine": "N. ORDINE",
            "articolo": "ARTICOLO",
            "consegna": "CONSEGNA",
            "quantita": "QUANTITÀ",
            "prezzo": "PREZZO",
        })
        for colonna in colonne_standard:
            if colonna not in df.columns:
                df[colonna] = ""
        return df[colonne_standard].fillna("").astype(str)
    except Exception:
        st.error("Impossibile leggere gli ordini da Supabase. Controlla i Secrets e i log dell'app mobile.")
        return None

# ---------------------------------------------------------
# INTERFACCIA MOBILE (CONSULTAZIONE E COMPARATIVA)
# ---------------------------------------------------------
st.title("📱 Consulta & Compara Ordini")

# Il comando di uscita resta accessibile senza occupare metà schermo.
if st.button("🔒 Disconnetti", key="mobile_logout"):
    st.session_state.autenticato_mobile = False
    st.session_state.pop("db_ordini", None)
    st.rerun()

if "db_ordini" not in st.session_state:
    dati = carica_db_cloud()
    if dati is None:
        st.stop()
    st.session_state.db_ordini = dati

if st.button("🔄 Aggiorna Dati"):
    dati = carica_db_cloud()
    if dati is not None:
        st.session_state.db_ordini = dati
        st.rerun()

df = st.session_state.db_ordini

if not df.empty:
    col_c, col_a = st.columns(2)

    list_clienti = ["Tutti"] + sorted(
        [x for x in df["CLIENTE"].unique() if str(x).strip()]
    )
    cli_sel = col_c.selectbox("Cliente:", list_clienti, key="mob_cli")

    df_filt = df.copy()
    if cli_sel != "Tutti":
        df_filt = df_filt[df_filt["CLIENTE"] == cli_sel]

    list_articoli = ["Tutti"] + sorted(
        [x for x in df_filt["ARTICOLO"].unique() if str(x).strip()]
    )
    art_sel = col_a.selectbox("Articolo:", list_articoli, key="mob_art")

    if art_sel != "Tutti":
        df_filt = df_filt[df_filt["ARTICOLO"] == art_sel]

    st.caption(f"Ordini trovati: **{len(df_filt)}**")
    st.dataframe(df_filt, use_container_width=True, hide_index=True)
else:
    st.info("Il database non contiene ordini.")
