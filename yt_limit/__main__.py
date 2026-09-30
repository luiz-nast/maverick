"""CLI: `python3 -m yt_limit [--limit N] [--status] [--reset] [--no-overlay] [--debug]`."""

from __future__ import annotations

import argparse
import logging
import sys

from .store import Config, State, fmt


def check() -> int:
    """Mostra o que o app enxerga neste instante."""
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
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yt-limit",
        description="Limita o tempo diário de YouTube contando só o tempo com vídeo tocando.",
    )
    parser.add_argument("--limit", type=int, metavar="MIN", help="define o limite diário em minutos e sai")
    parser.add_argument("--status", action="store_true", help="mostra o uso de hoje e sai")
    parser.add_argument("--reset", action="store_true", help="zera o contador de hoje e sai")
    parser.add_argument("--no-overlay", action="store_true", help="roda sem janelas (só conta e pausa)")
    parser.add_argument("--debug", action="store_true", help="loga cada player detectado")
    parser.add_argument("--check", action="store_true", help="diagnostica a detecção agora e sai")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

    if args.limit is not None:
        if args.limit <= 0:
            parser.error("--limit precisa ser maior que zero")
        cfg = Config.load()
        cfg.limit_minutes = args.limit
        cfg.save()
        print(f"Limite diário: {args.limit} min. Reinicie o serviço para aplicar.")
        return 0

    if args.reset:
        state = State.load()
        state.seconds = 0
        state.per_video = {}
        state.save()
        print("Contador de hoje zerado.")
        return 0

    if args.status:
        cfg, state = Config.load(), State.load()
        print(f"Hoje ({state.day}): {fmt(state.seconds)} de {fmt(cfg.limit_minutes * 60)}")
        for title, secs in sorted((state.per_video or {}).items(), key=lambda kv: -kv[1])[:10]:
            print(f"  {fmt(secs)}  {title}")
        return 0

    if args.check:
        return check()

    from .app import App

    App(show_overlay=not args.no_overlay, debug=args.debug).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
