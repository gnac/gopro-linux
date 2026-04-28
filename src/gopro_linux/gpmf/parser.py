"""
GPMF (GoPro Metadata Format) binary parser.

The GPMF format is a binary Key-Length-Value (KLV) structure embedded as a
dedicated data track inside GoPro MP4 files. All header values are big-endian.

Each record:
  - FourCC key  : 4 bytes (ASCII)
  - Type        : 1 byte  (character code for data type)
  - Size        : 1 byte  (bytes per element)
  - Repeat      : 2 bytes (element count, big-endian uint16)
  - Data        : size * repeat bytes, zero-padded to 4-byte boundary

Nested containers (DEVC, STRM) use type = '\x00' and contain child records.
"""

import json
import struct
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ── Type map: GPMF type char -> (struct fmt char, byte size) ─────────────────
_TYPES: dict[str, tuple[str, int]] = {
    "b": ("b", 1),   # int8
    "B": ("B", 1),   # uint8
    "d": ("d", 8),   # float64
    "f": ("f", 4),   # float32
    "F": ("4s", 4),  # FourCC (4-char string)
    "j": ("q", 8),   # int64
    "J": ("Q", 8),   # uint64
    "l": ("i", 4),   # int32
    "L": ("I", 4),   # uint32
    "q": ("i", 4),   # Q32 fixed-point stored as int32
    "Q": ("Q", 8),   # Q64 fixed-point stored as uint64
    "s": ("h", 2),   # int16
    "S": ("H", 2),   # uint16
}

# FourCCs that carry stream metadata rather than sensor data
_META_KEYS = frozenset({
    "STMP", "TSMP", "STNM", "SIUN", "SCAL", "ORIN", "ORIO",
    "TMPC", "MTYP", "DVNM", "DVID", "EMPT", "MANL", "SOFF",
    "TICK", "GPSU", "GPSP", "GPSF", "GPRI",
})


@dataclass
class GpmfRecord:
    fourcc: str
    type: str
    size: int
    repeat: int
    value: Any
    children: list = field(default_factory=list)


@dataclass
class GpmfStream:
    """A parsed GPMF sensor stream (contents of one STRM container)."""
    name: str           # STNM
    fourcc: str         # data FourCC, e.g. "ACCL", "GPS5"
    samples: list       # list of parsed sample values
    scale: Any          # SCAL (int or list[int])
    units: str          # SIUN
    timestamp_us: int   # STMP – microseconds of first sample
    total_samples: int  # TSMP – cumulative sample count
    orin: str           # ORIN – stored orientation  e.g. "ZXY"
    orio: str           # ORIO – preferred output orientation


@dataclass
class GpmfPacket:
    """One MP4 sample worth of GPMF data, with its presentation timestamp."""
    pts_seconds: float
    duration_seconds: float
    streams: dict[str, GpmfStream]   # keyed by sensor FourCC


# ── ffprobe / ffmpeg helpers ─────────────────────────────────────────────────

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def find_gpmf_stream_index(input_path: Path) -> Optional[int]:
    """Return the stream index of the GoPro metadata track, or None."""
    r = _run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", str(input_path)],
        capture_output=True, text=True,
    )
    data = json.loads(r.stdout)
    streams = data.get("streams", [])

    # Priority 1: the explicit 'gpmd' codec tag is the definitive GoPro GPMF marker.
    # ('tmcd' is the *timecode* track — a completely different data stream that also
    #  carries a GoPro handler name, so it must be excluded explicitly.)
    for s in streams:
        if s.get("codec_tag_string") == "gpmd" and s.get("codec_type") == "data":
            return s["index"]

    # Priority 2: handler name says "GoPro MET" (metadata), not "GoPro TCD" (timecode)
    for s in streams:
        if s.get("codec_type") != "data":
            continue
        handler = s.get("tags", {}).get("handler_name", "")
        if "GoPro MET" in handler:
            return s["index"]

    # Priority 3: any data stream with 'gopro' in the handler that is not a timecode track
    for s in streams:
        if s.get("codec_type") != "data":
            continue
        handler = s.get("tags", {}).get("handler_name", "").lower()
        tag     = s.get("codec_tag_string", "").lower()
        if "gopro" in handler and "tcd" not in handler and tag != "tmcd":
            return s["index"]

    return None


