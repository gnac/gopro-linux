"""Overlay renderer: composites widgets into a single RGBA frame."""
from __future__ import annotations
from dataclasses import dataclass
from PIL import Image

from gopro_linux.overlay.widgets.base import Widget
from gopro_linux.overlay.widgets.speed       import SpeedWidget
from gopro_linux.overlay.widgets.gforce      import GForceWidget
from gopro_linux.overlay.widgets.track       import TrackMapWidget
from gopro_linux.overlay.widgets.speed_graph import SpeedGraphWidget
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
        speed_units:      str  = "mph",
        show_speed:       bool = True,
        show_gforce:      bool = True,
        show_track:       bool = True,
        show_speed_graph: bool = True,
    ) -> "OverlayRenderer":
        """
        Create the default motorsport overlay layout.

        Bottom-left  : speed readout
        Bottom-right : speed graph (full-duration timeline)
        Top-right    : g-force circle
        Top Left:      GPS track map
        """
        w   = telem.width
        h   = telem.height
        mgn = 20

        # Widget size scales with video height, capped at 220 px
        ws  = min(330, h // 4)

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
            # top right
            renderer.add(gw, w - ws - mgn, mgn)

        if show_track and telem.has_gps():
            tw = TrackMapWidget(size=ws)
            # top left
            renderer.add(tw, mgn, mgn)
            # top right
            # renderer.add(tw, w - ws - mgn, mgn)

        # If you want to move or resize it, those are the knobs:
        #   `graph_x`/`graph_y` set the top-left corner, `graph_w`/`graph_h` set the size.
        # You can also construct a `SpeedGraphWidget` directly in your layout code
        # and place it anywhere with `renderer.add(sgw, x, y)`.
        # To disable it from the CLI: `gopro-overlay overlay input.mp4 out.mp4 --no-speed-graph`.
        if show_speed_graph and telem.has_gps():
            # Wide strip along the bottom, centred between the two corner widgets.
            # Leave room for the g-force widget on the left and speed on the right.
            # graph_x = ws + 2 * mgn
            # # graph_x = ws / 2 #+ 2 * mgn
            graph_x = (w // 2) + mgn
            graph_w = w // 2 - (mgn * 2)
            graph_h = max(350, ws)
            graph_y = h - graph_h - mgn
            sgw = SpeedGraphWidget(
                width=graph_w,
                height=graph_h,
                units=speed_units,
            )
            renderer.add(sgw, graph_x, graph_y)

        return renderer
