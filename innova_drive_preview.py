"""Prima fase del bot Innova: lettura PDF dalla sola cartella di collaudo.

Questo modulo NON realizza ancora il piano di archiviazione della V4 e non
contiene alcuna operazione di scrittura su Google Drive. Il servizio Drive
deve essere costruito dal chiamante con credenziali OAuth custodite nei
Secrets di Streamlit, non nel repository.
"""

from __future__ import annotations

from io import BytesIO
import re

import pdfplumber
from googleapiclient.http import MediaIoBaseDownload


TEST_ROOT_ID = "1SCWDJ2WqTGVAH3EbOfmHRtaCFupL3z1C"
TEST_INBOX_ID = "1H7v7tYALCD9mojlnTYNJPr_i54ieeyzZ"
MAX_PDFS = 50
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PAGES = 3


class AnteprimaNonDisponibile(RuntimeError):
    """Errore controllato nella sola lettura dei documenti di collaudo."""


def _verifica_root_test(drive):
    root = drive.files().get(
        fileId=TEST_ROOT_ID, fields="id,name,mimeType,parents", supportsAllDrives=True
    ).execute()
    if (
        root.get("id") != TEST_ROOT_ID
        or root.get("name") != "TEST BOT CLOUD"
        or root.get("mimeType") != "application/vnd.google-apps.folder"
    ):
        raise AnteprimaNonDisponibile("La cartella radice TEST BOT CLOUD non corrisponde a quella prevista.")
    return root


def _verifica_cartella_test(drive):
    """Impedisce di usare per errore una cartella di produzione."""
    _verifica_root_test(drive)
    source = drive.files().get(
        fileId=TEST_INBOX_ID, fields="id,name,mimeType,parents",
        supportsAllDrives=True,
    ).execute()
    if (
        source.get("id") != TEST_INBOX_ID
        or source.get("name") != "01 ORDINI SENZA CO"
        or source.get("mimeType") != "application/vnd.google-apps.folder"
        or TEST_ROOT_ID not in source.get("parents", [])
    ):
        raise AnteprimaNonDisponibile("La cartella di ingresso non appartiene al collaudo previsto.")


def elenca_pdf_test(drive):
    """Elenca soltanto i PDF direttamente nella cartella di ingresso TEST."""
    _verifica_cartella_test(drive)
    risultati = []
    page_token = None
    while True:
        risposta = drive.files().list(
            q=(f"'{TEST_INBOX_ID}' in parents and "
               "mimeType = 'application/pdf' and trashed = false"),
            fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,modifiedTime,parents)",
            pageSize=100,
            pageToken=page_token,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        for item in risposta.get("files", []):
            if TEST_INBOX_ID not in item.get("parents", []):
                raise AnteprimaNonDisponibile("Risposta Drive inattesa: file fuori dalla cartella di test.")
            risultati.append(item)
            if len(risultati) > MAX_PDFS:
                raise AnteprimaNonDisponibile(
                    f"La cartella contiene oltre {MAX_PDFS} PDF: ridurre il lotto di prova."
                )
        page_token = risposta.get("nextPageToken")
        if not page_token:
            break
    return sorted(risultati, key=lambda item: item.get("name", "").casefold())


def _leggi_bytes_pdf(drive, file_info):
    dimensione = int(file_info.get("size") or 0)
    if dimensione <= 0 or dimensione > MAX_PDF_BYTES:
        raise AnteprimaNonDisponibile("PDF vuoto o oltre il limite di 15 MB per il collaudo.")
    memoria = BytesIO()
    richiesta = drive.files().get_media(fileId=file_info["id"])
    downloader = MediaIoBaseDownload(memoria, richiesta, chunksize=1024 * 1024)
    completato = False
    while not completato:
        stato, completato = downloader.next_chunk()
        if stato is not None and stato.resumable_progress > MAX_PDF_BYTES:
            raise AnteprimaNonDisponibile("Download interrotto: limite di 15 MB superato.")
    if memoria.tell() > MAX_PDF_BYTES:
        raise AnteprimaNonDisponibile("PDF oltre il limite di 15 MB.")
    memoria.seek(0)
    return memoria