def get_video_info(input_path: Path) -> dict:
    """Return fps, width, height, duration from the first video stream."""
    r = _run(
        ["ffprobe", "-v", "quiet", "-print_format", "json",
         "-show_streams", "-show_format", str(input_path)],
        capture_output=True, text=True,
    )
    data = json.loads(r.stdout)

    info: dict = {"duration": float(data.get("format", {}).get("duration", 0))}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            num, den = (int(x) for x in s.get("avg_frame_rate", "30/1").split("/"))
            info["fps"] = num / max(den, 1)
            info["width"] = s["width"]
            info["height"] = s["height"]
            break

    info.setdefault("fps", 30.0)
    info.setdefault("width", 1920)
    info.setdefault("height", 1080)
    return info


def _get_packet_meta(input_path: Path, stream_index: int) -> list[dict]:
    """Return [{pts, duration, size}, ...] for every GPMF packet."""
    r = _run(
        ["ffprobe", "-v", "quiet",
         "-select_streams", str(stream_index),
         "-show_packets",
         "-show_entries", "packet=pts_time,duration_time,size",
         "-print_format", "json",
         str(input_path)],
        capture_output=True, text=True,
    )
    out = []
    for p in json.loads(r.stdout).get("packets", []):
        out.append({
            "pts": float(p.get("pts_time") or 0),
            "duration": float(p.get("duration_time") or 0),
            "size": int(p.get("size") or 0),
        })
    return out


def _extract_raw_gpmf(input_path: Path, stream_index: int) -> bytes:
    """Dump the GPMF data track as raw bytes via FFmpeg."""
    r = _run(
        ["ffmpeg", "-v", "quiet", "-i", str(input_path),
         "-map", f"0:{stream_index}",
         "-f", "rawvideo", "-vcodec", "copy", "pipe:1"],
        capture_output=True,
    )
    return r.stdout


# ── Binary parser ────────────────────────────────────────────────────────────

def _parse_value(type_char: str, size: int, repeat: int, raw: bytes) -> Any:
    """Decode a GPMF payload into Python scalars or lists."""
    # String / datetime
    if type_char in ("c", "U"):
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace")

    # Unknown / pure binary
    if type_char not in _TYPES:
        return raw

    fmt_char, type_size = _TYPES[type_char]
    n_per_elem = size // type_size if type_size else 1

    if n_per_elem == 0:
        return raw  # element size smaller than type — return raw bytes

    # Build the struct format string.
    # For multi-character format codes like '4s' (FourCC), simple integer
    # prefixing breaks: f">{n}4s" → ">14s" (14-byte string!) instead of
    # ">4s" (one 4-byte string).  Repeat the pattern instead.
    if len(fmt_char) > 1:
        fmt = ">" + fmt_char * n_per_elem
    else:
        fmt = f">{n_per_elem}{fmt_char}"

    results = []
    for i in range(repeat):
        chunk = raw[i * size : i * size + size]
        if len(chunk) < size:
            continue
        try:
            vals = struct.unpack(fmt, chunk)
        except struct.error:
            continue
        results.append(vals[0] if n_per_elem == 1 else list(vals))

    if not results:
        return None  # guard against all-failed unpacks

    return results[0] if repeat == 1 else results


