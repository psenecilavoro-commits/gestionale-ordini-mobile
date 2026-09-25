"""Archivio Innova nel Gestionale Ordini.

Pagina desktop per analisi e archiviazione supervisionata dei PDF su Google Drive.
La configurazione reale arriva esclusivamente dai Secrets Streamlit.
"""

import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from innova_v4_cloud_full import inspect_cloud, build_preview_plan
from innova_drive_modes import real_runtime_from_secrets
from innova_drive_readonly import (
    ArchivioReadOnlyError,
    load_pdf_inbox,
    map_archive,
    verify_runtime,
)
from innova_drive_execute_real import (
    EsecuzioneRealeBloccata,
    make_snapshot,
    execute_real_group,
    execute_real_all,
)
from stile import applica_stile, mostra_navigazione


st.set_page_config(page_title="Archivio Innova", layout="wide")
applica_stile()
mostra_navigazione()

if not st.session_state.get("autenticato", False):
    st.warning("Accedi prima al Gestionale Ordini.")
    if st.button("Vai al Gestionale Ordini"):
        st.switch_page("app_ordini.py")
    st.stop()

st.title("Archivio Innova")
st.caption(
    "Analizza i documenti presenti nella cartella di ingresso e archivia un solo gruppo per volta."
)


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
        aliases[nome] = [valori] if isinstance(valori, str) else list(valori)
    return aliases


def _piano_visibile(piano):
    return [
        {k: v for k, v in riga.items() if not k.startswith("_")}
        for riga in piano
    ]


def _gruppi_eseguibili(piano):
    allowed = {"ANTEPRIMA SPOSTA", "ANTEPRIMA RINOMINA"}
    grouped = {}
    for row in piano or []:
        gid = row.get("_group_id")
        if not gid:
            continue
        grouped.setdefault(gid, []).append(row)

    result = []
    for gid, rows in grouped.items():
        if any(row.get("Esito") not in allowed for row in rows):
            continue

        if gid.startswith("PAIR:"):
            if len(rows) != 2 or {row.get("Tipo") for row in rows} != {"ordine", "conferma"}:
                continue
            if any("Coppia ordine-conferma" not in row.get("Motivo", "") for row in rows):
                continue
            first = rows[0]
            order_no = next(
                (str(row.get("N. ordine")) for row in rows if row.get("N. ordine")),
                "",
            )
            suffix = f"ordine {order_no}" if order_no else first.get("Data", "")
            label = f"COPPIA · {first.get('Cliente', '')} · {suffix}"
        else:
            if len(rows) != 1:
                continue
            row = rows[0]
            if row.get("Tipo") == "offerta":
                prefix = "OFFERTA"
            elif row.get("Esito") == "ANTEPRIMA RINOMINA":
                prefix = "ORDINE IN ATTESA"
            else:
                prefix = str(row.get("Tipo", "")).upper()
            label = f"{prefix} · {row.get('Cliente', '')} · {row.get('File originale', '')}"

        result.append({
            "group_id": gid,
            "label": label,
            "file_ids": [row.get("_file_id") for row in rows],
            "rows": rows,
        })

    result.sort(key=lambda item: item["label"].casefold())
    for i, item in enumerate(result, start=1):
        item["display"] = f"{i}. {item['label']}"
    return result


credenziali = _credenziali_drive()
if credenziali is None:
    st.error("Autorizzazione Google Drive non configurata.")
    st.stop()

try:
    runtime = real_runtime_from_secrets(st.secrets)
except Exception as exc:
    runtime = None
    st.error(f"Configurazione Archivio Innova non valida: {exc}")

if runtime is None:
    st.error("Configurazione dell'archivio non presente nei Secrets.")
    st.stop()

for key in (
    "innova_real_preview_rows",
    "innova_real_snapshot",
    "innova_real_client_count",
    "innova_real_file_count",
    "innova_real_last_execution",
):
    if key not in st.session_state:
        st.session_state[key] = None

if runtime.writes_enabled:
    st.success("Archiviazione abilitata.")
else:
    st.info(
        "Analisi disponibile. Le modifiche a Google Drive sono attualmente disabilitate."
    )

if st.button("Analizza archivio", type="primary"):
    try:
        with st.spinner("Analisi documenti in corso…"):
            servizio = _servizio_drive()
            verify_runtime(servizio, runtime)
            archivio = map_archive(servizio, runtime)
            file_memoria = load_pdf_inbox(servizio, runtime)
            aliases = _alias_clienti()
            docs = [
                inspect_cloud(
                    info,
                    contenuto,
                    sorted(archivio.keys()),
                    aliases,
                )
                for info, contenuto in file_memoria
            ]
            piano = build_preview_plan(
                docs,
                archivio,
                f"{runtime.root_name} / 01 ORDINI SENZA CO",
            )
            snapshot = (
                make_snapshot(file_memoria, docs, piano)
                if file_memoria
                else []
            )

        st.session_state.innova_real_preview_rows = piano
        st.session_state.innova_real_snapshot = snapshot
        st.session_state.innova_real_client_count = len(archivio)
        st.session_state.innova_real_file_count = len(file_memoria)
        st.session_state.innova_real_last_execution = None
    except ArchivioReadOnlyError as exc:
        st.error(str(exc))
    except Exception:
        st.session_state.innova_real_preview_rows = None
        st.session_state.innova_real_snapshot = None
        st.session_state.innova_real_client_count = None
        st.session_state.innova_real_file_count = None
        st.error("Impossibile completare l'analisi. Nessun file è stato modificato.")

