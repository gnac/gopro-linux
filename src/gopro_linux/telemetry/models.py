"""Telemetry data models."""
from __future__ import annotations
import numpy as np


class TelemetryData:
    """
    Time-indexed telemetry extracted from a GoPro video.

    All sensor arrays are parallel numpy arrays indexed by time (seconds
    from the start of the video).  Use the ``*_at(t)`` helper methods to
    interpolate values at an arbitrary video timestamp.
    """

    def __init__(self) -> None:
        # GPS / position
        self.gps_time:  np.ndarray = np.array([])   # s
        self.gps_lat:   np.ndarray = np.array([])   # degrees
        self.gps_lon:   np.ndarray = np.array([])   # degrees
        self.gps_alt:   np.ndarray = np.array([])   # metres
        self.gps_speed: np.ndarray = np.array([])   # m/s (2-D)

        # Accelerometer (after ORIN normalisation & mounting correction)
        # ZXY order → az, ax, ay  →  stored as separate arrays for clarity
        self.accl_time: np.ndarray = np.array([])   # s
        self.accl_x:    np.ndarray = np.array([])   # m/s² lateral
        self.accl_y:    np.ndarray = np.array([])   # m/s² longitudinal
        self.accl_z:    np.ndarray = np.array([])   # m/s² vertical (~+9.81 at rest)

        # Video metadata
        self.duration: float = 0.0
        self.fps:      float = 30.0
        self.width:    int   = 1920
        self.height:   int   = 1080

    # ── Presence checks ──────────────────────────────────────────────────────

    def has_gps(self) -> bool:
        return len(self.gps_time) > 1

    def has_accl(self) -> bool:
        return len(self.accl_time) > 1

    # ── Interpolation helpers ────────────────────────────────────────────────

    def speed_at(self, t: float) -> float:
        """GPS speed in m/s at video time *t*."""
        if not self.has_gps():
            return 0.0
        return float(np.interp(t, self.gps_time, self.gps_speed))

    def alt_at(self, t: float) -> float:
        """GPS altitude in metres at video time *t*."""
        if not self.has_gps():
            return 0.0
        return float(np.interp(t, self.gps_time, self.gps_alt))

    def gps_at(self, t: float) -> tuple[float, float]:
        """(latitude, longitude) in degrees at video time *t*."""
        if not self.has_gps():
            return 0.0, 0.0
        return (
            float(np.interp(t, self.gps_time, self.gps_lat)),
            float(np.interp(t, self.gps_time, self.gps_lon)),
        )

    def accl_at(self, t: float) -> tuple[float, float, float]:
        """(ax, ay, az) in m/s² at video time *t*."""
        if not self.has_accl():
            return 0.0, 0.0, 9.81
        return (
            float(np.interp(t, self.accl_time, self.accl_x)),
            float(np.interp(t, self.accl_time, self.accl_y)),
            float(np.interp(t, self.accl_time, self.accl_z)),
        )

    def lateral_g_at(self, t: float) -> float:
        """Lateral g-force at *t* (positive = rightward)."""
        ax, _, _ = self.accl_at(t)
        return ax / 9.80665

    def longitudinal_g_at(self, t: float) -> float:
        """Longitudinal g-force at *t* (positive = forward acceleration)."""
        _, ay, _ = self.accl_at(t)
        return ay / 9.80665
