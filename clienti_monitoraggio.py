"""Clienti aggiunti manualmente al solo Monitoraggio nella copia locale."""

import streamlit as st
from database import _connect


def carica_clienti_monitoraggio():
    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT cliente FROM clienti_monitoraggio_manual ORDER BY cliente"
            ).fetchall()
        return [r["cliente"] for r in rows]
    except Exception as exc:
        st.warning(f"Clienti manuali non disponibili: {exc}")
        return None


def aggiungi_cliente_monitoraggio(nome):
    nome = " ".join(str(nome or "").split())
    if not nome or len(nome) > 250:
        return False
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO clienti_monitoraggio_manual(cliente) VALUES (?)",
                (nome,),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Impossibile salvare il cliente manuale: {exc}")
        return False


def rimuovi_cliente_monitoraggio(nome):
    if not nome:
        return False
    try:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM clienti_monitoraggio_manual WHERE cliente=?",
                (nome,),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Impossibile rimuovere il cliente manuale: {exc}")
        return False
