"""Autorizzazione OAuth UNA TANTUM da PC dell'utente, senza token in GitHub.

PREREQUISITI:
- Nel client OAuth di tipo Applicazione web autorizzare ESATTAMENTE
  http://127.0.0.1:8765/ come URI di reindirizzamento aggiuntivo.
- Scaricare il JSON del medesimo client OAuth sul proprio PC, FUORI dal repo.
- pip install google-auth-oauthlib
- python tools/authorize_innova_drive_once.py "PERCORSO_JSON_CLIENT_OAUTH"

Crea in home un file TOML riservato da copiare personalmente nei Secrets
Streamlit (mai in chat/GitHub). Non archivia un access token o i PDF.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPE = "https://www.googleapis.com/auth/drive"
OUTPUT = Path.home() / "innova_drive_oauth_secrets.txt"


def main() -> int:
    if len(sys.argv) != 2:
        print("Uso: python tools/authorize_innova_drive_once.py PERCORSO_JSON_CLIENT_OAUTH")
        return 2

    client_file = Path(sys.argv[1]).expanduser().resolve()
    if not client_file.is_file():
        print("File JSON OAuth non trovato. Non incollare le credenziali in chat.")
        return 2
    if OUTPUT.exists():
        print("Esiste già un file credenziali nella home: non lo sovrascrivo.")
        return 2

    try:
        config = json.loads(client_file.read_text(encoding="utf-8"))
        web = config["web"]
        client_id, client_secret = web["client_id"], web["client_secret"]
        if not client_id or not client_secret:
            raise ValueError("client OAuth incompleto")
    except (ValueError, KeyError, OSError, TypeError):
        print("JSON non valido: scarica il JSON del client OAuth web corretto.")
        return 2

    print("Si aprirà Google nel browser: scegli SOLTANTO il tuo account di lavoro.")
    print("Non condividere né il JSON né codici o token. Nessun file Drive sarà modificato.")
    try:
        flow = InstalledAppFlow.from_client_config(config, scopes=[SCOPE])
        credentials = flow.run_local_server(
            host="127.0.0.1",
            bind_addr="127.0.0.1",
            port=8765,
            open_browser=True,
            access_type="offline",
            prompt="consent",
            success_message="Autorizzazione completata. Puoi chiudere questa scheda.",
        )
        refresh_token = credentials.refresh_token
        if not refresh_token:
            print("Google non ha restituito un refresh token. Nessun file creato.")
            return 1
        testo = (
            "[innova_drive_oauth]\n"
            f"client_id = {json.dumps(client_id)}\n"
            f"client_secret = {json.dumps(client_secret)}\n"
            f"refresh_token = {json.dumps(refresh_token)}\n"
        )
        # O_EXCL evita sovrascritture; su Unix limita l'accesso all'utente.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        fd = os.open(str(OUTPUT), flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(testo)
    except Exception:
        # Non stampare eccezioni OAuth: alcune includono parametri sensibili.
        print("Autorizzazione non completata. Controlla l'URI locale e l'account usato.")
        return 1

    print("Autorizzazione riuscita. File riservato creato nella tua cartella utente:")
    print(str(OUTPUT))
    print("Copialo SOLTANTO nei Secrets Streamlit, poi eliminalo in modo sicuro.")
    print("Non inviare screenshot del contenuto e non aggiungerlo al repository.")
    print("In modalità OAuth TEST il refresh token Drive può scadere dopo 7 giorni.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
