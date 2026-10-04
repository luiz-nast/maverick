"""Bloqueio de sites de jogos no sistema.

Três camadas, todas gravadas pelo helper root `maverick-blockctl`:

- /etc/hosts: bloco gerenciado apontando cada domínio (e www., m.) para 0.0.0.0 e ::.
  Vale para qualquer navegador e programa. O Firefox respeita /etc/hosts mesmo com
  DNS sobre HTTPS (`network.trr.exclude-etc-hosts`, padrão true).
- /etc/firefox/policies/policies.json: `WebsiteFilter.Block` com `*://*.dominio/*`.
  Cobre todos os subdomínios e mostra a página de bloqueio do Firefox. O snap do
  Firefox lê /etc/firefox (plug `etc-firefox`). Exige reiniciar o Firefox.
- /etc/opt/chrome e /etc/chromium policies/managed/maverick.json: `URLBlocklist`.

Este módulo só lê o sistema; a escrita fica em blockctl.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SITES: list[tuple[str, tuple[str, ...]]] = [
    ("Click Jogos", ("clickjogos.com.br",)),
    ("Friv", ("friv.com",)),
    ("Poki", ("poki.com", "poki.com.br")),
    ("CrazyGames", ("crazygames.com", "crazygames.com.br")),
    ("Jogos 360", ("jogos360.com.br",)),
    ("1001 Jogos", ("1001jogos.com.br",)),
    ("Y8", ("y8.com",)),
    ("Miniclip", ("miniclip.com",)),
    ("Coolmath Games", ("coolmathgames.com",)),
    ("Kizi", ("kizi.com",)),
]

HOSTS_FILE = Path("/etc/hosts")
FIREFOX_POLICY_FILE = Path("/etc/firefox/policies/policies.json")
CHROMIUM_POLICY_FILES = (
    Path("/etc/opt/chrome/policies/managed/maverick.json"),
    Path("/etc/chromium/policies/managed/maverick.json"),
)
HELPER = Path("/usr/lib/maverick/maverick-blockctl")

BEGIN = "# >>> maverick: sites bloqueados (gerado, não edite) >>>"
END = "# <<< maverick <<<"
DOMAINS_TAG = "# maverick-domains:"
SUBDOMAINS = ("", "www.", "m.")
MAX_DOMAINS = 500

_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def default_domains() -> list[str]:
    return [d for _, domains in DEFAULT_SITES for d in domains]


def site_name(domain: str) -> str:
    for name, domains in DEFAULT_SITES:
        if domain in domains:
            return name
    return domain


def group_by_site(domains: list[str]) -> list[tuple[str, list[str]]]:
    """[(nome, [domínios])] preservando a ordem da lista."""
    groups: dict[str, list[str]] = {}
    for d in domains:
        groups.setdefault(site_name(d), []).append(d)
    return list(groups.items())


def normalize_domain(raw: str) -> str | None:
    """Aceita 'https://www.Poki.com/jogo?x=1' e devolve 'poki.com'. None se inválido."""
    s = str(raw).strip().lower()
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s)
    s = re.split(r"[/?#]", s, maxsplit=1)[0]
    s = s.rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".")
    for prefix in ("www.", "m."):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s if _DOMAIN_RE.match(s) else None


# --- /etc/hosts -----------------------------------------------------------
def strip_block(text: str) -> str:
    out, inside = [], False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            inside = True
            continue
        if inside:
            if line.strip() == END:
                inside = False
            continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


def render_hosts(text: str, domains: list[str]) -> str:
    base = strip_block(text)
    if not domains:
        return base
    lines = [BEGIN, f"{DOMAINS_TAG} {' '.join(domains)}"]
    for d in domains:
        for sub in SUBDOMAINS:
            lines.append(f"0.0.0.0 {sub}{d}")
            lines.append(f":: {sub}{d}")
    lines.append(END)
    return base + "\n" + "\n".join(lines) + "\n"


def hosts_domains(text: str) -> list[str]:
    """Domínios do bloco gerenciado que de fato têm a linha 0.0.0.0."""
    declared: list[str] = []
    mapped: set[str] = set()
    inside = False
    for line in text.splitlines():
        s = line.strip()
        if s == BEGIN:
            inside = True
        elif s == END:
            inside = False
        elif inside and s.startswith(DOMAINS_TAG):
            declared = s[len(DOMAINS_TAG):].split()
        elif inside and s.startswith("0.0.0.0 "):
            mapped.add(s.split()[1])
    return [d for d in declared if d in mapped]


# --- políticas dos navegadores --------------------------------------------
def firefox_patterns(domains: list[str]) -> list[str]:
    return [f"*://*.{d}/*" for d in domains]


def merge_firefox_policy(existing: dict | None, new: list[str], old: list[str]) -> dict:
    """Troca os padrões do Maverick em WebsiteFilter.Block preservando o resto."""
    data = existing if isinstance(existing, dict) else {}
    policies = data.setdefault("policies", {})
    wf = policies.get("WebsiteFilter") or {}
    ours = set(firefox_patterns(old)) | set(firefox_patterns(new))
    block = [p for p in wf.get("Block", []) if p not in ours] + firefox_patterns(new)
    if block:
        wf["Block"] = block
    else:
        wf.pop("Block", None)
    if wf:
        policies["WebsiteFilter"] = wf
    else:
        policies.pop("WebsiteFilter", None)
    return data


def firefox_policy_domains() -> set[str]:
    try:
        data = json.loads(FIREFOX_POLICY_FILE.read_text())
        block = data["policies"]["WebsiteFilter"]["Block"]
    except (OSError, ValueError, KeyError, TypeError):
        return set()
    out = set()
    for p in block:
        m = re.fullmatch(r"\*://\*\.([^/]+)/\*", p)
        if m:
            out.add(m.group(1))
    return out


# --- status (sem root) ----------------------------------------------------
@dataclass
class BlockStatus:
    helper_installed: bool
    hosts: list[str]
    firefox: set[str]

    def missing(self, wanted: list[str]) -> list[str]:
        applied = set(self.hosts)
        return [d for d in wanted if d not in applied]

    def extra(self, wanted: list[str]) -> list[str]:
        w = set(wanted)
        return [d for d in self.hosts if d not in w]

    def in_sync(self, wanted: list[str]) -> bool:
        return not self.missing(wanted) and not self.extra(wanted)


def status() -> BlockStatus:
    try:
        hosts = hosts_domains(HOSTS_FILE.read_text())
    except OSError:
        hosts = []
    return BlockStatus(HELPER.exists(), hosts, firefox_policy_domains())
