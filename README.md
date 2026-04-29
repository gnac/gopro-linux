# gopro-linux

A (Linux) command-line tool for adding telemetry overlays to GoPro videos.
There are many overlay tools, but this one is mine, and it works on Linux with a minimum of fuss.
Reads the embedded GPMF metadata track (GPS, accelerometer) and renders
configurable widgets onto the video using FFmpeg.

## What it does

| Widget | Data source | Notes |
|---|---|---|
| **Speed** | GPS 2-D speed | Selectable mph / kph / m/s |
| **G-force circle** | Accelerometer (ACCL) | Lateral vs longitudinal, with fading trail |
| **GPS track map** | GPS5 / GPS9 | Full track with live position dot, adjustable smoothing |
| **Speed Graphs** | GPS 2-D speed | Graph of speed over time during the video |

These are the similar to the overlays (aka stickers) available in the GoPro Quik app, but running
entirely on Linux. No GoPro account or smart phone required. 
The GForce overlay also can be "flipped" to account for camera orientation using the `--flip` flag.
The GoPro app doesn't account for this when displaying the 
GForce sticker, so your GForce remains inverted on GoPro Quick generated videos.

## Requirements

- Linux
  - This may also work on Windows (because python) but I have no way of verifying this.

- Python 3.10+
- `ffmpeg` and `ffprobe` (must be on `$PATH`)
- `libraqm` (for Pillow complex-text shaping — usually already installed)
- A system TrueType font (DejaVu, Noto, Ubuntu, Roboto, or Liberation)

Install FFmpeg on Arch:   `sudo pacman -S ffmpeg`
Install FFmpeg on Debian: `sudo apt install ffmpeg`

## Installation

```bash
cd ~/src/gopro-linux
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The `gopro-overlay` command is now available inside the venv.

## Usage

### Add overlays to a single video

```bash
# Default layout
gopro-overlay overlay GH010123.MP4 out.mp4

# Camera mounted upside-down — corrects g-force axes (negates X and Z)
gopro-overlay overlay GH010123.MP4 out.mp4 --flip

# Speed in km/h, skip the track map
gopro-overlay overlay GH010123.MP4 out.mp4 --units kph --no-track

# Higher quality output
gopro-overlay overlay GH010123.MP4 out.mp4 --crf 18 --preset slow

# NVIDIA GPU encoding (requires NVENC)
gopro-overlay overlay GH010123.MP4 out.mp4 --gpu
```

### Extract telemetry to CSV

```bash
gopro-overlay extract GH010123.MP4               # saves GH010123.csv
gopro-overlay extract GH010123.MP4 -o lap1.csv   # custom output path
gopro-overlay extract GH010123.MP4 --flip        # with mounting correction
```

The CSV contains: `time_s, lat_deg, lon_deg, alt_m, speed_ms, speed_mph,
speed_kph, accl_x_ms2, accl_y_ms2, accl_z_ms2, lateral_g, longitudinal_g`

### Trim a video before processing

The `--start` and `--end` flags accept seconds or `[HH:]MM:SS` format,
matching FFmpeg's own `-ss`/`-to` syntax.  The telemetry is sliced to the
same window, so the speed graph, g-force trail, and track position all
reflect only the trimmed section.

```bash
# Trim to a single lap (1 min 30 s → 4 min 45 s)
gopro-overlay overlay GH010123.MP4 lap1.mp4 --start 1:30 --end 4:45

# Start 90 seconds in, run to the end of the file
gopro-overlay overlay GH010123.MP4 out.mp4 --start 90

# Trim using plain seconds (decimals accepted)
gopro-overlay overlay GH010123.MP4 out.mp4 --start 12.5 --end 187.0

