"""Stile condiviso del Gestionale Ordini.

Replica la palette blu pastello del Gestionale Partita IVA e definisce
la navigazione laterale con le sole voci Database e Automazione.
"""

import streamlit as st

_CSS = """
<style>
:root {
  --gest-blu-chiaro: #e9f4ff;
  --gest-blu-medio: #cde6f8;
  --gest-blu-accento: #4b89bb;
  --gest-blu-scuro: #193c5a;
}
[data-testid="stAppViewContainer"] {
  background: linear-gradient(155deg, #f4f9ff 0%, #edf6ff 56%, #f8fbff 100%);
}
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #dfedfa 0%, #edf6ff 100%);
  border-right: 1px solid #bbd6eb;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li {
  color: var(--gest-blu-scuro);
}
[data-testid="stHeader"] { background: rgba(244,249,255,.94); }
.stApp h1, .stApp h2, .stApp h3 { color: #204e73; letter-spacing: -.015em; }
.stApp [data-testid="stForm"],
.stApp [data-testid="stExpander"],
.stApp [data-testid="stVerticalBlockBorderWrapper"] {
  border-color: #c7dff1;
  border-radius: 12px;
}
.stApp [data-baseweb="tab-list"] {
  background-color: #e2f0fb;
  border: 1px solid #c7dff1;
  border-radius: 12px;
  padding: 4px;
  gap: 3px;
}
.stApp button[role="tab"] {
  border-radius: 9px;
  color: #285a7e;
}
.stApp button[role="tab"][aria-selected="true"] {
  background: #ffffff;
  color: #1d527b;
  box-shadow: 0 1px 5px rgba(36,84,126,.12);
}
.stApp button[kind="primary"],
.stApp button[data-testid="stBaseButton-primary"] {
  background-color: #4b89bb !important;
  border-color: #4b89bb !important;
  color: #ffffff !important;
  border-radius: 9px;
}
.stApp button[kind="primary"]:hover,
.stApp button[data-testid="stBaseButton-primary"]:hover {
  background-color: #326f9f !important;
  border-color: #326f9f !important;
  color: #ffffff !important;
}
.stApp button:focus-visible,
.stApp input:focus-visible,
.stApp textarea:focus-visible {
  outline: 3px solid #2d6b9d !important;
  outline-offset: 2px;
}
.stApp [data-testid="stDataFrame"] {
  border: 1px solid #c7dff1;
  border-radius: 10px;
  overflow: hidden;
}
.stApp [data-testid="stMetric"] {
  background: #e8f3fd;
  border: 1px solid #c7dff1;
  border-radius: 10px;
  padding: 12px;
}
[data-testid="stSidebar"] [data-testid="stDataFrame"] {
  border-radius: 10px;
  border: 1px solid #b6d3e9;
}
/* Nasconde la navigazione multipagina generata automaticamente:
   viene sostituita dai due link con etichette richieste. */
[data-testid="stSidebarNav"] {
  display: none;
}
@media (min-width: 1050px) {
  [data-testid="stSidebar"][aria-expanded="true"] {
    min-width: 390px;
    max-width: 430px;
  }
}
@media (max-width: 700px) {
  .stApp [data-baseweb="tab-list"] { flex-wrap: wrap; }
}
</style>
"""


def applica_stile() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def mostra_navigazione() -> None:
    with st.sidebar:
        st.page_link("app_ordini.py", label="Database")
        st.page_link("pages/Archivio_Innova.py", label="Automazione")
        st.divider()
