"""Command-line interface."""
from __future__ import annotations
import csv
import sys
from pathlib import Path
from typing import Optional

import click

from gopro_linux.telemetry import load_telemetry
from gopro_linux.overlay.renderer import OverlayRenderer
from gopro_linux.ffmpeg import render_to_video


# ── shared options ────────────────────────────────────────────────────────────

_flip_options = [
    click.option("--flip", is_flag=True, default=False,
                 help="Correct g-forces for upside-down camera mounting "
                      "(negates lateral X and vertical Z axes). "
                      "Use when the camera body is flipped 180° around the "
                      "lens axis, e.g. mounted on a roll cage or windshield "
                      "top."),
    click.option("--flip-x", is_flag=True, default=False,
                 help="Negate the lateral (X) g-force axis independently."),
    click.option("--flip-y", is_flag=True, default=False,
                 help="Negate the longitudinal (Y) g-force axis independently."),
    click.option("--flip-z", is_flag=True, default=False,
                 help="Negate the vertical (Z) g-force axis independently."),
]


def _add_options(options):
    def decorator(f):
        for opt in reversed(options):
            f = opt(f)
        return f
    return decorator


def _resolve_flip(flip, flip_x, flip_y, flip_z):
    """--flip is shorthand for --flip-x --flip-z (upside-down lens-axis rotation)."""
    if flip:
        flip_x = flip_z = True
    return flip_x, flip_y, flip_z


# ── CLI root ──────────────────────────────────────────────────────────────────

@click.group()
@click.version_option()
def main():
    """GoPro telemetry overlay tool for Linux.

    Reads GPMF telemetry (GPS, accelerometer) embedded in GoPro MP4 files and
    renders configurable overlays: speed, g-force circle, GPS track map.

    \b
    Quick start:
        gopro-overlay overlay GH010123.MP4 out.mp4
        gopro-overlay overlay GH010123.MP4 out.mp4 --flip   # upside-down mount
        gopro-overlay extract GH010123.MP4                  # dump to CSV
    """


# ── overlay command ───────────────────────────────────────────────────────────

@main.command()
@click.argument("input",  type=click.Path(exists=True,  path_type=Path))
@click.argument("output", type=click.Path(              path_type=Path))
@_add_options(_flip_options)
@click.option("--units", default="mph", show_default=True,
              type=click.Choice(["mph", "kph", "ms"], case_sensitive=False),
              help="Speed display units.")
@click.option("--no-speed",  is_flag=True, default=False, help="Hide speed widget.")
@click.option("--no-gforce", is_flag=True, default=False, help="Hide g-force widget.")
@click.option("--no-track",  is_flag=True, default=False, help="Hide GPS track widget.")
@click.option("--smooth", default=5, show_default=True, metavar="N",
              help="Accelerometer moving-average window (samples). 1 = off.")
@click.option("--crf", default=23, show_default=True,
              help="H.264 quality (18 = near-lossless … 28 = small file).")
@click.option("--preset", default="medium", show_default=True,
              type=click.Choice(["ultrafast","superfast","veryfast","faster",
                                 "fast","medium","slow","slower","veryslow"]),
              help="FFmpeg encoding speed/quality preset.")
@click.option("--gpu", is_flag=True, default=False,
              help="Use NVIDIA NVENC GPU encoder (requires NVENC support).")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show FFmpeg output.")
