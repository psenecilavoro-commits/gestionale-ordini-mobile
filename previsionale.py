import pandas as pd
from datetime import datetime, timedelta


# ---------------------------------------------------------
# CALCOLO ALGORITMO PREVISIONALE RIORDINI
# ---------------------------------------------------------
def calcola_previsionale(df_ordini):
    if df_ordini.empty:
        return pd.DataFrame()

    df = df_ordini.copy()
    df["DATA_DT"] = pd.to_datetime(df["CONSEGNA"], format="%d/%m/%Y", errors="coerce")
    df = df.dropna(subset=["DATA_DT"]).sort_values(["CLIENTE", "ARTICOLO", "DATA_DT"])

    oggi = datetime.now()
    mese_corrente = oggi.month
    anno_corrente = oggi.year
    
    prossimo_mese_dt = (oggi.replace(day=1) + timedelta(days=32)).replace(day=1)
    mese_prossimo = prossimo_mese_dt.month
    anno_prossimo = prossimo_mese_dt.year

    previsioni = []

    gruppi = df.groupby(["CLIENTE", "ARTICOLO"])

    for (cliente, articolo), g in gruppi:
        if len(g) == 0:
            continue

        date_consegne = g["DATA_DT"].tolist()
        ultima_data = date_consegne[-1]
        ultima_qta = g["QUANTITÀ"].iloc[-1]
        ultimo_prezzo = g["PREZZO"].iloc[-1]

        gg_trascorsi = (oggi - ultima_data).days

        if len(date_consegne) > 1:
            diffs = [(date_consegne[k] - date_consegne[k-1]).days for k in range(1, len(date_consegne))]
            intervallo_medio = sum(diffs) / len(diffs)
            intervallo_medio = max(intervallo_medio, 15)
        else:
            intervallo_medio = 60

        data_stimata = ultima_data + timedelta(days=int(intervallo_medio))
        ha_ordine_futuro = any(d >= oggi.replace(day=1) for d in date_consegne)

        stesso_mese_corr = (data_stimata.month == mese_corrente and data_stimata.year == anno_corrente)
        stesso_mese_prox = (data_stimata.month == mese_prossimo and data_stimata.year == anno_prossimo)
        in_ritardo = (data_stimata < oggi and not ha_ordine_futuro)

        if gg_trascorsi > 365:
            stato = "⚪ Articolo Declassato"
            periodo_rif = "Inattivo (> 1 anno)"
            previsioni.append({
                "CLIENTE": cliente,
                "ARTICOLO": articolo,
                "STATO": stato,
                "PERIODO ATTESO": periodo_rif,
                "GG TRASCORSI": gg_trascorsi,
                "DATA STIMATA RIORDINO": data_stimata.strftime("%d/%m/%Y"),
                "FREQ. MEDIA (GG)": int(intervallo_medio),
                "ULTIMA CONSEGNA": ultima_data.strftime("%d/%m/%Y"),
                "ULTIMA Q.TÀ": ultima_qta,
                "ULTIMO PREZZO": ultimo_prezzo
            })
        elif stesso_mese_corr or stesso_mese_prox or in_ritardo:
            if in_ritardo:
                stato = "🔴 In Ritardo / Da Sollecitare"
                periodo_rif = "Scaduto"
            elif stesso_mese_corr:
                stato = "🟢 Già Ordinato" if ha_ordine_futuro else "🟡 Mese Corrente"
                periodo_rif = "Mese Corrente"
            else:
                stato = "🟢 Già Ordinato" if ha_ordine_futuro else "🔵 Mese Successivo"
                periodo_rif = "Mese Successivo"

            previsioni.append({
                "CLIENTE": cliente,
                "ARTICOLO": articolo,
                "STATO": stato,
                "PERIODO ATTESO": periodo_rif,
                "GG TRASCORSI": gg_trascorsi,
                "DATA STIMATA RIORDINO": data_stimata.strftime("%d/%m/%Y"),
                "FREQ. MEDIA (GG)": int(intervallo_medio),
                "ULTIMA CONSEGNA": ultima_data.strftime("%d/%m/%Y"),
                "ULTIMA Q.TÀ": ultima_qta,
                "ULTIMO PREZZO": ultimo_prezzo
            })

    df_prev = pd.DataFrame(previsioni)
    if not df_prev.empty:
        df_prev = df_prev.sort_values(by=["STATO", "DATA STIMATA RIORDINO"])
    return df_prev
