"""Base widget class and font helpers."""
from __future__ import annotations
from abc import ABC, abstractmethod
import os
from PIL import Image, ImageFont


_FONT_CANDIDATES = [
    # Noto (common across many distros)
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    # DejaVu (very common)
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    # Ubuntu
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    # Liberation
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Roboto
    "/usr/share/fonts/truetype/roboto/Roboto-Bold.ttf",
    "/usr/share/fonts/truetype/roboto/Roboto-Regular.ttf",
    "/usr/share/fonts/TTF/Roboto-Bold.ttf",
    "/usr/share/fonts/TTF/Roboto-Regular.ttf",
]


def find_font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    """Return the best available system TrueType font at *size* pt."""
    for path in _FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        # Prefer bold candidates first when bold=True
        if bold and "Bold" not in path and "B.ttf" not in path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    # Try any existing font regardless of bold preference
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # Absolute fallback: PIL built-in bitmap font (ugly but functional)
    return ImageFont.load_default()


class Widget(ABC):
    """Base class for RGBA overlay widgets."""

    def __init__(self, width: int, height: int) -> None:
        self.width  = int(width)
        self.height = int(height)

    def _blank(self) -> Image.Image:
        return Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))

    @abstractmethod
    def render(self, t: float, telem) -> Image.Image:
        """
        Render this widget at video time *t* seconds.

        Parameters
        ----------
        t : float
            Current video timestamp (seconds from the start).
        telem : TelemetryData
            Telemetry data object for the current video.

        Returns
        -------
        PIL RGBA Image of size ``(self.width, self.height)``.
        """
