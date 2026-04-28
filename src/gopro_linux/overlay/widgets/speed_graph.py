"""
Speed graph widget.

Renders a full-duration speed timeline as a filled area chart.  A vertical
cursor tracks the current video time, and the speed value at the cursor is
printed above it.

Typical placement: a wide strip along the bottom of the frame.

    ┌──────────────────────────────────────────────────────────────┐
    │  57 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
    │       ╭──╮                                                   │
    │      ╭╯  ╰─╮      ╭───╮        32 mph                       │
    │  ────╯     ╰──────╯   ╰──── │ ────────────────────╮         │
    │                             │                      ╰──╮      │
    │  0 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ╰─ ─  │
    └──────────────────────────────────────────────────────────────┘
      0s                       current time              duration
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from gopro_linux.overlay.widgets.base import Widget, find_font

_CONVERSIONS = {
    "mph": 2.236_94,
    "kph": 3.6,
    "ms":  1.0,
}


class SpeedGraphWidget(Widget):
    """
    Full-duration speed timeline with a live cursor.

    Parameters
    ----------
    width, height : int
        Widget dimensions in pixels.
    units : str
        ``'mph'``, ``'kph'``, or ``'ms'``.
    padding : int
        Inner padding (pixels) between the widget border and the plot area.
    bg_color : tuple
        RGBA background colour.
    line_color : tuple
        RGBA colour for the speed curve line.
    fill_color : tuple
        RGBA colour for the filled area under the curve.
    grid_color : tuple
        RGBA colour for horizontal grid lines and axis labels.
    cursor_color : tuple
        RGBA colour for the current-time cursor line.
    label_color : tuple
        RGBA colour for the speed-at-cursor label.
    n_grid_lines : int
        Number of horizontal guide lines (including the max-speed line).
        Set to 0 to disable.
    """

    def __init__(
        self,
        width:        int   = 800,
        height:       int   = 120,
        units:        str   = "mph",
        padding:      int   = 18,
        bg_color:     tuple = (0, 0, 0, 170),
        line_color:   tuple = (100, 200, 255, 240),
        fill_color:   tuple = (60, 140, 220, 100),
        grid_color:   tuple = (80, 80, 80, 180),
        cursor_color: tuple = (255, 60, 60, 230),
        label_color:  tuple = (255, 255, 255, 230),
        n_grid_lines: int   = 3,
    ) -> None:
        super().__init__(width, height)
        self.units        = units.lower()
        self.padding      = padding
        self.bg_color     = bg_color
        self.line_color   = line_color
        self.fill_color   = fill_color
        self.grid_color   = grid_color
        self.cursor_color = cursor_color
        self.label_color  = label_color
        self.n_grid_lines = n_grid_lines

        # Cached pre-computed data (built on first render)
        self._speed_pts:   list[tuple[int, int]] | None = None
        self._max_speed:   float = 1.0   # in display units
        self._duration:    float = 1.0   # seconds
        self._plot_left:   int   = 0
        self._plot_right:  int   = 0
        self._plot_top:    int   = 0
        self._plot_bottom: int   = 0

        lh = max(10, height // 8)
        self._font_label  = find_font(lh)
        self._font_cursor = find_font(max(10, height // 7), bold=True)

    # ── helpers ───────────────────────────────────────────────────────────────

    @property
    def _factor(self) -> float:
        return _CONVERSIONS.get(self.units, 1.0)

    def _speed_to_y(self, speed_in_units: float) -> int:
        """Map a speed value (display units) to a Y pixel inside the plot."""
        frac = max(0.0, min(1.0, speed_in_units / self._max_speed))
        return int(self._plot_bottom - frac * (self._plot_bottom - self._plot_top))

    def _time_to_x(self, t: float) -> int:
        """Map a time (seconds) to an X pixel inside the plot."""
        frac = max(0.0, min(1.0, t / self._duration))
        return int(self._plot_left + frac * (self._plot_right - self._plot_left))

    # ── pre-computation (runs once) ───────────────────────────────────────────

    def _precompute(self, telem) -> None:
        """Sample the full speed profile and build the polyline pixel list."""
        factor   = self._factor
        duration = telem.duration

        # Plot area boundaries
        pad = self.padding
        # Leave a little extra on the left for the Y-axis labels
        label_w          = max(0, pad * 2)
        self._plot_left   = pad + label_w
        self._plot_right  = self.width  - pad
        self._plot_top    = pad
        self._plot_bottom = self.height - pad

        self._duration = max(duration, 1e-3)

        # Sample one point per horizontal pixel for a smooth curve
        n_samples  = int(max(self._plot_right - self._plot_left, 2))
        times      = np.linspace(0.0, duration, n_samples)
        speeds     = np.array([telem.speed_at(t) * factor for t in times])

        # Set the Y-axis ceiling to the nearest "round" number above the peak
        raw_max = float(speeds.max()) if speeds.size else 1.0
        if raw_max < 1.0:
            raw_max = 1.0
        # Round up to a clean value (10, 20, 30, … mph/kph or 5, 10, … m/s)
        step = 5.0 if self.units == "ms" else 10.0
        self._max_speed = max(step, np.ceil(raw_max / step) * step)

        # Build polyline as (x, y) pixel tuples
        pts: list[tuple[int, int]] = []
        for i, (t, s) in enumerate(zip(times, speeds)):
            x = self._plot_left + i   # one point per pixel column
            y = self._speed_to_y(s)
            pts.append((x, y))

        self._speed_pts = pts

    # ── render ────────────────────────────────────────────────────────────────

    def render(self, t: float, telem) -> Image.Image:
        img  = self._blank()

        if not telem.has_gps():
            return img

        if self._speed_pts is None:
            self._precompute(telem)

        draw = ImageDraw.Draw(img)

        pl = self._plot_left
        pr = self._plot_right
        pt = self._plot_top
        pb = self._plot_bottom

        # ── background ───────────────────────────────────────────────────────
        draw.rounded_rectangle(
            [(0, 0), (self.width - 1, self.height - 1)],
            radius=10,
            fill=self.bg_color,
        )

        # ── horizontal grid lines ────────────────────────────────────────────
        if self.n_grid_lines > 0:
            for i in range(self.n_grid_lines + 1):
                frac       = i / self.n_grid_lines
                speed_val  = frac * self._max_speed
                gy         = self._speed_to_y(speed_val)
                draw.line([(pl, gy), (pr, gy)], fill=self.grid_color, width=1)

                # Y-axis label (right-aligned against the plot edge)
                lbl = f"{speed_val:.0f}"
                draw.text(
                    (pl - 4, gy),
                    lbl,
                    font=self._font_label,
                    fill=self.grid_color,
                    anchor="rm",
                )

        # units label at top-right of plot area
        draw.text(
            (pr, pt - 2),
            self.units.upper(),
            font=self._font_label,
            fill=self.grid_color,
            anchor="rb",
        )

        # ── filled area under the speed curve ────────────────────────────────
        if self._speed_pts and len(self._speed_pts) > 1:
            # Close the polygon at the bottom of the plot
            poly = [(pl, pb)] + self._speed_pts + [(pr, pb)]
            draw.polygon(poly, fill=self.fill_color)

            # Speed curve line
            draw.line(self._speed_pts, fill=self.line_color, width=2)

        # ── cursor ───────────────────────────────────────────────────────────
        cx = self._time_to_x(t)

        # Vertical cursor line
        draw.line([(cx, pt), (cx, pb)], fill=self.cursor_color, width=2)

        # Small triangle / tick at the top of the cursor
        tri_h = 6
        draw.polygon(
            [(cx - 5, pt), (cx + 5, pt), (cx, pt + tri_h)],
            fill=self.cursor_color,
        )

        # Speed value label just above the cursor point
        current_speed = telem.speed_at(t) * self._factor
        cy_speed      = self._speed_to_y(current_speed)

        # Dot on the curve at the cursor
        r = 5
        draw.ellipse(
            [(cx - r, cy_speed - r), (cx + r, cy_speed + r)],
            fill=self.cursor_color,
        )
        draw.ellipse(
            [(cx - 2, cy_speed - 2), (cx + 2, cy_speed + 2)],
            fill=(255, 255, 255, 255),
        )

        # Speed value text — nudge left if we're near the right edge
        lbl      = f"{current_speed:.0f}"
        text_x   = cx + 7 if cx < pr - 60 else cx - 7
        anchor   = "lm"       if cx < pr - 60 else "rm"
        text_y   = max(pt + 2, cy_speed - 12)

        draw.text(
            (text_x, text_y),
            lbl,
            font=self._font_cursor,
            fill=self.label_color,
            anchor=anchor,
        )

        return img
