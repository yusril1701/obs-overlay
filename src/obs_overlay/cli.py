"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import sys

from . import paths
from .config.models import SourceKind
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
            "  obs-overlay --source ndi             receive from the network\n"
            "  obs-overlay --image logo.png         show an image file\n"
            "  obs-overlay --source screen --capture-monitor 1\n"
            "  obs-overlay --list-senders           print the active Spout senders and exit\n"
            "  obs-overlay --list-senders --source screen   list the connected monitors\n"
            "  obs-overlay --log-level DEBUG        verbose logging\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument(
        "-p", "--profile", metavar="NAME", help="Profile to load instead of the last used one."
    )
    parser.add_argument(
        "--source",
        metavar="KIND",
        choices=[kind.value for kind in SourceKind],
        help="Force a source for this run: " + ", ".join(kind.value for kind in SourceKind) + ".",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Shorthand for --source demo.",
    )
    parser.add_argument(
        "--sender",
        metavar="NAME",
        help="Override the sender name for this run (Spout, or NDI with --source ndi).",
    )
    parser.add_argument(
        "--image",
        metavar="PATH",
        help="Image file to show. Implies --source image unless --source says otherwise.",
    )
    parser.add_argument(
        "--capture-monitor",
        type=int,
        metavar="INDEX",
        help="Monitor to capture with --source screen (0 is the first).",
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
        help="Print what the source could connect to, then exit. Defaults to Spout; "
        "use with --source ndi or --source screen for those.",
    )
    parser.add_argument(
        "--list-profiles", action="store_true", help="Print the stored profiles, then exit."
    )
    return parser


def _list_senders(kind: SourceKind) -> int:
    """Print whatever the given source kind could connect to."""
    from .sources.registry import available_sender_names, kind_available, unavailable_reason

    if not kind_available(kind):
        print(unavailable_reason(kind), file=sys.stderr)
        return 2

    # Enumerating monitors goes through Qt, which needs a live application
    # object. The binding below is load-bearing: PyQt destroys the C++
    # application the moment its Python wrapper is collected, and a destroyed
    # application reports no screens at all. So it is created here, held across
    # the scan, and only then released.
    app = None
    if kind is SourceKind.SCREEN:
        from PyQt6.QtGui import QGuiApplication

        app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])

    names = available_sender_names(kind)
    del app  # the scan is done; nothing below needs Qt
    if not names:
        if kind is SourceKind.SPOUT:
            print("No Spout senders are currently publishing.")
            print("In OBS, add the 'Spout Filter' to a scene or source.")
        elif kind is SourceKind.NDI:
            print("No NDI sources found on the network.")
            print("Check that the sender is reachable and mDNS is not blocked.")
        else:
            print(f"Nothing to list for source kind {kind.value!r}.")
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
        return _list_senders(_selected_kind(args) or SourceKind.SPOUT)
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


def _selected_kind(args: argparse.Namespace) -> SourceKind | None:
    """The source kind the command line asks for, if any.

    ``--demo`` is a shorthand for ``--source demo``, and naming an image file
    implies the image source unless ``--source`` says otherwise.
    """
    if args.source:
        return SourceKind(args.source)
    if args.demo:
        return SourceKind.DEMO
    if args.image:
        return SourceKind.IMAGE
    return None


def _apply_overrides(controller: object, args: argparse.Namespace) -> None:
    """Apply one-run command-line overrides to the loaded profile.

    These are deliberately not saved: a ``--demo`` run should not silently
    rewrite the user's profile.
    """
    from .config.models import SourceKind

    profile = getattr(controller, "_profile", None)
    if profile is None:  # pragma: no cover - defensive
        return

    kind = _selected_kind(args)
    if kind is not None:
        profile.source.kind = kind
        logger.info("Override: source %s", kind.value)

    if args.sender:
        if profile.source.kind is SourceKind.NDI:
            profile.source.ndi.source_name = args.sender
        else:
            profile.source.spout.sender_name = args.sender
        logger.info("Override: sender name %r", args.sender)

    if args.image:
        profile.source.image.path = args.image
        logger.info("Override: image %r", args.image)

    if args.capture_monitor is not None:
        profile.source.screen.monitor_index = max(0, args.capture_monitor)
        logger.info("Override: capture monitor %d", profile.source.screen.monitor_index)

    if args.monitor is not None:
        from .config.models import GeometryMode

        profile.display.geometry_mode = GeometryMode.MONITOR
        profile.display.monitor_index = max(0, args.monitor)
        logger.info("Override: monitor %d", profile.display.monitor_index)

    if args.no_panel:
        profile.behavior.show_panel_on_start = False
