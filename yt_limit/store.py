"""Persistência: config em ~/.config/yt-limit, estado diário em ~/.local/share/yt-limit."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "yt-limit"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "yt-limit"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = DATA_DIR / "state.json"


def fmt(seconds: int) -> str:
    """Formata segundos como MM:SS."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


@dataclass
class Config:
    limit_minutes: int = 30
    # Mostrar o contador mesmo sem nenhum player do YouTube aberto.
    always_show_overlay: bool = True
    # Avisar quando faltarem N minutos.
    warn_minutes_left: int = 5

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_FILE.read_text())
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2))


@dataclass
class State:
    day: str = ""
    seconds: int = 0
    # Segundos por vídeo (título -> segundos), só do dia corrente.
    per_video: dict | None = None

    @classmethod
    def load(cls) -> "State":
        try:
            data = json.loads(STATE_FILE.read_text())
            state = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            state = cls()
        state.roll_day()
        return state

    def roll_day(self) -> bool:
        """Zera o contador se o dia mudou. Retorna True se zerou."""
        today = date.today().isoformat()
        if self.day != today:
            self.day = today
            self.seconds = 0
            self.per_video = {}
            return True
        if self.per_video is None:
            self.per_video = {}
        return False

    def add_second(self, title: str) -> None:
        self.seconds += 1
        if title:
            self.per_video[title] = self.per_video.get(title, 0) + 1

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))
        os.replace(tmp, STATE_FILE)
