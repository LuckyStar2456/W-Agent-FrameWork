"""Bounded, replaceable offline media presentation; never fetches or plays media."""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import os
import re
import unicodedata
import warnings
import wave
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class MediaDisplayError(ValueError):
    """Content-free presentation failure safe to show in a terminal."""


@dataclass(frozen=True, slots=True)
class MediaDisplayLimits:
    max_bytes: int = 8 * 1024 * 1024
    max_pixels: int = 4_000_000
    columns: int = 64
    rows: int = 24

    def __post_init__(self) -> None:
        for value, upper in ((self.max_bytes, 32 * 1024 * 1024),
                             (self.max_pixels, 16_000_000), (self.columns, 128),
                             (self.rows, 64)):
            if type(value) is not int or not 1 <= value <= upper:
                raise ValueError("Invalid media presentation limit.")


@dataclass(frozen=True, slots=True)
class MediaPreview:
    summary: str
    image_art: str = ""


class MediaDisplay(Protocol):
    """Trusted host extension; implementations must not fetch, play or execute."""

    def render(self, block: Mapping[str, object], *, confirmed: bool = False) -> MediaPreview: ...


def safe_media_text(value: object, limit: int = 2048) -> str:
    """Remove terminal controls, bidi controls and invisible format characters."""
    text = str(value)[:limit]
    return "".join(char if unicodedata.category(char)[0] != "C" else "?" for char in text)


def decode_inline_media(block: Mapping[str, object], *, confirmed: bool = False,
                        limits: MediaDisplayLimits = MediaDisplayLimits()) -> bytes:
    if confirmed is not True:
        raise MediaDisplayError("Explicit media disclosure confirmation is required.")
    if block.get("kind") not in {"image", "audio"} or block.get("source") != "inline":
        raise MediaDisplayError("Only recorded inline image/audio bytes are available; URLs are never fetched.")
    size, encoded, digest = block.get("size_bytes"), block.get("data_base64"), block.get("sha256")
    if type(size) is not int or not 0 < size <= limits.max_bytes:
        raise MediaDisplayError("Recorded media exceeds the byte limit or is empty.")
    if not isinstance(encoded, str):
        raise MediaDisplayError("Inline content is withheld; reread with media=content and VIEW CONTENT.")
    if len(encoded) > ((limits.max_bytes + 2) // 3) * 4:
        raise MediaDisplayError("Encoded media exceeds the byte limit.")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise MediaDisplayError("Invalid media integrity metadata.")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise MediaDisplayError("Invalid base64 media.") from None
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
        raise MediaDisplayError("Recorded media integrity check failed.")
    return raw


class TerminalMediaDisplay:
    """ASCII luminance image preview and audio metadata, with lazy Pillow import."""

    def __init__(self, limits: MediaDisplayLimits = MediaDisplayLimits()) -> None:
        self.limits = limits

    def render(self, block: Mapping[str, object], *, confirmed: bool = False) -> MediaPreview:
        if confirmed is not True:
            raise MediaDisplayError("Type VIEW MEDIA to disclose the selected media.")
        if block.get("source") == "url":
            return MediaPreview("Reference only; never fetched: " + safe_media_text(block.get("url", "withheld")))
        raw = decode_inline_media(block, confirmed=True, limits=self.limits)
        media_type = block.get("media_type")
        if block.get("kind") == "image":
            return self._image(raw, media_type)
        summary = f"Audio / 音频: {safe_media_text(media_type, 255)}, {len(raw)} bytes; no playback."
        if media_type in {"audio/wav", "audio/x-wav", "audio/wave"}:
            try:
                with wave.open(io.BytesIO(raw), "rb") as audio:
                    summary += (f" PCM {audio.getnchannels()} channels, {audio.getframerate()} Hz, "
                                f"{audio.getsampwidth() * 8}-bit, "
                                f"{audio.getnframes() / audio.getframerate():.3f} s.")
            except (wave.Error, EOFError, ZeroDivisionError):
                raise MediaDisplayError("Invalid or unsupported WAV recording.") from None
        else:
            summary += " Compressed/raw audio duration and codec are not decoded or verified."
        return MediaPreview(summary)

    def _image(self, raw: bytes, media_type: object) -> MediaPreview:
        formats = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}
        if media_type not in formats:
            raise MediaDisplayError("Image preview supports PNG, JPEG and WebP only.")
        try:
            from PIL import Image
        except ImportError:
            raise MediaDisplayError("Image preview requires optional Pillow; no dependency was installed.") from None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw), formats=[formats[media_type]]) as source:
                    width, height = source.size
                    if width * height > self.limits.max_pixels or width <= 0 or height <= 0:
                        raise MediaDisplayError("Image exceeds the decoded pixel limit.")
                    if getattr(source, "n_frames", 1) != 1:
                        raise MediaDisplayError("Animated images are not previewed.")
                    # Validate the entire file before decoding into a second bounded image.
                    source.verify()
                with Image.open(io.BytesIO(raw), formats=[formats[media_type]]) as source:
                    rgba = source.convert("RGBA")
                    background = Image.new("RGBA", rgba.size, "white")
                    background.alpha_composite(rgba)
                    scale = min(self.limits.columns / width, self.limits.rows * 2 / height, 1)
                    preview = background.convert("L").resize(
                        (max(1, int(width * scale)), max(1, int(height * scale / 2))))
                    ramp = "@%#*+=-:. "
                    pixels = list(preview.tobytes())
                    art = "\n".join("".join(ramp[value * (len(ramp) - 1) // 255]
                                              for value in pixels[start:start + preview.width])
                                    for start in range(0, len(pixels), preview.width))
                    return MediaPreview(f"Image / 图片: {width}×{height}, {len(raw)} bytes; ASCII luminance preview.", art)
        except MediaDisplayError:
            raise
        except Exception:
            raise MediaDisplayError("Image decoding failed or the image is unsafe/unsupported.") from None


def export_recorded_media(block: Mapping[str, object], directory: Path, *, confirmed: bool = False,
                          limits: MediaDisplayLimits = MediaDisplayLimits()) -> Path:
    """Explicit export under an existing unredirected directory, never overwrite.

    Assumes the directory ancestors are not concurrently replaced by another local
    process. This is path hardening, not isolation from a malicious filesystem owner.
    """
    raw = decode_inline_media(block, confirmed=confirmed, limits=limits)
    suffixes = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
                "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/flac": ".flac",
                "audio/mp4": ".m4a", "audio/pcm": ".pcm"}
    # Unknown media is inert .bin, never an extension supplied by a recording.
    suffix = suffixes.get(block.get("media_type"), ".bin")
    try:
        selected = Path(os.path.abspath(directory))
        if selected.resolve(strict=True) != selected or not selected.is_dir():
            raise MediaDisplayError("Export directory must exist without symbolic-link redirection.")
        for ancestor in (selected, *selected.parents):
            stat = ancestor.lstat()
            if ancestor.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise MediaDisplayError("Export directory cannot contain links or reparse points.")
        target = selected / ("media-" + hashlib.sha256(raw).hexdigest() + suffix)
        # O_EXCL rejects existing targets including symlinks, and prevents replacement.
        with target.open("xb") as stream:
            stream.write(raw)
        return target
    except MediaDisplayError:
        raise
    except (OSError, ValueError, TypeError):
        raise MediaDisplayError("Export failed; no existing file replaced. A partial new file may remain.") from None
