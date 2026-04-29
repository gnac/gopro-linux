"""Command-line interface."""
from __future__ import annotations
import csv
import sys
from pathlib import Path
from typing import Optional

import click


def _parse_time(value: str) -> float:
    """
    Parse an FFmpeg-style time string to seconds.

    Accepted formats (matching FFmpeg's -ss / -to syntax):
        90          pure seconds (int or float)
        1:30        MM:SS
        1:30.5      MM:SS.mmm
        1:30:00     HH:MM:SS
        1:30:00.5   HH:MM:SS.mmm
    """
    value = value.strip()
    # Pure number
    try:
        return float(value)
    except ValueError:
        pass
    # [HH:]MM:SS[.mmm]
    parts = value.split(":")
    try:
        parts = [float(p) for p in parts]
        if len(parts) == 2:
            return parts[0] * 60.0 + parts[1]
        if len(parts) == 3:
            return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
    except ValueError:
        pass
    raise click.BadParameter(
        f"Cannot parse time {value!r}. Use seconds (90.5) or [HH:]MM:SS."
    )

from gopro_linux.telemetry import load_telemetry
from gopro_linux.overlay.renderer import OverlayRenderer
from gopro_linux.ffmpeg import render_to_video


# ── shared option lists ───────────────────────────────────────────────────────

_flip_options = [
    click.option("--flip", is_flag=True, default=False,
                 help="Correct g-forces for upside-down camera mounting "
                      "(negates lateral X and vertical Z axes). "
                      "Use when the camera body is flipped 180° around the "
                      "lens axis, e.g. mounted on a roll cage or windshield top."),
    click.option("--flip-x", is_flag=True, default=False,
                 help="Negate the lateral (X) g-force axis independently."),
    click.option("--flip-y", is_flag=True, default=False,
                 help="Negate the longitudinal (Y) g-force axis independently."),
    click.option("--flip-z", is_flag=True, default=False,
                 help="Negate the vertical (Z) g-force axis independently."),
]

_render_options = [
    click.option("--units", default="mph", show_default=True,
                 type=click.Choice(["mph", "kph", "ms"], case_sensitive=False),
                 help="Speed display units."),
    click.option("--no-speed",       is_flag=True, default=False, help="Hide speed widget."),
    click.option("--no-gforce",      is_flag=True, default=False, help="Hide g-force widget."),
    click.option("--no-track",       is_flag=True, default=False, help="Hide GPS track widget."),
    click.option("--no-speed-graph", is_flag=True, default=False, help="Hide speed timeline graph."),
    click.option("--smooth", default=5, show_default=True, metavar="N",
                 help="Accelerometer moving-average window (samples). 1 = off."),
    click.option("--crf", default=23, show_default=True,
                 help="H.264 quality (18 = near-lossless … 28 = small file)."),
    click.option("--preset", default="medium", show_default=True,
                 type=click.Choice(["ultrafast", "superfast", "veryfast", "faster",
                                    "fast", "medium", "slow", "slower", "veryslow"]),
                 help="FFmpeg encoding speed/quality preset."),
    click.option("--gpu", is_flag=True, default=False,
                 help="Use NVIDIA NVENC GPU encoder (requires NVENC support)."),
]


def _add_options(options):
    def decorator(f):
        for opt in reversed(options):
            f = opt(f)
        return f
    return decorator


def _resolve_trim(start_str: Optional[str], end_str: Optional[str]) -> tuple[float, Optional[float]]:
    """Parse --start / --end strings into (start_seconds, end_seconds_or_None)."""
    start = _parse_time(start_str) if start_str else 0.0
    end   = _parse_time(end_str)   if end_str   else None
    return start, end


def _resolve_flip(flip, flip_x, flip_y, flip_z):
    """--flip is shorthand for --flip-x --flip-z (upside-down lens-axis rotation)."""
    if flip:
        flip_x = flip_z = True
    return flip_x, flip_y, flip_z


# ── shared rendering helper ───────────────────────────────────────────────────

