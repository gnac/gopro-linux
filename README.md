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
| **Speed Grapsh** | GPS 2-D speed | Graph of speed over time during the video |

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

### Add overlays to a video

```bash
# Default layout (speed bottom-left, g-force circle bottom-right, track top-right)
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

### Batch processing
Same options as above, but can be applied all videos ina directory.
```bash
# default layout
gopro-overlay batch   Videos/ --output-dir processed/

# NVIDIA GPU encoding with axis correction.
gopro-overlay batch Videos/ --output-dir processed/ --flip --gpu
```

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
gopro-overlay extract --help
gopro-overlay batch --help
```

## Project structure

```
src/gopro_linux/
├── gpmf/
│   └── parser.py        Binary GPMF KLV parser (no C extension required)
├── telemetry/
│   ├── models.py        TelemetryData with numpy time-series + interpolation
│   ├── correction.py    Axis-negation corrections for mounting orientation
│   └── __init__.py      load_telemetry() convenience function
├── overlay/
│   ├── renderer.py      Composites widgets into RGBA frames
│   └── widgets/
│       ├── base.py         Widget ABC + system font finder
│       ├── gforce.py       G-force scatter circle
│       ├── speed.py        Digital speed readout
│       ├── speed_graph.py  Live update Speed Graph
│       └── track.py        GPS track map
├── ffmpeg.py            Pipes RGBA frames into FFmpeg for encoding
└── cli.py               Click CLI (overlay / extract commands)
```

## Supported cameras

Theortically this should work with any GoPro that embeds GPMF telemetry — Hero 5 through Hero 13 and beyond,
including GPS5 (older) and GPS9 (Hero 11+) stream formats.
Only tested on a GoPro Hero 10. Feel free to donate additional cameras for testing.

## Performance

Rendering is CPU-bound.  Expect roughly 1× real-time on a modern i7 (a
10-minute video takes ~10 minutes).  Use `--preset fast` or `--gpu` to
speed things up at the cost of slightly larger files.
