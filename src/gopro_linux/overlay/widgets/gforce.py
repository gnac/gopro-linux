"""
G-force scatter-plot widget.

Renders a classic motorsport "g-circle" showing lateral (X) vs longitudinal
(Y) g-forces with a fading history trail and a bright current-position dot.

Layout
------
    ▲  ACCEL (positive longitudinal, i.e. throttle)
    │
────┼────  0.5 / 1.0 / 1.5 g rings
    │
    ▼  BRAKE
    L ◀──────── lateral ──────▶ R
"""

from __future__ import annotations

from collections import deque

from PIL import Image, ImageDraw

from gopro_linux.overlay.widgets.base import Widget, find_font


class GForceWidget(Widget):
    """Motorsport-style g-force scatter display with history trail."""

    def __init__(
        self,
        size: int = 220,
        max_g: float = 1.5,
        trail_seconds: float = 1.5,
        fps: float = 30.0,
        bg_color: tuple = (0, 0, 0, 170),
        grid_color: tuple = (70, 70, 70, 200),
        dot_color: tuple = (255, 60, 60, 255),
        trail_color: tuple = (255, 150, 50, 200)
    ) -> None:
        super().__init__(size, size)
        self.max_g = max_g
        self.bg_color = bg_color
        self.grid_color = grid_color
        self.dot_color = dot_color
        self.trail_color = trail_color

        max_trail = max(1, int(trail_seconds * fps))
        self._history: deque[tuple[float, float]] = deque(maxlen=max_trail)
        self._last_t = -1.0

        label_size = max(10, size // 16)
        self._font_lbl = find_font(label_size)
        self._font_g = find_font(max(9, size // 18))

    # ── helpers ──────────────────────────────────────────────────────────────

    @property
    def _radius(self) -> int:
        return self.width // 2 - 14

    def _to_px(self, gx: float, gy: float) -> tuple[int, int]:
        """Map g-values to pixel coords (clamps to max_g)."""
        cx = self.width // 2
        cy = self.height // 2
        r = self._radius
        gx = max(-self.max_g, min(self.max_g, gx))
        gy = max(-self.max_g, min(self.max_g, gy))
        px = cx + int(gx / self.max_g * r)
        py = cy - int(gy / self.max_g * r)  # image Y increases downward
        return px, py

    # ── render ───────────────────────────────────────────────────────────────

    def render(self, t: float, telem) -> Image.Image:
        img = self._blank()
        draw = ImageDraw.Draw(img)
        cx = self.width // 2
        cy = self.height // 2
        r = self._radius

        # Background disc
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], fill=self.bg_color)

        # Reference rings: 0.5 g, 1.0 g, (1.5 g = border)
        for g_ring in (0.5, 1.0):
            gr = int(g_ring / self.max_g * r)
            draw.ellipse(
                [(cx - gr, cy - gr), (cx + gr, cy + gr)],
                outline=self.grid_color,
                width=1,
            )
            # Label the ring
            lbl_y = cy - gr - 1
            draw.text(
                (cx, lbl_y),
                f"{g_ring:.1f}g",
                font=self._font_g,
                fill=(*self.grid_color[:3], 160),
                anchor="mb",
            )

        # Cross-hairs
        draw.line([(cx - r, cy), (cx + r, cy)], fill=self.grid_color, width=1)
        draw.line([(cx, cy - r), (cx, cy + r)], fill=self.grid_color, width=1)

        # Outer border
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            outline=(*self.grid_color[:3], 255),
            width=2,
        )

        # Axis labels
        lc = (190, 190, 190, 220)
        draw.text((cx, cy + r + 2), "ACCEL", font=self._font_lbl, fill=lc, anchor="mt")
        draw.text((cx, cy - r - 2), "BRAKE", font=self._font_lbl, fill=lc, anchor="mb")
        draw.text((cx - r - 2, cy), "L", font=self._font_lbl, fill=lc, anchor="rm")
        draw.text((cx + r + 2, cy), "R", font=self._font_lbl, fill=lc, anchor="lm")

        # Update history when time advances
        if t > self._last_t:
            lat_g = telem.lateral_g_at(t)
            lon_g = telem.longitudinal_g_at(t)
            self._history.append((lat_g, lon_g))
            self._last_t = t

        hist = list(self._history)
        n = len(hist)

        # Trail (older points, fading)
        for i, (gx, gy) in enumerate(hist[:-1]):
            frac = i / max(n - 1, 1)
            alpha = int(40 + 140 * frac)
            tr = max(1, int(1 + 4 * frac))
            px, py = self._to_px(gx, gy)
            draw.ellipse(
                [(px - tr, py - tr), (px + tr, py + tr)],
                fill=(*self.trail_color[:3], alpha),
            )

        # Current dot
        if hist:
            gx, gy = hist[-1]
            px, py = self._to_px(gx, gy)
            dot_r = 8
            draw.ellipse(
                [(px - dot_r, py - dot_r), (px + dot_r, py + dot_r)],
                fill=self.dot_color,
            )
            # Bright white core
            draw.ellipse(
                [(px - 3, py - 3), (px + 3, py + 3)], fill=(255, 255, 255, 255)
            )

        return img