def parse_binary(data: bytes, offset: int = 0) -> list[GpmfRecord]:
    """Recursively parse GPMF binary data, returning a list of GpmfRecord."""
    records: list[GpmfRecord] = []

    while offset + 8 <= len(data):
        raw_key = data[offset : offset + 4]
        if raw_key == b"\x00\x00\x00\x00":
            break

        try:
            fourcc = raw_key.decode("ascii")
        except UnicodeDecodeError:
            break

        type_char = chr(data[offset + 4])
        size      = data[offset + 5]
        repeat    = struct.unpack_from(">H", data, offset + 6)[0]

        data_len   = size * repeat
        padded_len = (data_len + 3) & ~3
        start      = offset + 8
        end        = start + data_len

        if end > len(data):
            break

        payload = data[start:end]

        rec = GpmfRecord(fourcc=fourcc, type=type_char,
                         size=size, repeat=repeat, value=None)

        if type_char == "\x00":          # nested container
            rec.children = parse_binary(payload)
        else:
            rec.value = _parse_value(type_char, size, repeat, payload)

        records.append(rec)
        offset += 8 + padded_len

    return records


def _first(records: list[GpmfRecord], fourcc: str) -> Optional[GpmfRecord]:
    for r in records:
        if r.fourcc == fourcc:
            return r
    return None


def _extract_stream(children: list[GpmfRecord]) -> Optional[GpmfStream]:
    """Build a GpmfStream from the children of a STRM record."""
    name = ""
    scale: Any = 1
    units = ""
    timestamp_us = 0
    total_samples = 0
    orin = "ZXY"
    orio = "ZXY"
    data_fourcc: Optional[str] = None
    data_samples: Optional[list] = None

    for rec in children:
        fc = rec.fourcc
        if   fc == "STNM": name = str(rec.value or "")
        elif fc == "SCAL": scale = rec.value
        elif fc == "SIUN": units = str(rec.value or "")
        elif fc == "STMP": timestamp_us  = int(rec.value or 0)
        elif fc == "TSMP": total_samples = int(rec.value or 0)
        elif fc == "ORIN": orin = str(rec.value or "ZXY")
        elif fc == "ORIO": orio = str(rec.value or "ZXY")
        elif fc not in _META_KEYS and rec.type != "\x00" and rec.value is not None:
            data_fourcc = fc
            v = rec.value
            data_samples = v if isinstance(v, list) else [v]

    if data_fourcc is None:
        return None

    return GpmfStream(
        name=name, fourcc=data_fourcc, samples=data_samples or [],
        scale=scale, units=units, timestamp_us=timestamp_us,
        total_samples=total_samples, orin=orin, orio=orio,
    )


# ── Public API ───────────────────────────────────────────────────────────────

def parse_gpmf_file(input_path: Path) -> tuple[list[GpmfPacket], dict]:
    """
    Parse all GPMF telemetry from a GoPro MP4 file.

    Returns
    -------
    packets : list[GpmfPacket]
        One entry per MP4 sample, each with a presentation timestamp and a
        dict of parsed sensor streams keyed by FourCC ("ACCL", "GPS5", …).
    video_info : dict
        {"fps", "width", "height", "duration"}
    """
    video_info = get_video_info(input_path)

    stream_idx = find_gpmf_stream_index(input_path)
    if stream_idx is None:
        raise ValueError(f"No GPMF data track found in {input_path}")

    pkt_meta = _get_packet_meta(input_path, stream_idx)
    if not pkt_meta:
        raise ValueError(f"No GPMF packets found in {input_path}")

    raw = _extract_raw_gpmf(input_path, stream_idx)

    packets: list[GpmfPacket] = []
    byte_offset = 0

    for meta in pkt_meta:
        sz = meta["size"]
        chunk = raw[byte_offset : byte_offset + sz]
        byte_offset += sz

        if len(chunk) < 8:
            continue

        records = parse_binary(chunk)
        streams: dict[str, GpmfStream] = {}

        for rec in records:
            if rec.fourcc != "DEVC":
                continue
            for child in rec.children:
                if child.fourcc != "STRM":
                    continue
                s = _extract_stream(child.children)
                if s:
                    streams[s.fourcc] = s

        if streams:
            packets.append(GpmfPacket(
                pts_seconds=meta["pts"],
                duration_seconds=meta["duration"],
                streams=streams,
            ))

    return packets, video_info
