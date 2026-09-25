"""Configurazione runtime dell'archivio REALE Innova.

Gli ID reali non sono salvati nel repository: vengono letti esclusivamente
dai Secrets Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriveArchiveRuntime:
    mode: str
    root_id: str
    inbox_id: str
    root_name: str
    writes_enabled: bool


def real_runtime_from_secrets(secrets) -> DriveArchiveRuntime | None:
    """Legge la configurazione REALE senza abilitarla implicitamente."""
    if "innova_drive_real" not in secrets:
        return None

    raw = secrets["innova_drive_real"]
    required = ("root_id", "inbox_id", "root_name")
    if any(not raw.get(key) for key in required):
        return None

    runtime = DriveArchiveRuntime(
        mode="REAL",
        root_id=str(raw["root_id"]),
        inbox_id=str(raw["inbox_id"]),
        root_name=str(raw["root_name"]),
        writes_enabled=bool(raw.get("writes_enabled", False)),
    )

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
