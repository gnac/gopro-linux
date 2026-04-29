"""Telemetry loading and pre-processing."""
from __future__ import annotations

import numpy as np
from pathlib import Path

from gopro_linux.gpmf.parser import parse_gpmf_file
from gopro_linux.telemetry.models import TelemetryData
from gopro_linux.telemetry.correction import apply_mounting_correction, smooth


def load_telemetry(
    input_path: Path,
    *,
    flip_x: bool = False,
    flip_y: bool = False,
    flip_z: bool = False,
    smooth_window: int = 5,
    start: float = 0.0,
    end: float | None = None,
) -> TelemetryData:
    """
    Load GPMF telemetry from a GoPro MP4 and return a ``TelemetryData`` object.

    Parameters
    ----------
    input_path : Path
        Path to the GoPro .MP4 file.
    flip_x / flip_y / flip_z : bool
        Negate the corresponding accelerometer axis (see correction module).
    smooth_window : int
        Moving-average window for accelerometer smoothing (1 = disabled).
    start : float
        Trim start time in seconds.  Defaults to 0 (beginning of video).
    end : float or None
        Trim end time in seconds.  Defaults to None (end of video).
    """
    packets, video_info = parse_gpmf_file(input_path)

    t = TelemetryData()
    t.duration = video_info.get("duration", 0.0)
    t.fps      = video_info.get("fps",      30.0)
    t.width    = video_info.get("width",    1920)
    t.height   = video_info.get("height",   1080)

    gps_t, gps_lat, gps_lon, gps_alt, gps_spd = [], [], [], [], []
    acc_t, acc_x, acc_y, acc_z = [], [], [], []

    for pkt in packets:
        t0   = pkt.pts_seconds
        dur  = pkt.duration_seconds

        # ── GPS (GPS5 or GPS9) ────────────────────────────────────────────
        for fc in ("GPS5", "GPS9"):
            if fc not in pkt.streams:
                continue
            s = pkt.streams[fc]
            n = len(s.samples)
            if n == 0:
                break

            sc = s.scale
            if not isinstance(sc, list):
                sc = [sc] * 5
            while len(sc) < 5:
                sc.append(sc[-1])
            sc = [float(v) or 1.0 for v in sc]

            for i, sample in enumerate(s.samples):
                if not isinstance(sample, list) or len(sample) < 5:
                    continue
                ts = t0 + (i / n) * dur
                gps_t.append(ts)
                gps_lat.append(sample[0] / sc[0])
                gps_lon.append(sample[1] / sc[1])
                gps_alt.append(sample[2] / sc[2])
                gps_spd.append(sample[3] / sc[3])   # 2-D speed m/s
            break   # prefer GPS5 over GPS9 to avoid duplicates

        # ── Accelerometer (ACCL) ─────────────────────────────────────────
        if "ACCL" in pkt.streams:
            s = pkt.streams["ACCL"]
            n = len(s.samples)
            if n == 0:
                continue

            sc = s.scale
            if isinstance(sc, list):
                sc = sc[0]
            sc = float(sc) if sc else 1.0

            for i, sample in enumerate(s.samples):
                if not isinstance(sample, list) or len(sample) < 3:
                    continue
                ts = t0 + (i / n) * dur
                # GPMF ZXY order: raw[0]=Z, raw[1]=X, raw[2]=Y
                acc_t.append(ts)
                acc_z.append(sample[0] / sc)   # camera-Z (longitudinal in ZXY)
                acc_x.append(sample[1] / sc)   # camera-X (lateral)
                acc_y.append(sample[2] / sc)   # camera-Y (vertical)

    # ── Assemble GPS arrays ──────────────────────────────────────────────────
    if gps_t:
        idx = np.argsort(gps_t)
        t.gps_time  = np.array(gps_t  )[idx]
        t.gps_lat   = np.array(gps_lat)[idx]
        t.gps_lon   = np.array(gps_lon)[idx]
        t.gps_alt   = np.array(gps_alt)[idx]
        t.gps_speed = np.array(gps_spd)[idx]

    # ── Assemble ACCL arrays (with correction + smoothing) ──────────────────
    if acc_t:
        idx = np.argsort(acc_t)
        ax  = np.array(acc_x)[idx]
        ay  = np.array(acc_y)[idx]
        az  = np.array(acc_z)[idx]

        ax, ay, az = apply_mounting_correction(
            ax, ay, az,
            flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
        )

        if smooth_window > 1:
            ax = smooth(ax, smooth_window)
            ay = smooth(ay, smooth_window)
            az = smooth(az, smooth_window)

        t.accl_time = np.array(acc_t)[idx]
        t.accl_x    = ax
        t.accl_y    = ay
        t.accl_z    = az

    # ── Trim to requested window ─────────────────────────────────────────────
    trim_start = max(0.0, start)
    trim_end   = min(t.duration, end) if end is not None else t.duration

    if trim_start > 0.0 or trim_end < t.duration:
        t = t.trim(trim_start, trim_end)

    return t
