"""Database locale SQLite per la copia PC distribuibile del Gestionale Ordini.

Mantiene le stesse funzioni usate dall'app cloud, ma tutti i dati restano
nel file locale dati/gestionale_ordini.sqlite. Il database nasce vuoto al
primo avvio. Nessuna connessione Supabase e nessuna credenziale richiesta.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "dati"
DB_PATH = DATA_DIR / "gestionale_ordini.sqlite"

# Compatibilità con moduli storici che importavano questo nome.
supabase = None


def _connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _init_schema(conn)
    return conn


def _init_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ordini (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL DEFAULT '',
            n_ordine TEXT NOT NULL DEFAULT '',
            articolo TEXT NOT NULL DEFAULT '',
            consegna TEXT NOT NULL DEFAULT '',
            quantita TEXT NOT NULL DEFAULT '',
            prezzo TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS articoli_obsoleti_analisi (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL,
            articolo TEXT NOT NULL,
            UNIQUE(cliente, articolo)
        );

        CREATE TABLE IF NOT EXISTS coppie_ignorate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            articolo_a TEXT NOT NULL,
            articolo_b TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mappatura_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parola_chiave TEXT NOT NULL UNIQUE,
            cliente TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS clienti_ignorati_visite (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS articoli_ignorati_previsionale (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL,
            articolo TEXT NOT NULL,
            UNIQUE(cliente, articolo)
        );

        CREATE TABLE IF NOT EXISTS calendar_eventi_gestiti (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calendar_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            stato TEXT NOT NULL,
            cliente TEXT,
            data_evento TEXT,
            UNIQUE(calendar_id, event_id)
        );

        CREATE TABLE IF NOT EXISTS clienti_monitoraggio_manual (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente TEXT NOT NULL UNIQUE
        );
        """
    )
    conn.commit()


def carica_db_cloud():
    try:
        with _connect() as conn:
            rows = conn.execute(
                """SELECT id, cliente, n_ordine, articolo, consegna, quantita, prezzo
                   FROM ordini ORDER BY id"""
            ).fetchall()
        if not rows:
            return pd.DataFrame(columns=[
                "id", "CLIENTE", "N. ORDINE", "ARTICOLO",
                "CONSEGNA", "QUANTITÀ", "PREZZO"
            ])
        df = pd.DataFrame([dict(r) for r in rows]).rename(columns={
            "cliente": "CLIENTE",
            "n_ordine": "N. ORDINE",
            "articolo": "ARTICOLO",
            "consegna": "CONSEGNA",
            "quantita": "QUANTITÀ",
            "prezzo": "PREZZO",
        })
        cols = ["id", "CLIENTE", "N. ORDINE", "ARTICOLO", "CONSEGNA", "QUANTITÀ", "PREZZO"]
        return df[cols].fillna("").astype(str)
    except Exception as exc:
        st.error(f"Errore nel caricamento del database locale: {exc}")
        return pd.DataFrame(columns=[
            "id", "CLIENTE", "N. ORDINE", "ARTICOLO",
            "CONSEGNA", "QUANTITÀ", "PREZZO"
        ])


