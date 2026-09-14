import re
from datetime import datetime

import pdfplumber


# ---------------------------------------------------------
# FUNZIONE DI ESTRAZIONE MULTI-LAYOUT (VECCHIO + NUOVO)
# ---------------------------------------------------------
def estrai_dati_pdf(pdf_file):
    righe_estratte = []
    
    with pdfplumber.open(pdf_file) as pdf:
        page = pdf.pages[0]
        words = page.extract_words()
        testo_layout = page.extract_text(layout=True) or ""
        testo_semplice = page.extract_text(layout=False) or ""

    if "BORGO SAN GIACOMO" in testo_semplice or "N° Ord. Cliente" in testo_semplice or "N Ord. Cliente" in testo_semplice:
        m_cli = re.search(r"Spett\.le\s*\n\s*([^\n]+)", testo_semplice)
        cliente = m_cli.group(1).strip() if m_cli else ""

        n_ordine = ""
        target_word = None
        for w in words:
            if "Cliente" in w['text'] and w['top'] < 300:
                target_word = w
                break
        
        if target_word:
            x0 = target_word['x0'] - 30
            x1 = target_word['x1'] + 60
            top = target_word['bottom']
            bottom = top + 35
            
            num_words = [
                w['text'].strip() for w in words 
                if x0 <= w['x0'] <= x1 and top <= w['top'] <= bottom
            ]
            for nw in num_words:
                if re.search(r"\d", nw) and "Causale" not in nw:
                    n_ordine = nw
                    break

        if not n_ordine:
            m_ord = re.search(r"N°?\s*Ord\.?\s*Cliente\s*[\n\r]*\s*([A-Z0-9/\-_]+)", testo_semplice, re.IGNORECASE)
            if m_ord:
                n_ordine = m_ord.group(1).strip()

        righe_raw = testo_layout.split("\n")
        
        idx_inizio = 0
        for i, riga in enumerate(righe_raw):
            if "Descrizione" in riga and "Quantità" in riga:
                idx_inizio = i
                break

        for i in range(idx_inizio + 1, len(righe_raw)):
            riga = righe_raw[i]
            
            m_consegna = re.search(r"(\d{2}\.\d{2}\.\d{4})", riga)
            if m_consegna:
                idx_date = riga.find(m_consegna.group(1))
                testo_dopo_data = riga[idx_date + len(m_consegna.group(1)):].strip()
                numeri_destra = re.findall(r"\b\d{1,3}(?:\.\d{3})*(?:,\d+)?\b", testo_dopo_data)
                
                if len(numeri_destra) < 2:
                    continue

                consegna = m_consegna.group(1).replace(".", "/")
                qta = numeri_destra[0]
                prezzo = f"€ {numeri_destra[1]}"

                descrizione = riga[:idx_date].strip()
                if i > 0 and (len(descrizione) < 3 or re.match(r"^[\d\s x X \.-]+$", descrizione)):
                    riga_sopra = righe_raw[i-1].strip()
                    if "Descrizione" not in riga_sopra:
                        descrizione = riga_sopra

                descrizione = re.sub(r"Kg\s*[\d\.,]+", "", descrizione, flags=re.IGNORECASE).strip()

                cartone = ""
                m_cartone = re.search(r"\b([A-Z]{2,4}\d{2,4}\s*[A-Z0-9]*)\b", riga[idx_date:])
                if not m_cartone and i + 1 < len(righe_raw):
                    m_cartone = re.search(r"\b([A-Z]{2,4}\d{2,4}\s*[A-Z0-9]*)\b", righe_raw[i+1])
                
                if m_cartone:
                    cartone = m_cartone.group(1).strip()

                if cartone and cartone not in descrizione:
                    articolo_completo = f"{descrizione} {cartone}".strip()
                else:
                    articolo_completo = descrizione

                if articolo_completo and consegna:
                    righe_estratte.append({
                        "CLIENTE": cliente,
                        "N. ORDINE": n_ordine,
                        "ARTICOLO": articolo_completo,
                        "CONSEGNA": consegna,
                        "QUANTITÀ": qta,
                        "PREZZO": prezzo
                    })

    else:
        m_cliente = re.search(r"Spett\.le\s*\n\s*([^\n]+)", testo_semplice)
        cliente = m_cliente.group(1).strip() if m_cliente else ""

        n_ordine = ""
        target_word = None
        for w in words:
            if "N°Ord" in w['text'] or "Cliente" in w['text']:
                if w['top'] < 300:
                    target_word = w
                    break
        
        if target_word:
            x0 = target_word['x0'] - 10
            x1 = target_word['x1'] + 60
            top = target_word['bottom']
            bottom = top + 45
            
            num_words = [
                w['text'].strip() for w in words 
                if x0 <= w['x0'] <= x1 and top <= w['top'] <= bottom
            ]
            
            for nw in num_words:
                clean_num = re.sub(r"\D", "", nw)
                if clean_num:
                    n_ordine = clean_num
                    break

        if not n_ordine:
            m_ord = re.search(r"N°Ord Cliente\s*[\n\r]*\s*(\d+)", testo_semplice)
            if m_ord:
                n_ordine = m_ord.group(1)

        righe_raw = testo_layout.split("\n")
        
        for i, riga in enumerate(righe_raw):
            m_consegna = re.search(r"(\d{2}/\d{2}/\d{4})", riga)
            m_prezzo = re.search(r"€\s*([\d\.,]+)", riga)
            
            if m_consegna and m_prezzo:
                consegna = m_consegna.group(1)
                prezzo = f"€ {m_prezzo.group(1).strip()}"
                
                idx_date = riga.find(consegna)
                idx_price = riga.find("€")
                segmento_qta = riga[idx_date + len(consegna):idx_price]
                m_qta = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)", segmento_qta)
                qta = m_qta.group(1).strip() if m_qta else ""

                articolo = ""
                testo_prima_data = riga[:idx_date].strip()
                if len(testo_prima_data) > 2:
                    articolo = testo_prima_data
                elif i > 0:
                    riga_sopra = righe_raw[i-1].strip()
                    riga_sopra_pulita = re.sub(r"Kg\s*[\d\.,]+", "", riga_sopra).strip()
                    if riga_sopra_pulita and not "Descrizione" in riga_sopra_pulita:
                        articolo = riga_sopra_pulita

                if articolo:
                    articolo = re.sub(r"^\s*\(\d+\)\s*", "", articolo)
                    articolo = re.sub(r"Kg\s*[\d\.,]+", "", articolo)
                    articolo = re.sub(r"\d+\s*x\s*\d+(\s*x\s*\d+)?", "", articolo, flags=re.IGNORECASE)
                    articolo = re.sub(r"\s{2,}", " ", articolo).strip()

                if not articolo or len(articolo) < 2:
                    m_code = re.findall(r"\b(IMSCA\d+|[A-Z0-9]{4,15})\b", testo_semplice)
                    if m_code and len(righe_estratte) < len(m_code):
                        articolo = m_code[len(righe_estratte)]

                if articolo and consegna:
                    righe_estratte.append({
                        "CLIENTE": cliente,
                        "N. ORDINE": n_ordine,
                        "ARTICOLO": articolo,
                        "CONSEGNA": consegna,
                        "QUANTITÀ": qta,
                        "PREZZO": prezzo
                    })

    return righe_estratte



