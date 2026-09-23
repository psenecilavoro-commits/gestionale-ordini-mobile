"""Adattamento prudente del parser V4 per anteprima cloud.

Nessuna operazione di scrittura su Drive. Implementa solo le regole necessarie
al lotto di collaudo Pastificio Mozzo mantenendo le stesse verifiche chiave
della V4: classificazione, cliente, data, numeri e coppia approvata via SHA-256.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
import pymupdf as fitz

MOZZO_APPROVED_PAIR = (
    "d895978211cacbaaa314febf3e031da939e217dd0a84d32ec8d0b5199ff0ed6d",
    "4cd310db6336d15e35ccc598259f8f9126a0d699c0b5b3332fe4336352d4ef41",
)
TEST_CLIENT_NAME = "PASTIFICIO MOZZO SRL"
TEST_DESTINATION = "TEST BOT CLOUD / PASTIFICIO MOZZO SRL / ORDINI / 2026"


@dataclass
class CloudDoc:
    file_id: str
    original_name: str
    content: bytes
    text: str = ""
    kind: str = "incerto"
    cliente: str = ""
    date: datetime | None = None
    numero: str = ""
    numero_conferma: str = ""
    err: str = ""
    newname: str = ""


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_company(s: str) -> str:
    s = re.sub(r"\b(s\s*\.?\s*r\s*\.?\s*l\.?|s\s*\.?\s*p\s*\.?\s*a\.?|societa|a socio unico)\b", "", s or "", flags=re.I)
    return normalize(s)


def extract_text(content: bytes) -> str:
    """Stessa estrazione testuale primaria della V4 locale, sulle prime 3 pagine."""
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        return "\n".join(page.get_text(sort=True) for page in doc[:min(len(doc), 3)])
    finally:
        doc.close()


def identify_kind(text: str) -> str:
    t = normalize(text[:13000])
    if "outlook" in t[:120] or ("da " in t[:250] and "inviato" in t):
        first = re.split(r"\n\s*(?:Da\s*:|Inviato\s*:)", text[:5000], maxsplit=1, flags=re.I)[0]
        msg = normalize(first)
        if any(x in msg for x in (
            "attendo vs conferma", "attendo vostra conferma", "confermiamo ordine",
            "procedete con ordine", "procedi", "seguente ordine",
            "mettete giu per favore il seguente ordine", "inserire il seguente ordine",
        )):
            return "ordine"
        latest_lines = first.splitlines()
        body = "\n".join(latest_lines[3:])
        short_body = normalize(body)
        if re.search(r"(?:^|\s)(?:procedi|procedete|confermo|confermiamo)(?:\s|$)", short_body) and re.search(
            r"(?:attendo (?:tua|vostra|vs) conferma|allego offerta|prezzi nuovi|proposta)",
            normalize(text[len(first):]),
        ):
            return "ordine"
        return "incerto"
    if re.search(r"\b(?:ordine a fornitore|ordine fornitore|ordine specifico)\b", t[:1800]):
        return "ordine"
    if re.search(r"\bofferta\s+n\b|\bofferta\s+numero\b", t[:1500]):
        return "offerta"
    if "conferma ordine acquisto" in t[:1500] or "ordine fornitore" in t[:1500]:
        return "ordine"
    if re.search(r"conferma\s+(?:data(?:\s+doc)?\s+)?(?:\d{4,10}\s+)?d ordine", t[:1800]):
        if "innovagroup" in t or "innova group" in t:
            return "conferma"
    if re.search(r"\bordine\b", t[:1100]) and "innova group" in t:
        return "ordine"
    return "incerto"


def parse_date(s: str) -> datetime | None:
    s = s.replace("-", "/").replace(".", "/")
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def find_date(text: str, kind: str) -> datetime | None:
    header = text[:3000]
    if kind == "ordine" and "outlook" in normalize(header[:150]):
        m = re.search(r"\b(?:Data|Inviato)\s*:?[ \t]*(?:lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica|lun|mar|mer|gio|ven)?[ \t]*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", header, re.I)
        return parse_date(m.group(1)) if m else None
    for pattern in (
        r"(?:Data\s+(?:doc\.?|documento)?)[^\n]{0,100}?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    ):
        for m in re.finditer(pattern, header[:1700], re.I):
            d = parse_date(m.group(1))
            if d and 2020 <= d.year <= 2100:
                return d
    return None


def find_number(text: str, kind: str) -> tuple[str, str]:
    head = text[:6000]
    if kind == "ordine":
        return "", ""
    if kind == "conferma":
        customer = re.search(r"N\s*[°º.]?\s*Ord\.?\s*Cliente[^\n]*\n\s*(?:SENECI\s+PIETRO|PIETRO\s+SENECI)?\s*(\d{1,12})\b", head, re.I)
        if not customer:
            customer = re.search(r"(?:SENECI\s+PIETRO|PIETRO\s+SENECI)\s+(\d{1,8})\s+(?:BANCO|INTESA|BPER|CREDITO)", head, re.I)
        if not customer:
            customer = re.search(r"N\s*[°º.]?\s*Ord\.?\s*Cliente[^\n]*\n[^\n]{0,85}?\b(\d{1,8})\s+(?:INTESA|BPER|BANCO|CREDITO)", head, re.I)
        internal = re.search(r"CONFERMA\s+D['’]?ORDINE\s+N\s*[°º.]?\s*[:#-]?\s*(\d{1,12})", head, re.I)
        if not internal:
            internal = re.search(r"CONFERMA\s+(?:Data(?:\s+doc\.?)?\s+)?(\d{5,9})\s+D['’]?ORDINE", head, re.I)
        if not internal:
            internal = re.search(r"(\d{5,9})\s+CONFERMA\s+D['’]?ORDINE", head, re.I)
        return (customer.group(1) if customer else "", internal.group(1) if internal else "")
    return "", ""


def resolve_client(text: str, kind: str, source_name: str) -> str:
    header = text[:2600]
    if kind == "ordine" and "outlook" in normalize(header[:150]):
        subject = normalize(" ".join(header.splitlines()[:5]))
        sender = normalize(" ".join(header.splitlines()[:6])).replace(" ", "")
        if "pastificio mozzo" in subject or "pastificiomozzo" in sender or "mozzo" in normalize(source_name):
            return TEST_CLIENT_NAME
    t = normalize(text[:8000] + " " + source_name)
    if "pastificio mozzo" in t or re.search(r"(?<!\w)mozzo(?!\w)", t):
        return TEST_CLIENT_NAME
    return ""


def basename_client(name: str) -> str:
    return clean_company(name)


def filename(d: CloudDoc) -> str:
    base = f"{d.date:%m-%d} {('conferma ordine' if d.kind == 'conferma' else d.kind)} {basename_client(d.cliente)}"
    if d.kind != "offerta" and d.numero:
        base += " " + d.numero
    return base + ".pdf"


def inspect_cloud(file_info: dict, content: bytes) -> CloudDoc:
    d = CloudDoc(file_id=file_info["id"], original_name=file_info.get("name", ""), content=content)
    try:
        d.text = extract_text(content)
        d.kind = identify_kind(d.text)
        if d.kind == "incerto":
            d.err = "Tipologia non riconosciuta con sufficiente certezza"
            return d
        d.cliente = resolve_client(d.text, d.kind, d.original_name)
        if not d.cliente:
            d.err = "Cliente assente dall'archivio o riconoscimento ambiguo"
            return d
        d.date = find_date(d.text, d.kind)
        if not d.date:
            d.err = "Data del documento non riconosciuta"
            return d
        d.numero, d.numero_conferma = find_number(d.text, d.kind)
        if d.kind == "ordine" and not d.numero and re.search(r"\s\d{2,10}\.pdf$", d.original_name, re.I):
            d.err = "Numero nel nome originale non verificato nel PDF: rinomina bloccata"
            return d
        d.newname = filename(d)
    except Exception:
        d.err = "Impossibile leggere PDF"
    return d


def _sha256(d: CloudDoc) -> str:
    return hashlib.sha256(d.content).hexdigest()


def build_preview_plan(docs: list[CloudDoc]) -> list[dict]:
    if len(docs) != 2:
        return [
            {
                "File originale": d.original_name,
                "Tipo": d.kind,
                "Cliente": d.cliente,
                "Data": d.date.strftime("%d/%m/%Y") if d.date else "",
                "N. ordine": d.numero,
                "Nuovo nome": d.newname,
                "Destinazione": "",
                "Esito": "ANOMALIA",
                "Motivo": d.err or "Il lotto di collaudo atteso contiene esattamente 2 PDF",
            }
            for d in docs
        ]

    order = next((d for d in docs if d.kind == "ordine"), None)
    confirmation = next((d for d in docs if d.kind == "conferma"), None)
    approved = (
        order is not None and confirmation is not None
        and not order.err and not confirmation.err
        and clean_company(order.cliente) == "pastificio mozzo"
        and clean_company(confirmation.cliente) == "pastificio mozzo"
        and order.date is not None and confirmation.date is not None
        and order.date.strftime("%Y-%m-%d") == "2026-09-22"
        and confirmation.numero == ""
        and confirmation.numero_conferma == "203875"
        and _sha256(order) == MOZZO_APPROVED_PAIR[0]
        and _sha256(confirmation) == MOZZO_APPROVED_PAIR[1]
    )

    rows = []
    for d in docs:
        if d.err:
            esito, motivo, dest = "ANOMALIA", d.err, ""
        elif approved:
            # Come V4: la data della conferma nel nome segue quella dell'ordine.
            if d.kind == "conferma":
                d.date = order.date
                d.newname = filename(d)
            esito, motivo, dest = "ANTEPRIMA SPOSTA", "Coppia ordine-conferma V4 approvata via SHA-256", TEST_DESTINATION
        else:
            esito, motivo, dest = "ANOMALIA", "Coppia Mozzo non identica ai due PDF approvati dalla V4", ""
        rows.append({
            "File originale": d.original_name,
            "Tipo": d.kind,
            "Cliente": d.cliente,
            "Data": d.date.strftime("%d/%m/%Y") if d.date else "",
            "N. ordine": d.numero,
            "N. conferma Innova": d.numero_conferma,
            "Nuovo nome": d.newname,
            "Destinazione": dest,
            "Esito": esito,
            "Motivo": motivo,
        })
    return rows
