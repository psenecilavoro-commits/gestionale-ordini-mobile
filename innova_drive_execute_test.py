"""Esecuzione controllata del solo lotto TEST BOT CLOUD.

Questo modulo contiene scritture Google Drive, ma rifiuta di operare fuori
dalla catena hardcoded TEST BOT CLOUD -> PASTIFICIO MOZZO SRL -> ORDINI.
Non contiene ID dell'archivio reale.
"""

from __future__ import annotations

import hashlib

from innova_drive_preview import TEST_ROOT_ID, TEST_INBOX_ID, carica_pdf_test
from innova_v4_cloud_preview import inspect_cloud, build_preview_plan

TEST_CLIENT_ID = "1ilkvWwNvaf0GX1lAd2qQjZ7xUbznfZ1i"
TEST_ORDERS_ID = "1NJyysFwXmX3GrhPBkd3xUQA11WrAwSQ_"
EXPECTED_ROOT_NAME = "TEST BOT CLOUD"
EXPECTED_CLIENT_NAME = "PASTIFICIO MOZZO SRL"
EXPECTED_ORDERS_NAME = "ORDINI"
YEAR_NAME = "2026"
FOLDER_MIME = "application/vnd.google-apps.folder"


class EsecuzioneTestBloccata(RuntimeError):
    pass


def _get_meta(drive, file_id, fields="id,name,mimeType,parents,size,md5Checksum,modifiedTime"):
    return drive.files().get(
        fileId=file_id,
        fields=fields,
        supportsAllDrives=True,
    ).execute()


def _verify_folder(drive, folder_id, expected_name, expected_parent=None):
    meta = _get_meta(drive, folder_id, fields="id,name,mimeType,parents")
    if meta.get("id") != folder_id or meta.get("mimeType") != FOLDER_MIME:
        raise EsecuzioneTestBloccata("Cartella TEST non valida.")
    if meta.get("name") != expected_name:
        raise EsecuzioneTestBloccata("Nome cartella TEST inatteso.")
    if expected_parent is not None and expected_parent not in meta.get("parents", []):
        raise EsecuzioneTestBloccata("Gerarchia cartelle TEST inattesa.")
    return meta


def verify_test_chain(drive):
    _verify_folder(drive, TEST_ROOT_ID, EXPECTED_ROOT_NAME)
    _verify_folder(drive, TEST_INBOX_ID, "01 ORDINI SENZA CO", TEST_ROOT_ID)
    _verify_folder(drive, TEST_CLIENT_ID, EXPECTED_CLIENT_NAME, TEST_ROOT_ID)
    _verify_folder(drive, TEST_ORDERS_ID, EXPECTED_ORDERS_NAME, TEST_CLIENT_ID)


def make_snapshot(file_memoria, docs, piano):
    doc_by_id = {d.file_id: d for d in docs}
    row_by_name = {r["File originale"]: r for r in piano}
    snapshot = []
    for info, content in file_memoria:
        d = doc_by_id.get(info["id"])
        row = row_by_name.get(info.get("name", ""))
        if d is None or row is None:
            raise EsecuzioneTestBloccata("Anteprima incoerente: snapshot non creato.")
        snapshot.append({
            "id": info["id"],
            "name": info.get("name", ""),
            "size": str(info.get("size") or ""),
            "md5Checksum": info.get("md5Checksum") or "",
            "modifiedTime": info.get("modifiedTime") or "",
            "sha256": hashlib.sha256(content).hexdigest(),
            "kind": d.kind,
            "newname": row.get("Nuovo nome", ""),
            "destination": row.get("Destinazione", ""),
            "preview_result": row.get("Esito", ""),
        })
    return sorted(snapshot, key=lambda x: x["id"])


