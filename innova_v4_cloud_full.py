"""Porting cloud read-only della logica di classificazione V4.

Scopo: generare un piano di anteprima sui PDF presenti nel TEST BOT CLOUD,
senza scritture su Google Drive. Le regole di riconoscimento derivano dalla V4
locale; le operazioni filesystem sono sostituite da metadati Drive letti in
sola lettura.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from io import BytesIO

import pymupdf as fitz


@dataclass
class CloudDoc:
    file_id: str
    original_name: str
    content: bytes
    md5: str = ""
    kind: str = "incerto"
    cliente: str = ""
    date: datetime | None = None
    numero: str = ""
    numero_conferma: str = ""
    text: str = ""
    err: str = ""
    newname: str = ""


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def clean_company(s: str) -> str:
    s = re.sub(
        r"\b(s\s*\.?\s*r\s*\.?\s*l\.?|s\s*\.?\s*p\s*\.?\s*a\.?|societa|a socio unico)\b",
        "",
        s or "",
        flags=re.I,
    )
    return normalize(s)


def read_pdf_bytes(content: bytes, force_ocr: bool = False) -> str:
    doc = fitz.open(stream=content, filetype="pdf")
    try:
        text = "\n".join(page.get_text(sort=True) for page in doc[:min(len(doc), 3)])
        if not force_ocr and len(re.sub(r"\s", "", text)) >= 75:
            return text
        try:
            import pytesseract
            from PIL import Image
            parts = []
            for page in doc[:min(len(doc), 3)]:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                parts.append(pytesseract.image_to_string(image, lang="ita+eng"))
            return "\n".join(parts)
        except Exception as exc:
            raise RuntimeError("PDF scansito: OCR non disponibile nel collaudo cloud") from exc
    finally:
        doc.close()


def identify_kind(text: str) -> str:
    t = normalize(text[:13000])
    if "outlook" in t[:120] or ("da " in t[:250] and "inviato" in t):
        first = re.split(r"\n\s*(?:Da\s*:|Inviato\s*:)", text[:5000], maxsplit=1, flags=re.I)[0]
        msg = normalize(first)
        if any(x in msg for x in (
            "attendo vs conferma", "attendo vostra conferma", "confermiamo ordine",
            "procedete con ordine", "va bene ci siete", "seguente ordine",
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
        m = re.search(
            r"\b(?:Data|Inviato)\s*:?[ \t]*(?:lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica|lun|mar|mer|gio|ven)?[ \t]*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
            header,
            re.I,
        )
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
        m = re.search(r"N\s*[°ºo.]?\s*ordine\s+di\s+acquisto\s*(OA\s*[-/]\s*\d{2}\s*[-/]\s*\d{1,10})\b", head, re.I)
        if m:
            return str(int(re.split(r"[-/]", m.group(1))[-1].strip())), ""
        m = re.search(r"(?<!\d)(\d{1,3}\.\d{3})\s+(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+\d{1,3}\b", head[:450])
        if m and "ordine a fornitore" in normalize(head[:1800]):
            return str(int(m.group(1).replace(".", ""))), ""
        m = re.search(r"\b[O0]F\s*[/\-]\s*20\d{2}0*(\d{1,5})\b", head, re.I)
        if m and "ordine fornitore" in normalize(head[:2000]):
            return str(int(m.group(1))), ""
        m = re.search(r"(?:Ns\.?\s*)?Ordine\s+nr\.?\s*20\d{2}\s*[/\-]\s*(\d{1,10})\s+del\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", head, re.I)
        if m:
            return str(int(m.group(1))), ""
        m = re.search(r"\bNumero\s+(0{2,}\d{1,8})\s+Del\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", head[:2200], re.I)
        if m and "ordine fornitore" in normalize(head[:2200]):
            return str(int(m.group(1))), ""
        m = re.search(r"Data\s+doc\.?\s+Numero\s+doc\.?\s*\n[^\n]{0,180}?(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\s+(\d{1,10})", head, re.I)
        if m:
            return m.group(1), ""
        m = re.search(r"Numero\s+documento[^\n]*\n[^\n]*?\b(\d{1,10})\s+(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", head, re.I)
        if m:
            return m.group(1), ""
        m = re.search(r"CONFERMA\s+ORDINE\s+ACQUISTO\s+(\d{1,12})", head, re.I)
        if m:
            return m.group(1), ""
        for pattern in (
            r"(?:Numero\s+(?:documento|doc\.?|ordine)|N[°º.]?\s*(?:Ordine|Ord\.?))\s*[:#-]?\s*(\d{1,12})",
            r"(?:Numero\s+doc\.?)[^\n]*\n\s*Ordine\s+fornitore\s*\n\s*(\d{1,12})",
            r"(?:Numero\s+documento)[^\n]*\n\s*(\d{1,12})",
            r"(?:Numero\s+doc\.?)\s*\n\s*(?:Data\s+doc\.?)?\s*\n?\s*(\d{1,12})",
        ):
            m = re.search(pattern, head, re.I)
            if m:
                return m.group(1), ""
        return "", ""

    if kind == "conferma":
        # Le CO Innova mostrano il riferimento cliente nella riga dell'agente.
        # Esempi reali:
        #   SENECI PIETRO 00153 BANCA ...       -> 153
        #   SENECI PIETRO 2026/8466 UNICREDIT  -> 8466
        # Non considerare l'anno 2026 come numero d'ordine.
        customer_value = ""
        customer_slash = re.search(
            r"(?:SENECI\s+PIETRO|PIETRO\s+SENECI)\s+20\d{2}\s*[/\\-]\s*0*(\d{1,10})\b",
            head,
            re.I,
        )
        if customer_slash:
            customer_value = str(int(customer_slash.group(1)))
        else:
            customer = re.search(
                r"N\s*[°º.]?\s*Ord\.?\s*Cliente[^\n]*\n\s*(?:SENECI\s+PIETRO|PIETRO\s+SENECI)?\s*(\d{1,12})\b",
                head,
                re.I,
            )
            if not customer:
                customer = re.search(
                    r"(?:SENECI\s+PIETRO|PIETRO\s+SENECI)\s+(\d{1,8})\s+(?:BANCO|INTESA|BPER|CREDITO|UNICREDIT)",
                    head,
                    re.I,
                )
            if not customer:
                customer = re.search(
                    r"N\s*[°º.]?\s*Ord\.?\s*Cliente[^\n]*\n[^\n]{0,85}?\b(\d{1,8})\s+(?:INTESA|BPER|BANCO|CREDITO|UNICREDIT)",
                    head,
                    re.I,
                )
            if customer:
                raw = customer.group(1)
                # I numeri cliente nelle CO possono essere zero-padded (00153).
                customer_value = str(int(raw)) if raw.isdigit() else raw

        internal = re.search(r"CONFERMA\s+D['’]?ORDINE\s+N\s*[°º.]?\s*[:#-]?\s*(\d{1,12})", head, re.I)
        if not internal:
            internal = re.search(r"CONFERMA\s+(?:Data(?:\s+doc\.?)?\s+)?(\d{5,9})\s+D['’]?ORDINE", head, re.I)
        if not internal:
            internal = re.search(r"(\d{5,9})\s+CONFERMA\s+D['’]?ORDINE", head, re.I)
        return (customer_value, internal.group(1) if internal else "")
    return "", ""


def resolve_client(text: str, client_names: list[str], aliases: dict | None = None, kind: str = "", source_name: str = "") -> str:
    aliases = aliases or {}
    header = text[:2600]
    if kind == "ordine" and "outlook" in normalize(header[:150]):
        subject = normalize(" ".join(header.splitlines()[:5]))
        matched = [
            name for name in client_names if any(
                len(v) >= 5 and re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", subject)
                for v in [clean_company(name)] + [normalize(x) for x in aliases.get(name, [])]
            )
        ]
        if len(matched) == 1:
            return matched[0]
        sender = normalize(" ".join(header.splitlines()[:6])).replace(" ", "")
        domain_matches = [
            name for name in client_names
            if len(key := clean_company(name).replace(" ", "")) >= 8 and key in sender
        ]
        if len(domain_matches) == 1:
            return domain_matches[0]
        distinctive = [
            name for name in client_names if any(
                len(w) >= 8 and w not in {"caseificio", "industria", "forneria", "azienda"}
                and re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", subject)
                for w in clean_company(name).split()
            )
        ]
        if len(distinctive) == 1:
            return distinctive[0]
        stem = normalize(source_name)
        matched = [
            name for name in client_names
            if (tokens := [w for w in clean_company(name).split() if len(w) >= 6])
            and all(w in stem for w in tokens)
        ]
        if len(matched) == 1:
            return matched[0]

    t = normalize(text[:8000])
    candidates = []
    for name in client_names:
        variants = [clean_company(name)] + [normalize(v) for v in aliases.get(name, [])]
        if any(len(v) >= 5 and re.search(r"(?<!\w)" + re.escape(v) + r"(?!\w)", t) for v in variants):
            candidates.append(name)
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return ""

    words = t.split()
    fuzzy = []
    for name in client_names:
        target = clean_company(name)
        tokens = target.split()
        if len(tokens) < 2 or len(target) < 12:
            continue
        for size in (len(tokens), len(tokens) + 1):
            if any(
                SequenceMatcher(None, target, " ".join(words[i:i + size])).ratio() >= 0.91
                for i in range(max(0, len(words) - size + 1))
            ):
                fuzzy.append(name)
                break
    if len(fuzzy) == 1:
        return fuzzy[0]

    heading = normalize(header[:1400] + " " + source_name)
    unique = []
    for name in client_names:
        words_name = [w for w in clean_company(name).split() if len(w) >= 7]
        if words_name and all(
            re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", heading)
            for w in words_name
        ):
            unique.append(name)
    if len(unique) == 1:
        return unique[0]
    distinctive = [
        name for name in client_names if any(
            len(w) >= 8 and w not in {"caseificio", "industria", "forneria", "azienda"}
            and re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", heading)
            for w in clean_company(name).split()
        )
    ]
    return distinctive[0] if len(distinctive) == 1 else ""


def basename_client(name: str) -> str:
    return clean_company(name)


def filename(d: CloudDoc, seq: int | None = None) -> str:
    base = f"{d.date:%m-%d} {('conferma ordine' if d.kind == 'conferma' else d.kind)} {basename_client(d.cliente)}"
    if d.kind != "offerta" and d.numero:
        base += " " + d.numero
    if seq:
        base += f" {seq}"
    return base + ".pdf"


def inspect_cloud(file_info: dict, content: bytes, client_names: list[str], aliases: dict | None = None) -> CloudDoc:
    d = CloudDoc(
        file_id=file_info["id"],
        original_name=file_info.get("name", ""),
        content=content,
        md5=file_info.get("md5Checksum") or "",
    )
    try:
        d.text = read_pdf_bytes(content)
        d.kind = identify_kind(d.text)
        if d.kind == "incerto":
            d.err = "Tipologia non riconosciuta con sufficiente certezza"
            return d
        d.cliente = resolve_client(d.text, client_names, aliases, d.kind, d.original_name)
        if not d.cliente:
            try:
                additional = read_pdf_bytes(content, force_ocr=True)
                candidate = resolve_client(additional, client_names, aliases, d.kind, d.original_name)
                if candidate:
                    d.cliente = candidate
            except Exception:
                pass
        if not d.cliente:
            d.err = "Cliente assente dall'archivio TEST o riconoscimento ambiguo"
            return d
        d.date = find_date(d.text, d.kind)
        if not d.date:
            d.err = "Data del documento non riconosciuta"
            return d
        d.numero, d.numero_conferma = find_number(d.text, d.kind)
        if d.kind == "ordine" and not d.numero and re.search(r"\s\d{2,10}\.pdf$", d.original_name, re.I):
            d.err = "Numero nel nome originale non verificato nel PDF: rinomina bloccata"
        if not d.err:
            d.newname = filename(d)
    except Exception as exc:
        d.err = f"Impossibile leggere PDF: {type(exc).__name__}"
    return d


def shared_distinctive_reference(order: CloudDoc, confirmation: CloudDoc) -> bool:
    if not order.date or not confirmation.date or order.date.date() != confirmation.date.date():
        return False
    if "outlook" not in normalize(order.text[:150]):
        return False
    latest = re.split(r"\n\s*(?:Da\s*:|Inviato\s*:)", order.text[:5000], maxsplit=1, flags=re.I)[0]
    m = re.search(r"(?:seguente ordine|confermiamo ordine)\s*[:?!.]?\s*\n\s*([^\n]+)", latest, re.I)
    if not m:
        return False
    product = set(re.findall(r"\b[a-z]{7,}\b", normalize(m.group(1))))
    excluded = {
        "quantita", "consegna", "cartone", "cliente", "ordine", "seguente",
        "seneci", "pietro", "maniglie", "settimanale", "settimana",
    }
    product -= excluded | set(clean_company(order.cliente).split())
    return bool(product & set(re.findall(r"\b[a-z]{7,}\b", normalize(confirmation.text[:3500]))))


MOZZO_APPROVED_PAIR = (
    "d895978211cacbaaa314febf3e031da939e217dd0a84d32ec8d0b5199ff0ed6d",
    "4cd310db6336d15e35ccc598259f8f9126a0d699c0b5b3332fe4336352d4ef41",
)


def _sha256(d: CloudDoc) -> str:
    return hashlib.sha256(d.content).hexdigest()


def approved_mozzo_pair(docs: list[CloudDoc], paired: set[str]) -> tuple[CloudDoc, CloudDoc] | None:
    matches = []
    for expected, kind in zip(MOZZO_APPROVED_PAIR, ("ordine", "conferma")):
        found = []
        for d in docs:
            if d.err or d.kind != kind or d.file_id in paired:
                continue
            if clean_company(d.cliente) != "pastificio mozzo" or not d.date or d.date.year != 2026:
                continue
            if _sha256(d) == expected:
                found.append(d)
        if len(found) != 1:
            return None
        matches.append(found[0])
    order, confirmation = matches
    if (
        order.date.strftime("%Y-%m-%d") != "2026-09-22"
        or confirmation.numero
        or confirmation.numero_conferma != "203875"
    ):
        return None
    return order, confirmation


def _dest_info(destinations: dict, client: str, kind: str, year: int):
    info = destinations.get(client, {}).get(kind)
    if not info:
        return None
    return {
        "base_id": info.get("id", ""),
        "base_path": info.get("path", ""),
        "year": str(year),
        "year_id": (info.get("years") or {}).get(str(year), {}).get("id", ""),
        "existing": (info.get("years") or {}).get(str(year), {}).get("files", {}),
    }


def build_preview_plan(docs: list[CloudDoc], destinations: dict, inbox_path: str) -> list[dict]:
    orders = defaultdict(list)
    confs = defaultdict(list)
    for d in docs:
        if d.err or not d.cliente:
            continue
        key = (d.cliente, d.numero, d.date.year if d.date else None)
        if d.kind == "ordine" and d.numero:
            orders[key].append(d)
        elif d.kind == "conferma" and d.numero:
            confs[key].append(d)

    paired: set[str] = set()
    pairs: list[tuple[CloudDoc, CloudDoc]] = []
    for key in orders.keys() & confs.keys():
        a, b = orders[key], confs[key]
        if len(a) == len(b) == 1:
            paired.update((a[0].file_id, b[0].file_id))
            pairs.append((a[0], b[0]))
        else:
            for d in a + b:
                d.err = "Più ordini/conferme con stesso cliente e numero: abbinamento ambiguo"

    remaining_orders = [d for d in docs if not d.err and d.kind == "ordine" and not d.numero and d.file_id not in paired]
    remaining_confs = [d for d in docs if not d.err and d.kind == "conferma" and not d.numero and d.file_id not in paired]
    proposals = [
        (o, c) for o in remaining_orders for c in remaining_confs
        if o.cliente == c.cliente and shared_distinctive_reference(o, c)
    ]
    for o, c in proposals:
        if sum(a is o for a, _ in proposals) == 1 and sum(b is c for _, b in proposals) == 1:
            paired.update((o.file_id, c.file_id))
            pairs.append((o, c))

    approved = approved_mozzo_pair(docs, paired)
    if approved:
        order, confirmation = approved
        paired.update((order.file_id, confirmation.file_id))
        pairs.append((order, confirmation))

    rows = []
    pending = []

    for d in docs:
        if d.err:
            rows.append({"d": d, "action": "ANOMALIA", "reason": d.err, "destination": ""})
            continue
        if d.kind == "ordine" and d.file_id not in paired:
            reason = (
                "Ordine senza numero: abbinamento automatico non sicuro; rinominato solo"
                if not d.numero else
                "Conferma Innova non ancora presente: rinominato solo"
            )
            pending.append((d, reason, {"base_path": inbox_path, "year": "", "year_id": "", "existing": {}}))
        elif d.kind == "conferma" and d.file_id not in paired:
            rows.append({
                "d": d,
                "action": "ANOMALIA",
                "reason": "Ordine cliente corrispondente non presente: conferma lasciata invariata",
                "destination": "",
            })
        elif d.kind == "offerta":
            dest = _dest_info(destinations, d.cliente, "OFFERTE", d.date.year)
            if dest is None:
                rows.append({
                    "d": d,
                    "action": "ANOMALIA",
                    "reason": "Cartella OFFERTE inesistente o ambigua",
                    "destination": "",
                })
            else:
                pending.append((d, "Offerta autonoma", dest))

    for a, b in pairs:
        dest = _dest_info(destinations, a.cliente, "ORDINI", a.date.year)
        if dest is None:
            for d in (a, b):
                rows.append({
                    "d": d,
                    "action": "ANOMALIA",
                    "reason": "Cartella ORDINI inesistente o ambigua",
                    "destination": "",
                })
            continue
        a_dest = dest
        b_dest = dest
        b.date = a.date
        b.newname = filename(b)
        pending.extend([
            (a, "Coppia ordine-conferma", a_dest),
            (b, "Coppia ordine-conferma", b_dest),
        ])

    planned = set()
    for d, reason, dest in sorted(
        pending,
        key=lambda v: (v[2].get("base_path", ""), str(v[0].date), v[0].kind, v[0].original_name),
    ):
        d.newname = filename(d)
        target_path = dest["base_path"]
        if dest.get("year"):
            target_path = f"{target_path} / {dest['year']}"

        existing = {k.casefold(): v for k, v in (dest.get("existing") or {}).items()}
        target_key = d.newname.casefold()

        if d.kind == "ordine" and not d.numero:
            seq = 1
            base_name = d.newname
            while target_key in existing or (target_path.casefold(), target_key) in planned:
                existing_meta = existing.get(target_key)
                if existing_meta and d.md5 and existing_meta.get("md5Checksum") == d.md5:
                    rows.append({
                        "d": d,
                        "action": "ANOMALIA",
                        "reason": f"PDF duplicato già presente: {target_path} / {d.newname}",
                        "destination": target_path,
                    })
                    break
                d.newname = filename(d, seq)
                target_key = d.newname.casefold()
                seq += 1
            else:
                planned.add((target_path.casefold(), target_key))
                action = "RINOMINA" if target_path == inbox_path else "SPOSTA"
                rows.append({"d": d, "action": action, "reason": reason, "destination": target_path})
                continue
            continue

        if target_key in existing:
            rows.append({
                "d": d,
                "action": "ANOMALIA",
                "reason": f"Destinazione già esistente: {target_path} / {d.newname}",
                "destination": target_path,
            })
            continue
        if (target_path.casefold(), target_key) in planned:
            rows.append({
                "d": d,
                "action": "ANOMALIA",
                "reason": f"Collisione tra file del lotto: {target_path} / {d.newname}",
                "destination": target_path,
            })
            continue

        planned.add((target_path.casefold(), target_key))
        action = "RINOMINA" if target_path == inbox_path else "SPOSTA"
        rows.append({"d": d, "action": action, "reason": reason, "destination": target_path})

    for a, b in pairs:
        ra = next((r for r in rows if r["d"] is a), None)
        rb = next((r for r in rows if r["d"] is b), None)
        if ra and rb and (ra["action"] == "ANOMALIA" or rb["action"] == "ANOMALIA"):
            reason = ra["reason"] if ra["action"] == "ANOMALIA" else rb["reason"]
            for r in (ra, rb):
                r["action"] = "ANOMALIA"
                r["reason"] = "Coppia bloccata: " + reason

    output = []
    for r in rows:
        d = r["d"]
        output.append({
            "File originale": d.original_name,
            "Tipo": d.kind,
            "Cliente": d.cliente,
            "Data": d.date.strftime("%d/%m/%Y") if d.date else "",
            "N. ordine": d.numero,
            "N. conferma Innova": d.numero_conferma,
            "Nuovo nome": d.newname,
            "Destinazione": r.get("destination", ""),
            "Esito": "ANTEPRIMA " + r["action"] if r["action"] != "ANOMALIA" else "ANOMALIA",
            "Motivo": r["reason"],
        })
    return output
