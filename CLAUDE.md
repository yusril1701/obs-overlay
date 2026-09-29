# CLAUDE.md

Instructions for an AI agent working on this repository. Read this before
changing anything.

Written in English to match the code and its comments. **User-facing
documentation in `docs/` and `README.md` is written in Indonesian** — keep it
that way. The application's own UI strings are English.

---

## What this is

A transparent, click-through Windows overlay. It receives video (OBS via
Spout2, NDI, screen capture, or an image file), paints it always-on-top with
true per-pixel alpha, and then **physically cuts its own window into boxes
("parcels")** so the gaps between them are not merely transparent — the window
is not there at all, and mouse clicks land on whatever is behind.

Python 3.9–3.13, PyQt6, numpy. No OpenCV, no Pillow.

---

## Environment

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

Optional extras: `.[ndi]` for the NDI source, `.[build]` for PyInstaller.
`SpoutGL` and `pywin32` install automatically on Windows and are skipped
elsewhere (environment markers in `pyproject.toml`).

**Python version matters.** SpoutGL publishes no wheel above CPython 3.13 and
its sdist does not build on a clean machine. Build with 3.12 or 3.13.

## The quality gate

Run all four before every commit. CI runs exactly these.

```powershell
ruff check src tests
ruff format src tests
mypy
pytest -q
```

On Windows also run `mypy --platform win32` — it type-checks the `native/`
branches that are stubbed out elsewhere, and it catches real bugs there that
the default platform never sees.

Tests need no GPU, no OBS and no Windows. On Linux they need
`QT_QPA_PLATFORM=offscreen`; on Windows they run as-is.

---

## Repository map

```
src/obs_overlay/
├── constants.py        Fixed values. Standard library only.
├── paths.py            %APPDATA%, portable mode, bundle dir.
├── cli.py              argparse. Touches Qt as late as possible.
├── app.py              Assembly only. No logic of its own.
├── config/             models.py (dataclasses), migrations.py, store.py
├── core/               geometry.py, mask.py, frame.py, fps.py, producer.py
├── sources/            base, spout, ndi, screen, image, demo, qt_frames, registry
├── native/             Win32 integration, with a Null implementation elsewhere
└── ui/                 overlay_window, editor, control_panel, parcel_table, tray, hud
```

**Layering rules.** `core/geometry.py` does not import Qt. `config/` does not
import Qt. `native/` does not import `ui/`. This is why the whole suite runs
headless — do not break it for convenience.

Full rationale, including the measurements behind each decision:
`docs/ARCHITECTURE.md`.

---

## Invariants — do not "fix" these

Every line below looks wrong at a glance and is deliberate. Each one was a bug
once. If you think one is a mistake, read the reasoning in
`docs/ARCHITECTURE.md` first, and change it only with evidence.

| Rule | Why |
|---|---|
| **Raster backing store, never `QOpenGLWidget`** | On Windows the raster path is flushed with `UpdateLayeredWindowIndirect(ULW_ALPHA)`, which gives per-pixel alpha *and* per-pixel hit-testing. An OpenGL surface falls back to `SetLayeredWindowAttributes` plus a DWM blur trick and loses hit-testing. |
| **Never call `SetLayeredWindowAttributes`** | After it is called, `UpdateLayeredWindow` fails until the layered bit is cleared and re-set. It permanently kills Qt's per-pixel alpha. |
| **Never clear `WS_EX_LAYERED`** | Qt sets it itself for translucent frameless windows. `native/win32_window.py` only read-modify-writes the three bits it owns: `TRANSPARENT`, `TOOLWINDOW`, `NOACTIVATE`. |
| **`SWP_FRAMECHANGED` after every ex-style change** | Windows caches frame data; without it the change does not take effect. |
| **Omit `SWP_NOZORDER` only when asserting topmost** | `HWND_TOPMOST` is honoured only when the Z-order is allowed to change. Include the flag for a plain style refresh. |
| **`WDA_EXCLUDEFROMCAPTURE` gated on build ≥ 19041** | Older builds silently downgrade it to `WDA_MONITOR`, which paints the overlay as a solid black box in every recording — worse than doing nothing. |
| **`__main__.py` imports absolutely, not relatively** | PyInstaller runs it as a bare script with no package, so `from .cli import …` raises and the .exe dies before drawing. Guarded by `tests/test_entry_point.py`. |
| **`FrameProducer` deep-copies its `SourceSettings`** | Holding a reference to the profile's object makes `_needs_reopen()` compare an object with itself, so changing the sender name never reconnects. |
| **The screen grabber lives on the GUI thread** | `QScreen.grabWindow` is not thread-safe, and blocking the producer on the GUI thread deadlocks against `FrameProducer.stop()`, which waits for the worker *from* the GUI thread. The producer pulls; nothing ever waits. |
| **The mask region is grown 1 px past the clip path** | A `QRegion` mask is 1-bit. Without the extra pixel it clips the antialiased edge the painter just drew. |
| **Never read a `QRegion` back** | PyQt6 removed `QRegion.rects()` and the object is not iterable. The parcel list is the only source of truth. |
| **Alpha defaults differ per source** | Premultiplied for Spout (OBS composites that way), straight for NDI (its spec says "not pre-multiplied"). Getting it backwards produces dark fringes or washed-out edges on every soft edge. |
| **NDI `BGRX` frames get alpha forced to 255** | In BGRX the fourth byte is padding, not alpha, and is not guaranteed to be `0xFF`. Passing it through makes an opaque source vanish. |
| **Hotkeys register against the thread (`HWND` = `NULL`)** | Qt destroys and recreates the native window on operations as innocuous as `setWindowFlags`. A hotkey bound to an HWND silently stops working. |
| **F12 is never offered as a hotkey** | Windows reserves it for the debugger; `RegisterHotKey` refuses it. |
| **Frame notifications and repaints are coalesced** | An unbounded posted-event queue starves Qt's timers, including the ones needed to paint. `_publish()` and `request_repaint()` collapse duplicates; the *data* is still latest-wins. |
| **`portable.txt` is excluded from the installer** | That marker switches the app to portable mode. An installed copy carrying one would try to write profiles into Program Files. |

