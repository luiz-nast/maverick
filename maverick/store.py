"""Persistência: config em ~/.config/maverick, estado do dia em ~/.local/share/maverick."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .blocking import default_domains, normalize_domain

APP_ID = "io.github.luiz_nast.Maverick"
APP_NAME = "Maverick"

CONFIG_FILE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "maverick" / "config.json"
STATE_FILE = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "maverick" / "state.json"


def fmt(seconds: int) -> str:
    """Segundos como MM:SS (negativos viram 00:00)."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def today_iso() -> str:
    return date.today().isoformat()


def mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def usage_status(used: int, limit: int, playing: bool, warn_minutes: int) -> str:
    """idle | playing | warning | blocked, igual para o daemon e a janela."""
    if used >= limit:
        return "blocked"
    if not playing:
        return "idle"
    return "warning" if limit - used <= warn_minutes * 60 else "playing"


def _load(cls, path: Path):
    try:
        data = json.loads(path.read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
    except (OSError, ValueError, TypeError, AttributeError):
        return cls()


def _save(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(obj), indent=2, ensure_ascii=False))
    os.replace(tmp, path)


@dataclass
class Config:
    # Limite que vale a partir de amanhã (e hoje, se não houver teto do dia).
    limit_minutes: int = 30
    # Teto do dia {"day", "minutes"}: aumentos não mexem nele, então só valem
    # amanhã; reduções o baixam na hora.
    today_cap: dict | None = None
    # Segundos que a pílula fica na tela depois que o vídeo para.
    hide_after_seconds: int = 2
    warn_minutes_left: int = 5
    # Mídia de janela privada quando a acessibilidade não confirma o site.
    count_private_media: bool = True
    blocked_sites: list[str] = field(default_factory=default_domains)

    @classmethod
    def load(cls) -> "Config":
        cfg = _load(cls, CONFIG_FILE)
        cfg.blocked_sites = list(dict.fromkeys(d for d in map(normalize_domain, cfg.blocked_sites) if d))
        return cfg

    def save(self) -> None:
        _save(self, CONFIG_FILE)

    def effective_limit(self, today: str | None = None) -> int:
        """Limite em minutos que vale hoje."""
        cap = self.today_cap or {}
        if cap.get("day") == (today or today_iso()) and isinstance(cap.get("minutes"), int):
            return min(self.limit_minutes, cap["minutes"])
        return self.limit_minutes

    def set_limit(self, minutes: int, today: str | None = None) -> bool:
        """Reduzir vale na hora; aumentar só amanhã. True se já vale hoje."""
        today = today or today_iso()
        current = self.effective_limit(today)
        self.today_cap = {"day": today, "minutes": min(current, minutes)}
        self.limit_minutes = minutes
        return minutes <= current


@dataclass
class State:
    day: str = ""
    seconds: int = 0
    per_video: dict = field(default_factory=dict)  # título -> segundos, só do dia

    @classmethod
    def load(cls) -> "State":
        state = _load(cls, STATE_FILE)
        state.per_video = state.per_video or {}
        state.roll_day()
        return state

    def save(self) -> None:
        _save(self, STATE_FILE)

    def roll_day(self) -> bool:
        """Zera se o dia mudou. True se zerou."""
        if self.day == today_iso():
            return False
        self.day, self.seconds, self.per_video = today_iso(), 0, {}
        return True

    def add_second(self, title: str) -> None:
        self.seconds += 1
        if title:
            self.per_video[title] = self.per_video.get(title, 0) + 1

    def top(self, n: int = 10) -> list[tuple[str, int]]:
        return sorted(self.per_video.items(), key=lambda kv: -kv[1])[:n]
