"""FFmpeg integration: pipe RGBA overlay frames into the encoder."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

from gopro_linux.telemetry.models import TelemetryData
from gopro_linux.overlay.renderer import OverlayRenderer


def render_to_video(
    input_path:  Path,
    output_path: Path,
    telem:       TelemetryData,
    renderer:    OverlayRenderer,
    *,
    crf:     int  = 23,
    preset:  str  = "medium",
    gpu:     bool = False,
    verbose: bool = False,
) -> None:
    """
    Render the overlay onto *input_path* and write to *output_path*.

    Pipeline
    --------
    Python generates RGBA frames (one per video frame) and writes them to
    FFmpeg's stdin.  FFmpeg reads the original video from the file path and
    uses the ``overlay`` filter to composite both streams, then encodes to
    H.264 while copying audio losslessly.

    Parameters
    ----------
    input_path : Path
        Original GoPro MP4.
    output_path : Path
        Destination MP4 (will be overwritten if it exists).
    telem : TelemetryData
        Parsed telemetry (used for duration / fps / resolution).
    renderer : OverlayRenderer
        Widget compositor configured for this video.
    crf : int
        H.264 Constant Rate Factor (18 = near-lossless, 28 = low quality).
    preset : str
        FFmpeg speed/compression preset.
    gpu : bool
        Use NVIDIA NVENC instead of libx264.
    verbose : bool
        Pass FFmpeg output through to stderr.
    """
    w   = telem.width
    h   = telem.height
    fps = telem.fps

    video_codec = "h264_nvenc" if gpu else "libx264"

    cmd = [
        "ffmpeg", "-y",
        # Input 0: original video (from file)
        "-i", str(input_path),
        # Input 1: RGBA overlay frames from Python via stdin
        # Use the standard -pix_fmt / -s / -r forms; the AVOption aliases
        # (-pixel_format, -video_size, -framerate) are not reliably accepted
        # by all FFmpeg builds when passed before -i for rawvideo input.
        "-f",      "rawvideo",
        "-pix_fmt","rgba",
        "-s",      f"{w}x{h}",
        "-r",      f"{fps:.6f}",
        "-i",      "pipe:0",
        # Composite: overlay[1] on top of video[0].
        # The explicit format=yuv420p conversion drops the deprecated yuvj420p
        # pixel format (JPEG full-range YUV) that GoPro cameras produce, which
        # causes FFmpeg to warn "deprecated pixel format used, make sure you did
        # set range correctly" — especially with NVENC.
        "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1,format=yuv420p",
        # Audio: copy from source unchanged
        "-map", "0:a?",
        # Encode
        "-c:v", video_codec,
        "-preset", preset,
        # libx264 uses -crf for constant quality; NVENC uses -cq.
        # Both accept the same 0-51 scale (lower = better quality).
        *([ "-cq",  str(crf)] if gpu else ["-crf", str(crf)]),
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(output_path),
    ]

    if not verbose:
        cmd = [cmd[0]] + ["-v", "warning", "-stats"] + cmd[1:]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stderr=(None if verbose else sys.stderr),
    )

    duration  = telem.duration
    n_frames  = max(1, int(duration * fps))
    log_every = max(1, int(fps))   # log once per second

    try:
        for idx in range(n_frames):
            t   = idx / fps
            img = renderer.render_frame(t, telem)
            proc.stdin.write(img.tobytes())

            if idx % log_every == 0:
                pct = t / duration * 100 if duration else 0
                print(f"\r  {t:6.1f}s / {duration:.1f}s  ({pct:3.0f}%)",
                      end="", flush=True)

        print()  # newline after progress line
        proc.stdin.close()
        proc.wait()

    except BaseException:
        # Kill FFmpeg on any failure (render error, KeyboardInterrupt, etc.)
        # so it doesn't block waiting for more stdin data and produce an empty file.
        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.kill()
        proc.wait()
        raise

    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg exited with code {proc.returncode}. "
            "Re-run with --verbose to see the full FFmpeg log."
        )
