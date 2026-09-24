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
from innova_drive_execute_real import (
    EsecuzioneRealeBloccata,
    execute_real_group,
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


def _gruppi_reali_eseguibili(piano):
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
    st.warning("Autorizzazione Drive non configurata nei Secrets di questa app di test.")
    st.stop()


st.divider()
st.subheader("Archivio REALE")

for key in (
    "innova_real_preview_rows",
    "innova_real_snapshot",
    "innova_real_client_count",
    "innova_real_file_count",
    "innova_real_last_execution",
):
    if key not in st.session_state:
        st.session_state[key] = None

try:
    runtime_reale = real_runtime_from_secrets(st.secrets)
except Exception as exc:
    runtime_reale = None
    st.error(f"Configurazione REALE non valida: {exc}")

if runtime_reale is None:
    st.info(
        "La configurazione REALE non è presente nei Secrets. "
        "Nessuna lettura o scrittura REALE è disponibile."
    )
else:
    if runtime_reale.writes_enabled:
        st.warning(
            "SCRITTURE REALI ABILITATE nei Secrets. "
            "L'analisi resta sempre in sola lettura; l'esecuzione richiede inoltre "
            "la selezione di UN SOLO gruppo, una conferma esplicita e la frase di sicurezza."
        )
    else:
        st.success(
            "Configurazione REALE caricata con scritture DISABILITATE. "
            "È disponibile soltanto l'anteprima."
        )

    if st.button(
        "ANALIZZA ARCHIVIO REALE · SOLA LETTURA",
        key="innova_real_preview",
    ):
        try:
            with st.spinner("Lettura archivio REALE senza modifiche…"):
                servizio = _servizio_drive()
                verify_runtime(servizio, runtime_reale)
                archivio_reale = map_archive(servizio, runtime_reale)
                file_reali = load_pdf_inbox(servizio, runtime_reale)
                aliases = _alias_clienti()
                docs_reali = [
                    inspect_cloud(
                        info,
                        contenuto,
                        sorted(archivio_reale.keys()),
                        aliases,
                    )
                    for info, contenuto in file_reali
                ]
                piano_reale = build_preview_plan(
                    docs_reali,
                    archivio_reale,
                    f"{runtime_reale.root_name} / 01 ORDINI SENZA CO",
                )
                snapshot_reale = (
                    make_snapshot(file_reali, docs_reali, piano_reale)
                    if file_reali
                    else []
                )

            st.session_state.innova_real_preview_rows = piano_reale
            st.session_state.innova_real_snapshot = snapshot_reale
            st.session_state.innova_real_client_count = len(archivio_reale)
            st.session_state.innova_real_file_count = len(file_reali)
            st.session_state.innova_real_last_execution = None
        except ArchivioReadOnlyError as exc:
            st.error(str(exc))
        except Exception:
            st.session_state.innova_real_preview_rows = None
            st.session_state.innova_real_snapshot = None
            st.session_state.innova_real_client_count = None
            st.session_state.innova_real_file_count = None
            st.error(
                "Errore inatteso durante l'anteprima REALE. "
                "Nessun file è stato modificato."
            )

    piano_reale = st.session_state.innova_real_preview_rows
    snapshot_reale = st.session_state.innova_real_snapshot

    if piano_reale is not None:
        st.success(
            f"Anteprima REALE completata: "
            f"{st.session_state.innova_real_client_count or 0} clienti rilevati · "
            f"{st.session_state.innova_real_file_count or 0} PDF in ingresso. "
            "Nessun file modificato."
        )

        if piano_reale:
            st.dataframe(
                _piano_visibile(piano_reale),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Nessun PDF presente nella cartella REALE di ingresso.")

        anomalie_reali = [
            row for row in piano_reale
            if row.get("Esito") == "ANOMALIA"
        ]
        if anomalie_reali:
            st.warning(
                f"Anteprima REALE: {len(anomalie_reali)} documenti richiedono controllo. "
                "I gruppi corretti restano separati dalle anomalie."
            )
        elif piano_reale:
            st.success("Anteprima REALE senza anomalie.")

        gruppi_reali = _gruppi_reali_eseguibili(piano_reale)

        if not runtime_reale.writes_enabled:
            if gruppi_reali:
                st.info(
                    f"Gruppi V4 eseguibili rilevati: {len(gruppi_reali)}. "
                    "Le scritture sono ancora disabilitate dai Secrets."
                )
        elif gruppi_reali:
            st.divider()
            st.subheader("Esecuzione REALE supervisionata · UN SOLO GRUPPO")
            st.error(
                "ATTENZIONE: il comando seguente modifica davvero l'archivio REALE. "
                "Al primo utilizzo verrà creata anche la cartella tecnica _BOT_CONTROL "
                "sotto la radice dell'archivio. Il writer rivalida l'intera cartella di "
                "ingresso, il piano V4, hash/metadati, destinazioni e collisioni prima "
                "di scrivere."
            )

            options = ["— seleziona un gruppo —"] + [
                item["display"] for item in gruppi_reali
            ]
            scelta = st.selectbox(
                "Gruppo da eseguire",
                options,
                key="innova_real_group_choice",
            )

            if scelta != options[0]:
                selected_index = options.index(scelta) - 1
                selected_group = gruppi_reali[selected_index]

                st.caption(
                    "Verranno toccati esclusivamente i documenti mostrati qui sotto."
                )
                st.dataframe(
                    _piano_visibile(selected_group["rows"]),
                    use_container_width=True,
                    hide_index=True,
                )

                conferma_reale = st.checkbox(
                    "Confermo di voler eseguire SOLO il gruppo selezionato nell'archivio REALE",
                    key="innova_real_confirm_checkbox",
                )
                frase_reale = st.text_input(
                    'Per abilitare il pulsante scrivi esattamente: ESEGUI REALE',
                    key="innova_real_confirm_text",
                )
                enabled_real = (
                    conferma_reale
                    and frase_reale.strip() == "ESEGUI REALE"
                )

                if st.button(
                    "ESEGUI GRUPPO NELL'ARCHIVIO REALE",
                    type="primary",
                    disabled=not enabled_real,
                    key="innova_real_execute",
                ):
                    try:
                        with st.spinner(
                            "Rivalidazione completa e scrittura del solo gruppo selezionato…"
                        ):
                            servizio = _servizio_drive()
                            risultati_reali = execute_real_group(
                                servizio,
                                runtime_reale,
                                snapshot_reale,
                                selected_group["file_ids"],
                                _alias_clienti(),
                            )

                        st.session_state.innova_real_last_execution = risultati_reali
                        st.session_state.innova_real_preview_rows = None
                        st.session_state.innova_real_snapshot = None
                        st.session_state.innova_real_client_count = None
                        st.session_state.innova_real_file_count = None

                        st.success(
                            f"Esecuzione REALE completata: "
                            f"{len(risultati_reali)} documenti gestiti."
                        )
                        st.dataframe(
                            risultati_reali,
                            use_container_width=True,
                            hide_index=True,
                        )
                    except EsecuzioneRealeBloccata as exc:
                        st.error(str(exc))
                    except Exception:
                        st.error(
                            "Errore inatteso durante l'esecuzione REALE. "
                            "Controllare manualmente l'archivio prima di riprovare."
                        )

if st.session_state.innova_real_last_execution:
    st.subheader("Ultima esecuzione REALE")
    st.dataframe(
        st.session_state.innova_real_last_execution,
        use_container_width=True,
        hide_index=True,
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
