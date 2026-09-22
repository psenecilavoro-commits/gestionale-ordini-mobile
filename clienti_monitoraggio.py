"""Clienti aggiunti al solo Monitoraggio; nessuna scrittura nella tabella ordini.

La tabella dedicata viene creata SOLO tramite lo script SQL separato,
mai automaticamente dal programma online.
"""

import streamlit as st
from database import supabase

TABELLA = "clienti_monitoraggio_manual"


def carica_clienti_monitoraggio():
    """Lista dei nomi o None se la tabella non è disponibile."""
    if supabase is None:
        return None
    try:
        nomi = []
        inizio = 0
        passo = 1000
        while True:
            risposta = (
                supabase.table(TABELLA)
                .select("cliente")
                .order("cliente")
                .range(inizio, inizio + passo - 1)
                .execute()
            )
            blocco = risposta.data or []
            nomi.extend(r["cliente"] for r in blocco)
            if len(blocco) < passo:
                break
            inizio += passo
        return nomi
    except Exception:
        st.warning(
            "Clienti manuali non disponibili: la tabella dedicata potrebbe non "
            "essere stata creata. Gli ordini e il monitoraggio esistente "
            "non vengono modificati."
        )
        return None


def aggiungi_cliente_monitoraggio(nome):
    """Aggiunge un nominativo alla sola tabella dedicata."""
    nome = " ".join(str(nome or "").split())
    if not nome or len(nome) > 250 or supabase is None:
        return False
    try:
        supabase.table(TABELLA).insert({"cliente": nome}).execute()
        return True
    except Exception:
        st.error("Impossibile salvare il cliente manuale. Verifica che non sia duplicato.")
        return False


def rimuovi_cliente_monitoraggio(nome):
    """Rimuove esclusivamente dalla tabella dedicata, mai dagli ordini."""
    if not nome or supabase is None:
        return False
    try:
        supabase.table(TABELLA).delete().eq("cliente", nome).execute()
        return True
    except Exception:
        st.error("Impossibile rimuovere il cliente manuale.")
        return False
