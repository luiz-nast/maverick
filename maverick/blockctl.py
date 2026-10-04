"""maverick-blockctl: aplica ou remove o bloqueio de sites no sistema (root).

Instalado em /usr/lib/maverick/maverick-blockctl e chamado via pkexec pela janela
e pelo `maverick block apply`. Cada domínio é validado antes de tocar em /etc.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import blocking as b


def write_atomic(path: Path, text: str, mode: int = 0o644) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply(domains: list[str]) -> list[str]:
    """Grava as três camadas. Retorna avisos não fatais."""
    warnings: list[str] = []
    hosts_text = b.HOSTS_FILE.read_text()
    old = b.hosts_domains(hosts_text)
    write_atomic(b.HOSTS_FILE, b.render_hosts(hosts_text, domains))

    # Firefox
    existing = None
    if b.FIREFOX_POLICY_FILE.exists():
        try:
            existing = json.loads(b.FIREFOX_POLICY_FILE.read_text())
        except ValueError:
            warnings.append(f"{b.FIREFOX_POLICY_FILE} não é JSON válido; Firefox não alterado")
            existing = False
    if existing is not False:
        old_ff = sorted(set(old) | b.firefox_policy_domains())
        data = b.merge_firefox_policy(existing, domains, old_ff)
        if data == {"policies": {}} and existing is None:
            pass  # nada a gravar e arquivo não existia
        elif data == {"policies": {}}:
            b.FIREFOX_POLICY_FILE.unlink(missing_ok=True)
        else:
            write_atomic(b.FIREFOX_POLICY_FILE, json.dumps(data, indent=2) + "\n")

    # Chrome / Chromium
    for path in b.CHROMIUM_POLICY_FILES:
        if domains:
            write_atomic(path, json.dumps({"URLBlocklist": domains}, indent=2) + "\n")
        else:
            path.unlink(missing_ok=True)

    subprocess.run(["resolvectl", "flush-caches"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maverick-blockctl", description="Bloqueio de sites do Maverick.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_apply = sub.add_parser("apply", help="substitui a lista bloqueada pelos domínios dados")
    p_apply.add_argument("domains", nargs="+")
    sub.add_parser("defaults", help="aplica a lista padrão de sites de jogos")
    sub.add_parser("reapply-or-defaults", help="reaplica a lista atual; padrão se não houver")
    sub.add_parser("clear", help="remove todo o bloqueio do Maverick")
    sub.add_parser("status", help="mostra o que está aplicado (não exige root)")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        st = b.status()
        print("hosts:  ", " ".join(st.hosts) or "-")
        print("firefox:", " ".join(sorted(st.firefox)) or "-")
        return 0

    if os.geteuid() != 0:
        print("maverick-blockctl: precisa de root (use pkexec ou sudo)", file=sys.stderr)
        return 1

    if args.cmd == "apply":
        domains = []
        for raw in args.domains:
            d = b.normalize_domain(raw)
            if not d:
                print(f"maverick-blockctl: domínio inválido: {raw!r}", file=sys.stderr)
                return 2
            domains.append(d)
        domains = list(dict.fromkeys(domains))
    elif args.cmd == "defaults":
        domains = b.default_domains()
    elif args.cmd == "reapply-or-defaults":
        domains = b.hosts_domains(b.HOSTS_FILE.read_text()) or b.default_domains()
    else:  # clear
        domains = []

    if len(domains) > b.MAX_DOMAINS:
        print(f"maverick-blockctl: máximo de {b.MAX_DOMAINS} domínios", file=sys.stderr)
        return 2

    for w in apply(domains):
        print(f"aviso: {w}", file=sys.stderr)
    print(f"{len(domains)} domínio(s) bloqueado(s)." if domains else "Bloqueio removido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