def inserisci_ordini_cloud(nuovi_dati):
    try:
        righe = [
            (
                str(d.get("CLIENTE", "")),
                str(d.get("N. ORDINE", "")),
                str(d.get("ARTICOLO", "")),
                str(d.get("CONSEGNA", "")),
                str(d.get("QUANTITÀ", "")),
                str(d.get("PREZZO", "")),
            )
            for d in nuovi_dati
        ]
        if not righe:
            return True
        with _connect() as conn:
            conn.executemany(
                """INSERT INTO ordini
                   (cliente, n_ordine, articolo, consegna, quantita, prezzo)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                righe,
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel salvataggio locale: {exc}")
        return False


def rinomina_articolo_cloud(vecchio_nome, nuovo_nome, cliente=None):
    try:
        with _connect() as conn:
            if cliente:
                conn.execute(
                    "UPDATE ordini SET articolo=? WHERE articolo=? AND cliente=?",
                    (nuovo_nome, vecchio_nome, cliente),
                )
            else:
                conn.execute(
                    "UPDATE ordini SET articolo=? WHERE articolo=?",
                    (nuovo_nome, vecchio_nome),
                )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nell'aggiornamento locale dell'articolo: {exc}")
        return False


def carica_articoli_obsoleti_analisi_cloud():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT cliente, articolo FROM articoli_obsoleti_analisi ORDER BY cliente, articolo"
        ).fetchall()
    return [(r["cliente"], r["articolo"]) for r in rows]


def aggiungi_articolo_obsoleto_analisi_cloud(cliente, articolo):
    cliente = str(cliente or "").strip()
    articolo = str(articolo or "").strip()
    if not cliente or not articolo:
        return False
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO articoli_obsoleti_analisi(cliente, articolo) VALUES (?, ?)",
                (cliente, articolo),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel salvataggio dell'articolo obsoleto: {exc}")
        return False


def rimuovi_articolo_obsoleto_analisi_cloud(cliente, articolo):
    try:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM articoli_obsoleti_analisi WHERE cliente=? AND articolo=?",
                (cliente, articolo),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel ripristino dell'articolo: {exc}")
        return False


def carica_coppie_ignorate_cloud():
    with _connect() as conn:
        rows = conn.execute("SELECT articolo_a, articolo_b FROM coppie_ignorate ORDER BY id").fetchall()
    return [tuple(sorted((r["articolo_a"], r["articolo_b"]))) for r in rows]


def aggiungi_coppia_ignorata_cloud(art_a, art_b):
    try:
        a, b = sorted((str(art_a), str(art_b)))
        with _connect() as conn:
            conn.execute(
                "INSERT INTO coppie_ignorate(articolo_a, articolo_b) VALUES (?, ?)",
                (a, b),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel salvataggio della coppia ignorata: {exc}")
        return False


def rimuovi_ultima_coppia_ignorata_cloud():
    try:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM coppie_ignorate WHERE id=(SELECT MAX(id) FROM coppie_ignorate)"
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nella rimozione dell'ultima coppia ignorata: {exc}")
        return False


def svuota_coppie_ignorate_cloud():
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM coppie_ignorate")
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nello svuotamento delle coppie ignorate: {exc}")
        return False


def carica_mappatura_calendar_cloud():
    with _connect() as conn:
        rows = conn.execute("SELECT parola_chiave, cliente FROM mappatura_calendar").fetchall()
    return {r["parola_chiave"]: r["cliente"] for r in rows}


def aggiungi_mappatura_calendar_cloud(parola_chiave, cliente):
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO mappatura_calendar(parola_chiave, cliente)
                   VALUES (?, ?)
                   ON CONFLICT(parola_chiave) DO UPDATE SET cliente=excluded.cliente""",
                (str(parola_chiave), str(cliente)),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel salvataggio della regola Calendar: {exc}")
        return False


def rimuovi_mappatura_calendar_cloud(parola_chiave):
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM mappatura_calendar WHERE parola_chiave=?", (parola_chiave,))
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nella rimozione della regola Calendar: {exc}")
        return False


def svuota_mappatura_calendar_cloud():
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM mappatura_calendar")
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nello svuotamento delle regole Calendar: {exc}")
        return False


def carica_clienti_ignorati_visite_cloud():
    with _connect() as conn:
        rows = conn.execute("SELECT cliente FROM clienti_ignorati_visite ORDER BY cliente").fetchall()
    return [r["cliente"] for r in rows]


def aggiungi_clienti_ignorati_visite_cloud(lista_clienti_nomi):
    try:
        with _connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO clienti_ignorati_visite(cliente) VALUES (?)",
                [(str(nome),) for nome in lista_clienti_nomi if nome],
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nell'esclusione dei clienti: {exc}")
        return False


def rimuovi_cliente_ignorato_visita_cloud(cliente_nome):
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM clienti_ignorati_visite WHERE cliente=?", (cliente_nome,))
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel ripristino del cliente: {exc}")
        return False


def svuota_clienti_ignorati_visite_cloud():
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM clienti_ignorati_visite")
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel ripristino dei clienti: {exc}")
        return False


def carica_articoli_ignorati_prev_cloud():
    with _connect() as conn:
        rows = conn.execute(
            "SELECT cliente, articolo FROM articoli_ignorati_previsionale ORDER BY cliente, articolo"
        ).fetchall()
    return [(r["cliente"], r["articolo"]) for r in rows]


def aggiungi_articoli_ignorati_prev_cloud(lista_coppie):
    try:
        with _connect() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO articoli_ignorati_previsionale(cliente, articolo)
                   VALUES (?, ?)""",
                [(str(c), str(a)) for c, a in lista_coppie if c and a],
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nell'esclusione dal previsionale: {exc}")
        return False


def rimuovi_articolo_ignorato_prev_cloud(cliente, articolo):
    try:
        with _connect() as conn:
            conn.execute(
                "DELETE FROM articoli_ignorati_previsionale WHERE cliente=? AND articolo=?",
                (cliente, articolo),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel ripristino dal previsionale: {exc}")
        return False


def svuota_articoli_ignorati_prev_cloud():
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM articoli_ignorati_previsionale")
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel ripristino totale del previsionale: {exc}")
        return False


def carica_decisioni_eventi_calendar_cloud():
    try:
        with _connect() as conn:
            rows = conn.execute(
                """SELECT calendar_id, event_id, stato, cliente, data_evento
                   FROM calendar_eventi_gestiti
                   ORDER BY calendar_id, event_id"""
            ).fetchall()
        return {
            (str(r["calendar_id"]), str(r["event_id"])): dict(r)
            for r in rows
        }
    except Exception as exc:
        st.error(f"Impossibile leggere gli eventi Calendar locali: {exc}")
        return None


def salva_decisione_evento_calendar_cloud(evento, stato, cliente=None):
    if stato not in {"ignorato", "associato"}:
        st.error("Stato evento non valido.")
        return False
    cliente = str(cliente).strip() if cliente is not None else None
    if stato == "associato" and not cliente:
        st.warning("Seleziona il cliente da associare.")
        return False
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO calendar_eventi_gestiti
                   (calendar_id, event_id, stato, cliente, data_evento)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(calendar_id, event_id)
                   DO UPDATE SET
                       stato=excluded.stato,
                       cliente=excluded.cliente,
                       data_evento=excluded.data_evento""",
                (
                    str(evento["calendar_id"]),
                    str(evento["event_id"]),
                    stato,
                    cliente if stato == "associato" else None,
                    str(evento.get("data_evento", "")),
                ),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel salvataggio della decisione Calendar: {exc}")
        return False


def ripristina_evento_ignorato_calendar_cloud(evento):
    try:
        with _connect() as conn:
            conn.execute(
                """DELETE FROM calendar_eventi_gestiti
                   WHERE calendar_id=? AND event_id=? AND stato='ignorato'""",
                (str(evento["calendar_id"]), str(evento["event_id"])),
            )
            conn.commit()
        return True
    except Exception as exc:
        st.error(f"Errore nel ripristino dell'evento: {exc}")
        return False
