"""Esecuzione generica e controllata della V4 nel solo TEST BOT CLOUD.

Le scritture sono consentite esclusivamente dentro la gerarchia TEST:
TEST BOT CLOUD -> cliente TEST -> ORDINI/OFFERTE -> anno
oppure come sola rinomina nella cartella TEST di ingresso.

Il modulo non contiene ID dell'archivio reale.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from innova_drive_preview import (
    TEST_ROOT_ID,
    TEST_INBOX_ID,
    carica_pdf_test,
    mappa_archivio_test,
)
from innova_v4_cloud_full import inspect_cloud, build_preview_plan

FOLDER_MIME = "application/vnd.google-apps.folder"
TEST_ROOT_NAME = "TEST BOT CLOUD"
TEST_INBOX_NAME = "01 ORDINI SENZA CO"
INBOX_PATH = f"{TEST_ROOT_NAME} / {TEST_INBOX_NAME}"
CONTROL_FOLDER_NAME = "_BOT_CONTROL"
LOCK_PREFIX = "LOCK_"
RECEIPT_PREFIX = "RECEIPT_"
LOCK_STALE_SECONDS = 15 * 60


class EsecuzioneTestBloccata(RuntimeError):
    pass


def _get_meta(drive, file_id, fields="id,name,mimeType,parents,size,md5Checksum,modifiedTime"):
    return drive.files().get(
        fileId=file_id,
        fields=fields,
        supportsAllDrives=True,
    ).execute()


def _list_children(drive, parent_id, folders_only=False):
    query = f"'{parent_id}' in parents and trashed = false"
    if folders_only:
        query += f" and mimeType = '{FOLDER_MIME}'"
    out = []
    token = None
    while True:
        resp = drive.files().list(
            q=query,
            fields="nextPageToken,files(id,name,mimeType,parents,size,md5Checksum,modifiedTime,createdTime)",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        out.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def _verify_test_root_and_inbox(drive):
    root = _get_meta(drive, TEST_ROOT_ID, fields="id,name,mimeType,parents")
    if (
        root.get("id") != TEST_ROOT_ID
        or root.get("name") != TEST_ROOT_NAME
        or root.get("mimeType") != FOLDER_MIME
    ):
        raise EsecuzioneTestBloccata("Radice TEST BOT CLOUD non valida.")

    inbox = _get_meta(drive, TEST_INBOX_ID, fields="id,name,mimeType,parents")
    if (
        inbox.get("id") != TEST_INBOX_ID
        or inbox.get("name") != TEST_INBOX_NAME
        or inbox.get("mimeType") != FOLDER_MIME
        or TEST_ROOT_ID not in inbox.get("parents", [])
    ):
        raise EsecuzioneTestBloccata("Cartella di ingresso TEST non valida.")


def _ensure_control_folder(drive):
    found = [
        item for item in _list_children(drive, TEST_ROOT_ID, folders_only=True)
        if item.get("name") == CONTROL_FOLDER_NAME
    ]
    if len(found) > 1:
        raise EsecuzioneTestBloccata(
            "Più cartelle di controllo BOT nel TEST: esecuzione bloccata."
        )
    if found:
        return found[0]

    created = drive.files().create(
        body={
            "name": CONTROL_FOLDER_NAME,
            "mimeType": FOLDER_MIME,
            "parents": [TEST_ROOT_ID],
        },
        fields="id,name,mimeType,parents",
        supportsAllDrives=True,
    ).execute()
    if (
        created.get("name") != CONTROL_FOLDER_NAME
        or created.get("mimeType") != FOLDER_MIME
        or TEST_ROOT_ID not in created.get("parents", [])
    ):
        raise EsecuzioneTestBloccata(
            "Creazione cartella di controllo BOT non verificata."
        )
    return created


def _parse_rfc3339(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _cleanup_stale_locks(drive, control_id):
    now = datetime.now(timezone.utc)
    for item in _list_children(drive, control_id, folders_only=False):
        name = item.get("name", "")
        if not name.startswith(LOCK_PREFIX):
            continue
        modified = _parse_rfc3339(item.get("modifiedTime", ""))
        if modified is None:
            continue
        age = (now - modified).total_seconds()
        if age > LOCK_STALE_SECONDS:
            try:
                drive.files().delete(
                    fileId=item["id"],
                    supportsAllDrives=True,
                ).execute()
            except Exception:
                pass


def _acquire_drive_lock(drive, control_id):
    _cleanup_stale_locks(drive, control_id)
    token = uuid.uuid4().hex
    lock_name = LOCK_PREFIX + token
    created = drive.files().create(
        body={
            "name": lock_name,
            "mimeType": "application/octet-stream",
            "parents": [control_id],
            "appProperties": {"token": token, "purpose": "innova_v4_test_lock"},
        },
        fields="id,name,parents,modifiedTime",
        supportsAllDrives=True,
    ).execute()

    if control_id not in created.get("parents", []):
        raise EsecuzioneTestBloccata("Lock TEST non creato nella cartella prevista.")

    # Due controlli separati riducono la finestra in cui due sessioni possono
    # acquisire quasi contemporaneamente il lock.
    for delay in (0.8, 1.2):
        time.sleep(delay)
        locks = [
            item for item in _list_children(drive, control_id, folders_only=False)
            if item.get("name", "").startswith(LOCK_PREFIX)
        ]
        own = [item for item in locks if item.get("id") == created.get("id")]
        if len(locks) != 1 or len(own) != 1:
            try:
                drive.files().delete(
                    fileId=created["id"],
                    supportsAllDrives=True,
                ).execute()
            except Exception:
                pass
            raise EsecuzioneTestBloccata(
                "Un'altra esecuzione del bot risulta attiva. Riprovare tra poco."
            )
    return created["id"]


def _release_drive_lock(drive, lock_id):
    if not lock_id:
        return
    try:
        drive.files().delete(
            fileId=lock_id,
            supportsAllDrives=True,
        ).execute()
    except Exception:
        pass


def _batch_id(snapshot):
    h = hashlib.sha256()
    for snap in sorted(snapshot, key=lambda x: x["id"]):
        h.update(snap["id"].encode("utf-8"))
        h.update(b"\0")
        h.update(snap["sha256"].encode("ascii"))
        h.update(b"\0")
        h.update(snap["name"].encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def _receipt_name(batch_id):
    return f"{RECEIPT_PREFIX}{batch_id}.ok"


def _receipt_exists(drive, control_id, batch_id):
    expected = _receipt_name(batch_id)
    return any(
        item.get("name") == expected
        for item in _list_children(drive, control_id, folders_only=False)
    )


def _create_receipt(drive, control_id, batch_id, count):
    created = drive.files().create(
        body={
            "name": _receipt_name(batch_id),
            "mimeType": "application/octet-stream",
            "parents": [control_id],
            "appProperties": {
                "batch_id": batch_id,
                "count": str(count),
                "status": "completed",
            },
        },
        fields="id,name,parents",
        supportsAllDrives=True,
    ).execute()
    if (
        created.get("name") != _receipt_name(batch_id)
        or control_id not in created.get("parents", [])
    ):
        raise EsecuzioneTestBloccata(
            "Ricevuta di idempotenza TEST non verificata."
        )


def _unique_folder_named(drive, parent_id, name):
    found = [
        item for item in _list_children(drive, parent_id, folders_only=True)
        if item.get("name") == name
    ]
    if len(found) != 1:
        raise EsecuzioneTestBloccata(
            f"Cartella TEST '{name}' mancante o duplicata: esecuzione bloccata."
        )
    return found[0]


def _year_folder(drive, base_id, year):
    found = [
        item for item in _list_children(drive, base_id, folders_only=True)
        if item.get("name") == str(year)
    ]
    if len(found) > 1:
        raise EsecuzioneTestBloccata(
            f"Più cartelle anno {year} nella destinazione TEST."
        )
    return found[0] if found else None


def _create_year_folder(drive, base_id, year):
    created = drive.files().create(
        body={
            "name": str(year),
            "mimeType": FOLDER_MIME,
            "parents": [base_id],
        },
        fields="id,name,mimeType,parents",
        supportsAllDrives=True,
    ).execute()
    if (
        created.get("name") != str(year)
        or created.get("mimeType") != FOLDER_MIME
        or base_id not in created.get("parents", [])
    ):
        raise EsecuzioneTestBloccata(
            f"Creazione cartella anno {year} nel TEST non verificata."
        )
    return created


def _parse_year(date_text):
    try:
        return datetime.strptime(date_text, "%d/%m/%Y").year
    except Exception as exc:
        raise EsecuzioneTestBloccata(
            f"Data piano non valida: {date_text!r}."
        ) from exc


def _canonical_plan_row(row):
    return {
        "_file_id": row.get("_file_id", ""),
        "File originale": row.get("File originale", ""),
        "Tipo": row.get("Tipo", ""),
        "Cliente": row.get("Cliente", ""),
        "Data": row.get("Data", ""),
        "N. ordine": row.get("N. ordine", ""),
        "N. conferma Innova": row.get("N. conferma Innova", ""),
        "Nuovo nome": row.get("Nuovo nome", ""),
        "Destinazione": row.get("Destinazione", ""),
        "Esito": row.get("Esito", ""),
        "Motivo": row.get("Motivo", ""),
    }


def make_snapshot(file_memoria, docs, piano):
    """Congela metadati, hash e piano generato in anteprima."""
    rows_by_id = {}
    for row in piano:
        file_id = row.get("_file_id", "")
        if not file_id or file_id in rows_by_id:
            raise EsecuzioneTestBloccata(
                "Piano V4 privo di identificazione univoca dei file."
            )
        rows_by_id[file_id] = _canonical_plan_row(row)

    docs_by_id = {d.file_id: d for d in docs}
    snapshot = []
    for info, content in file_memoria:
        file_id = info["id"]
        row = rows_by_id.get(file_id)
        doc = docs_by_id.get(file_id)
        if row is None or doc is None:
            raise EsecuzioneTestBloccata(
                "Anteprima incoerente: impossibile creare lo snapshot."
            )
        snapshot.append({
            "id": file_id,
            "name": info.get("name", ""),
            "parents": list(info.get("parents", [])),
            "size": str(info.get("size") or ""),
            "md5Checksum": info.get("md5Checksum") or "",
            "modifiedTime": info.get("modifiedTime") or "",
            "sha256": hashlib.sha256(content).hexdigest(),
            "plan": row,
        })
    return sorted(snapshot, key=lambda x: x["id"])


def _revalidate_source_set(current_files, snapshot):
    current = {info["id"]: (info, content) for info, content in current_files}
    expected_ids = {s["id"] for s in snapshot}
    if set(current) != expected_ids:
        raise EsecuzioneTestBloccata(
            "Il contenuto della cartella di ingresso è cambiato dall'anteprima."
        )

    for snap in snapshot:
        info, content = current[snap["id"]]
        checks = (
            info.get("name", "") == snap["name"],
            str(info.get("size") or "") == snap["size"],
            (info.get("md5Checksum") or "") == snap["md5Checksum"],
            (info.get("modifiedTime") or "") == snap["modifiedTime"],
            TEST_INBOX_ID in info.get("parents", []),
            hashlib.sha256(content).hexdigest() == snap["sha256"],
        )
        if not all(checks):
            raise EsecuzioneTestBloccata(
                f"Il file '{snap['name']}' è cambiato dall'anteprima."
            )


def _fresh_plan(drive, current_files, aliases):
    archivio = mappa_archivio_test(drive)
    client_names = sorted(archivio.keys())
    docs = [
        inspect_cloud(info, content, client_names, aliases or {})
        for info, content in current_files
    ]
    piano = build_preview_plan(docs, archivio, INBOX_PATH)
    return piano


def _compare_plans(snapshot, fresh_plan):
    old = {s["id"]: s["plan"] for s in snapshot}
    fresh = {}
    for row in fresh_plan:
        file_id = row.get("_file_id", "")
        if not file_id or file_id in fresh:
            raise EsecuzioneTestBloccata(
                "Rivalidazione V4 con identificazione file ambigua."
            )
        fresh[file_id] = _canonical_plan_row(row)

    if set(old) != set(fresh):
        raise EsecuzioneTestBloccata(
            "Il piano V4 non contiene più gli stessi file dell'anteprima."
        )

    changed = [
        old[file_id]["File originale"]
        for file_id in old
        if old[file_id] != fresh[file_id]
    ]
    if changed:
        raise EsecuzioneTestBloccata(
            "Il piano V4 è cambiato dall'anteprima per: " + ", ".join(changed)
        )


def _validate_actionable_plan(plan):
    if not plan:
        raise EsecuzioneTestBloccata("Nessun documento da eseguire.")

    allowed = {"ANTEPRIMA SPOSTA", "ANTEPRIMA RINOMINA"}
    blocked = [r for r in plan if r.get("Esito") not in allowed]
    if blocked:
        raise EsecuzioneTestBloccata(
            "La V4 ha bloccato almeno un documento: esecuzione generica annullata."
        )

    for row in plan:
        destination = row.get("Destinazione", "")
        if not destination.startswith(TEST_ROOT_NAME + " / "):
            raise EsecuzioneTestBloccata(
                "Piano con destinazione fuori TEST BOT CLOUD."
            )


def _resolve_destination(drive, row):
    action = row["Esito"]
    if action == "ANTEPRIMA RINOMINA":
        if row.get("Destinazione") != INBOX_PATH:
            raise EsecuzioneTestBloccata(
                "Rinomina prevista fuori dalla cartella di ingresso TEST."
            )
        return {
            "parent_id": TEST_INBOX_ID,
            "created_year": None,
            "kind": "INBOX",
            "year": None,
        }

    client_name = row.get("Cliente", "")
    kind = row.get("Tipo", "")
    if kind in {"ordine", "conferma"}:
        base_name = "ORDINI"
    elif kind == "offerta":
        base_name = "OFFERTE"
    else:
        raise EsecuzioneTestBloccata(
            f"Tipo documento non eseguibile: {kind!r}."
        )

    year = _parse_year(row.get("Data", ""))
    client = _unique_folder_named(drive, TEST_ROOT_ID, client_name)
    base = _unique_folder_named(drive, client["id"], base_name)

    expected_path = f"{TEST_ROOT_NAME} / {client_name} / {base_name} / {year}"
    if row.get("Destinazione") != expected_path:
        raise EsecuzioneTestBloccata(
            f"Destinazione V4 inattesa per '{row.get('File originale', '')}'."
        )

    year_folder = _year_folder(drive, base["id"], year)
    return {
        "parent_id": year_folder["id"] if year_folder else None,
        "base_id": base["id"],
        "client_id": client["id"],
        "created_year": None,
        "kind": base_name,
        "year": year,
    }


def _children_name_map(drive, parent_id):
    out = defaultdict(list)
    for item in _list_children(drive, parent_id, folders_only=False):
        out[item.get("name", "").casefold()].append(item)
    return out


def _preflight_targets(drive, plan):
    resolved = {}
    planned = set()

    for row in plan:
        file_id = row["_file_id"]
        dest = _resolve_destination(drive, row)
        resolved[file_id] = dest

        target_name = row.get("Nuovo nome", "")
        if not target_name:
            raise EsecuzioneTestBloccata(
                f"Nuovo nome mancante per '{row.get('File originale', '')}'."
            )

        logical_parent = (
            dest["parent_id"]
            if dest["parent_id"]
            else f"CREATE:{dest.get('base_id')}:{dest.get('year')}"
        )
        key = (str(logical_parent), target_name.casefold())
        if key in planned:
            raise EsecuzioneTestBloccata(
                f"Collisione interna al lotto sul nome '{target_name}'."
            )
        planned.add(key)

        if dest["parent_id"]:
            by_name = _children_name_map(drive, dest["parent_id"])
            collisions = [
                item for item in by_name.get(target_name.casefold(), [])
                if item.get("id") != file_id
            ]
            if collisions:
                raise EsecuzioneTestBloccata(
                    f"Destinazione già occupata nel TEST: {target_name}."
                )

    return resolved


def _ensure_year_folders(drive, resolved):
    created = []
    cache = {}
    try:
        for dest in resolved.values():
            if dest["kind"] == "INBOX":
                continue
            key = (dest["base_id"], dest["year"])
            if key in cache:
                dest["parent_id"] = cache[key]
                continue

            existing = _year_folder(drive, dest["base_id"], dest["year"])
            if existing:
                cache[key] = existing["id"]
                dest["parent_id"] = existing["id"]
                continue

            made = _create_year_folder(drive, dest["base_id"], dest["year"])
            cache[key] = made["id"]
            dest["parent_id"] = made["id"]
            dest["created_year"] = made["id"]
            created.append(made["id"])
        return created
    except Exception:
        _cleanup_empty_created_folders(drive, created)
        raise


def _revalidate_single_source(drive, snap):
    meta = _get_meta(
        drive,
        snap["id"],
        fields="id,name,mimeType,parents,size,md5Checksum,modifiedTime",
    )
    if (
        meta.get("name", "") != snap["name"]
        or str(meta.get("size") or "") != snap["size"]
        or (meta.get("md5Checksum") or "") != snap["md5Checksum"]
        or (meta.get("modifiedTime") or "") != snap["modifiedTime"]
        or TEST_INBOX_ID not in meta.get("parents", [])
    ):
        raise EsecuzioneTestBloccata(
            f"Il file '{snap['name']}' è cambiato subito prima della scrittura."
        )


def _check_target_still_free(drive, parent_id, target_name, source_id):
    by_name = _children_name_map(drive, parent_id)
    collisions = [
        item for item in by_name.get(target_name.casefold(), [])
        if item.get("id") != source_id
    ]
    if collisions:
        raise EsecuzioneTestBloccata(
            f"Collisione comparsa durante l'esecuzione: {target_name}."
        )


def _cleanup_empty_created_folders(drive, created_ids):
    failed = []
    for folder_id in reversed(created_ids):
        try:
            if _list_children(drive, folder_id, folders_only=False):
                failed.append(folder_id)
                continue
            drive.files().delete(
                fileId=folder_id,
                supportsAllDrives=True,
            ).execute()
        except Exception:
            failed.append(folder_id)
    return failed


def execute_test_plan(drive, snapshot, aliases=None):
    """Esegue l'intero piano V4 come lotto logico nel solo TEST BOT CLOUD."""
    _verify_test_root_and_inbox(drive)
    control = _ensure_control_folder(drive)
    lock_id = None

    try:
        lock_id = _acquire_drive_lock(drive, control["id"])

        batch_id = _batch_id(snapshot)
        if _receipt_exists(drive, control["id"], batch_id):
            raise EsecuzioneTestBloccata(
                "Questo identico lotto risulta già completato in precedenza."
            )

        current_files = carica_pdf_test(drive)
        _revalidate_source_set(current_files, snapshot)

        fresh_plan = _fresh_plan(drive, current_files, aliases or {})
        _compare_plans(snapshot, fresh_plan)
        _validate_actionable_plan(fresh_plan)

        resolved = _preflight_targets(drive, fresh_plan)

        snapshots = {s["id"]: s for s in snapshot}
        rows_by_id = {r["_file_id"]: r for r in fresh_plan}

        created_folders = []
        completed = []
        results = []
        try:
            created_folders = _ensure_year_folders(drive, resolved)

            for file_id, row in rows_by_id.items():
                dest = resolved[file_id]
                _check_target_still_free(
                    drive,
                    dest["parent_id"],
                    row["Nuovo nome"],
                    file_id,
                )

            ordered_ids = sorted(
                rows_by_id,
                key=lambda file_id: (
                    0 if rows_by_id[file_id]["Tipo"] == "ordine" else
                    1 if rows_by_id[file_id]["Tipo"] == "conferma" else 2,
                    rows_by_id[file_id]["Cliente"],
                    rows_by_id[file_id]["File originale"],
                ),
            )

            for file_id in ordered_ids:
                snap = snapshots[file_id]
                row = rows_by_id[file_id]
                dest = resolved[file_id]
                target_name = row["Nuovo nome"]

                _revalidate_single_source(drive, snap)
                _check_target_still_free(
                    drive,
                    dest["parent_id"],
                    target_name,
                    file_id,
                )

                if dest["parent_id"] == TEST_INBOX_ID and snap["name"] == target_name:
                    results.append({
                        "File originale": snap["name"],
                        "Nuovo nome": target_name,
                        "Destinazione": INBOX_PATH,
                        "Esito": "GIÀ CORRETTO NEL TEST",
                    })
                    continue

                if dest["parent_id"] == TEST_INBOX_ID:
                    updated = drive.files().update(
                        fileId=file_id,
                        body={"name": target_name},
                        fields="id,name,parents,modifiedTime",
                        supportsAllDrives=True,
                    ).execute()
                    if (
                        updated.get("name") != target_name
                        or TEST_INBOX_ID not in updated.get("parents", [])
                    ):
                        raise EsecuzioneTestBloccata(
                            "Google Drive non ha confermato la rinomina TEST."
                        )
                    completed.append({
                        "id": file_id,
                        "target_parent": TEST_INBOX_ID,
                        "moved": False,
                    })
                    results.append({
                        "File originale": snap["name"],
                        "Nuovo nome": target_name,
                        "Destinazione": INBOX_PATH,
                        "Esito": "RINOMINATO NEL TEST",
                    })
                else:
                    updated = drive.files().update(
                        fileId=file_id,
                        addParents=dest["parent_id"],
                        removeParents=TEST_INBOX_ID,
                        body={"name": target_name},
                        fields="id,name,parents,modifiedTime",
                        supportsAllDrives=True,
                    ).execute()
                    if (
                        updated.get("name") != target_name
                        or dest["parent_id"] not in updated.get("parents", [])
                        or TEST_INBOX_ID in updated.get("parents", [])
                    ):
                        raise EsecuzioneTestBloccata(
                            "Google Drive non ha confermato lo spostamento TEST."
                        )
                    completed.append({
                        "id": file_id,
                        "target_parent": dest["parent_id"],
                        "moved": True,
                    })
                    results.append({
                        "File originale": snap["name"],
                        "Nuovo nome": target_name,
                        "Destinazione": row["Destinazione"],
                        "Esito": "SPOSTATO NEL TEST",
                    })

            # La ricevuta fa parte del commit logico: se non può essere creata,
            # il lotto viene riportato indietro.
            _create_receipt(
                drive,
                control["id"],
                batch_id,
                len(results),
            )

        except Exception as exc:
            rollback_failed = []
            for item in reversed(completed):
                snap = snapshots[item["id"]]
                try:
                    if item["moved"]:
                        restored = drive.files().update(
                            fileId=item["id"],
                            addParents=TEST_INBOX_ID,
                            removeParents=item["target_parent"],
                            body={"name": snap["name"]},
                            fields="id,name,parents",
                            supportsAllDrives=True,
                        ).execute()
                        ok = (
                            restored.get("name") == snap["name"]
                            and TEST_INBOX_ID in restored.get("parents", [])
                        )
                    else:
                        restored = drive.files().update(
                            fileId=item["id"],
                            body={"name": snap["name"]},
                            fields="id,name,parents",
                            supportsAllDrives=True,
                        ).execute()
                        ok = (
                            restored.get("name") == snap["name"]
                            and TEST_INBOX_ID in restored.get("parents", [])
                        )
                    if not ok:
                        rollback_failed.append(snap["name"])
                except Exception:
                    rollback_failed.append(snap["name"])

            folder_cleanup_failed = _cleanup_empty_created_folders(
                drive, created_folders
            )
            if rollback_failed or folder_cleanup_failed:
                details = []
                if rollback_failed:
                    details.append(
                        "file da controllare: " + ", ".join(rollback_failed)
                    )
                if folder_cleanup_failed:
                    details.append(
                        "cartelle anno TEST da controllare: "
                        + ", ".join(folder_cleanup_failed)
                    )
                raise EsecuzioneTestBloccata(
                    "Errore durante il lotto TEST e rollback incompleto; "
                    + "; ".join(details)
                ) from exc

            if isinstance(exc, EsecuzioneTestBloccata):
                raise
            raise EsecuzioneTestBloccata(
                "Lotto TEST non completato; le modifiche già eseguite sono state ripristinate."
            ) from exc

        return results
    finally:
        _release_drive_lock(drive, lock_id)
