"""Ponto de entrada. `maverick` sem argumentos abre a janela; o resto é CLI."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys

from . import __version__, blocking
from .store import Config, State, fmt, migrate_legacy


def check() -> int:
    """Mostra o que o daemon enxerga neste instante."""
    from .a11y import A11y
    from .mpris import Mpris

    players = Mpris().players()
    print(f"Players MPRIS: {len(players)}")
    for p in players:
        tag = "YouTube" if p.is_youtube else ("privado/sem metadados" if p.metadata_hidden else "outro")
        print(f"  {p.status:8} {tag:24} {p.bus_name}")
        print(f"           título: {p.title[:70]!r}")
        print(f"           url: {p.url or '-'}  capa: {p.art_url[:60] or '-'}")

    a11y = A11y()
    browsers = a11y.browsers_on_bus()
    if a11y.conn is None:
        print("Acessibilidade: barramento AT-SPI indisponível")
    elif not browsers:
        print("Acessibilidade: barramento ok, nenhum navegador registrado")
        print("  Mídia em janela privada será contada pelo fallback (count_private_media).")
        print("  Para detecção exata em janela privada:")
        print("    gsettings set org.gnome.desktop.interface toolkit-accessibility true")
        print("  e reabra o navegador.")
    else:
        verdict = a11y.browser_has_youtube()
        print(f"Acessibilidade: navegadores no barramento: {', '.join(browsers)}")
        print(f"  Aba do YouTube encontrada: {'sim' if verdict else 'não'}")

    print()
    return block_list()


def block_list() -> int:
    cfg, st = Config.load(), blocking.status()
    applied = set(st.hosts)
    print(f"Sites bloqueados ({len(cfg.blocked_sites)} domínios):")
    for name, domains in blocking.group_by_site(cfg.blocked_sites):
        marks = "  ".join(f"{'✓' if d in applied else '✗'} {d}" for d in domains)
        print(f"  {name:16} {marks}")
    extra = st.extra(cfg.blocked_sites)
    if extra:
        print(f"  Aplicados no sistema mas fora da lista: {', '.join(extra)}")
    if not st.helper_installed:
        print("Bloqueio no sistema indisponível: instale o pacote .deb (packaging/install-system.sh).")
    elif not st.in_sync(cfg.blocked_sites):
        print("Há mudanças pendentes: rode `maverick block apply`.")
    else:
        print("Bloqueio ativo e em dia.")
    return 0


def block_apply() -> int:
    cfg = Config.load()
    if not blocking.HELPER.exists():
        print("O bloqueio de sites precisa do pacote .deb instalado (packaging/install-system.sh).", file=sys.stderr)
        return 1
    args = ["apply", *cfg.blocked_sites] if cfg.blocked_sites else ["clear"]
    return subprocess.run(["pkexec", str(blocking.HELPER), *args]).returncode


def main(argv: list[str] | None = None) -> int:
    migrate_legacy()
    parser = argparse.ArgumentParser(
        prog="maverick",
        description="Limite diário de YouTube (só conta vídeo tocando) e bloqueio de sites de jogos.",
    )
    parser.add_argument("--version", action="version", version=f"maverick {__version__}")
    sub = parser.add_subparsers(dest="cmd", metavar="COMANDO")
    sub.add_parser("gui", help="abre a janela (padrão sem comando)")
    p_daemon = sub.add_parser("daemon", help="contador em segundo plano (usado pelo serviço systemd)")
    p_daemon.add_argument("--no-overlay", action="store_true", help="sem janelas: só conta e pausa")
    p_daemon.add_argument("--debug", action="store_true", help="loga cada player a cada segundo")
    sub.add_parser("status", help="tempo de hoje e vídeos mais assistidos")
    sub.add_parser("check", help="diagnóstico de detecção e de bloqueio")
    p_limit = sub.add_parser("limit", help="define o limite diário em minutos")
    p_limit.add_argument("minutes", type=int)
    sub.add_parser("reset", help="zera o contador de hoje")
    p_block = sub.add_parser("block", help="sites bloqueados")
    bsub = p_block.add_subparsers(dest="block_cmd", required=True, metavar="AÇÃO")
    bsub.add_parser("list", help="lista os sites e se estão aplicados")
    p_add = bsub.add_parser("add", help="adiciona domínios à lista")
    p_add.add_argument("domains", nargs="+")
    p_rm = bsub.add_parser("remove", help="remove domínios da lista")
    p_rm.add_argument("domains", nargs="+")
    bsub.add_parser("apply", help="aplica a lista no sistema (pede senha de admin)")
    args = parser.parse_args(argv)

    if args.cmd in (None, "gui"):
        from .gui import run_gui

        return run_gui()

    if args.cmd == "daemon":
        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format="%(asctime)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
            stream=sys.stdout,
        )
        from .app import App

        App(show_overlay=not args.no_overlay, debug=args.debug).run()
        return 0

    if args.cmd == "status":
        cfg, state = Config.load(), State.load()
        print(f"Hoje ({state.day}): {fmt(state.seconds)} de {fmt(cfg.limit_minutes * 60)}")
        for title, secs in state.top(10):
            print(f"  {fmt(secs)}  {title}")
        return 0

    if args.cmd == "check":
        return check()

    if args.cmd == "limit":
        if args.minutes <= 0:
            parser.error("o limite precisa ser maior que zero")
        cfg = Config.load()
        cfg.limit_minutes = args.minutes
        cfg.save()
        print(f"Limite diário: {args.minutes} min (aplicado na hora).")
        return 0

    if args.cmd == "reset":
        state = State.load()
        state.seconds = 0
        state.per_video = {}
        state.save()
        print("Contador de hoje zerado.")
        return 0

    if args.cmd == "block":
        if args.block_cmd == "list":
            return block_list()
        if args.block_cmd == "apply":
            return block_apply()
        cfg = Config.load()
        for raw in args.domains:
            d = blocking.normalize_domain(raw)
            if not d:
                print(f"Domínio inválido: {raw}", file=sys.stderr)
                return 2
            if args.block_cmd == "add" and d not in cfg.blocked_sites:
                cfg.blocked_sites.append(d)
            elif args.block_cmd == "remove" and d in cfg.blocked_sites:
                cfg.blocked_sites.remove(d)
        cfg.save()
        print("Lista salva. Rode `maverick block apply` para aplicar no sistema.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
