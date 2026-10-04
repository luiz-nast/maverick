"""Persistência: config em ~/.config/maverick, estado diário em ~/.local/share/maverick."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .blocking import default_domains, normalize_domain

APP_ID = "io.github.luiz_nast.Maverick"
APP_NAME = "Maverick"

_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
CONFIG_DIR = _CONFIG_HOME / "maverick"
DATA_DIR = _DATA_HOME / "maverick"
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = DATA_DIR / "state.json"

# Nome antigo do projeto. Os dados são movidos uma única vez.
_LEGACY_DIRS = ((_CONFIG_HOME / "yt-limit", CONFIG_DIR), (_DATA_HOME / "yt-limit", DATA_DIR))


def migrate_legacy() -> None:
    for old, new in _LEGACY_DIRS:
        if old.is_dir() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)


def fmt(seconds: int) -> str:
    """Formata segundos como MM:SS."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


@dataclass
class Config:
    limit_minutes: int = 30
    # Quantos segundos a pílula continua na tela depois que o vídeo para.
    hide_after_seconds: int = 2
    # Avisar quando faltarem N minutos.
    warn_minutes_left: int = 5
    # Janela privada esconde título e URL no MPRIS. Se a árvore de acessibilidade
    # não puder confirmar, contar essa mídia como YouTube mesmo assim.
    count_private_media: bool = True
    # Domínios bloqueados no sistema (aplicados via maverick-blockctl).
    blocked_sites: list[str] = field(default_factory=default_domains)

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_FILE.read_text())
            cfg = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            cfg = cls()
        cfg.blocked_sites = list(dict.fromkeys(d for d in map(normalize_domain, cfg.blocked_sites) if d))
        return cfg

    def save(self) -> None:
        _write_json(CONFIG_FILE, asdict(self))


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

    def top(self, n: int = 10) -> list[tuple[str, int]]:
        return sorted((self.per_video or {}).items(), key=lambda kv: -kv[1])[:n]

    def save(self) -> None:
        _write_json(STATE_FILE, asdict(self))
