"""maverick-blockctl: aplica ou remove o bloqueio de sites no sistema (root).

Instalado em /usr/lib/maverick/maverick-blockctl; chamado via pkexec pela janela,
pelo `maverick block apply` e pelos scripts do pacote. Valida cada domínio antes
de tocar em /etc.
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


def _apply_firefox(domains: list[str], old: list[str]) -> str | None:
    """Atualiza a política do Firefox. Devolve um aviso se não puder."""
    f = b.FIREFOX_POLICY_FILE
    try:
        existing = json.loads(f.read_text()) if f.exists() else None
    except ValueError:
        return f"{f} não é JSON válido; Firefox não alterado"
    data = b.merge_firefox_policy(existing, domains, sorted(set(old) | b.firefox_policy_domains()))
    if data == {"policies": {}}:
        f.unlink(missing_ok=True)
    else:
        write_atomic(f, json.dumps(data, indent=2) + "\n")
    return None


def apply(domains: list[str]) -> str | None:
    """Grava as três camadas. Devolve um aviso não fatal, se houver."""
    hosts = b.HOSTS_FILE.read_text()
    write_atomic(b.HOSTS_FILE, b.render_hosts(hosts, domains))
    warning = _apply_firefox(domains, b.hosts_domains(hosts))
    for path in b.CHROMIUM_POLICY_FILES:
        if domains:
            write_atomic(path, json.dumps({"URLBlocklist": domains}, indent=2) + "\n")
        else:
            path.unlink(missing_ok=True)
    subprocess.run(["resolvectl", "flush-caches"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return warning


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maverick-blockctl", description="Bloqueio de sites do Maverick.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("apply", help="substitui a lista bloqueada pelos domínios dados").add_argument("domains", nargs="+")
    sub.add_parser("reapply-or-defaults", help="reaplica a lista atual; a padrão se não houver")
    sub.add_parser("clear", help="remove todo o bloqueio do Maverick")
    args = parser.parse_args(argv)

    if os.geteuid() != 0:
        print("maverick-blockctl: precisa de root (use pkexec ou sudo)", file=sys.stderr)
        return 1
    if args.cmd == "apply":
        domains = [b.normalize_domain(raw) for raw in args.domains]
        if bad := [raw for raw, d in zip(args.domains, domains) if not d]:
            print(f"maverick-blockctl: domínio inválido: {bad[0]!r}", file=sys.stderr)
            return 2
        domains = list(dict.fromkeys(domains))
    elif args.cmd == "reapply-or-defaults":
        domains = b.hosts_domains(b.HOSTS_FILE.read_text()) or b.default_domains()
    else:
        domains = []
    if len(domains) > b.MAX_DOMAINS:
        print(f"maverick-blockctl: máximo de {b.MAX_DOMAINS} domínios", file=sys.stderr)
        return 2

    if warning := apply(domains):
        print(f"aviso: {warning}", file=sys.stderr)
    print(f"{len(domains)} domínio(s) bloqueado(s)." if domains else "Bloqueio removido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
