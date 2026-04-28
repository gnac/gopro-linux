"""Overlay renderer: composites widgets into a single RGBA frame."""
from __future__ import annotations
from dataclasses import dataclass
from PIL import Image

from gopro_linux.overlay.widgets.base import Widget
from gopro_linux.overlay.widgets.speed  import SpeedWidget
from gopro_linux.overlay.widgets.gforce import GForceWidget
from gopro_linux.overlay.widgets.track  import TrackMapWidget
from gopro_linux.telemetry.models import TelemetryData


@dataclass
class _Placement:
    widget: Widget
    x: int
    y: int


class OverlayRenderer:
    """Composites multiple widgets onto a transparent RGBA canvas."""

    def __init__(self, width: int, height: int) -> None:
        self.width  = width
        self.height = height
        self._slots: list[_Placement] = []

    def add(self, widget: Widget, x: int, y: int) -> None:
        """Place *widget* with its top-left corner at pixel *(x, y)*."""
        self._slots.append(_Placement(widget=widget, x=x, y=y))

    def render_frame(self, t: float, telem: TelemetryData) -> Image.Image:
        """Return a fully composited RGBA frame for video time *t*."""
        canvas = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        for s in self._slots:
            tile = s.widget.render(t, telem)
            canvas.paste(tile, (s.x, s.y), tile)
        return canvas

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def default_layout(
        cls,
        telem: TelemetryData,
        *,
        speed_units:  str  = "mph",
        show_speed:   bool = True,
        show_gforce:  bool = True,
        show_track:   bool = True,
    ) -> "OverlayRenderer":
        """
        Create the default motorsport overlay layout.

        Bottom-left  : speed readout
        Bottom-right : g-force circle
        Top-right    : GPS track map
        """
        w   = telem.width
        h   = telem.height
        mgn = 20

        # Widget size scales with video height, capped at 220 px
        ws  = min(220, h // 4)

        renderer = cls(w, h)

        if show_speed:
            sw = SpeedWidget(
                width=int(ws * 0.92),
                height=int(ws * 0.54),
                units=speed_units,
            )
            renderer.add(sw, mgn, h - sw.height - mgn)

        if show_gforce and telem.has_accl():
            gw = GForceWidget(size=ws, max_g=1.5, fps=telem.fps)
            renderer.add(gw, w - ws - mgn, h - ws - mgn)

        if show_track and telem.has_gps():
            tw = TrackMapWidget(size=ws)
            renderer.add(tw, w - ws - mgn, mgn)

        return renderer