# Trim + flip + GPU in one pass
gopro-overlay overlay GH010123.MP4 lap1.mp4 --start 1:30 --end 4:45 --flip --gpu
```

> **Note on seek accuracy** — `--start` uses FFmpeg's fast keyframe seek,
> which is accurate to within one GOP (typically < 0.5 s on GoPro footage).
> This is precise enough for lap-level trimming.  If you need frame-exact
> trimming, pre-trim the source with `ffmpeg -ss … -to … -c copy` first,
> then run `gopro-overlay overlay` on the result without `--start`/`--end`.

### Batch processing

The `batch` command processes multiple files in a single run.  `INPUTS` can
be any mix of individual MP4 files and directories; directories are scanned
with `--pattern` (default `*.MP4`).

```bash
# All MP4s in a folder, outputs written alongside originals as *_overlay.mp4
gopro-overlay batch Videos/ --flip

# Write all outputs to a separate directory
gopro-overlay batch Videos/ --output-dir processed/ --flip

# Two specific files
gopro-overlay batch GH010150.MP4 GH010167.MP4 --output-dir processed/

# Custom output filename suffix
gopro-overlay batch Videos/ --output-dir processed/ --suffix _telemetry

# GPU encoding, skip files already rendered
gopro-overlay batch Videos/ --output-dir processed/ --flip --gpu --skip-existing

# Trim the same window from every file in the batch (e.g. skip a 30 s pre-roll)
gopro-overlay batch Videos/ --output-dir processed/ --start 0:30

# Scan for lower-case extensions or a different format
gopro-overlay batch Videos/ --pattern "*.mp4" --output-dir processed/
```

#### Batch output naming

Each output filename is formed as `{input_stem}{suffix}.mp4`.  With the
default `--suffix _overlay`:

```
Videos/GH010150.MP4  →  processed/GH010150_overlay.mp4
Videos/GH010167.MP4  →  processed/GH010167_overlay.mp4
```

#### Resuming an interrupted batch

`--skip-existing` checks whether the output path already exists before
processing each file, making it safe to re-run the same command after an
interruption:

```bash
gopro-overlay batch Videos/ --output-dir processed/ --skip-existing
```

#### Error handling

If one file fails (corrupt data, missing GPS, etc.) the error is printed and
the batch continues.  A summary of successes and failures is printed at the
end, and the exit code is non-zero if any file failed.

## Upside-down mounting

GoPro cameras store accelerometer data in **ZXY order** (camera-Z,
camera-X, camera-Y) in m/s².  When the camera is mounted upside-down
(rotated 180° around the lens axis — typical for roll-cage or top-of-windshield
mounts), the **X** (lateral) and **Z** (stored-vertical) axes are negated.

`--flip` applies this correction automatically.  You can also control each
axis independently:

```bash
--flip-x   negate lateral axis only
--flip-y   negate longitudinal axis only
--flip-z   negate vertical axis only
```

## All options

```
gopro-overlay overlay --help
gopro-overlay batch   --help
gopro-overlay extract --help
```

## Project structure

```
src/gopro_linux/
├── gpmf/
│   └── parser.py        Binary GPMF KLV parser (no C extension required)
├── telemetry/
│   ├── models.py        TelemetryData with numpy time-series + interpolation + trim()
│   ├── correction.py    Axis-negation corrections for mounting orientation
│   └── __init__.py      load_telemetry() — parses, corrects, smooths, trims
├── overlay/
│   ├── renderer.py      Composites widgets into RGBA frames
│   └── widgets/
│       ├── base.py         Widget ABC + system font finder
│       ├── gforce.py       G-force scatter circle with EMA smoothing
│       ├── speed.py        Digital speed readout
│       ├── speed_graph.py  Full-duration speed timeline with live cursor
│       └── track.py        GPS track map with PCA rotation and north arrow
├── ffmpeg.py            Pipes RGBA overlay frames into FFmpeg for encoding
└── cli.py               Click CLI: overlay / batch / extract commands
```

## Supported cameras

Theortically this should work with any GoPro that embeds GPMF telemetry — Hero 5 through Hero 13 and beyond,
including GPS5 (older) and GPS9 (Hero 11+) stream formats.
Only tested on a GoPro Hero 10. Feel free to donate additional cameras for testing.

## Performance

Rendering is CPU-bound.  Expect roughly 1× real-time on a modern i7 (a
10-minute video takes ~10 minutes).  Use `--preset fast` or `--gpu` to
speed things up at the cost of slightly larger files.