---

## Common recipes

### Adding a video source

1. `sources/<name>_source.py` — subclass `VideoSource`; implement `open()`,
   `close()`, `capture(pool)`, `display_name`. Use
   `qt_frames.frame_from_qimage()` if the data arrives as a `QImage` — it
   handles stride correctly.
2. `config/models.py` — add `<Name>Settings`, a field on `SourceSettings`,
   and a `SourceKind` member.
3. `config/migrations.py` — add a step, and bump `PROFILE_SCHEMA_VERSION` in
   `constants.py`. **Every bump needs a migration**; old profiles must keep
   opening.
4. `sources/registry.py` — `kind_available`, `unavailable_reason`,
   `available_sender_names`, `create_source`.
5. `core/producer.py` — extend `_needs_reopen()` so a change to the new
   group's settings reconnects, and nothing else does.
6. `ui/control_panel.py` — a `_build_<name>_page()` and an `_edit_<name>()`.
7. `ui/overlay_window.py` — a `_WAITING_TEXT` entry.
8. `cli.py` — extend `--source`, and `_list_senders` if it can enumerate.
9. Tests in `tests/test_sources.py`, docs in `README.md`,
   `docs/USER_GUIDE.md`, `docs/TROUBLESHOOTING.md`, `CHANGELOG.md`.

Import every optional dependency **inside a function**, never at module level.
The package must stay importable on a machine with none of them — that is the
condition CI runs under.

### Adding a setting

`config/models.py` → migration + schema bump → `ui/control_panel.py` →
`app.py` if it needs to act on change → `docs/USER_GUIDE.md` → a round-trip
test. `from_dict()` must stay **total**: any JSON at all, including corrupt or
hostile, has to produce a usable object with out-of-range values clamped.

### Releasing

```powershell
# bump together, they must agree:
#   src/obs_overlay/constants.py   APP_VERSION
#   pyproject.toml                 version
#   packaging/version_info.txt     4 places
#   CHANGELOG.md                   a new entry

git tag v1.2.0
git push origin v1.2.0
```

CI builds the installer and the portable zip and attaches both to the GitHub
Release. The installer's version is read from `APP_VERSION`, not from the tag.

---

## State of the code

**Verified.** Everything that runs headless: geometry, masking, profiles and
migrations, the frame pipeline, the editor state machine, the control panel,
the CLI, and the screen-capture, image and test-pattern sources — exercised
end to end through the real producer, not mocked. 381 tests.

**Not verified by anything automatic.** Spout and NDI need hardware, a
runtime and a live sender, so CI cannot touch their receive paths; the same
goes for every Win32 behaviour (click-through, topmost, hotkeys, capture
exclusion) and the installer's actual install/uninstall. `ndi_source.py` says
so in its own docstring rather than pretending otherwise.
**`docs/WINDOWS_CHECKLIST.md` is the list of what to verify by hand, in
order.** Working through it is the highest-value thing to do on a Windows
machine.

**Known issue.** Under a headless QPA (`offscreen` / `minimal`), `app.exec()`
sometimes does not return at shutdown with the overlay visible and a live
feed. Coalescing frame notifications and repaints took it from 2/8 clean runs
to 6/8 but did not remove it; stack dumps show the producer sleeping normally
and the main thread inside `app.exec()` with no Python frame — nothing in
application code is blocking. Never observed on a real Windows session. If you
reproduce it on Windows, that is new and important information.

---

## Conventions

- **Docs in Indonesian, code and UI in English.** Do not translate one into
  the other.
- Comments explain **why**, not what. If a line looks wrong and is not, say
  why in a comment — that is how the invariants above stay intact.
- Commit messages: a short imperative subject, then prose explaining the
  reasoning. Look at `git log` for the register.
- Do not add a dependency to make something marginally shorter. Qt and numpy
  already cover it, and every extra package is another thing that can break
  the PyInstaller bundle.
- Never let the .exe smoke test pass on exit code alone; check the output.
  That is how the broken entry point survived a release.
