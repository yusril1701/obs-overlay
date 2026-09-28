"""Animated RGBA test pattern.

Exists for three reasons:

* You can lay out parcels before OBS is even installed.
* It proves the alpha path end to end — if the demo's transparent areas come
  out black instead of see-through, the problem is the window, not Spout.
* CI can exercise the whole frame pipeline with no GPU.

The pattern deliberately contains large fully transparent regions, soft alpha
gradients and hard edges, because those are exactly the cases where a broken
compositing path shows up.

Performance notes
-----------------
This has to hold 60 fps at 1080p on the CPU, so the render is arranged to touch
full-resolution memory as little as possible, and only through operations numpy
has a fast path for:

* Smooth content (the drifting blobs) is computed on a quarter-resolution grid
  and upsampled with ``np.repeat``. Measured on the development machine, that
  upsample costs ~2 ms at 1080p, where the equivalent broadcast-assignment into
  a strided view costs ~12 ms and a masked ``np.copyto`` ~14 ms — both avoided
  here for that reason.
* Crisp content (frame, brackets, grid, sweep bar) is drawn as a handful of
  slice assignments touching a few thousand rows/columns, never a full-frame
  masked composite.
* Blob falloff uses squared distance, so there is no per-pixel ``sqrt``.
* Every intermediate buffer is preallocated and reused.
"""

from __future__ import annotations

import time

import numpy as np

from ..core.frame import (
    Frame,
    FrameBufferPool,
    PixelFormat,
    is_valid_dimensions,
    required_buffer_size,
)
from .base import SourceState, VideoSource

#: Distinct hues for the moving blobs, as straight (non-premultiplied) RGB.
_BLOB_COLORS: tuple[tuple[int, int, int], ...] = (
    (255, 92, 92),
    (92, 200, 255),
    (255, 214, 92),
    (140, 255, 160),
    (206, 140, 255),
)

#: Blobs are rendered at 1/N resolution and upsampled. They are low-frequency
#: by construction, so this is invisible while the arithmetic gets N² cheaper.
_BLOB_DOWNSCALE = 4

_WHITE = np.array((255, 255, 255, 255), dtype=np.uint8)
_CYAN = np.array((26, 230, 255, 255), dtype=np.uint8)
_GRID = np.array((150, 150, 150, 80), dtype=np.uint8)