piano = st.session_state.innova_real_preview_rows
snapshot = st.session_state.innova_real_snapshot

if piano is not None:
    st.subheader("Anteprima")
    st.caption(
        f"Clienti rilevati: {st.session_state.innova_real_client_count or 0} · "
        f"PDF in ingresso: {st.session_state.innova_real_file_count or 0}"
    )

    if piano:
        st.dataframe(
            _piano_visibile(piano),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Nessun PDF presente nella cartella di ingresso.")

    anomalie = [row for row in piano if row.get("Esito") == "ANOMALIA"]
    if anomalie:
        st.warning(
            f"{len(anomalie)} documenti richiedono controllo e non sono eseguibili automaticamente."
        )
    elif piano:
        st.success("Anteprima senza anomalie.")

    gruppi = _gruppi_eseguibili(piano)

    if gruppi and not runtime.writes_enabled:
        st.info(
            f"Gruppi eseguibili rilevati: {len(gruppi)}. "
            "Le modifiche sono disabilitate dalla configurazione."
        )

    if gruppi and runtime.writes_enabled:
        st.divider()
        st.subheader("Archivia tutti")
        totale_documenti = sum(len(item["file_ids"]) for item in gruppi)
        st.caption(
            f"Archivia in un solo passaggio tutti i {len(gruppi)} gruppi conformi "
            f"alle regole V4 ({totale_documenti} documenti). "
            "Eventuali anomalie restano escluse e non vengono modificate."
        )

        conferma_tutti = st.checkbox(
            "Confermo di voler archiviare tutti i gruppi conformi mostrati nell'anteprima",
            key="innova_real_all_confirm_checkbox",
        )
        frase_tutti = st.text_input(
            'Per abilitare il pulsante scrivi esattamente: ARCHIVIA TUTTI',
            key="innova_real_all_confirm_text",
        )
        enabled_tutti = (
            conferma_tutti
            and frase_tutti.strip() == "ARCHIVIA TUTTI"
        )

        if st.button(
            "Archivia tutti",
            type="primary",
            disabled=not enabled_tutti,
            key="innova_real_execute_all",
        ):
            try:
                with st.spinner(
                    "Rivalidazione completa e archiviazione di tutti i gruppi conformi…"
                ):
                    servizio = _servizio_drive()
                    risultati = execute_real_all(
                        servizio,
                        runtime,
                        snapshot,
                        _alias_clienti(),
                    )

                st.session_state.innova_real_last_execution = risultati
                st.session_state.innova_real_preview_rows = None
                st.session_state.innova_real_snapshot = None
                st.session_state.innova_real_client_count = None
                st.session_state.innova_real_file_count = None

                st.success(
                    f"Archiviazione completa: {len(risultati)} documenti gestiti."
                )
                st.dataframe(
                    risultati,
                    use_container_width=True,
                    hide_index=True,
                )
            except EsecuzioneRealeBloccata as exc:
                st.error(str(exc))
            except Exception:
                st.error(
                    "Errore durante Archivia tutti. "
                    "Controllare manualmente Google Drive prima di riprovare."
                )

        st.divider()
        st.subheader("Esegui un gruppo")

        options = ["— seleziona un gruppo —"] + [
            item["display"] for item in gruppi
        ]
        scelta = st.selectbox(
            "Gruppo da archiviare",
            options,
            key="innova_real_group_choice",
        )

        if scelta != options[0]:
            selected = gruppi[options.index(scelta) - 1]

            st.dataframe(
                _piano_visibile(selected["rows"]),
                use_container_width=True,
                hide_index=True,
            )

            conferma = st.checkbox(
                "Confermo di voler eseguire soltanto il gruppo selezionato",
                key="innova_real_confirm_checkbox",
            )
            frase = st.text_input(
                'Per abilitare il pulsante scrivi esattamente: ESEGUI',
                key="innova_real_confirm_text",
            )
            enabled = conferma and frase.strip() == "ESEGUI"

            if st.button(
                "Esegui archiviazione",
                type="primary",
                disabled=not enabled,
                key="innova_real_execute",
            ):
                try:
                    with st.spinner("Rivalidazione e archiviazione in corso…"):
                        servizio = _servizio_drive()
                        risultati = execute_real_group(
                            servizio,
                            runtime,
                            snapshot,
                            selected["file_ids"],
                            _alias_clienti(),
                        )

                    st.session_state.innova_real_last_execution = risultati
                    st.session_state.innova_real_preview_rows = None
                    st.session_state.innova_real_snapshot = None
                    st.session_state.innova_real_client_count = None
                    st.session_state.innova_real_file_count = None

                    st.success(
                        f"Archiviazione completata: {len(risultati)} documenti gestiti."
                    )
                    st.dataframe(
                        risultati,
                        use_container_width=True,
                        hide_index=True,
                    )
                except EsecuzioneRealeBloccata as exc:
                    st.error(str(exc))
                except Exception:
                    st.error(
                        "Errore durante l'archiviazione. "
                        "Controllare manualmente Google Drive prima di riprovare."
                    )

if st.session_state.innova_real_last_execution:
    st.subheader("Ultima esecuzione")
    st.dataframe(
        st.session_state.innova_real_last_execution,
        use_container_width=True,
        hide_index=True,
    )