def overlay(
    input: Path, output: Path,
    flip: bool, flip_x: bool, flip_y: bool, flip_z: bool,
    units: str,
    no_speed: bool, no_gforce: bool, no_track: bool,
    smooth: int,
    crf: int, preset: str, gpu: bool, verbose: bool,
):
    """Add telemetry overlays to a GoPro video.

    \b
    INPUT   GoPro MP4 source file
    OUTPUT  Output video file path

    \b
    Examples:
      gopro-overlay overlay GH010123.MP4 out.mp4
      gopro-overlay overlay GH010123.MP4 out.mp4 --flip --units kph
      gopro-overlay overlay GH010123.MP4 out.mp4 --no-track --crf 18
    """
    flip_x, flip_y, flip_z = _resolve_flip(flip, flip_x, flip_y, flip_z)

    click.echo(f"Loading telemetry from {input.name} …")
    try:
        telem = load_telemetry(
            input,
            flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
            smooth_window=smooth,
        )
    except Exception as exc:
        click.echo(f"Error loading telemetry: {exc}", err=True)
        sys.exit(1)

    # ── Summary ───────────────────────────────────────────────────────────
    click.echo(
        f"  Video  : {telem.width}x{telem.height} @ {telem.fps:.2f} fps  "
        f"duration {telem.duration:.1f}s"
    )
    if telem.has_gps():
        hz = len(telem.gps_time) / max(telem.duration, 1)
        click.echo(f"  GPS    : {len(telem.gps_time)} samples  (~{hz:.0f} Hz)")
    else:
        click.echo("  GPS    : no data found")

    if telem.has_accl():
        hz = len(telem.accl_time) / max(telem.duration, 1)
        click.echo(f"  ACCL   : {len(telem.accl_time)} samples  (~{hz:.0f} Hz)")
        if flip_x or flip_y or flip_z:
            axes = [a for a, f in [("X", flip_x), ("Y", flip_y), ("Z", flip_z)] if f]
            click.echo(f"  Mounting correction: negated {', '.join(axes)}")
    else:
        click.echo("  ACCL   : no data found")

    # ── Build renderer ────────────────────────────────────────────────────
    renderer = OverlayRenderer.default_layout(
        telem,
        speed_units=units,
        show_speed=not no_speed,
        show_gforce=not no_gforce,
        show_track=not no_track,
    )

    click.echo(f"Rendering to {output} …")
    try:
        render_to_video(
            input, output, telem, renderer,
            crf=crf, preset=preset, gpu=gpu, verbose=verbose,
        )
    except Exception as exc:
        click.echo(f"Render error: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Done  →  {output}")


# ── extract command ───────────────────────────────────────────────────────────

@main.command()
@click.argument("input", type=click.Path(exists=True, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), default=None,
              help="Output CSV path (default: <input>.csv).")
@_add_options(_flip_options)
@click.option("--hz", default=10.0, show_default=True,
              help="Sampling rate for CSV output (samples per second).")
def extract(
    input: Path,
    output: Optional[Path],
    flip: bool, flip_x: bool, flip_y: bool, flip_z: bool,
    hz: float,
):
    """Extract GPMF telemetry to a CSV file.

    \b
    INPUT   GoPro MP4 source file

    \b
    Examples:
      gopro-overlay extract GH010123.MP4
      gopro-overlay extract GH010123.MP4 -o laps/lap1.csv --flip
    """
    flip_x, flip_y, flip_z = _resolve_flip(flip, flip_x, flip_y, flip_z)

    if output is None:
        output = input.with_suffix(".csv")

    click.echo(f"Loading telemetry from {input.name} …")
    try:
        telem = load_telemetry(input, flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
                               smooth_window=1)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    n = max(1, int(telem.duration * hz))

    with open(output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "time_s",
            "lat_deg", "lon_deg", "alt_m",
            "speed_ms", "speed_mph", "speed_kph",
            "accl_x_ms2", "accl_y_ms2", "accl_z_ms2",
            "lateral_g", "longitudinal_g",
        ])
        for i in range(n):
            t        = i / hz
            lat, lon = telem.gps_at(t)
            spd      = telem.speed_at(t)
            alt      = telem.alt_at(t)
            ax, ay, az = telem.accl_at(t)
            writer.writerow([
                f"{t:.2f}",
                f"{lat:.7f}", f"{lon:.7f}", f"{alt:.2f}",
                f"{spd:.4f}", f"{spd * 2.23694:.3f}", f"{spd * 3.6:.3f}",
                f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
                f"{ax / 9.80665:.4f}", f"{ay / 9.80665:.4f}",
            ])

    click.echo(f"Saved {n} rows @ {hz} Hz  →  {output}")
