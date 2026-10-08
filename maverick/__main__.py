"""Ponto de entrada. `maverick` sem argumentos abre a janela; o resto é CLI."""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys

from . import __version__, blocking
from .store import Config, State, fmt, today_iso

NEEDS_PACKAGE = "O bloqueio de sites precisa do pacote .deb instalado (packaging/install-system.sh)."


def cmd_gui(_args) -> int:
    from .gui import run_gui

    return run_gui()


def cmd_daemon(args) -> int:
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    from .app import App

    App(show_overlay=not args.no_overlay, debug=args.debug).run()
    return 0


def cmd_status(_args) -> int:
    import time

    from .sites import evaluate

    cfg, state = Config.load(), State.load()
    print(f"YouTube hoje ({state.day}): {fmt(state.seconds)} de {fmt(cfg.effective_limit() * 60)}")
    if cfg.limit_minutes != cfg.effective_limit():
        print(f"A partir de amanhã: {cfg.limit_minutes} min")
    for title, secs in state.top(10):
        print(f"  {fmt(secs)}  {title}")
    for domain in cfg.sites:
        status = evaluate(cfg, domain, state.sites.get(domain, {}), time.time(), count=False)
        print(f"{status.name}: {status.summary}")
    return 0


def cmd_check(args) -> int:
    """O que o daemon enxerga agora: players, acessibilidade e bloqueio."""
    from .a11y import A11y, private_media_verdict
    from .mpris import Mpris

    players = Mpris().players()
    print(f"Players MPRIS: {len(players)}")
    for p in players:
        kind = "YouTube" if p.is_youtube else "privado/sem metadados" if p.metadata_hidden else "outro"
        print(f"  {p.status:8} {kind:22} {p.bus_name}\n           título: {p.title[:70]!r}\n"
              f"           url: {p.url or '-'}  capa: {p.art_url[:60] or '-'}")

    a11y = A11y()
    windows = a11y.windows()
    if windows is None:
        mode = "contada como YouTube" if Config.load().count_private_media else "ignorada"
        bus = "nenhum navegador no barramento" if a11y.conn else "barramento indisponível"
        print(f"Acessibilidade: {bus}. Mídia em janela privada: {mode}.")
        print("  Detecção exata: Maverick > Janela anônima > Ativar, depois reabra o navegador.")
    else:
        print("Acessibilidade: detecção exata")
        for w in windows:
            fresh = "em dia" if w.tabs_fresh else "desatualizada"
            print(f"  Janela {'privada' if w.private else 'normal'}: "
                  f"{w.selected_title[:70] or '(nova aba)'}  [lista de abas {fresh}]")
            for t in w.tabs:
                flags = [f for f, on in (("selecionada", t.selected), (f"som:{t.audio}", t.audio)) if on]
                print(f"    [{' '.join(flags) or '-'}] {t.title[:66]}")
        verdict = "YouTube" if private_media_verdict(windows) else "outro site"
        print(f"  Mídia de janela privada agora seria: {verdict}")
        print(f"  Aba visível da janela em foco: {a11y.focused_url() or 'nenhuma janela de navegador em foco'}")
    print()
    return cmd_block_list(args)


def cmd_limit(args) -> int:
    cfg = Config.load()
    now = cfg.set_limit(args.minutes)
    cfg.save()
    print(f"Limite diário: {args.minutes} min, já vale hoje." if now else
          f"Limite diário: {args.minutes} min a partir de amanhã. Hoje continua {cfg.effective_limit()} min.")
    return 0


def cmd_reset(_args) -> int:
    State(day=today_iso()).save()  # o daemon percebe a mudança e recarrega
    print("Contador de hoje zerado.")
    return 0


def cmd_block_list(_args) -> int:
    cfg, st = Config.load(), blocking.status()
    print(f"Sites bloqueados ({len(cfg.blocked_sites)} domínios):")
    for name, domains in blocking.group_by_site(cfg.blocked_sites):
        print(f"  {name:16} " + "  ".join(f"{'✓' if d in st.hosts else '✗'} {d}" for d in domains))
    if extra := st.extra(cfg.blocked_sites):
        print(f"  Aplicados no sistema mas fora da lista: {', '.join(extra)}")
    print(NEEDS_PACKAGE if not st.helper_installed else
          "Bloqueio ativo e em dia." if st.in_sync(cfg.blocked_sites) else
          "Há mudanças pendentes: rode `maverick block apply`.")
    return 0


def cmd_block_edit(args) -> int:
    domains = [blocking.normalize_domain(raw) for raw in args.domains]
    if bad := [raw for raw, d in zip(args.domains, domains) if not d]:
        print(f"Domínio inválido: {bad[0]}", file=sys.stderr)
        return 2
    cfg = Config.load()
    if args.action == "add":
        cfg.blocked_sites += [d for d in dict.fromkeys(domains) if d not in cfg.blocked_sites]
    else:
        cfg.blocked_sites = [d for d in cfg.blocked_sites if d not in domains]
    cfg.save()
    print("Lista salva. Rode `maverick block apply` para aplicar no sistema.")
    return 0


def cmd_block_apply(_args) -> int:
    if not blocking.HELPER.exists():
        print(NEEDS_PACKAGE, file=sys.stderr)
        return 1
    domains = Config.load().blocked_sites
    return subprocess.run(["pkexec", str(blocking.HELPER), *(["apply", *domains] if domains else ["clear"])]).returncode


def _positive(value: str) -> int:
    if (n := int(value)) <= 0:
        raise argparse.ArgumentTypeError("precisa ser maior que zero")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="maverick", description="Limite diário de YouTube (só conta vídeo tocando) e bloqueio de sites de jogos.")
    parser.add_argument("--version", action="version", version=f"maverick {__version__}")
    parser.set_defaults(run=cmd_gui)
    sub = parser.add_subparsers(metavar="COMANDO")
    sub.add_parser("gui", help="abre a janela (padrão sem comando)").set_defaults(run=cmd_gui)
    daemon = sub.add_parser("daemon", help="contador em segundo plano (usado pelo serviço systemd)")
    daemon.add_argument("--no-overlay", action="store_true", help="sem janelas: só conta e pausa")
    daemon.add_argument("--debug", action="store_true", help="loga cada player a cada segundo")
    daemon.set_defaults(run=cmd_daemon)
    sub.add_parser("status", help="tempo de hoje e vídeos mais assistidos").set_defaults(run=cmd_status)
    sub.add_parser("check", help="diagnóstico de detecção e de bloqueio").set_defaults(run=cmd_check)
    limit = sub.add_parser("limit", help="limite diário em minutos (reduzir vale hoje, aumentar amanhã)")
    limit.add_argument("minutes", type=_positive)
    limit.set_defaults(run=cmd_limit)
    sub.add_parser("reset", help="zera o contador de hoje").set_defaults(run=cmd_reset)

    block = sub.add_parser("block", help="sites bloqueados").add_subparsers(metavar="AÇÃO", required=True)
    block.add_parser("list", help="lista os sites e se estão aplicados").set_defaults(run=cmd_block_list)
    for action, help_text in (("add", "adiciona domínios à lista"), ("remove", "remove domínios da lista")):
        edit = block.add_parser(action, help=help_text)
        edit.add_argument("domains", nargs="+")
        edit.set_defaults(run=cmd_block_edit, action=action)
    block.add_parser("apply", help="aplica a lista no sistema (pede senha de admin)").set_defaults(run=cmd_block_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
