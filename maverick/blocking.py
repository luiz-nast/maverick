"""Bloqueio de sites de jogos no sistema (leitura; a escrita fica em blockctl.py).

Três camadas, gravadas pelo helper root `maverick-blockctl`:

- /etc/hosts: bloco gerenciado com cada domínio (e www., m.) em 0.0.0.0 e ::. Vale
  para qualquer programa; o Firefox respeita mesmo com DNS sobre HTTPS
  (`network.trr.exclude-etc-hosts`, padrão true).
- /etc/firefox/policies/policies.json: `WebsiteFilter.Block` com `*://*.dominio/*`;
  cobre subdomínios e mostra a página de bloqueio. O snap lê /etc/firefox.
- /etc/opt/chrome e /etc/chromium policies/managed/maverick.json: `URLBlocklist`.
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
_SITE_OF = {d: name for name, domains in DEFAULT_SITES for d in domains}

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
_FIREFOX_PATTERN_RE = re.compile(r"\*://\*\.([^/]+)/\*")


def default_domains() -> list[str]:
    return list(_SITE_OF)


def group_by_site(domains: list[str]) -> list[tuple[str, list[str]]]:
    """[(nome do site, [domínios])] na ordem da lista; domínio avulso vira o próprio nome."""
    groups: dict[str, list[str]] = {}
    for d in domains:
        groups.setdefault(_SITE_OF.get(d, d), []).append(d)
    return list(groups.items())


def normalize_domain(raw: str) -> str | None:
    """'https://www.Poki.com/jogo?x=1' -> 'poki.com'. None se inválido."""
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", str(raw).strip().lower())
    s = re.split(r"[/?#]", s, maxsplit=1)[0].rsplit("@", 1)[-1].split(":", 1)[0].rstrip(".")
    s = re.sub(r"^(www|m)\.", "", s)
    return s if _DOMAIN_RE.match(s) else None


# --- /etc/hosts -----------------------------------------------------------
def _split_hosts(text: str) -> tuple[list[str], list[str]]:
    """(linhas fora do bloco do Maverick, linhas dentro)."""
    outside, inside, in_block = [], [], False
    for line in text.splitlines():
        s = line.strip()
        if s == BEGIN:
            in_block = True
        elif s == END and in_block:
            in_block = False
        else:
            (inside if in_block else outside).append(line)
    return outside, inside


def render_hosts(text: str, domains: list[str]) -> str:
    base = "\n".join(_split_hosts(text)[0]).rstrip("\n") + "\n"
    if not domains:
        return base
    lines = [BEGIN, f"{DOMAINS_TAG} {' '.join(domains)}"]
    lines += [f"{ip} {sub}{d}" for d in domains for sub in SUBDOMAINS for ip in ("0.0.0.0", "::")]
    return base + "\n" + "\n".join(lines + [END]) + "\n"


def hosts_domains(text: str) -> list[str]:
    """Domínios do bloco que de fato têm a linha 0.0.0.0 (detecta edição manual)."""
    inside = [line.strip() for line in _split_hosts(text)[1]]
    declared = next((s[len(DOMAINS_TAG):].split() for s in inside if s.startswith(DOMAINS_TAG)), [])
    mapped = {s.split()[1] for s in inside if s.startswith("0.0.0.0 ")}
    return [d for d in declared if d in mapped]


# --- Firefox --------------------------------------------------------------
def firefox_patterns(domains: list[str]) -> list[str]:
    return [f"*://*.{d}/*" for d in domains]


def merge_firefox_policy(existing: dict | None, new: list[str], old: list[str]) -> dict:
    """Troca os padrões do Maverick em WebsiteFilter.Block, preservando o resto."""
    data = existing if isinstance(existing, dict) else {}
    policies = data.setdefault("policies", {})
    wf = policies.pop("WebsiteFilter", None) or {}
    ours = set(firefox_patterns(old + new))
    block = [p for p in wf.pop("Block", []) if p not in ours] + firefox_patterns(new)
    if block:
        wf["Block"] = block
    if wf:
        policies["WebsiteFilter"] = wf
    return data


def firefox_policy_domains() -> set[str]:
    try:
        block = json.loads(FIREFOX_POLICY_FILE.read_text())["policies"]["WebsiteFilter"]["Block"]
        return {m.group(1) for p in block if (m := _FIREFOX_PATTERN_RE.fullmatch(p))}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


# --- status (sem root) ----------------------------------------------------
@dataclass
class BlockStatus:
    helper_installed: bool
    hosts: list[str]

    def missing(self, wanted: list[str]) -> list[str]:
        return [d for d in wanted if d not in self.hosts]

    def in_sync(self, wanted: list[str]) -> bool:
        return set(wanted) == set(self.hosts)

    def extra(self, wanted: list[str]) -> list[str]:
        return [d for d in self.hosts if d not in wanted]


def status() -> BlockStatus:
    try:
        hosts = hosts_domains(HOSTS_FILE.read_text())
    except OSError:
        hosts = []
    return BlockStatus(HELPER.exists(), hosts)
