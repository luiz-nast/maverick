"""Tempo de tela em foco por site (Instagram, Pinterest...).

Um segundo conta quando o site está na aba visível da janela de navegador em foco
e o usuário está presente (mexeu em teclado/mouse há pouco ou há mídia tocando).

- "daily": N minutos por dia; aumentar vale amanhã, reduzir na hora.
- "cycle": A minutos livres, depois B minutos bloqueado (relógio), e recomeça. Uma
  mudança de A ou B vale a partir da próxima rodada.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlparse

from .store import Config, fmt


def site_for_url(url: str | None, domains) -> str | None:
    """Domínio com regra que corresponde à URL (subdomínios incluídos)."""
    host = (urlparse(url).hostname or "") if url else ""
    return next((d for d in domains if host == d or host.endswith("." + d)), None)


@dataclass
class SiteStatus:
    domain: str
    name: str
    mode: str
    blocked: bool
    used: int  # segundos em foco no período (dia ou rodada)
    limit: int  # segundos permitidos no período
    wait: int = 0  # segundos até liberar (ciclo bloqueado)

    @property
    def pill(self) -> str:
        return f"{self.name} {fmt(self.used)} / {fmt(self.limit)}"

    @property
    def summary(self) -> str:
        if self.mode == "daily":
            return (f"Esgotado hoje: {fmt(self.used)} em foco" if self.blocked
                    else f"Hoje: {fmt(self.used)} de {fmt(self.limit)} em foco")
        return (f"Bloqueado: libera em {fmt(self.wait)}" if self.blocked
                else f"Livre: {fmt(self.limit - self.used)} restantes nesta rodada")

    @property
    def block_message(self) -> str:
        if self.mode == "daily":
            return f"{self.limit // 60} min de {self.name} já usados hoje. Volta amanhã."
        return f"Pausa do {self.name}: libera em {fmt(self.wait)}."


def evaluate(cfg: Config, domain: str, st: dict, now: float, count: bool) -> SiteStatus:
    """Atualiza `st` (estado do site) e devolve o status. `count`: soma 1 s em foco
    se o site estiver liberado."""
    rule = cfg.sites[domain]
    st.setdefault("seconds", 0)
    if rule["mode"] == "daily":
        limit = cfg.site_limit(domain) * 60
        if count and st["seconds"] < limit:
            st["seconds"] += 1
        return SiteStatus(domain, rule["name"], "daily", st["seconds"] >= limit, st["seconds"], limit)

    if st.get("blocked_until", 0) > now:
        allow = st.get("round_allow", rule["allow_minutes"] * 60)
        return SiteStatus(domain, rule["name"], "cycle", True, allow, allow, math.ceil(st["blocked_until"] - now))
    if st.get("blocked_until") or "round_allow" not in st:  # bloqueio acabou ou primeira vez: nova rodada
        st.update(round_used=0, round_allow=rule["allow_minutes"] * 60, blocked_until=0)
    if count:
        st["round_used"] += 1
        st["seconds"] += 1
        if st["round_used"] >= st["round_allow"]:
            st["blocked_until"] = now + rule["block_minutes"] * 60
            return SiteStatus(domain, rule["name"], "cycle", True, st["round_used"], st["round_allow"],
                              rule["block_minutes"] * 60)
    return SiteStatus(domain, rule["name"], "cycle", False, st["round_used"], st["round_allow"])