# ---------------------------------------------------------
# VALIDAZIONE CONSERVATIVA DEI DATI ESTRATTI
# ---------------------------------------------------------
def valida_riga_importazione(riga):
    """
    Restituisce una lista di avvisi senza modificare né bloccare la riga.
    La validazione è volutamente prudente: segnala solo campi mancanti
    o formati chiaramente anomali.
    """

    avvisi = []

    cliente = str(riga.get("CLIENTE", "") or "").strip()
    n_ordine = str(riga.get("N. ORDINE", "") or "").strip()
    articolo = str(riga.get("ARTICOLO", "") or "").strip()
    consegna = str(riga.get("CONSEGNA", "") or "").strip()
    quantita = str(riga.get("QUANTITÀ", "") or "").strip()
    prezzo = str(riga.get("PREZZO", "") or "").strip()

    if not cliente:
        avvisi.append("Cliente mancante")

    if not n_ordine:
        avvisi.append("N. ordine mancante")

    if not articolo:
        avvisi.append("Articolo mancante")

    if not consegna:
        avvisi.append("Consegna mancante")
    else:
        try:
            datetime.strptime(consegna, "%d/%m/%Y")
        except ValueError:
            avvisi.append("Data consegna non valida")

    if not quantita:
        avvisi.append("Quantità mancante")
    else:
        qta_norm = quantita.replace(".", "").replace(",", ".").strip()
        try:
            qta_num = float(qta_norm)
            if qta_num <= 0:
                avvisi.append("Quantità non positiva")
        except ValueError:
            avvisi.append("Quantità non valida")

    if not prezzo:
        avvisi.append("Prezzo mancante")
    else:
        prezzo_norm = prezzo.replace("€", "").replace(".", "").replace(",", ".").strip()
        try:
            prezzo_num = float(prezzo_norm)
            if prezzo_num < 0:
                avvisi.append("Prezzo negativo")
        except ValueError:
            avvisi.append("Prezzo non valido")

    return avvisi


