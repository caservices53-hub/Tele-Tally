from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    tally_url: str = os.getenv("TALLY_URL", "http://localhost:9000").rstrip("/")
    tally_company: str = os.getenv("TALLY_COMPANY", "").strip()
    db_path: str = os.getenv("GPT_TALLY_DB", "./data/gpt_tally_v2.sqlite3")
    auto_threshold: float = _f("GPT_TALLY_AUTO_THRESHOLD", 0.90)
    batch_size: int = max(1, _i("GPT_TALLY_BATCH_SIZE", 100))
    default_bank_ledger: str = os.getenv("GPT_TALLY_DEFAULT_BANK_LEDGER", "").strip()
    openai_model: str = os.getenv("OPENAI_MODEL", "").strip()
    ai_auto_approve: bool = os.getenv("GPT_TALLY_AI_AUTO_APPROVE", "0").strip() == "1"

    def ensure_dirs(self) -> None:
        Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
