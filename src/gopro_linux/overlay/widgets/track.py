"""GPS track-map widget."""
from __future__ import annotations
import math
from PIL import Image, ImageDraw
from gopro_linux.overlay.widgets.base import Widget


class TrackMapWidget(Widget):
    """
    Renders the GPS track as a line with the current position highlighted.

    The track extents are computed from the full GPS dataset the first time
    ``render`` is called; subsequent calls reuse the cached pixel coordinates.
    """

    def __init__(
        self,
        size:        int   = 220,
        padding:     int   = 14,
        track_color: tuple = (100, 180, 255, 200),
        pos_color:   tuple = (255, 60, 60, 255),
        bg_color:    tuple = (0, 0, 0, 170),
    ) -> None:
        super().__init__(size, size)
        self.padding     = padding
        self.track_color = track_color
        self.pos_color   = pos_color
        self.bg_color    = bg_color

        self._track_px:  list[tuple[int, int]] | None = None
        self._transform: dict | None = None   # cached geo→px parameters

    # ── internals ────────────────────────────────────────────────────────────

    def _build_transform(self, telem) -> None:
        """Compute geo-to-pixel transform from the full GPS track."""
        lats = telem.gps_lat
        lons = telem.gps_lon

        lat_min, lat_max = float(lats.min()), float(lats.max())
        lon_min, lon_max = float(lons.min()), float(lons.max())

        # Correct longitude span for latitude (Mercator-ish)
        lat_mid = (lat_min + lat_max) / 2.0
        cos_lat = math.cos(math.radians(lat_mid))

        draw_size  = self.width - 2 * self.padding
        lat_span   = max(lat_max - lat_min, 1e-8)
        lon_span   = max((lon_max - lon_min) * cos_lat, 1e-8)
        scale      = draw_size / max(lat_span, lon_span)

        self._transform = dict(
            lat_max=lat_max, lat_min=lat_min,
            lon_min=lon_min,
            cos_lat=cos_lat, scale=scale,
            padding=self.padding,
        )
        self._track_px = [
            self._geo_to_px(float(la), float(lo))
            for la, lo in zip(lats, lons)
        ]

    def _geo_to_px(self, lat: float, lon: float) -> tuple[int, int]:
        tr  = self._transform
        px  = tr["padding"] + int((lon - tr["lon_min"]) * tr["cos_lat"] * tr["scale"])
        py  = tr["padding"] + int((tr["lat_max"] - lat)              * tr["scale"])
        return px, py

    # ── render ───────────────────────────────────────────────────────────────

    def render(self, t: float, telem) -> Image.Image:
        img  = self._blank()
        if not telem.has_gps():
            return img

        if self._track_px is None:
            self._build_transform(telem)

        draw = ImageDraw.Draw(img)

        # Background rounded rectangle
        draw.rounded_rectangle(
            [(0, 0), (self.width - 1, self.height - 1)],
            radius=12, fill=self.bg_color,
        )

        # Track line
        pts = self._track_px
        if pts and len(pts) > 1:
            draw.line(pts, fill=self.track_color, width=2)

        # Current position
        lat, lon = telem.gps_at(t)
        px, py   = self._geo_to_px(lat, lon)

        r = 6
        draw.ellipse([(px - r, py - r), (px + r, py + r)], fill=self.pos_color)
        draw.ellipse(
            [(px - r, py - r), (px + r, py + r)],
            outline=(255, 255, 255, 220), width=2,
        )

        return img