def _find_year_folder(drive):
    resp = drive.files().list(
        q=(
            f"'{TEST_ORDERS_ID}' in parents and "
            f"name = '{YEAR_NAME}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        ),
        fields="files(id,name,mimeType,parents)",
        pageSize=10,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    found = resp.get("files", [])
    if len(found) > 1:
        raise EsecuzioneTestBloccata("Più cartelle anno 2026 nel TEST: esecuzione bloccata.")
    return found[0] if found else None


def _create_year_folder(drive):
    created = drive.files().create(
        body={
            "name": YEAR_NAME,
            "mimeType": FOLDER_MIME,
            "parents": [TEST_ORDERS_ID],
        },
        fields="id,name,mimeType,parents",
        supportsAllDrives=True,
    ).execute()
    if created.get("name") != YEAR_NAME or TEST_ORDERS_ID not in created.get("parents", []):
        raise EsecuzioneTestBloccata("Creazione cartella anno TEST non verificata.")
    return created


def _destination_names(drive, year_id):
    resp = drive.files().list(
        q=f"'{year_id}' in parents and trashed = false",
        fields="files(id,name,parents)",
        pageSize=1000,
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    return {item.get("name", "").casefold(): item.get("id") for item in resp.get("files", [])}


def _revalidate_snapshot(current_files, snapshot):
    by_id = {info["id"]: (info, content) for info, content in current_files}
    if set(by_id) != {s["id"] for s in snapshot}:
        raise EsecuzioneTestBloccata("Il contenuto della cartella di ingresso è cambiato dall'anteprima.")

    for s in snapshot:
        info, content = by_id[s["id"]]
        checks = (
            info.get("name", "") == s["name"],
            str(info.get("size") or "") == s["size"],
            (info.get("md5Checksum") or "") == s["md5Checksum"],
            (info.get("modifiedTime") or "") == s["modifiedTime"],
            TEST_INBOX_ID in info.get("parents", []),
            hashlib.sha256(content).hexdigest() == s["sha256"],
        )
        if not all(checks):
            raise EsecuzioneTestBloccata(
                f"Il file {s['name']} è cambiato dall'anteprima: esecuzione annullata."
            )


def execute_test_pair(drive, snapshot):
    """Rivalida e sposta la coppia nel solo archivio TEST, con rollback best-effort."""
    if len(snapshot) != 2 or any(s.get("preview_result") != "ANTEPRIMA SPOSTA" for s in snapshot):
        raise EsecuzioneTestBloccata("Anteprima non approvata: esecuzione bloccata.")

    verify_test_chain(drive)

    current_files = carica_pdf_test(drive)
    _revalidate_snapshot(current_files, snapshot)

    docs = [inspect_cloud(info, content) for info, content in current_files]
    piano = build_preview_plan(docs)
    if len(piano) != 2 or any(r.get("Esito") != "ANTEPRIMA SPOSTA" for r in piano):
        raise EsecuzioneTestBloccata("La rivalidazione V4 non conferma più la coppia.")

    expected_names = {s["newname"] for s in snapshot}
    current_plan_names = {r.get("Nuovo nome", "") for r in piano}
    if expected_names != current_plan_names:
        raise EsecuzioneTestBloccata("I nomi previsti sono cambiati dalla prima anteprima.")

    year = _find_year_folder(drive)
    if year is None:
        year = _create_year_folder(drive)
    year_id = year["id"]

    existing = _destination_names(drive, year_id)
    collisions = [name for name in expected_names if name.casefold() in existing]
    if collisions:
        raise EsecuzioneTestBloccata(
            "Destinazione già occupata nel TEST: " + ", ".join(sorted(collisions))
        )

    original = {s["id"]: s for s in snapshot}
    moved = []
    results = []
    try:
        # Ordine prima, conferma dopo; in caso di errore si tenta il rollback.
        ordered = sorted(snapshot, key=lambda s: 0 if s.get("kind") == "ordine" else 1)
        for s in ordered:
            updated = drive.files().update(
                fileId=s["id"],
                addParents=year_id,
                removeParents=TEST_INBOX_ID,
                body={"name": s["newname"]},
                fields="id,name,parents,modifiedTime",
                supportsAllDrives=True,
            ).execute()
            if year_id not in updated.get("parents", []) or updated.get("name") != s["newname"]:
                raise EsecuzioneTestBloccata("Google Drive non ha confermato lo spostamento previsto.")
            moved.append(s["id"])
            results.append({
                "File originale": s["name"],
                "Nuovo nome": updated.get("name", ""),
                "Esito": "SPOSTATO NEL TEST",
            })
    except Exception as exc:
        rollback_failed = []
        for file_id in reversed(moved):
            s = original[file_id]
            try:
                restored = drive.files().update(
                    fileId=file_id,
                    addParents=TEST_INBOX_ID,
                    removeParents=year_id,
                    body={"name": s["name"]},
                    fields="id,name,parents",
                    supportsAllDrives=True,
                ).execute()
                if TEST_INBOX_ID not in restored.get("parents", []) or restored.get("name") != s["name"]:
                    rollback_failed.append(s["name"])
            except Exception:
                rollback_failed.append(s["name"])
        if rollback_failed:
            raise EsecuzioneTestBloccata(
                "Errore durante lo spostamento e rollback incompleto. Controllare manualmente: "
                + ", ".join(rollback_failed)
            ) from exc
        raise EsecuzioneTestBloccata(
            "Spostamento non completato; i file già mossi sono stati ripristinati nel TEST."
        ) from exc

    return results
