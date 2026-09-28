"""Application-wide constants.

Kept dependency-free (standard library only) so that every other module —
including the ones imported before Qt exists — can rely on it.
"""

from __future__ import annotations

import sys

APP_NAME = "OBS Overlay"
APP_SLUG = "obs-overlay"
APP_VERSION = "1.0.0"
ORG_NAME = "obs-overlay"
APP_DESCRIPTION = "Transparent click-through OBS Spout2 overlay with window masking"

IS_WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------------
# Profile schema
# --------------------------------------------------------------------------
#: Bumped whenever the on-disk profile layout changes in a way that needs a
#: migration step. ``config.migrations`` must gain an entry for every bump.
PROFILE_SCHEMA_VERSION = 2

DEFAULT_PROFILE_NAME = "Default"
PROFILE_SUFFIX = ".json"

# --------------------------------------------------------------------------
# Video / timing
# --------------------------------------------------------------------------
DEFAULT_SENDER_NAME = "OBS_Sender"
DEFAULT_TARGET_FPS = 60
MIN_TARGET_FPS = 1
MAX_TARGET_FPS = 240

#: How long the receiver waits between reconnect attempts when no Spout sender
#: is available yet (seconds).
RECONNECT_INTERVAL_S = 1.0

#: Number of frame buffers kept in the pool. Three lets the producer fill one
#: while the GUI thread paints another, with one spare to absorb jitter.
FRAME_POOL_SIZE = 3

#: Hard cap on a single frame's dimensions. Guards against a malformed sender
#: announcing an absurd size and making us allocate gigabytes.
MAX_FRAME_DIMENSION = 16384

# --------------------------------------------------------------------------
# Editor defaults
# --------------------------------------------------------------------------
DEFAULT_GRID_SIZE = 10
DEFAULT_SNAP_THRESHOLD = 8
MIN_PARCEL_SIZE = 8
HANDLE_SIZE = 10
HANDLE_HIT_SLACK = 4

# --------------------------------------------------------------------------
# Hotkeys (defaults chosen to avoid clashing with OBS and common games)
# --------------------------------------------------------------------------
# F12 is deliberately avoided everywhere: Windows reserves it for the debugger
# and RegisterHotKey will not bind it.
DEFAULT_HOTKEYS = {
    "toggle_editor": "Ctrl+Alt+M",
    "toggle_click_through": "Ctrl+Alt+C",
    "toggle_overlay": "Ctrl+Alt+H",
    "toggle_panel": "Ctrl+Alt+P",
    "reload_profile": "Ctrl+Alt+R",
    "panic": "Ctrl+Alt+Shift+F9",
}

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOG_FILE_NAME = "obs-overlay.log"
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
