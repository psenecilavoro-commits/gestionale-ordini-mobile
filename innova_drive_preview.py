"""Prima fase del bot Innova: lettura PDF dalla sola cartella di collaudo.

Questo modulo NON realizza ancora il piano di archiviazione della V4 e non
contiene alcuna operazione di scrittura su Google Drive. Il servizio Drive
deve essere costruito dal chiamante con credenziali OAuth custodite nei
Secrets di Streamlit, non nel repository.
"""

from __future__ import annotations

from io import BytesIO

import pdfplumber
from googleapiclient.http import MediaIoBaseDownload


TEST_ROOT_ID = "1SCWDJ2WqTGVAH3EbOfmHRtaCFupL3z1C"
TEST_INBOX_ID = "1H7v7tYALCD9mojlnTYNJPr_i54ieeyzZ"
MAX_PDFS = 50
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_PAGES = 3


class AnteprimaNonDisponibile(RuntimeError):
    """Errore controllato nella sola lettura dei documenti di collaudo."""


def _verifica_cartella_test(drive):
    """Impedisce di usare per errore una cartella di produzione."""
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
                riga["Testo leggibile"] = "No: OCR V4 ancora da integrare"
        except Exception:
            # Non mostrare messaggi provider che potrebbero contenere dati sensibili.
            riga["Esito"] = "Errore lettura PDF: verificare autorizzazione/formato"
        righe.append(riga)
    return righe