def _lista_figli(drive, parent_id, folders_only=False):
    query = f"'{parent_id}' in parents and trashed = false"
    if folders_only:
        query += " and mimeType = 'application/vnd.google-apps.folder'"
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


def mappa_archivio_test(drive):
    """Legge la struttura clienti/ORDINI/OFFERTE del solo TEST BOT CLOUD.

    Restituisce nomi e ID necessari all'anteprima V4. Nessuna scrittura.
    Cartelle ORDINI/OFFERTE duplicate o mancanti restano escluse: sarà la V4
    a segnalarle come anomalie invece di scegliere arbitrariamente.
    """
    _verifica_root_test(drive)
    clienti = {}
    for client in _lista_figli(drive, TEST_ROOT_ID, folders_only=True):
        if client.get("id") == TEST_INBOX_ID or client.get("name") == "01 ORDINI SENZA CO":
            continue
        nome = client.get("name", "")
        if not nome:
            continue
        entry = {"id": client["id"], "path": f"TEST BOT CLOUD / {nome}"}
        children = _lista_figli(drive, client["id"], folders_only=True)
        for kind in ("ORDINI", "OFFERTE"):
            found = [x for x in children if x.get("name", "").upper() == kind]
            if len(found) != 1:
                continue
            base = found[0]
            base_path = f"{entry['path']} / {kind}"
            years = {}
            for year in _lista_figli(drive, base["id"], folders_only=True):
                yname = year.get("name", "")
                if not re.fullmatch(r"20\d{2}", yname):
                    continue
                files = {}
                for item in _lista_figli(drive, year["id"], folders_only=False):
                    if item.get("mimeType") == "application/vnd.google-apps.folder":
                        continue
                    files[item.get("name", "")] = {
                        "id": item.get("id", ""),
                        "md5Checksum": item.get("md5Checksum") or "",
                        "size": item.get("size") or "",
                        "modifiedTime": item.get("modifiedTime") or "",
                    }
                years[yname] = {"id": year["id"], "files": files}
            entry[kind] = {"id": base["id"], "path": base_path, "years": years}
        clienti[nome] = entry
    return clienti


def carica_pdf_test(drive):
    """Scarica in memoria i soli PDF di collaudo, senza scrivere su Drive."""
    return [(file_info, _leggi_bytes_pdf(drive, file_info).getvalue()) for file_info in elenca_pdf_test(drive)]


def anteprima_test(drive):
    """Restituisce metadati e diagnostica testo; non modifica alcun file.

    NON assegna tipo documento, cliente, numero, destinazione o nuovo nome:
    questi risultati richiedono l'adattamento e i test delle regole V4.
    """
    righe = []
    for file_info in elenca_pdf_test(drive):
        riga = {
            "File": file_info.get("name", ""),
            "Dimensione (byte)": int(file_info.get("size") or 0),
            "Testo leggibile": "Da verificare",
            "Esito": "Sola lettura",
        }
        try:
            contenuto = _leggi_bytes_pdf(drive, file_info)
            with pdfplumber.open(contenuto) as pdf:
                testo = "\n".join(
                    pagina.extract_text() or "" for pagina in pdf.pages[:MAX_PAGES]
                )
            if len("".join(testo.split())) >= 75:
                riga["Testo leggibile"] = "Sì"
            else:
                riga["Testo leggibile"] = "No testo nativo: verrà tentato OCR V4"
        except Exception:
            # Non mostrare messaggi provider che potrebbero contenere dati sensibili.
            riga["Esito"] = "Errore lettura PDF: verificare autorizzazione/formato"
        righe.append(riga)
    return righe