class DemoSource(VideoSource):
    """Synthetic source producing an animated, genuinely transparent pattern."""

    kind = "demo"

    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        super().__init__()
        if not is_valid_dimensions(width, height):
            raise ValueError(f"Invalid demo resolution {width}x{height}")
        self._width = width
        self._height = height
        self._start = time.perf_counter()
        self._ready = False

        # Low-resolution scratch for the blob field.
        self._small_shape: tuple[int, int] = (0, 0)
        self._small_gx: np.ndarray | None = None
        self._small_gy: np.ndarray | None = None
        self._small_rgb: np.ndarray | None = None
        self._small_alpha: np.ndarray | None = None
        self._small_blob: np.ndarray | None = None
        self._blob_rgba: np.ndarray | None = None
        #: Normalised x coordinates, used by the sweep bar.
        self._xs: np.ndarray | None = None
        # Geometry of the crisp layer, derived once.
        self._border = 0
        self._inset = 0
        self._arm = 0
        self._step_x = 1
        self._step_y = 1

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> bool:
        self._allocate()
        self._start = time.perf_counter()
        self._set_state(SourceState.CONNECTED)
        return True

    def close(self) -> None:
        self._small_gx = self._small_gy = None
        self._small_rgb = self._small_alpha = self._small_blob = None
        self._blob_rgba = None
        self._xs = None
        self._ready = False
        self._set_state(SourceState.CLOSED)

    @property
    def display_name(self) -> str:
        return "Test Pattern"

    def set_resolution(self, width: int, height: int) -> None:
        if not is_valid_dimensions(width, height):
            raise ValueError(f"Invalid demo resolution {width}x{height}")
        if (width, height) == (self._width, self._height):
            return
        self._width, self._height = width, height
        self._ready = False
        if self.is_connected:
            self._allocate()

    # -- allocation --------------------------------------------------------
    def _allocate(self) -> None:
        width, height = self._width, self._height
        factor = _BLOB_DOWNSCALE
        # Round up, then crop after upsampling, so any resolution works.
        small_w = max(2, -(-width // factor))
        small_h = max(2, -(-height // factor))
        self._small_shape = (small_h, small_w)

        xs = np.linspace(0.0, 1.0, small_w, dtype=np.float32)
        ys = np.linspace(0.0, 1.0, small_h, dtype=np.float32)
        self._small_gx, self._small_gy = np.meshgrid(xs, ys, copy=True)

        self._small_rgb = np.zeros((small_h, small_w, 3), dtype=np.float32)
        self._small_alpha = np.zeros((small_h, small_w), dtype=np.float32)
        self._small_blob = np.zeros((small_h, small_w), dtype=np.float32)
        self._blob_rgba = np.zeros((small_h, small_w, 4), dtype=np.uint8)

        self._xs = np.linspace(0.0, 1.0, width, dtype=np.float32)

        self._border = max(2, min(width, height) // 160)
        self._inset = max(self._border * 3, min(width, height) // 24)
        self._arm = max(8, min(width, height) // 12)
        self._step_x = max(1, width // 10)
        self._step_y = max(1, height // 10)
        self._ready = True

    # -- rendering ---------------------------------------------------------
    def _render_blobs(self, elapsed: float) -> None:
        """Fill the low-resolution colour/alpha scratch with drifting blobs."""
        gx, gy = self._small_gx, self._small_gy
        rgb, alpha, blob = self._small_rgb, self._small_alpha, self._small_blob
        assert gx is not None and gy is not None
        assert rgb is not None and alpha is not None and blob is not None

        rgb.fill(0.0)
        alpha.fill(0.0)
        aspect = self._width / max(1, self._height)

        for index, colour in enumerate(_BLOB_COLORS):
            phase = elapsed * (0.17 + 0.05 * index) + index * 1.7
            cx = 0.5 + 0.34 * float(np.cos(phase))
            cy = 0.5 + 0.30 * float(np.sin(phase * 1.31 + index))
            radius = 0.10 + 0.035 * float(np.sin(elapsed * 0.9 + index))
            inv_r2 = 1.0 / max(1e-6, radius * radius)

            # Squared distance keeps the falloff smooth without a sqrt pass.
            dx = (gx - cx) * aspect
            dy = gy - cy
            np.multiply(dx, dx, out=blob)
            blob += dy * dy
            blob *= inv_r2
            np.subtract(1.0, blob, out=blob)
            np.clip(blob, 0.0, 1.0, out=blob)

            # Painter's algorithm: the newest blob wins where it is strongest.
            tint = np.asarray(colour, dtype=np.float32) / 255.0
            weight = blob[..., None]
            rgb *= 1.0 - weight
            rgb += tint * weight
            np.maximum(alpha, blob, out=alpha)

        # A slow global pulse so a frozen feed is unmistakable.
        alpha *= 0.82 + 0.18 * float(np.sin(elapsed * 2.2))

    def _pack_blob_layer(self) -> np.ndarray:
        """Quantise the low-resolution blob field into RGBA bytes."""
        rgb, alpha, rgba = self._small_rgb, self._small_alpha, self._blob_rgba
        assert rgb is not None and alpha is not None and rgba is not None

        np.clip(rgb, 0.0, 1.0, out=rgb)
        np.multiply(rgb, 255.0, out=rgb)
        rgba[..., :3] = rgb
        np.clip(alpha, 0.0, 1.0, out=alpha)
        np.multiply(alpha, 255.0, out=alpha)
        rgba[..., 3] = alpha
        return rgba

    def _draw_crisp_layer(self, out: np.ndarray) -> None:
        """Frame, corner brackets and percentage grid, as slice writes.

        Drawn every frame rather than composited from a baked image: these
        touch a few thousand rows and columns, where a full-frame masked copy
        would touch two million pixels.
        """
        height, width = self._height, self._width
        border, inset, arm = self._border, self._inset, self._arm

        # Faint grid every 10% — a ruler for judging parcel placement.
        out[:, :: self._step_x] = _GRID
        out[:: self._step_y, :] = _GRID

        # Outer frame: proves the overlay covers exactly the canvas you expect.
        out[:border, :] = _WHITE
        out[height - border :, :] = _WHITE
        out[:, :border] = _WHITE
        out[:, width - border :] = _WHITE

        # Corner brackets, so a mis-anchored or cropped feed is obvious.
        for y0, y1 in ((inset, inset + border), (height - inset - border, height - inset)):
            if 0 <= y0 < y1 <= height:
                out[y0:y1, inset : inset + arm] = _CYAN
                out[y0:y1, max(0, width - inset - arm) : width - inset] = _CYAN
        for x0, x1 in ((inset, inset + border), (width - inset - border, width - inset)):
            if 0 <= x0 < x1 <= width:
                out[inset : inset + arm, x0:x1] = _CYAN
                out[max(0, height - inset - arm) : height - inset, x0:x1] = _CYAN

    def _render_into(self, out: np.ndarray, elapsed: float) -> None:
        assert self._xs is not None
        height, width = self._height, self._width
        factor = _BLOB_DOWNSCALE

        self._render_blobs(elapsed)
        blob = self._pack_blob_layer()

        # np.repeat has an optimised path; the temporaries it allocates are far
        # cheaper than writing through a strided view of `out`.
        upsampled = np.repeat(np.repeat(blob, factor, axis=0), factor, axis=1)
        out[:] = upsampled[:height, :width]

        self._draw_crisp_layer(out)

        # Sweeping bar: a contiguous column slice, so no fancy indexing.
        sweep = (elapsed * 0.28) % 1.0
        half = max(1, int(0.012 * width))
        centre = int(sweep * width)
        lo = max(0, centre - half)
        hi = min(width, centre + half + 1)
        if hi > lo:
            ramp = np.clip(1.0 - np.abs(self._xs[lo:hi] - sweep) / 0.012, 0.0, 1.0)
            ramp_u8 = (ramp * 229.0).astype(np.uint8)
            out[:, lo:hi, :3] = 255
            np.maximum(out[:, lo:hi, 3], ramp_u8, out=out[:, lo:hi, 3])

    # -- capture -----------------------------------------------------------
    def capture(self, pool: FrameBufferPool) -> Frame | None:
        if self._state is not SourceState.CONNECTED:
            return None
        if not self._ready:
            self._allocate()

        needed = required_buffer_size(self._width, self._height)
        if pool.buffer_size != needed:
            pool.resize(needed)

        buffer = pool.acquire()
        if buffer is None:
            return None

        try:
            # Render straight into the pooled memory. `buffer.data` is a
            # bytearray, so np.frombuffer gives a writable view and the frame
            # never needs a second full-resolution copy.
            target = np.frombuffer(buffer.data, dtype=np.uint8, count=needed).reshape(
                self._height, self._width, 4
            )
            self._render_into(target, time.perf_counter() - self._start)
        except Exception:
            buffer.release()
            raise

        return Frame(
            width=self._width,
            height=self._height,
            pixel_format=PixelFormat.RGBA8888,
            buffer=buffer,
            sequence=self._next_sequence(),
            timestamp=time.perf_counter(),
            premultiplied=False,
        )

    @staticmethod
    def list_senders() -> list[str]:
        return ["Test Pattern"]
