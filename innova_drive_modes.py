"""Separazione esplicita tra configurazione TEST e futura configurazione REALE.

Gli ID reali NON devono essere salvati nel repository. La configurazione reale,
quando verrà abilitata, sarà letta esclusivamente dai Secrets Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass

from innova_drive_preview import TEST_ROOT_ID, TEST_INBOX_ID


@dataclass(frozen=True)
class DriveArchiveRuntime:
    mode: str
    root_id: str
    inbox_id: str
    root_name: str
    writes_enabled: bool


TEST_RUNTIME = DriveArchiveRuntime(
    mode="TEST",
    root_id=TEST_ROOT_ID,
    inbox_id=TEST_INBOX_ID,
    root_name="TEST BOT CLOUD",
    writes_enabled=True,
)


def real_runtime_from_secrets(secrets) -> DriveArchiveRuntime | None:
    """Legge la futura configurazione REALE senza abilitarla implicitamente.

    Se la sezione non esiste, restituisce None. Le scritture reali richiederanno
    comunque un gate esplicito separato; la sola presenza degli ID non basta.
    """
    if "innova_drive_real" not in secrets:
        return None

    raw = secrets["innova_drive_real"]
    required = ("root_id", "inbox_id", "root_name")
    if any(not raw.get(key) for key in required):
        return None

    enabled = bool(raw.get("writes_enabled", False))
    runtime = DriveArchiveRuntime(
        mode="REAL",
        root_id=str(raw["root_id"]),
        inbox_id=str(raw["inbox_id"]),
        root_name=str(raw["root_name"]),
        writes_enabled=enabled,
    )

    if runtime.root_id in {TEST_RUNTIME.root_id, TEST_RUNTIME.inbox_id}:
        raise ValueError("Configurazione REALE sovrapposta alla gerarchia TEST.")
    if runtime.inbox_id in {TEST_RUNTIME.root_id, TEST_RUNTIME.inbox_id}:
        raise ValueError("Configurazione REALE sovrapposta alla gerarchia TEST.")
    if runtime.root_id == runtime.inbox_id:
        raise ValueError("root_id e inbox_id REALI non possono coincidere.")
    return runtime


def assert_real_writes_explicitly_enabled(runtime: DriveArchiveRuntime | None):
    if runtime is None or runtime.mode != "REAL":
        raise RuntimeError("Configurazione REALE non disponibile.")
    if not runtime.writes_enabled:
        raise RuntimeError(
            "Scritture REALI disabilitate nei Secrets. "
            "La sola configurazione degli ID non abilita la produzione."
        )
