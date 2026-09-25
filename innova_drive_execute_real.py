"""Writer supervisionato per l'archivio REALE Innova su Google Drive.

Nessun ID reale è hardcoded: la gerarchia arriva da DriveArchiveRuntime,
costruito esclusivamente dai Secrets Streamlit. Il writer opera su UN SOLO
gruppo atomico per volta (coppia ordine+conferma oppure singolo documento).
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from innova_drive_modes import assert_real_writes_explicitly_enabled
from innova_drive_readonly import (
    FOLDER_MIME,
    load_pdf_inbox,
    map_archive,
    verify_runtime,
)
from innova_v4_cloud_full import inspect_cloud, build_preview_plan

CONTROL_FOLDER_NAME = "_BOT_CONTROL"
LOCK_PREFIX = "LOCK_REAL_"
RECEIPT_PREFIX = "RECEIPT_REAL_"
LOCK_STALE_SECONDS = 15 * 60


class EsecuzioneRealeBloccata(RuntimeError):
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
    items = []
    token = None
    while True:
        resp = drive.files().list(
            q=query,
            fields="nextPageToken,files(id,name,mimeType,parents,size,md5Checksum,modifiedTime)",
            pageSize=1000,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        items.extend(resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def _parse_rfc3339(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _ensure_control_folder(drive, runtime):
    found = [
        item for item in _list_children(drive, runtime.root_id, folders_only=True)
        if item.get("name") == CONTROL_FOLDER_NAME
    ]
    if len(found) > 1:
        raise EsecuzioneRealeBloccata(
            "Più cartelle _BOT_CONTROL nell'archivio REALE."
        )
    if found:
        return found[0]

    created = drive.files().create(
        body={
            "name": CONTROL_FOLDER_NAME,
            "mimeType": FOLDER_MIME,
            "parents": [runtime.root_id],
        },
        fields="id,name,mimeType,parents",
        supportsAllDrives=True,
    ).execute()
    if (
        created.get("name") != CONTROL_FOLDER_NAME
        or created.get("mimeType") != FOLDER_MIME
        or runtime.root_id not in created.get("parents", [])
    ):
        raise EsecuzioneRealeBloccata(
            "Creazione cartella _BOT_CONTROL REALE non verificata."
        )
    return created


def _cleanup_stale_locks(drive, control_id):
    now = datetime.now(timezone.utc)
    for item in _list_children(drive, control_id):
        name = item.get("name", "")
        if not name.startswith(LOCK_PREFIX):
            continue
        modified = _parse_rfc3339(item.get("modifiedTime", ""))
        if modified is None:
            continue
        if (now - modified).total_seconds() > LOCK_STALE_SECONDS:
            try:
                drive.files().delete(
                    fileId=item["id"],
                    supportsAllDrives=True,
                ).execute()
            except Exception:
                pass


def _acquire_lock(drive, control_id):
    _cleanup_stale_locks(drive, control_id)
    token = uuid.uuid4().hex
    created = drive.files().create(
        body={
            "name": LOCK_PREFIX + token,
            "mimeType": "application/octet-stream",
            "parents": [control_id],
            "appProperties": {
                "token": token,
                "purpose": "innova_v4_real_lock",
            },
        },
        fields="id,name,parents,modifiedTime",
        supportsAllDrives=True,
    ).execute()
    if control_id not in created.get("parents", []):
        raise EsecuzioneRealeBloccata("Lock REALE non creato nella cartella prevista.")

    for delay in (0.8, 1.2):
        time.sleep(delay)
        locks = [
            item for item in _list_children(drive, control_id)
            if item.get("name", "").startswith(LOCK_PREFIX)
        ]
        if len(locks) != 1 or locks[0].get("id") != created.get("id"):
            try:
                drive.files().delete(
                    fileId=created["id"],
                    supportsAllDrives=True,
                ).execute()
            except Exception:
                pass
            raise EsecuzioneRealeBloccata(
                "Un'altra esecuzione REALE risulta attiva. Riprovare più tardi."
            )
    return created["id"]


def _release_lock(drive, lock_id):
    if not lock_id:
        return
    try:
        drive.files().delete(
            fileId=lock_id,
            supportsAllDrives=True,
        ).execute()
    except Exception:
        pass


def _canonical_row(row):
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


def _batch_id(snapshot, selected_ids):
    selected = set(selected_ids)
    h = hashlib.sha256()
    for snap in sorted(snapshot, key=lambda x: x["id"]):
        if snap["id"] not in selected:
            continue
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
        for item in _list_children(drive, control_id)
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
                "mode": "REAL",
            },
        },
        fields="id,name,parents",
        supportsAllDrives=True,
    ).execute()
    if (
        created.get("name") != _receipt_name(batch_id)
        or control_id not in created.get("parents", [])
    ):
        try:
            if created.get("id"):
                drive.files().delete(
                    fileId=created["id"],
                    supportsAllDrives=True,
                ).execute()
        except Exception:
            pass
        raise EsecuzioneRealeBloccata(
            "Ricevuta di idempotenza REALE non verificata."
        )


def _revalidate_full_snapshot(current_files, snapshot, inbox_id):
    current = {info["id"]: (info, content) for info, content in current_files}
    expected = {snap["id"] for snap in snapshot}
    if set(current) != expected:
        raise EsecuzioneRealeBloccata(
            "La cartella REALE di ingresso è cambiata dall'anteprima. "
            "Rifare l'anteprima prima di eseguire."
        )

    for snap in snapshot:
        info, content = current[snap["id"]]
        checks = (
            info.get("name", "") == snap["name"],
            str(info.get("size") or "") == snap["size"],
            (info.get("md5Checksum") or "") == snap["md5Checksum"],
            (info.get("modifiedTime") or "") == snap["modifiedTime"],
            inbox_id in info.get("parents", []),
            hashlib.sha256(content).hexdigest() == snap["sha256"],
        )
        if not all(checks):
            raise EsecuzioneRealeBloccata(
                f"Il file '{snap['name']}' è cambiato dall'anteprima."
            )


def _fresh_plan(drive, runtime, current_files, aliases):
    archive = map_archive(drive, runtime)
    clients = sorted(archive.keys())
    docs = [
        inspect_cloud(info, content, clients, aliases or {})
        for info, content in current_files
    ]
    inbox_path = f"{runtime.root_name} / 01 ORDINI SENZA CO"
    return build_preview_plan(docs, archive, inbox_path)


def _compare_full_plan(snapshot, fresh_plan):
    old = {snap["id"]: snap["plan"] for snap in snapshot}
    fresh = {}
    for row in fresh_plan:
        file_id = row.get("_file_id", "")
        if not file_id or file_id in fresh:
            raise EsecuzioneRealeBloccata(
                "Rivalidazione V4 REALE con file ambiguo."
            )
        fresh[file_id] = _canonical_row(row)

    if set(old) != set(fresh):
        raise EsecuzioneRealeBloccata(
            "Il piano REALE non contiene più gli stessi file dell'anteprima."
        )

    changed = [
        old[file_id]["File originale"]
        for file_id in old
        if old[file_id] != fresh[file_id]
    ]
    if changed:
        raise EsecuzioneRealeBloccata(
            "Il piano V4 REALE è cambiato dall'anteprima per: "
            + ", ".join(changed)
        )


def _validate_selected_group(fresh_plan, selected_ids):
    selected = set(selected_ids)
    if not selected:
        raise EsecuzioneRealeBloccata("Nessun gruppo REALE selezionato.")

    rows = [r for r in fresh_plan if r.get("_file_id") in selected]
    if len(rows) != len(selected):
        raise EsecuzioneRealeBloccata(
            "Il gruppo selezionato non coincide più con il piano corrente."
        )

    group_ids = {r.get("_group_id", "") for r in rows}
    if len(group_ids) != 1 or "" in group_ids:
        raise EsecuzioneRealeBloccata(
            "Il gruppo selezionato non è più atomico/univoco."
        )
    group_id = next(iter(group_ids))

    all_group_rows = [
        r for r in fresh_plan if r.get("_group_id") == group_id
    ]
    if {r.get("_file_id") for r in all_group_rows} != selected:
        raise EsecuzioneRealeBloccata(
            "Il gruppo V4 è cambiato dall'anteprima."
        )

    allowed = {"ANTEPRIMA SPOSTA", "ANTEPRIMA RINOMINA"}
    if any(r.get("Esito") not in allowed for r in rows):
        raise EsecuzioneRealeBloccata(
            "Il gruppo selezionato contiene anomalie o azioni non eseguibili."
        )

    if group_id.startswith("PAIR:"):
        if len(rows) != 2 or {r.get("Tipo") for r in rows} != {"ordine", "conferma"}:
            raise EsecuzioneRealeBloccata(
                "Coppia REALE incompleta: esecuzione bloccata."
            )
        if any("Coppia ordine-conferma" not in r.get("Motivo", "") for r in rows):
            raise EsecuzioneRealeBloccata(
                "La coppia non è più confermata dalla V4."
            )
    elif len(rows) != 1:
        raise EsecuzioneRealeBloccata(
            "Un gruppo singolo REALE contiene più documenti."
        )

    return rows


def _unique_folder_named(drive, parent_id, name):
    found = [
        item for item in _list_children(drive, parent_id, folders_only=True)
        if item.get("name") == name
    ]
    if len(found) != 1:
        raise EsecuzioneRealeBloccata(
            f"Cartella REALE '{name}' mancante o duplicata."
        )
    return found[0]


def _parse_year(date_text):
    try:
        return datetime.strptime(date_text, "%d/%m/%Y").year
    except Exception as exc:
        raise EsecuzioneRealeBloccata(
            f"Data piano REALE non valida: {date_text!r}."
        ) from exc


def _year_folder(drive, base_id, year):
    found = [
        item for item in _list_children(drive, base_id, folders_only=True)
        if item.get("name") == str(year)
    ]
    if len(found) > 1:
        raise EsecuzioneRealeBloccata(
            f"Più cartelle anno {year} nella destinazione REALE."
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
        raise EsecuzioneRealeBloccata(
            f"Creazione cartella anno {year} REALE non verificata."
        )
    return created


def _resolve_destination(drive, runtime, row):
    inbox_path = f"{runtime.root_name} / 01 ORDINI SENZA CO"
    if row.get("Esito") == "ANTEPRIMA RINOMINA":
        if row.get("Destinazione") != inbox_path:
            raise EsecuzioneRealeBloccata(
                "Rinomina REALE prevista fuori dalla cartella di ingresso."
            )
        return {
            "parent_id": runtime.inbox_id,
            "kind": "INBOX",
            "year": None,
            "base_id": None,
        }

    kind = row.get("Tipo")
    if kind in {"ordine", "conferma"}:
        base_name = "ORDINI"
    elif kind == "offerta":
        base_name = "OFFERTE"
    else:
        raise EsecuzioneRealeBloccata(
            f"Tipo documento REALE non eseguibile: {kind!r}."
        )

    client_name = row.get("Cliente", "")
    year = _parse_year(row.get("Data", ""))
    client = _unique_folder_named(drive, runtime.root_id, client_name)
    base = _unique_folder_named(drive, client["id"], base_name)
    expected_path = f"{runtime.root_name} / {client_name} / {base_name} / {year}"

    if row.get("Destinazione") != expected_path:
        raise EsecuzioneRealeBloccata(
            f"Destinazione REALE inattesa per '{row.get('File originale', '')}'."
        )

    year_folder = _year_folder(drive, base["id"], year)
    return {
        "parent_id": year_folder["id"] if year_folder else None,
        "kind": base_name,
        "year": year,
        "base_id": base["id"],
    }


def _children_by_name(drive, parent_id):
    result = defaultdict(list)
    for item in _list_children(drive, parent_id):
        result[item.get("name", "").casefold()].append(item)
    return result


def _preflight(drive, runtime, rows):
    resolved = {}
    planned = set()

    for row in rows:
        file_id = row["_file_id"]
        dest = _resolve_destination(drive, runtime, row)
        resolved[file_id] = dest

        target_name = row.get("Nuovo nome", "")
        if not target_name:
            raise EsecuzioneRealeBloccata(
                f"Nuovo nome mancante per '{row.get('File originale', '')}'."
            )

        logical_parent = (
            dest["parent_id"]
            if dest["parent_id"]
            else f"CREATE:{dest.get('base_id')}:{dest.get('year')}"
        )
        key = (str(logical_parent), target_name.casefold())
        if key in planned:
            raise EsecuzioneRealeBloccata(
                f"Collisione interna al gruppo: {target_name}."
            )
        planned.add(key)

        if dest["parent_id"]:
            children = _list_children(drive, dest["parent_id"])
            for item in children:
                if item.get("id") == file_id:
                    continue
                if item.get("name", "").casefold() == target_name.casefold():
                    raise EsecuzioneRealeBloccata(
                        f"Destinazione REALE già occupata: {target_name}."
                    )
    return resolved


def _source_md5_map(snapshot):
    return {snap["id"]: snap.get("md5Checksum", "") for snap in snapshot}


def _check_duplicate_hashes(drive, rows, resolved, snapshot):
    md5_by_id = _source_md5_map(snapshot)
    for row in rows:
        file_id = row["_file_id"]
        source_md5 = md5_by_id.get(file_id, "")
        dest = resolved[file_id]
        if not source_md5 or not dest.get("parent_id"):
            continue
        for item in _list_children(drive, dest["parent_id"]):
            if item.get("id") == file_id:
                continue
            if (item.get("md5Checksum") or "") == source_md5:
                raise EsecuzioneRealeBloccata(
                    "PDF identico già presente nella destinazione REALE: "
                    + item.get("name", "")
                )


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
                dest["parent_id"] = existing["id"]
                cache[key] = existing["id"]
                continue

            made = _create_year_folder(drive, dest["base_id"], dest["year"])
            dest["parent_id"] = made["id"]
            cache[key] = made["id"]
            created.append(made["id"])
        return created
    except Exception:
        _cleanup_empty_folders(drive, created)
        raise


def _cleanup_empty_folders(drive, folder_ids):
    failed = []
    for folder_id in reversed(folder_ids):
        try:
            if _list_children(drive, folder_id):
                failed.append(folder_id)
                continue
            drive.files().delete(
                fileId=folder_id,
                supportsAllDrives=True,
            ).execute()
        except Exception:
            failed.append(folder_id)
    return failed


def _check_target_free(drive, parent_id, target_name, source_id):
    for item in _list_children(drive, parent_id):
        if item.get("id") == source_id:
            continue
        if item.get("name", "").casefold() == target_name.casefold():
            raise EsecuzioneRealeBloccata(
                f"Collisione comparsa durante l'esecuzione: {target_name}."
            )


def _revalidate_source_meta(drive, runtime, snap):
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
        or runtime.inbox_id not in meta.get("parents", [])
    ):
        raise EsecuzioneRealeBloccata(
            f"Il file '{snap['name']}' è cambiato subito prima della scrittura."
        )


def execute_real_group(drive, runtime, snapshot, selected_ids, aliases=None):
    """Esegue un solo gruppo V4 supervisionato nell'archivio REALE."""
    try:
        assert_real_writes_explicitly_enabled(runtime)
    except Exception as exc:
        raise EsecuzioneRealeBloccata(str(exc)) from exc

    verify_runtime(drive, runtime)
    control = _ensure_control_folder(drive, runtime)
    lock_id = None

    try:
        lock_id = _acquire_lock(drive, control["id"])

        batch_id = _batch_id(snapshot, selected_ids)
        if _receipt_exists(drive, control["id"], batch_id):
            raise EsecuzioneRealeBloccata(
                "Questo identico gruppo REALE risulta già completato."
            )

        current_files = load_pdf_inbox(drive, runtime)
        _revalidate_full_snapshot(current_files, snapshot, runtime.inbox_id)

        fresh_plan = _fresh_plan(
            drive,
            runtime,
            current_files,
            aliases or {},
        )
        _compare_full_plan(snapshot, fresh_plan)
        selected_rows = _validate_selected_group(fresh_plan, selected_ids)

        resolved = _preflight(drive, runtime, selected_rows)
        _check_duplicate_hashes(
            drive,
            selected_rows,
            resolved,
            snapshot,
        )

        snapshots = {snap["id"]: snap for snap in snapshot}
        created_folders = []
        completed = []
        results = []

        try:
            created_folders = _ensure_year_folders(drive, resolved)

            # Dopo l'eventuale creazione anno, ricontrollo collisioni e hash.
            _check_duplicate_hashes(
                drive,
                selected_rows,
                resolved,
                snapshot,
            )
            for row in selected_rows:
                dest = resolved[row["_file_id"]]
                _check_target_free(
                    drive,
                    dest["parent_id"],
                    row["Nuovo nome"],
                    row["_file_id"],
                )

            ordered = sorted(
                selected_rows,
                key=lambda row: (
                    0 if row["Tipo"] == "ordine" else
                    1 if row["Tipo"] == "conferma" else 2,
                    row["File originale"],
                ),
            )

            for row in ordered:
                file_id = row["_file_id"]
                snap = snapshots[file_id]
                dest = resolved[file_id]
                target_name = row["Nuovo nome"]

                _revalidate_source_meta(drive, runtime, snap)
                _check_target_free(
                    drive,
                    dest["parent_id"],
                    target_name,
                    file_id,
                )

                if dest["parent_id"] == runtime.inbox_id:
                    if snap["name"] == target_name:
                        results.append({
                            "File originale": snap["name"],
                            "Nuovo nome": target_name,
                            "Destinazione": row["Destinazione"],
                            "Esito": "GIÀ CORRETTO",
                        })
                        continue

                    updated = drive.files().update(
                        fileId=file_id,
                        body={"name": target_name},
                        fields="id,name,parents,modifiedTime",
                        supportsAllDrives=True,
                    ).execute()
                    if (
                        updated.get("name") != target_name
                        or runtime.inbox_id not in updated.get("parents", [])
                    ):
                        raise EsecuzioneRealeBloccata(
                            "Google Drive non ha confermato la rinomina REALE."
                        )
                    completed.append({
                        "id": file_id,
                        "moved": False,
                        "target_parent": runtime.inbox_id,
                    })
                    results.append({
                        "File originale": snap["name"],
                        "Nuovo nome": target_name,
                        "Destinazione": row["Destinazione"],
                        "Esito": "RINOMINATO",
                    })
                else:
                    updated = drive.files().update(
                        fileId=file_id,
                        addParents=dest["parent_id"],
                        removeParents=runtime.inbox_id,
                        body={"name": target_name},
                        fields="id,name,parents,modifiedTime",
                        supportsAllDrives=True,
                    ).execute()
                    if (
                        updated.get("name") != target_name
                        or dest["parent_id"] not in updated.get("parents", [])
                        or runtime.inbox_id in updated.get("parents", [])
                    ):
                        raise EsecuzioneRealeBloccata(
                            "Google Drive non ha confermato lo spostamento REALE."
                        )
                    completed.append({
                        "id": file_id,
                        "moved": True,
                        "target_parent": dest["parent_id"],
                    })
                    results.append({
                        "File originale": snap["name"],
                        "Nuovo nome": target_name,
                        "Destinazione": row["Destinazione"],
                        "Esito": "SPOSTATO",
                    })

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
                            addParents=runtime.inbox_id,
                            removeParents=item["target_parent"],
                            body={"name": snap["name"]},
                            fields="id,name,parents",
                            supportsAllDrives=True,
                        ).execute()
                    else:
                        restored = drive.files().update(
                            fileId=item["id"],
                            body={"name": snap["name"]},
                            fields="id,name,parents",
                            supportsAllDrives=True,
                        ).execute()

                    if (
                        restored.get("name") != snap["name"]
                        or runtime.inbox_id not in restored.get("parents", [])
                    ):
                        rollback_failed.append(snap["name"])
                except Exception:
                    rollback_failed.append(snap["name"])

            folder_cleanup_failed = _cleanup_empty_folders(
                drive,
                created_folders,
            )
            if rollback_failed or folder_cleanup_failed:
                details = []
                if rollback_failed:
                    details.append(
                        "file da controllare: " + ", ".join(rollback_failed)
                    )
                if folder_cleanup_failed:
                    details.append(
                        "cartelle anno da controllare: "
                        + ", ".join(folder_cleanup_failed)
                    )
                raise EsecuzioneRealeBloccata(
                    "Errore durante il gruppo REALE e rollback incompleto; "
                    + "; ".join(details)
                ) from exc

            if isinstance(exc, EsecuzioneRealeBloccata):
                raise
            raise EsecuzioneRealeBloccata(
                "Gruppo REALE non completato; le modifiche già eseguite "
                "sono state ripristinate."
            ) from exc

        return results
    finally:
        _release_lock(drive, lock_id)