# ---------------------------------------------------------
# CONTROLLO DUPLICATI PRIMA DEL SALVATAGGIO
# ---------------------------------------------------------
def classifica_righe_importazione(nuovi_dati, df_esistente):
    """
    Classifica ogni riga estratta dal PDF senza modificare il database.

    Stati:
    - 🟢 NUOVO: nessuna corrispondenza esatta nel database.
    - 🔴 GIÀ PRESENTE: tutti i campi principali coincidono.
    - 🟡 DA VERIFICARE: stesso cliente + stesso numero ordine già presenti,
      ma almeno uno degli altri campi è diverso.

    Il controllo è volutamente conservativo:
    non usa fuzzy matching e non modifica/scarta dati in base a somiglianze.
    """

    campi_confronto = [
        "CLIENTE",
        "N. ORDINE",
        "ARTICOLO",
        "CONSEGNA",
        "QUANTITÀ",
        "PREZZO",
    ]

    def normalizza_testo(valore):
        if valore is None:
            return ""
        return re.sub(r"\s+", " ", str(valore)).strip().upper()

    righe_db = []
    if df_esistente is not None and not df_esistente.empty:
        for _, riga in df_esistente.iterrows():
            righe_db.append({
                campo: normalizza_testo(riga.get(campo, ""))
                for campo in campi_confronto
            })

    risultati = []

    for riga_originale in nuovi_dati:
        riga = dict(riga_originale)

        riga_norm = {
            campo: normalizza_testo(riga.get(campo, ""))
            for campo in campi_confronto
        }

        duplicato_esatto = any(
            all(db_row[campo] == riga_norm[campo] for campo in campi_confronto)
            for db_row in righe_db
        )

        if duplicato_esatto:
            stato = "🔴 GIÀ PRESENTE"
        else:
            stesso_ordine = any(
                db_row["CLIENTE"] == riga_norm["CLIENTE"]
                and db_row["N. ORDINE"] == riga_norm["N. ORDINE"]
                and riga_norm["CLIENTE"] != ""
                and riga_norm["N. ORDINE"] != ""
                for db_row in righe_db
            )

            if stesso_ordine:
                stato = "🟡 DA VERIFICARE"
            else:
                stato = "🟢 NUOVO"

        riga["STATO"] = stato

        avvisi = valida_riga_importazione(riga)
        riga["AVVISI"] = " | ".join(avvisi) if avvisi else "✅ OK"

        risultati.append(riga)

    return risultati
