"""Real offline image/audio fixtures and terminal/file safety boundaries."""

import base64
import hashlib
import io
import wave

import pytest

from w_agent.media_display import (
    MediaDisplayError, MediaDisplayLimits, TerminalMediaDisplay,
    decode_inline_media, export_recorded_media, safe_media_text,
)


def block(raw, kind="image", media_type="image/png"):
    return {"kind": kind, "source": "inline", "media_type": media_type,
            "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "data_base64": base64.b64encode(raw).decode("ascii")}


def png():
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (16, 8), "white")
    for x in range(8):
        for y in range(8):
            image.putpixel((x, y), (0, 0, 0))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def wav():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 800)
    return stream.getvalue()


def test_actual_image_preview_and_wav_metadata():
    result = TerminalMediaDisplay().render(block(png()), confirmed=True)
    assert "16×8" in result.summary
    assert len(result.image_art.splitlines()) == 4
    assert result.image_art.splitlines()[0] == "@@@@@@@@        "
    audio = TerminalMediaDisplay().render(block(wav(), "audio", "audio/wav"), confirmed=True)
    assert "8000 Hz" in audio.summary and "0.100 s" in audio.summary
    assert not audio.image_art


@pytest.mark.parametrize("value", [False, 1, "yes", None])
def test_disclosure_is_exact_boolean(value):
    with pytest.raises(MediaDisplayError, match="VIEW MEDIA"):
        TerminalMediaDisplay().render(block(png()), confirmed=value)


def test_pixel_and_byte_limits():
    with pytest.raises(MediaDisplayError, match="pixel limit"):
        TerminalMediaDisplay(MediaDisplayLimits(max_pixels=10)).render(block(png()), confirmed=True)
    with pytest.raises(MediaDisplayError, match="byte limit"):
        decode_inline_media(block(png()), confirmed=True, limits=MediaDisplayLimits(max_bytes=1))


@pytest.mark.parametrize("change", [{"sha256": "0" * 64}, {"size_bytes": True},
                                    {"data_base64": "!!!!"}, {"data_base64": None}])
def test_rejects_invalid_recorded_content(change):
    value = block(png())
    value.update(change)
    with pytest.raises(MediaDisplayError):
        decode_inline_media(value, confirmed=True)


def test_url_never_loaded_or_control_rendered(monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))
    result = TerminalMediaDisplay().render({"kind": "image", "source": "url",
                                          "url": "file:///secret\x1b[2J\u202e"}, confirmed=True)
    assert "never fetched" in result.summary
    assert "\x1b" not in result.summary and "\u202e" not in result.summary
    assert safe_media_text("\x00\x9b\u202e") == "???"


def test_rejects_svg_and_declared_mime_mismatch():
    with pytest.raises(MediaDisplayError, match="PNG"):
        TerminalMediaDisplay().render(block(b"<svg/>", media_type="image/svg+xml"), confirmed=True)
    with pytest.raises(MediaDisplayError, match="decoding"):
        TerminalMediaDisplay().render(block(png(), media_type="image/jpeg"), confirmed=True)


def test_new_file_export_and_existing_file_protected(tmp_path):
    value = block(wav(), "audio", "audio/wav")
    with pytest.raises(MediaDisplayError):
        export_recorded_media(value, tmp_path)
    assert not list(tmp_path.iterdir())
    target = export_recorded_media(value, tmp_path, confirmed=True)
    assert target.parent == tmp_path and target.suffix == ".wav" and target.read_bytes() == wav()
    with pytest.raises(MediaDisplayError, match="no existing file replaced"):
        export_recorded_media(value, tmp_path, confirmed=True)
    assert target.read_bytes() == wav()


def test_unknown_format_inert_and_nonexistent_parent_rejected(tmp_path):
    value = block(b"opaque", "audio", "../../malicious.exe")
    assert export_recorded_media(value, tmp_path, confirmed=True).suffix == ".bin"
    with pytest.raises(MediaDisplayError):
        export_recorded_media(value, tmp_path / "missing", confirmed=True)
    assert not (tmp_path / "missing").exists()


def test_symlink_export_directory_rejected(tmp_path, monkeypatch):
    # Portable representation of the lstat link check (Windows often lacks privilege).
    original = type(tmp_path).is_symlink
    monkeypatch.setattr(type(tmp_path), "is_symlink", lambda p: p == tmp_path or original(p))
    with pytest.raises(MediaDisplayError, match="links"):
        export_recorded_media(block(png()), tmp_path, confirmed=True)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("limits", [{"max_bytes": True}, {"columns": 129}, {"rows": 0}])
def test_invalid_limits(limits):
    with pytest.raises(ValueError):
        MediaDisplayLimits(**limits)
