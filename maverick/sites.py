"""Tempo de tela em foco por site (Instagram, Pinterest...), em ciclos.

Um segundo conta quando o site está na aba visível da janela de navegador em foco
e o usuário está presente (mexeu em teclado/mouse há pouco ou há mídia tocando).
Cada site tem `allow_minutes` livres em foco, depois `block_minutes` bloqueado no
relógio, e recomeça. Mudar os valores vale a partir da próxima rodada.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .store import Config, fmt


def site_for_url(url: str | None, domains) -> str | None:
    """Domínio com regra que corresponde à URL (subdomínios incluídos)."""
    host = (urlparse(url).hostname or "") if url else ""
    return next((d for d in domains if host == d or host.endswith("." + d)), None)


def site_for_title(title: str, rules: dict) -> str | None:
    """Plano B sem URL: o nome do site como palavra no título da aba ("(3) Instagram",
    "Pin em ... | Pinterest")."""
    return next((d for d, r in rules.items()
                 if re.search(rf"(^|\W){re.escape(r['name'].lower())}(\W|$)", title.lower())), None)


@dataclass
class SiteStatus:
    name: str
    blocked: bool
    used: int  # segundos em foco na rodada
    allow: int  # segundos livres da rodada
    wait: int = 0  # segundos até liberar

    @property
    def pill(self) -> str:
        return f"{self.name} {fmt(self.used)} / {fmt(self.allow)}"

    @property
    def summary(self) -> str:
        return (f"Bloqueado: libera em {fmt(self.wait)}" if self.blocked
                else f"Livre: {fmt(self.allow - self.used)} restantes nesta rodada")

    @property
    def block_message(self) -> str:
        return f"Pausa do {self.name}: libera em {fmt(self.wait)}."


def evaluate(cfg: Config, domain: str, st: dict, now: float, count: bool) -> SiteStatus:
    """Atualiza `st` (estado do site) e devolve o status. `count`: soma 1 s em foco se
    o site estiver liberado; ao fim da rodada começa o bloqueio."""
    rule = cfg.sites[domain]
    if st.get("blocked_until", 0) > now:
        allow = st.get("round_allow", rule["allow_minutes"] * 60)
        return SiteStatus(rule["name"], True, allow, allow, math.ceil(st["blocked_until"] - now))
    if st.get("blocked_until") or "round_allow" not in st:  # bloqueio acabou ou primeira vez: nova rodada
        st.update(round_used=0, round_allow=rule["allow_minutes"] * 60, blocked_until=0)
    if count:
        st["round_used"] += 1
        st["seconds"] = st.get("seconds", 0) + 1
        if st["round_used"] >= st["round_allow"]:
            st["blocked_until"] = now + rule["block_minutes"] * 60
            return SiteStatus(rule["name"], True, st["round_used"], st["round_allow"], rule["block_minutes"] * 60)
    return SiteStatus(rule["name"], False, st["round_used"], st["round_allow"])
