"""Digital speed display widget."""
from __future__ import annotations
from PIL import Image, ImageDraw
from gopro_linux.overlay.widgets.base import Widget, find_font


_CONVERSIONS = {
    "mph": 2.236_94,
    "kph": 3.6,
    "ms":  1.0,
}


class SpeedWidget(Widget):
    """
    Large digital speed readout.

    Displays the current GPS speed with a unit label beneath it.
    """

    def __init__(
        self,
        width:    int   = 200,
        height:   int   = 110,
        units:    str   = "mph",
        color:    tuple = (255, 255, 255, 240),
        bg_color: tuple = (0, 0, 0, 170),
    ) -> None:
        super().__init__(width, height)
        self.units    = units.lower()
        self.color    = color
        self.bg_color = bg_color

        self._font_num  = find_font(int(height * 0.56), bold=True)
        self._font_unit = find_font(int(height * 0.22))

    def render(self, t: float, telem) -> Image.Image:
        img  = self._blank()
        draw = ImageDraw.Draw(img)

        # Background pill
        draw.rounded_rectangle(
            [(0, 0), (self.width - 1, self.height - 1)],
            radius=12, fill=self.bg_color,
        )

        speed_ms  = telem.speed_at(t)
        factor    = _CONVERSIONS.get(self.units, 1.0)
        speed_val = speed_ms * factor

        cx = self.width  // 2
        cy = self.height // 2

        draw.text(
            (cx, int(cy * 0.88)),
            f"{speed_val:.0f}",
            font=self._font_num,
            fill=self.color,
            anchor="mm",
        )
        draw.text(
            (cx, int(self.height * 0.84)),
            self.units.upper(),
            font=self._font_unit,
            fill=(*self.color[:3], 180),
            anchor="mm",
        )

        return img
