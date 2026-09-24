"""Lettura generica di un archivio Innova su Google Drive.

Questo modulo contiene esclusivamente letture Drive. È usato per la futura
modalità REALE con scritture disabilitate e può essere riutilizzato nel TEST.
"""

from __future__ import annotations

from io import BytesIO
import re

from googleapiclient.http import MediaIoBaseDownload

FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"
MAX_PDFS = 50
MAX_PDF_BYTES = 15 * 1024 * 1024


class ArchivioReadOnlyError(RuntimeError):
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
            fields="nextPageToken,files(id,name,mimeType,parents,size,md5Checksum,modifiedTime)",
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


def verify_runtime(drive, runtime, expected_inbox_name="01 ORDINI SENZA CO"):
    root = _get_meta(drive, runtime.root_id, fields="id,name,mimeType,parents")
    if (
        root.get("id") != runtime.root_id
        or root.get("mimeType") != FOLDER_MIME
        or root.get("name") != runtime.root_name
    ):
        raise ArchivioReadOnlyError(
            f"Radice {runtime.mode} diversa dalla configurazione prevista."
        )

    inbox = _get_meta(drive, runtime.inbox_id, fields="id,name,mimeType,parents")
    if (
        inbox.get("id") != runtime.inbox_id
        or inbox.get("mimeType") != FOLDER_MIME
        or inbox.get("name") != expected_inbox_name
        or runtime.root_id not in inbox.get("parents", [])
    ):
        raise ArchivioReadOnlyError(
            f"Cartella ingresso {runtime.mode} diversa dalla configurazione prevista."
        )
    return root, inbox


def list_pdf_inbox(drive, runtime):
    verify_runtime(drive, runtime)
    results = []
    token = None
    while True:
        resp = drive.files().list(
            q=(
                f"'{runtime.inbox_id}' in parents and "
                f"mimeType = '{PDF_MIME}' and trashed = false"
            ),
            fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,parents)",
            pageSize=100,
            pageToken=token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for item in resp.get("files", []):
            if runtime.inbox_id not in item.get("parents", []):
                raise ArchivioReadOnlyError(
                    "Risposta Drive inattesa: PDF fuori dalla cartella configurata."
                )
            results.append(item)
            if len(results) > MAX_PDFS:
                raise ArchivioReadOnlyError(
                    f"Oltre {MAX_PDFS} PDF nella cartella: usare un lotto più piccolo."
                )
        token = resp.get("nextPageToken")
        if not token:
            break
    return sorted(results, key=lambda x: x.get("name", "").casefold())


def _download_pdf_bytes(drive, info):
    size = int(info.get("size") or 0)
    if size <= 0 or size > MAX_PDF_BYTES:
        raise ArchivioReadOnlyError("PDF vuoto o oltre 15 MB.")
    memory = BytesIO()
    request = drive.files().get_media(fileId=info["id"])
    downloader = MediaIoBaseDownload(memory, request, chunksize=1024 * 1024)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status is not None and status.resumable_progress > MAX_PDF_BYTES:
            raise ArchivioReadOnlyError("Download interrotto: PDF oltre 15 MB.")
    if memory.tell() > MAX_PDF_BYTES:
        raise ArchivioReadOnlyError("PDF oltre 15 MB.")
    return memory.getvalue()


def load_pdf_inbox(drive, runtime):
    return [
        (info, _download_pdf_bytes(drive, info))
        for info in list_pdf_inbox(drive, runtime)
    ]


def map_archive(drive, runtime):
    """Mappa clienti e cartelle ORDINI/OFFERTE senza alcuna scrittura."""
    verify_runtime(drive, runtime)
    clients = {}
    for client in _list_children(drive, runtime.root_id, folders_only=True):
        name = client.get("name", "")
        if (
            client.get("id") == runtime.inbox_id
            or name == "01 ORDINI SENZA CO"
            or name == "_BOT_CONTROL"
        ):
            continue
        if not name:
            continue

        entry = {
            "id": client["id"],
            "path": f"{runtime.root_name} / {name}",
        }
        children = _list_children(drive, client["id"], folders_only=True)

        for kind in ("ORDINI", "OFFERTE"):
            found = [
                x for x in children
                if x.get("name", "").upper() == kind
            ]
            if len(found) != 1:
                continue

            base = found[0]
            base_path = f"{entry['path']} / {kind}"
            years = {}
            for year in _list_children(drive, base["id"], folders_only=True):
                year_name = year.get("name", "")
                if not re.fullmatch(r"20\d{2}", year_name):
                    continue
                files = {}
                for item in _list_children(drive, year["id"], folders_only=False):
                    if item.get("mimeType") == FOLDER_MIME:
                        continue
                    files[item.get("name", "")] = {
                        "id": item.get("id", ""),
                        "md5Checksum": item.get("md5Checksum") or "",
                        "size": item.get("size") or "",
                        "modifiedTime": item.get("modifiedTime") or "",
                    }
                years[year_name] = {
                    "id": year["id"],
                    "files": files,
                }

            entry[kind] = {
                "id": base["id"],
                "path": base_path,
                "years": years,
            }

        clients[name] = entry

    return clients