def _all_executable_groups(fresh_plan):
    """Restituisce tutti e soli i gruppi V4 eseguibili.

    Le anomalie restano escluse. Se una riga apparentemente eseguibile appartiene
    a un gruppo incoerente, blocchiamo l'intero batch prima di qualsiasi write.
    """
    allowed = {"ANTEPRIMA SPOSTA", "ANTEPRIMA RINOMINA"}
    grouped = defaultdict(list)
    for row in fresh_plan:
        gid = row.get("_group_id", "")
        if gid:
            grouped[gid].append(row)

    selected_rows = []
    selected_ids = []
    for gid, rows in grouped.items():
        if any(row.get("Esito") not in allowed for row in rows):
            continue
        ids = [row.get("_file_id") for row in rows]
        if not all(ids):
            raise EsecuzioneRealeBloccata(
                "Piano V4 con gruppo eseguibile privo di identificazione file."
            )
        validated = _validate_selected_group(fresh_plan, ids)
        selected_rows.extend(validated)
        selected_ids.extend(ids)

    if not selected_rows:
        raise EsecuzioneRealeBloccata(
            "Nessun gruppo conforme alle regole è disponibile per Archivia tutti."
        )

    return selected_rows, selected_ids


def execute_real_all(drive, runtime, snapshot, aliases=None):
    """Archivia in un solo lotto tutti i gruppi V4 attualmente eseguibili.

    Le righe in ANOMALIA o comunque non eseguibili vengono ignorate. L'intero
    lotto conforme viene rivalidato e preflightato prima di spostare/rinominare
    qualsiasi PDF. Se un controllo fallisce, nessun PDF del lotto viene toccato.
    """
    try:
        assert_real_writes_explicitly_enabled(runtime)
    except Exception as exc:
        raise EsecuzioneRealeBloccata(str(exc)) from exc

    verify_runtime(drive, runtime)
    control = _ensure_control_folder(drive, runtime)
    lock_id = None

    try:
        lock_id = _acquire_lock(drive, control["id"])

        current_files = load_pdf_inbox(drive, runtime)
        _revalidate_full_snapshot(current_files, snapshot, runtime.inbox_id)

        fresh_plan = _fresh_plan(
            drive,
            runtime,
            current_files,
            aliases or {},
        )
        _compare_full_plan(snapshot, fresh_plan)

        selected_rows, selected_ids = _all_executable_groups(fresh_plan)

        batch_id = _batch_id(snapshot, selected_ids)
        if _receipt_exists(drive, control["id"], batch_id):
            raise EsecuzioneRealeBloccata(
                "Questo identico lotto ARCHIVIA TUTTI risulta già completato."
            )

        # Preflight dell'intero lotto prima di muovere/rinominare PDF.
        resolved = _preflight(drive, runtime, selected_rows)
        _check_duplicate_hashes(
            drive,
            selected_rows,
            resolved,
            snapshot,
        )

        snapshots = {snap["id"]: snap for snap in snapshot}
        created_folders = []
        completed = []
        results = []

        try:
            # Le sole write che possono precedere i PDF sono eventuali cartelle anno
            # mancanti; se un controllo successivo fallisce vengono rimosse se vuote.
            created_folders = _ensure_year_folders(drive, resolved)

            # Ultimo preflight globale dopo la risoluzione/creazione delle cartelle.
            _check_duplicate_hashes(
                drive,
                selected_rows,
                resolved,
                snapshot,
            )
            for row in selected_rows:
                dest = resolved[row["_file_id"]]
                _check_target_free(
                    drive,
                    dest["parent_id"],
                    row["Nuovo nome"],
                    row["_file_id"],
                )

            ordered = sorted(
                selected_rows,
                key=lambda row: (
                    row.get("_group_id", ""),
                    0 if row["Tipo"] == "ordine" else
                    1 if row["Tipo"] == "conferma" else 2,
                    row["File originale"],
                ),
            )

            for row in ordered:
                file_id = row["_file_id"]
                snap = snapshots[file_id]
                dest = resolved[file_id]
                target_name = row["Nuovo nome"]

                # Race protection immediatamente prima della singola write.
                _revalidate_source_meta(drive, runtime, snap)
                _check_target_free(
                    drive,
                    dest["parent_id"],
                    target_name,
                    file_id,
                )

                if dest["parent_id"] == runtime.inbox_id:
                    if snap["name"] == target_name:
                        results.append({
                            "File originale": snap["name"],
                            "Nuovo nome": target_name,
                            "Destinazione": row["Destinazione"],
                            "Esito": "GIÀ CORRETTO",
                        })
                        continue

                    updated = drive.files().update(
                        fileId=file_id,
                        body={"name": target_name},
                        fields="id,name,parents,modifiedTime",
                        supportsAllDrives=True,
                    ).execute()
                    if (
                        updated.get("name") != target_name
                        or runtime.inbox_id not in updated.get("parents", [])
                    ):
                        raise EsecuzioneRealeBloccata(
                            "Google Drive non ha confermato una rinomina del lotto."
                        )
                    completed.append({
                        "id": file_id,
                        "moved": False,
                        "target_parent": runtime.inbox_id,
                    })
                    results.append({
                        "File originale": snap["name"],
                        "Nuovo nome": target_name,
                        "Destinazione": row["Destinazione"],
                        "Esito": "RINOMINATO",
                    })
                else:
                    updated = drive.files().update(
                        fileId=file_id,
                        addParents=dest["parent_id"],
                        removeParents=runtime.inbox_id,
                        body={"name": target_name},
                        fields="id,name,parents,modifiedTime",
                        supportsAllDrives=True,
                    ).execute()
                    if (
                        updated.get("name") != target_name
                        or dest["parent_id"] not in updated.get("parents", [])
                        or runtime.inbox_id in updated.get("parents", [])
                    ):
                        raise EsecuzioneRealeBloccata(
                            "Google Drive non ha confermato uno spostamento del lotto."
                        )
                    completed.append({
                        "id": file_id,
                        "moved": True,
                        "target_parent": dest["parent_id"],
                    })
                    results.append({
                        "File originale": snap["name"],
                        "Nuovo nome": target_name,
                        "Destinazione": row["Destinazione"],
                        "Esito": "SPOSTATO",
                    })

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
                            addParents=runtime.inbox_id,
                            removeParents=item["target_parent"],
                            body={"name": snap["name"]},
                            fields="id,name,parents",
                            supportsAllDrives=True,
                        ).execute()
                    else:
                        restored = drive.files().update(
                            fileId=item["id"],
                            body={"name": snap["name"]},
                            fields="id,name,parents",
                            supportsAllDrives=True,
                        ).execute()

                    if (
                        restored.get("name") != snap["name"]
                        or runtime.inbox_id not in restored.get("parents", [])
                    ):
                        rollback_failed.append(snap["name"])
                except Exception:
                    rollback_failed.append(snap["name"])

            folder_cleanup_failed = _cleanup_empty_folders(
                drive,
                created_folders,
            )
            if rollback_failed or folder_cleanup_failed:
                details = []
                if rollback_failed:
                    details.append(
                        "file da controllare: " + ", ".join(rollback_failed)
                    )
                if folder_cleanup_failed:
                    details.append(
                        "cartelle anno da controllare: "
                        + ", ".join(folder_cleanup_failed)
                    )
                raise EsecuzioneRealeBloccata(
                    "Errore durante ARCHIVIA TUTTI e rollback incompleto; "
                    + "; ".join(details)
                ) from exc

            if isinstance(exc, EsecuzioneRealeBloccata):
                raise
            raise EsecuzioneRealeBloccata(
                "ARCHIVIA TUTTI non completato; le modifiche già eseguite "
                "sono state ripristinate."
            ) from exc

        return results
    finally:
        _release_lock(drive, lock_id)
