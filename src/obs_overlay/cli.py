"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from . import paths
from .constants import APP_DESCRIPTION, APP_NAME, APP_VERSION

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="obs-overlay",
        description=f"{APP_NAME} — {APP_DESCRIPTION}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  obs-overlay                          start with the last used profile\n"
            "  obs-overlay --profile Stream         start with a named profile\n"
            "  obs-overlay --demo                   run with the built-in test pattern\n"
            "  obs-overlay --list-senders           print the active Spout senders and exit\n"
            "  obs-overlay --log-level DEBUG        verbose logging\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument(
        "-p", "--profile", metavar="NAME", help="Profile to load instead of the last used one."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Force the built-in test pattern source, ignoring the profile's setting.",
    )
    parser.add_argument(
        "--sender",
        metavar="NAME",
        help="Override the Spout sender name for this run.",
    )
    parser.add_argument(
        "--monitor",
        type=int,
        metavar="INDEX",
        help="Place the overlay on this monitor (0 is the first).",
    )
    parser.add_argument("--edit", action="store_true", help="Start in layout-edit mode.")
    parser.add_argument(
        "--no-panel", action="store_true", help="Do not open the control panel at startup."
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: the value stored in settings).",
    )
    parser.add_argument(
        "--data-dir",
        metavar="PATH",
        help="Use this directory for profiles and logs instead of the default.",
    )
    parser.add_argument(
        "--list-senders",
        action="store_true",
        help="Print the Spout senders currently publishing, then exit.",
    )
    parser.add_argument(
        "--list-profiles", action="store_true", help="Print the stored profiles, then exit."
    )
    return parser


def _list_senders() -> int:
    from .sources.registry import available_sender_names, spout_available

    if not spout_available():
        print(
            "SpoutGL is not available. It is Windows-only; install it with:\n"
            "    pip install SpoutGL",
            file=sys.stderr,
        )
        return 2
    names = available_sender_names()
    if not names:
        print("No Spout senders are currently publishing.")
        print("In OBS, add the 'Spout2 Output' filter to a scene or source.")
        return 1
    for name in names:
        print(name)
    return 0


def _list_profiles() -> int:
    from .config.store import ConfigStore

    store = ConfigStore()
    names = store.list_profiles()
    if not names:
        print("No profiles stored yet.")
        return 1
    settings = store.load_settings()
    for name in names:
        marker = "*" if name == settings.active_profile else " "
        print(f"{marker} {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, configure logging and run the GUI."""
    args = build_parser().parse_args(argv)

    if args.data_dir:
        import os

        os.environ["OBS_OVERLAY_DATA_DIR"] = args.data_dir

    # These two need no GUI, so handle them before Qt is touched.
    if args.list_senders:
        return _list_senders()
    if args.list_profiles:
        return _list_profiles()

    from .config.store import ConfigStore
    from .logging_setup import install_excepthook, setup_logging

    store = ConfigStore()
    store.ensure_dirs()
    settings = store.load_settings()
    level = args.log_level or settings.log_level
    log_path = setup_logging(level)
    install_excepthook()

    logger.info("%s %s starting (log: %s)", APP_NAME, APP_VERSION, log_path)
    logger.info("Data directory: %s", paths.data_dir())

    from .app import OverlayApplication, create_application

    app = create_application([])
    controller = OverlayApplication(app, store=store, profile_name=args.profile)
    _apply_overrides(controller, args)
    controller.start()

    if args.edit:
        controller.set_edit_mode(True)

    return app.exec()


def _apply_overrides(controller: object, args: argparse.Namespace) -> None:
    """Apply one-run command-line overrides to the loaded profile.

    These are deliberately not saved: a ``--demo`` run should not silently
    rewrite the user's profile.
    """
    from .config.models import SourceKind

    profile = getattr(controller, "_profile", None)
    if profile is None:  # pragma: no cover - defensive
        return

    if args.demo:
        profile.source.kind = SourceKind.DEMO
        logger.info("Override: using the built-in test pattern.")
    if args.sender:
        profile.source.sender_name = args.sender
        logger.info("Override: sender name %r", args.sender)
    if args.monitor is not None:
        from .config.models import GeometryMode

        profile.display.geometry_mode = GeometryMode.MONITOR
        profile.display.monitor_index = max(0, args.monitor)
        logger.info("Override: monitor %d", profile.display.monitor_index)
    if args.no_panel:
        profile.behavior.show_panel_on_start = False
