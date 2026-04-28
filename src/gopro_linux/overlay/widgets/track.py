"""GPS track-map widget."""
from __future__ import annotations
import math
import numpy as np
from PIL import Image, ImageDraw
from gopro_linux.overlay.widgets.base import Widget, find_font


class TrackMapWidget(Widget):
    """
    Renders the GPS track as a line with the current position highlighted.

    The track extents are computed from the full GPS dataset the first time
    ``render`` is called; subsequent calls reuse the cached pixel coordinates.
    """

    def __init__(
        self,
        size:         int   = 220,
        padding:      int   = 14,
        track_color:  tuple = (100, 180, 255, 200),
        pos_color:    tuple = (255, 60, 60, 255),
        bg_color:     tuple = (0, 0, 0, 170),
        arrow_color:  tuple = (255, 255, 255, 220),
    ) -> None:
        super().__init__(size, size)
        self.padding     = padding
        self.track_color = track_color
        self.pos_color   = pos_color
        self.bg_color    = bg_color
        self.arrow_color = arrow_color

        self._track_px:  list[tuple[int, int]] | None = None
        self._transform: dict | None = None   # cached geo→px parameters

        self._font_arrow = find_font(max(9, size // 16), bold=True)

    # ── internals ────────────────────────────────────────────────────────────

    def _build_transform(self, telem) -> None:
        """
        Compute the geo-to-pixel transform from the full GPS track.

        The track is rotated to the angle that minimises its bounding box
        (found via PCA on the flat 2-D point cloud) so that it fills as much
        of the square widget as possible.  The result is centred inside the
        draw area.
        """
        lats = telem.gps_lat
        lons = telem.gps_lon

        # ── 1. Project to a flat, aspect-correct 2-D space ───────────────
        lat_mid = float((lats.min() + lats.max()) / 2.0)
        cos_lat = math.cos(math.radians(lat_mid))

        cx = float(lons.mean())
        cy = float(lats.mean())

        # xs / ys are centred and in the same angular unit
        xs = (lons - cx) * cos_lat   # numpy array
        ys =  lats - cy              # numpy array

        # ── 2. PCA → rotation angle that aligns the principal axis ────────
        if len(xs) >= 2:
            pts = np.column_stack([xs, ys])
            cov = np.cov(pts.T)
            # eigh returns eigenvalues in ascending order
            _, eigvecs = np.linalg.eigh(cov)
            # principal axis = eigenvector with the largest eigenvalue
            principal = eigvecs[:, -1]
            angle = math.atan2(float(principal[1]), float(principal[0]))
        else:
            angle = 0.0

        cos_a =  math.cos(-angle)
        sin_a =  math.sin(-angle)

        # ── 3. Rotate the point cloud ─────────────────────────────────────
        rx =  xs * cos_a + ys * sin_a
        ry = -xs * sin_a + ys * cos_a

        rx_min, rx_max = float(rx.min()), float(rx.max())
        ry_min, ry_max = float(ry.min()), float(ry.max())
        rx_span = max(rx_max - rx_min, 1e-8)
        ry_span = max(ry_max - ry_min, 1e-8)

        # ── 4. Scale to fit the draw area, preserving aspect ratio ────────
        draw_size = self.width - 2 * self.padding
        scale     = draw_size / max(rx_span, ry_span)

        # Offsets that centre the track inside the draw area
        x_off = self.padding + (draw_size - rx_span * scale) / 2.0
        y_off = self.padding + (draw_size - ry_span * scale) / 2.0

        self._transform = dict(
            cx=cx, cy=cy,
            cos_lat=cos_lat,
            cos_a=cos_a, sin_a=sin_a,
            rx_min=rx_min, ry_max=ry_max,
            scale=scale,
            x_off=x_off, y_off=y_off,
        )
        self._track_px = [
            self._geo_to_px(float(la), float(lo))
            for la, lo in zip(lats, lons)
        ]

    def _geo_to_px(self, lat: float, lon: float) -> tuple[int, int]:
        tr = self._transform

        # Flat centred coordinates
        x = (lon - tr["cx"]) * tr["cos_lat"]
        y =  lat - tr["cy"]

        # Apply PCA rotation
        rx =  x * tr["cos_a"] + y * tr["sin_a"]
        ry = -x * tr["sin_a"] + y * tr["cos_a"]

        px = int(tr["x_off"] + (rx - tr["rx_min"]) * tr["scale"])
        py = int(tr["y_off"] + (tr["ry_max"] - ry) * tr["scale"])  # flip Y for image coords
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

        # ── North arrow ───────────────────────────────────────────────────
        # After rotating by -angle, north (+Y in geographic space) maps to
        # image direction (sin_a, -cos_a):
        #   rx = 0*cos_a + 1*sin_a = sin_a   → positive = right in image
        #   ry =          1*cos_a  = cos_a   → positive = UP in image = -py
        tr  = self._transform
        ndx =  tr["sin_a"]   # image +x component of north (right = positive)
        ndy = -tr["cos_a"]   # image +y component of north (down  = positive)

        arrow_len = max(16, self.width // 9)
        mgn       = self.padding + 12

        # Base of arrow — top-left corner
        bx = mgn + arrow_len // 2
        by = mgn + arrow_len // 2

        # Tip and tail
        tip_x  = int(bx + ndx * arrow_len / 2)
        tip_y  = int(by + ndy * arrow_len / 2)
        tail_x = int(bx - ndx * arrow_len / 2)
        tail_y = int(by - ndy * arrow_len / 2)

        # Perpendicular unit vector for the arrowhead wings
        pdx, pdy = -ndy, ndx

        head = max(5, arrow_len // 3)
        wing = max(3, arrow_len // 5)
        base_x = int(tip_x - ndx * head)
        base_y = int(tip_y - ndy * head)

        left_x  = int(base_x + pdx * wing)
        left_y  = int(base_y + pdy * wing)
        right_x = int(base_x - pdx * wing)
        right_y = int(base_y - pdy * wing)

        # Shaft
        draw.line([(tail_x, tail_y), (base_x, base_y)],
                  fill=self.arrow_color, width=2)
        # Filled arrowhead
        draw.polygon([(tip_x, tip_y), (left_x, left_y), (right_x, right_y)],
                     fill=self.arrow_color)

        # "N" label just beyond the tip
        lbl_off = head + 5
        draw.text(
            (int(tip_x + ndx * lbl_off), int(tip_y + ndy * lbl_off)),
            "N",
            font=self._font_arrow,
            fill=self.arrow_color,
            anchor="mm",
        )

        return img
