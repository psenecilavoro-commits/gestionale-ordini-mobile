# Bot Innova — collaudo cloud (bozza, NON distribuire)

Questa è una prova **separata dall'archivio reale**. L'unico ingresso consentito dal modulo è la cartella `TEST BOT CLOUD / 01 ORDINI SENZA CO` (ID `1H7v7tYALCD9mojlnTYNJPr_i54ieeyzZ`); la cartella padre di test deve avere ID `1SCWDJ2WqTGVAH3EbOfmHRtaCFupL3z1C`. La pagina `pages/Archivio_Innova.py` appartiene alla stessa app Streamlit del gestionale principale; `app_mobile.py` non è coinvolta.

## Cosa fa e cosa NON fa

- Richiede l'autenticazione della sessione al Gestionale Ordini prima di mostrare la pagina.
- Legge al massimo 50 PDF direttamente nell'ingresso di prova, con limite dichiarato di 15 MB ciascuno; estrae testo da non più di 3 pagine e segnala se il PDF richiederà OCR.
- Non applica ancora classificazione, riconciliazione ordine/conferma, rinomina, creazione cartelle o spostamento del bot V4.
- Non aggiorna Supabase, non scrive su Google Drive e non salva copie dei PDF in modo persistente.
- Non cambia il codice dell'applicazione principale e non imposta una schedulazione.

## Credenziali: NON inserire valori veri nel repository

La pagina è bloccata finché i **Secrets privati** dell'app Streamlit non includono la sezione `innova_drive_oauth` con i campi `client_id`, `client_secret` e `refresh_token`. **Non incollare token o segreti in GitHub, screenshot o chat.** Il client OAuth web e lo scope `https://www.googleapis.com/auth/drive` sono stati configurati in Google Cloud. La connessione ChatGPT a Drive non è trasferibile a Streamlit.

### Bootstrap locale una tantum (non ancora testato end-to-end)

1. Nel client OAuth WEB **già creato**, aggiungere come URI di reindirizzamento autorizzato `http://127.0.0.1:8765/`, mantenendo l'indirizzo Streamlit esistente. Non aggiungere origini JavaScript; non creare un nuovo client.
2. Sul proprio PC scaricare il file JSON del client OAuth web da Google Cloud e conservarlo **fuori dal repository**. Non caricarlo in chat o GitHub.
3. Installare `google-auth-oauthlib` nell'ambiente Python locale e lanciare `python tools/authorize_innova_drive_once.py "PERCORSO_JSON_CLIENT_OAUTH"`. Lo script avvia un callback locale solo su `127.0.0.1:8765`, richiede `access_type=offline`, `prompt=consent` e lo scope Drive. Non modifica file Drive.
4. Solo se Google restituisce un refresh token, lo script crea nella cartella utente `innova_drive_oauth_secrets.txt` con la sezione TOML da copiare **esclusivamente nei Secrets dell'app Streamlit** dopo revisione e prima del test del ramo. Non inviare né condividere il file. Eliminarlo dopo aver configurato e verificato i Secrets; eliminare anche il JSON client scaricato se non serve più.
5. Lo script non è ancora stato eseguito con credenziali reali né la pagina è stata provata in Streamlit Cloud. **Non unire o distribuire questa PR prima della verifica.** La cartella utente sul PC deve essere protetta da altri utenti; il file contiene un refresh token altamente sensibile.

L'app OAuth attualmente in modalità *Test* può rilasciare refresh token con scadenza di 7 giorni per scope Drive. Per uso continuativo occorre risolvere e verificare lo stato di pubblicazione e gli eventuali requisiti Google, senza assumere che un'app non verificata sia automaticamente approvata.

## Requisiti prima di distribuire

1. Revisione della privacy: scope Drive completo consente tecnicamente accesso a tutto il Drive dell'utente, non solo a TEST BOT CLOUD; il vincolo della cartella è implementato in questo modulo, non imposto da Google.
2. Testare il bootstrap OAuth e la conservazione sicura delle credenziali, con revoca, gestione della scadenza e nessun segreto nei log.
3. Provare isolatamente con le copie PDF di Pastificio Mozzo, controllando la leggibilità; successivamente adattare le regole V4 con test di regressione.
4. Prima dell'esecuzione reale: snapshot e confronto metadati, controllo collisioni Google Drive, piano approvato, idempotenza, blocco di esecuzioni concorrenti e gestione di errori parziali.
5. Valutare limiti di durata, memoria e inattività di Streamlit Community Cloud; costo zero non è una garanzia di servizio senza limiti.

**Non unire questa PR in `main` né configurare i Secrets finché il flusso OAuth e i test non sono pronti.**
