"""Pagina di collaudo del bot Innova nel Gestionale Ordini principale.

Anteprima ed esecuzione generica V4 sono limitate alla sola gerarchia
TEST BOT CLOUD. Nessun ID dell'archivio reale è usato da questa pagina.
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
from innova_drive_modes import real_runtime_from_secrets
from innova_drive_readonly import (
    ArchivioReadOnlyError,
    load_pdf_inbox,
    map_archive,
    verify_runtime,
)
from innova_drive_execute_test import (
    EsecuzioneTestBloccata,
    execute_test_plan,
    make_snapshot,
    self_test_protections,
)


st.set_page_config(page_title="Archivio Innova · TEST", layout="wide")

if not st.session_state.get("autenticato", False):
    st.warning("Accedi prima al Gestionale Ordini principale.")
    if st.button("Vai al Gestionale Ordini"):
        st.switch_page("app_ordini.py")
    st.stop()

st.title("Archiviazione documenti · TEST")
st.info(
    "La V4 completa può ora essere eseguita sul solo TEST BOT CLOUD. "
    "Prima di ogni scrittura il lotto viene riletto e rivalidato; "
    "qualsiasi anomalia blocca l'esecuzione generica. "
    "Sono attive anche protezione anti-esecuzione simultanea e ricevuta di idempotenza."
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


def _piano_visibile(piano):
    return [
        {k: v for k, v in riga.items() if not k.startswith("_")}
        for riga in piano
    ]


credenziali = _credenziali_drive()
if credenziali is None:
    st.warning("Autorizzazione Drive non configurata nei Secrets di questa app di test.")
    st.stop()


st.divider()
st.subheader("Archivio REALE · SOLO LETTURA")
try:
    runtime_reale = real_runtime_from_secrets(st.secrets)
except Exception as exc:
    runtime_reale = None
    st.error(f"Configurazione REALE non valida: {exc}")

if runtime_reale is None:
    st.info(
        "La configurazione REALE non è ancora presente nei Secrets. "
        "Aggiungila con writes_enabled = false: finché resta false, "
        "questa pagina non abilita alcuna scrittura sull'archivio reale."
    )
elif runtime_reale.writes_enabled:
    st.error(
        "Sicurezza: writes_enabled è TRUE nei Secrets. "
        "Questa fase richiede writes_enabled = false; anteprima REALE bloccata."
    )
else:
    st.success(
        "Configurazione REALE caricata con scritture DISABILITATE. "
        "Disponibile solo anteprima in lettura."
    )
    if st.button("ANALIZZA ARCHIVIO REALE · SOLA LETTURA", key="innova_real_preview"):
        try:
            with st.spinner("Lettura archivio REALE senza modifiche…"):
                servizio = _servizio_drive()
                verify_runtime(servizio, runtime_reale)
                archivio_reale = map_archive(servizio, runtime_reale)
                file_reali = load_pdf_inbox(servizio, runtime_reale)
                aliases = _alias_clienti()
                docs_reali = [
                    inspect_cloud(info, contenuto, sorted(archivio_reale.keys()), aliases)
                    for info, contenuto in file_reali
                ]
                piano_reale = build_preview_plan(
                    docs_reali,
                    archivio_reale,
                    f"{runtime_reale.root_name} / 01 ORDINI SENZA CO",
                )

            st.success(
                f"Anteprima REALE completata in sola lettura: "
                f"{len(archivio_reale)} clienti rilevati · {len(file_reali)} PDF in ingresso. "
                "Nessun file modificato."
            )
            if piano_reale:
                st.dataframe(
                    _piano_visibile(piano_reale),
                    use_container_width=True,
                    hide_index=True,
                )
                anomalie_reali = [
                    r for r in piano_reale if r.get("Esito") == "ANOMALIA"
                ]
                if anomalie_reali:
                    st.warning(
                        f"Anteprima REALE: {len(anomalie_reali)} documenti richiedono controllo."
                    )
                else:
                    st.success(
                        "Anteprima REALE senza anomalie. "
                        "Le scritture restano comunque disabilitate."
                    )
            else:
                st.info("Nessun PDF presente nella cartella REALE di ingresso.")
        except ArchivioReadOnlyError as exc:
            st.error(str(exc))
        except Exception:
            st.error(
                "Errore inatteso durante l'anteprima REALE. "
                "Nessun file è stato modificato."
            )


with st.expander("Diagnostica protezioni TEST", expanded=False):
    st.caption(
        "Questo controllo usa soltanto la cartella tecnica _BOT_CONTROL. "
        "Non sposta, rinomina o elimina documenti cliente."
    )
    if st.button("TESTA LOCK E IDEMPOTENZA", key="innova_test_protezioni"):
        try:
            with st.spinner("Verifica lock concorrente e idempotenza…"):
                servizio = _servizio_drive()
                esiti_protezioni = self_test_protections(servizio)
            st.success("Protezioni TEST verificate.")
            st.dataframe(
                esiti_protezioni,
                use_container_width=True,
                hide_index=True,
            )
        except EsecuzioneTestBloccata as exc:
            st.error(str(exc))
        except Exception:
            st.error(
                "Errore inatteso durante il test delle protezioni. "
                "Nessun documento cliente è stato modificato."
            )

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
        st.dataframe(
            _piano_visibile(piano),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nessun PDF da elaborare nella cartella di ingresso TEST.")

    anomalie = [r for r in piano if r.get("Esito") == "ANOMALIA"]
    eseguibili = [
        r for r in piano
        if r.get("Esito") in {"ANTEPRIMA SPOSTA", "ANTEPRIMA RINOMINA"}
    ]

    if anomalie:
        st.warning(
            f"Documenti bloccati dalla V4: {len(anomalie)}. "
            "L'esecuzione generica resta disabilitata finché il piano contiene anomalie."
        )

    lotto_ok = bool(piano) and not anomalie and len(eseguibili) == len(piano)

    if lotto_ok:
        spostamenti = sum(r.get("Esito") == "ANTEPRIMA SPOSTA" for r in piano)
        rinomine = sum(r.get("Esito") == "ANTEPRIMA RINOMINA" for r in piano)

        st.success(
            f"Lotto TEST eseguibile: {len(piano)} documenti · "
            f"{spostamenti} spostamenti · {rinomine} rinomine."
        )

        st.divider()
        st.subheader("Esecuzione generica · SOLO TEST BOT CLOUD")
        st.warning(
            "Il comando seguente modifica Google Drive, ma può scrivere solo nella "
            "gerarchia TEST BOT CLOUD. Prima di ogni scrittura ricontrolla file, "
            "metadati, SHA-256, piano V4 e collisioni. In caso di errore tenta il "
            "rollback dell'intero lotto. Un lock su Drive impedisce due esecuzioni "
            "contemporanee e una ricevuta impedisce di rieseguire lo stesso identico lotto."
        )

        conferma = st.checkbox(
            "Confermo che voglio eseguire l'intero lotto esclusivamente nel TEST BOT CLOUD",
            key="innova_generic_test_confirm_checkbox",
        )
        frase = st.text_input(
            'Per abilitare il pulsante scrivi esattamente: ESEGUI LOTTO TEST',
            key="innova_generic_test_confirm_text",
        )
        abilitato = conferma and frase.strip() == "ESEGUI LOTTO TEST"

        if st.button(
            "ESEGUI LOTTO V4 NEL TEST",
            type="primary",
            disabled=not abilitato,
        ):
            try:
                with st.spinner(
                    "Rivalidazione completa e archiviazione del lotto nel solo TEST…"
                ):
                    servizio = _servizio_drive()
                    risultati = execute_test_plan(
                        servizio,
                        snapshot,
                        _alias_clienti(),
                    )

                st.session_state.innova_v4_last_execution = risultati
                st.session_state.innova_v4_base_rows = None
                st.session_state.innova_v4_preview_rows = None
                st.session_state.innova_v4_snapshot = None
                st.session_state.innova_v4_client_count = None

                st.success(
                    f"Lotto TEST completato: {len(risultati)} documenti gestiti. "
                    "Nessun archivio reale è stato usato."
                )
                st.dataframe(
                    risultati,
                    use_container_width=True,
                    hide_index=True,
                )
            except EsecuzioneTestBloccata as exc:
                st.error(str(exc))
            except Exception:
                st.error(
                    "Errore inatteso durante l'esecuzione del lotto TEST. "
                    "Controllare manualmente TEST BOT CLOUD prima di riprovare."
                )

if st.session_state.innova_v4_last_execution:
    st.subheader("Ultima esecuzione TEST")
    st.dataframe(
        st.session_state.innova_v4_last_execution,
        use_container_width=True,
        hide_index=True,
    )