def _render_one(
    input_path:     Path,
    output_path:    Path,
    *,
    flip_x:         bool,
    flip_y:         bool,
    flip_z:         bool,
    units:          str,
    no_speed:       bool,
    no_gforce:      bool,
    no_track:       bool,
    no_speed_graph: bool,
    smooth:         int,
    crf:            int,
    preset:         str,
    gpu:            bool,
    verbose:        bool,
    start:          float        = 0.0,
    end:            Optional[float] = None,
    label:          str          = "",
) -> bool:
    """
    Load telemetry for *input_path*, render the overlay, and write *output_path*.

    Returns True on success, False on any failure (errors are printed but not
    re-raised so that batch processing can continue past individual failures).
    """
    prefix = f"[{label}] " if label else ""

    click.echo(f"{prefix}Loading telemetry from {input_path.name} …")
    try:
        telem = load_telemetry(
            input_path,
            flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
            smooth_window=smooth,
            start=start,
            end=end,
        )
    except Exception as exc:
        click.echo(f"{prefix}Error loading telemetry: {exc}", err=True)
        return False

    click.echo(
        f"{prefix}  Video  : {telem.width}x{telem.height} @ {telem.fps:.2f} fps  "
        f"duration {telem.duration:.1f}s"
    )
    if start > 0.0 or end is not None:
        t_end = end if end is not None else start + telem.duration
        click.echo(f"{prefix}  Trim   : {start:.1f}s → {t_end:.1f}s")
    if telem.has_gps():
        hz = len(telem.gps_time) / max(telem.duration, 1)
        click.echo(f"{prefix}  GPS    : {len(telem.gps_time)} samples  (~{hz:.0f} Hz)")
    else:
        click.echo(f"{prefix}  GPS    : no data found")

    if telem.has_accl():
        hz = len(telem.accl_time) / max(telem.duration, 1)
        click.echo(f"{prefix}  ACCL   : {len(telem.accl_time)} samples  (~{hz:.0f} Hz)")
        if flip_x or flip_y or flip_z:
            axes = [a for a, f in [("X", flip_x), ("Y", flip_y), ("Z", flip_z)] if f]
            click.echo(f"{prefix}  Mounting correction: negated {', '.join(axes)}")
    else:
        click.echo(f"{prefix}  ACCL   : no data found")

    renderer = OverlayRenderer.default_layout(
        telem,
        speed_units=units,
        show_speed=not no_speed,
        show_gforce=not no_gforce,
        show_track=not no_track,
        show_speed_graph=not no_speed_graph,
    )

    click.echo(f"{prefix}Rendering to {output_path} …")
    try:
        render_to_video(
            input_path, output_path, telem, renderer,
            crf=crf, preset=preset, gpu=gpu, verbose=verbose,
            start=start, end=end,
        )
    except Exception as exc:
        click.echo(f"{prefix}Render error: {exc}", err=True)
        return False

    click.echo(f"{prefix}Done  →  {output_path}")
    return True


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
        gopro-overlay batch   Videos/ --flip --output-dir processed/
        gopro-overlay extract GH010123.MP4                  # dump to CSV
    """


# ── overlay command ───────────────────────────────────────────────────────────

@main.command()
@click.argument("input",  type=click.Path(exists=True, path_type=Path))
@click.argument("output", type=click.Path(path_type=Path))
@_add_options(_flip_options)
@_add_options(_render_options)
@click.option("--start", "start_str", default=None, metavar="TIME",
              help="Trim start time — seconds (90) or [HH:]MM:SS (1:30). "
                   "Default: beginning of video.")
@click.option("--end", "end_str", default=None, metavar="TIME",
              help="Trim end time — seconds (270) or [HH:]MM:SS (4:30). "
                   "Default: end of video.")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show FFmpeg output.")
def overlay(
    input: Path, output: Path,
    flip: bool, flip_x: bool, flip_y: bool, flip_z: bool,
    units: str,
    no_speed: bool, no_gforce: bool, no_track: bool, no_speed_graph: bool,
    smooth: int, crf: int, preset: str, gpu: bool,
    start_str: Optional[str], end_str: Optional[str],
    verbose: bool,
):
    """Add telemetry overlays to a GoPro video.

    \b
    INPUT   GoPro MP4 source file
    OUTPUT  Output video file path

    \b
    Examples:
      gopro-overlay overlay GH010123.MP4 out.mp4
      gopro-overlay overlay GH010123.MP4 out.mp4 --flip --units kph
      gopro-overlay overlay GH010123.MP4 out.mp4 --start 1:30 --end 4:45
    """
    flip_x, flip_y, flip_z = _resolve_flip(flip, flip_x, flip_y, flip_z)
    start, end = _resolve_trim(start_str, end_str)

    ok = _render_one(
        input, output,
        flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
        units=units,
        no_speed=no_speed, no_gforce=no_gforce,
        no_track=no_track, no_speed_graph=no_speed_graph,
        smooth=smooth, crf=crf, preset=preset, gpu=gpu,
        verbose=verbose,
        start=start, end=end,
    )
    if not ok:
        sys.exit(1)


# ── batch command ─────────────────────────────────────────────────────────────

@main.command()
@click.argument("inputs", nargs=-1, required=True,
                type=click.Path(exists=True, path_type=Path))
@_add_options(_flip_options)
@_add_options(_render_options)
@click.option("--output-dir", "-d", type=click.Path(path_type=Path), default=None,
              help="Directory for all output files. "
                   "Default: write each output alongside its input.")
@click.option("--suffix", default="_overlay", show_default=True,
              help="String appended to the input stem to form the output filename. "
                   "e.g. GH010123_overlay.mp4")
@click.option("--pattern", default="*.MP4", show_default=True,
              help="Glob pattern used when scanning a directory input.")
@click.option("--skip-existing", is_flag=True, default=False,
              help="Skip a file if its output already exists.")
@click.option("--start", "start_str", default=None, metavar="TIME",
              help="Trim start time applied to every file (seconds or [HH:]MM:SS).")
@click.option("--end", "end_str", default=None, metavar="TIME",
              help="Trim end time applied to every file (seconds or [HH:]MM:SS).")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show FFmpeg output for each file.")
def batch(
    inputs: tuple[Path, ...],
    flip: bool, flip_x: bool, flip_y: bool, flip_z: bool,
    units: str,
    no_speed: bool, no_gforce: bool, no_track: bool, no_speed_graph: bool,
    smooth: int, crf: int, preset: str, gpu: bool,
    output_dir: Optional[Path],
    suffix: str,
    pattern: str,
    skip_existing: bool,
    start_str: Optional[str], end_str: Optional[str],
    verbose: bool,
):
    """Process multiple GoPro videos in one run.

    INPUTS can be any mix of individual MP4 files and/or directories.
    When a directory is given, every file matching --pattern inside it
    (non-recursively) is queued.

    \b
    Examples:
      # All MP4s in a folder
      gopro-overlay batch Videos/ --flip

      # Two specific files
      gopro-overlay batch GH010150.MP4 GH010167.MP4 --output-dir processed/

      # Full session with GPU encoding, skip already-done files
      gopro-overlay batch Videos/ --flip --gpu --output-dir processed/ --skip-existing

      # Recurse manually with find (shell glob expansion)
      gopro-overlay batch Videos/**/*.MP4 --output-dir processed/
    """
    flip_x, flip_y, flip_z = _resolve_flip(flip, flip_x, flip_y, flip_z)
    start, end = _resolve_trim(start_str, end_str)

    # ── Collect the file list ─────────────────────────────────────────────
    queue: list[Path] = []
    for inp in inputs:
        if inp.is_dir():
            found = sorted(inp.glob(pattern))
            if not found:
                click.echo(f"Warning: no files matching '{pattern}' in {inp}", err=True)
            queue.extend(found)
        else:
            queue.append(inp)

    if not queue:
        click.echo("No input files found.", err=True)
        sys.exit(1)

    # ── Resolve output directory ──────────────────────────────────────────
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    # ── Build the (input, output) work list ───────────────────────────────
    work: list[tuple[Path, Path]] = []
    for src in queue:
        dest_dir = output_dir if output_dir is not None else src.parent
        dest     = dest_dir / f"{src.stem}{suffix}.mp4"
        work.append((src, dest))

    # ── Skip-existing filter ──────────────────────────────────────────────
    if skip_existing:
        before = len(work)
        work   = [(s, d) for s, d in work if not d.exists()]
        skipped = before - len(work)
        if skipped:
            click.echo(f"Skipping {skipped} file(s) whose output already exists.")

    if not work:
        click.echo("Nothing to do.")
        return

    total = len(work)
    click.echo(f"Queued {total} file(s).\n")

    # ── Process files sequentially ────────────────────────────────────────
    succeeded, failed = 0, 0
    failures: list[str] = []

    for i, (src, dest) in enumerate(work, start=1):
        click.echo(f"── File {i}/{total} ──────────────────────────────")
        ok = _render_one(
            src, dest,
            flip_x=flip_x, flip_y=flip_y, flip_z=flip_z,
            units=units,
            no_speed=no_speed, no_gforce=no_gforce,
            no_track=no_track, no_speed_graph=no_speed_graph,
            smooth=smooth, crf=crf, preset=preset, gpu=gpu,
            verbose=verbose,
            start=start, end=end,
            label=f"{i}/{total}",
        )
        if ok:
            succeeded += 1
        else:
            failed += 1
            failures.append(src.name)
        click.echo()

    # ── Summary ───────────────────────────────────────────────────────────
    click.echo("── Batch complete ───────────────────────────────────")
    click.echo(f"  Succeeded : {succeeded}")
    click.echo(f"  Failed    : {failed}")
    if failures:
        click.echo("  Failed files:")
        for name in failures:
            click.echo(f"    • {name}", err=True)

    if failed:
        sys.exit(1)


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
            t          = i / hz
            lat, lon   = telem.gps_at(t)
            spd        = telem.speed_at(t)
            alt        = telem.alt_at(t)
            ax, ay, az = telem.accl_at(t)
            writer.writerow([
                f"{t:.2f}",
                f"{lat:.7f}", f"{lon:.7f}", f"{alt:.2f}",
                f"{spd:.4f}", f"{spd * 2.23694:.3f}", f"{spd * 3.6:.3f}",
                f"{ax:.4f}", f"{ay:.4f}", f"{az:.4f}",
                f"{ax / 9.80665:.4f}", f"{ay / 9.80665:.4f}",
            ])

    click.echo(f"Saved {n} rows @ {hz} Hz  →  {output}")
