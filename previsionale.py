import pandas as pd
from datetime import datetime, timedelta


def formatta_giorni(oggi, data_riferimento):
    """
    Restituisce una dicitura leggibile rispetto alla data di riferimento:
    - "24 gg trascorsi" se la data è passata
    - "Oggi" se è oggi
    - "Tra 11 gg" se la data è futura
    """
    differenza = (data_riferimento - oggi).days

    if differenza > 0:
        return f"Tra {differenza} gg"
    if differenza == 0:
        return "Oggi"
    return f"{abs(differenza)} gg trascorsi"


def _stesso_mese(data, mese, anno):
    return (
        data is not None
        and data.month == mese
        and data.year == anno
    )


# ---------------------------------------------------------
# CALCOLO ALGORITMO PREVISIONALE RIORDINI
# ---------------------------------------------------------
def calcola_previsionale(df_ordini):
    if df_ordini.empty:
        return pd.DataFrame()

    df = df_ordini.copy()
    df["DATA_DT"] = pd.to_datetime(
        df["CONSEGNA"],
        format="%d/%m/%Y",
        errors="coerce"
    )
    df = df.dropna(subset=["DATA_DT"]).sort_values(
        ["CLIENTE", "ARTICOLO", "DATA_DT"]
    )

    # Solo giorno corrente: niente differenze dovute all'orario.
    oggi = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    mese_corrente = oggi.month
    anno_corrente = oggi.year

    prossimo_mese_dt = (
        oggi.replace(day=1) + timedelta(days=32)
    ).replace(day=1)
    mese_prossimo = prossimo_mese_dt.month
    anno_prossimo = prossimo_mese_dt.year

    previsioni = []

    gruppi = df.groupby(["CLIENTE", "ARTICOLO"])

    for (cliente, articolo), g in gruppi:
        if g.empty:
            continue

        # -------------------------------------------------
        # 6B: separazione netta tra storico e ordini futuri
        # -------------------------------------------------
        g_storico = g[g["DATA_DT"] < oggi].copy()
        g_futuro = g[g["DATA_DT"] >= oggi].copy()

        date_storiche = g_storico["DATA_DT"].tolist()
        date_future = g_futuro["DATA_DT"].tolist()

        ultima_storica = date_storiche[-1] if date_storiche else None
        prossima_consegna = date_future[0] if date_future else None
        ha_ordine_futuro = prossima_consegna is not None

        # Per la colonna GIORNI:
        # - se c'è un ordine futuro, mostriamo quanto manca alla prossima consegna;
        # - altrimenti mostriamo quanto tempo è passato dall'ultima consegna storica.
        data_riferimento = (
            prossima_consegna
            if ha_ordine_futuro
            else ultima_storica
        )
        giorni_testo = (
            formatta_giorni(oggi, data_riferimento)
            if data_riferimento is not None
            else "N/D"
        )

        # Quantità/prezzo informativi:
        # usiamo l'ultima consegna storica; se non c'è storico, la prossima futura.
        if not g_storico.empty:
            riga_riferimento = g_storico.iloc[-1]
        elif not g_futuro.empty:
            riga_riferimento = g_futuro.iloc[0]
        else:
            riga_riferimento = g.iloc[-1]

        ultima_qta = riga_riferimento["QUANTITÀ"]
        ultimo_prezzo = riga_riferimento["PREZZO"]

        # -------------------------------------------------
        # Frequenza: SOLO consegne storiche già avvenute.
        # Gli ordini futuri non devono alterare la media.
        # -------------------------------------------------
        if len(date_storiche) > 1:
            diffs = [
                (date_storiche[k] - date_storiche[k - 1]).days
                for k in range(1, len(date_storiche))
            ]
            intervallo_medio = sum(diffs) / len(diffs)
            intervallo_medio = max(intervallo_medio, 15)
        else:
            # Manteniamo il default storico già usato dall'app.
            intervallo_medio = 60

        # La previsione matematica parte SOLO dall'ultima consegna storica.
        data_stimata = (
            ultima_storica + timedelta(days=int(intervallo_medio))
            if ultima_storica is not None
            else None
        )

        stima_mese_corrente = _stesso_mese(
            data_stimata,
            mese_corrente,
            anno_corrente
        )
        stima_mese_prossimo = _stesso_mese(
            data_stimata,
            mese_prossimo,
            anno_prossimo
        )
        stima_in_ritardo = (
            data_stimata is not None
            and data_stimata < oggi
        )

        consegna_mese_corrente = _stesso_mese(
            prossima_consegna,
            mese_corrente,
            anno_corrente
        )
        consegna_mese_prossimo = _stesso_mese(
            prossima_consegna,
            mese_prossimo,
            anno_prossimo
        )

        # Un ordine futuro deve risultare "Già Ordinato" quando:
        # 1) la consegna reale è nel mese corrente o successivo, ANCHE se
        #    la previsione matematica cadrebbe più avanti;
        # oppure
        # 2) la previsione è già rilevante (corrente/prossimo/in ritardo)
        #    e nel database esiste comunque un ordine futuro.
        ordine_futuro_rilevante = ha_ordine_futuro and (
            consegna_mese_corrente
            or consegna_mese_prossimo
            or stima_mese_corrente
            or stima_mese_prossimo
            or stima_in_ritardo
        )

        # Un articolo con un nuovo ordine futuro non viene considerato inattivo,
        # anche se l'ultima consegna storica risale a oltre un anno fa.
        gg_da_ultima_storica = (
            (oggi - ultima_storica).days
            if ultima_storica is not None
            else None
        )
        articolo_declassato = (
            gg_da_ultima_storica is not None
            and gg_da_ultima_storica > 365
            and not ha_ordine_futuro
        )

        # -------------------------------------------------
        # PRIORITÀ 1: ordine futuro reale
        # -------------------------------------------------
        if ordine_futuro_rilevante:
            stato = "🟢 Già Ordinato"

            if consegna_mese_corrente:
                periodo_rif = "Mese Corrente"
            elif consegna_mese_prossimo:
                periodo_rif = "Mese Successivo"
            elif stima_in_ritardo:
                periodo_rif = "Scaduto"
            elif stima_mese_corrente:
                periodo_rif = "Mese Corrente"
            else:
                periodo_rif = "Mese Successivo"

            previsioni.append({
                "CLIENTE": cliente,
                "ARTICOLO": articolo,
                "STATO": stato,
                "PERIODO ATTESO": periodo_rif,
                "GIORNI": giorni_testo,
                "PROSSIMA CONSEGNA": (
                    prossima_consegna.strftime("%d/%m/%Y")
                    if prossima_consegna is not None
                    else "N/D"
                ),
                "STIMA DA STORICO": (
                    data_stimata.strftime("%d/%m/%Y")
                    if data_stimata is not None
                    else "N/D"
                ),
                "FREQ. MEDIA (GG)": int(intervallo_medio),
                "ULTIMA CONSEGNA": (
                    ultima_storica.strftime("%d/%m/%Y")
                    if ultima_storica is not None
                    else "N/D"
                ),
                "ULTIMA Q.TÀ": ultima_qta,
                "ULTIMO PREZZO": ultimo_prezzo
            })
            continue

        # -------------------------------------------------
        # PRIORITÀ 2: articolo realmente inattivo
        # -------------------------------------------------
        if articolo_declassato:
            previsioni.append({
                "CLIENTE": cliente,
                "ARTICOLO": articolo,
                "STATO": "⚪ Articolo Declassato",
                "PERIODO ATTESO": "Inattivo (> 1 anno)",
                "GIORNI": giorni_testo,
                "PROSSIMA CONSEGNA": (
                    prossima_consegna.strftime("%d/%m/%Y")
                    if prossima_consegna is not None
                    else "N/D"
                ),
                "STIMA DA STORICO": (
                    data_stimata.strftime("%d/%m/%Y")
                    if data_stimata is not None
                    else "N/D"
                ),
                "FREQ. MEDIA (GG)": int(intervallo_medio),
                "ULTIMA CONSEGNA": (
                    ultima_storica.strftime("%d/%m/%Y")
                    if ultima_storica is not None
                    else "N/D"
                ),
                "ULTIMA Q.TÀ": ultima_qta,
                "ULTIMO PREZZO": ultimo_prezzo
            })
            continue

        # -------------------------------------------------
        # PRIORITÀ 3: normale previsione senza ordine futuro
        # -------------------------------------------------
        if stima_in_ritardo:
            stato = "🔴 In Ritardo / Da Sollecitare"
            periodo_rif = "Scaduto"
        elif stima_mese_corrente:
            stato = "🟡 Mese Corrente"
            periodo_rif = "Mese Corrente"
        elif stima_mese_prossimo:
            stato = "🔵 Mese Successivo"
            periodo_rif = "Mese Successivo"
        else:
            continue

        previsioni.append({
            "CLIENTE": cliente,
            "ARTICOLO": articolo,
            "STATO": stato,
            "PERIODO ATTESO": periodo_rif,
            "GIORNI": giorni_testo,
            "PROSSIMA CONSEGNA": (
                prossima_consegna.strftime("%d/%m/%Y")
                if prossima_consegna is not None
                else "N/D"
            ),
            "STIMA DA STORICO": (
                data_stimata.strftime("%d/%m/%Y")
                if data_stimata is not None
                else "N/D"
            ),
            "FREQ. MEDIA (GG)": int(intervallo_medio),
            "ULTIMA CONSEGNA": (
                ultima_storica.strftime("%d/%m/%Y")
                if ultima_storica is not None
                else "N/D"
            ),
            "ULTIMA Q.TÀ": ultima_qta,
            "ULTIMO PREZZO": ultimo_prezzo
        })

    df_prev = pd.DataFrame(previsioni)

    if not df_prev.empty:
        df_prev = df_prev.sort_values(
            by=["STATO", "STIMA DA STORICO"]
        )

    return df_prev
