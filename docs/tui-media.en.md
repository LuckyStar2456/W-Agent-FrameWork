# Replay media presentation

> Applies to 2.0.0. `Experimental` APIs remain experimental; `Planned` / `Reserved` does not mean implemented. See [release verification](./acceptance-2026-10-01-stable-release.en.md).

[中文](tui-media.md)

Status: Experimental. Local replay now offers real PNG/JPEG/WebP ASCII luminance previews instead of only media JSON. Audio has metadata and explicit export. This is not a player and executes no models or tools.

## Usage

Image decoding is optional: from source, select `pip install '.[tui,media-preview]'`. Core imports do not load Pillow/Textual. Missing Pillow produces an explicit error without installing anything. The existing test environment already has Pillow 12.3.0 through document parsing dependencies; no dependency was installed/reinstalled in this round, and the new extra has not undergone installation acceptance.

Select a Run/Session on the TUI replay page, set output `media=content` or Session `input-media=content`, enter `VIEW CONTENT`, and read one batch. The existing `metadata` default is unchanged; `references` does not disclose inline bytes.

The separate media area initially lists only kind and position. Select previous/next, type `VIEW MEDIA`, and press Preview:

- Static PNG/JPEG/WebP becomes an aspect-aware ASCII luminance image, up to 64 columns by 24 rows. Transparency is composited onto white. This loses color and resolution and never fetches remote images.
- WAV uses the standard library to report channels, sample rate, bit depth and duration. Nothing plays or transcodes. Other audio reports declared MIME and byte count without claiming codec or duration validation.
- URLs are sanitized text only: no network fetch, `file:` read, or browser opening. References themselves may be sensitive and require separate confirmation.

Export requires an explicit **existing local directory**, `EXPORT MEDIA`, and the Export button. Names use content SHA-256 plus a fixed extension table; unknown MIME uses `.bin`. No directory creation, overwrites or recording-provided filenames. Symbolic links and Windows reparse points in directory ancestry are rejected. Exported original bytes may be invalid or unsafe and are never opened automatically.

`VIEW CONTENT` does not grant preview/export authority. Each action consumes its own confirmation. Changing media, clearing or replacing the snapshot hides the prior preview and discards stale asynchronous UI delivery. A file write already started may finish after clearing/unmounting; cancellation is not rollback.

## Open extension point

`w_agent.media_display` has no mandatory TUI/Pillow dependency. The default image renderer imports Pillow only when needed; missing Pillow causes an explicit error, never automatic installation. The `knowledge-documents` combination normally brings Pillow through python-pptx, but applications must not assume its presence.

```python
from pathlib import Path
from w_agent.media_display import MediaPreview
from w_agent.tui_replay import ReplayPanel

class MyDisplay:
    def render(self, block, *, confirmed=False):
        if confirmed is not True:
            raise ValueError("confirmation required")
        return MediaPreview("Host-defined presentation", "your bounded image art")

panel = ReplayPanel(Path.cwd(), media_renderer=MyDisplay())
```

`MediaDisplay` is a structural protocol. Injected renderers are trusted Python, not a sandbox. They must not secretly fetch, play or execute; TUI output limits do not isolate extension code. Configure the default renderer through `MediaDisplayLimits` to change bytes, pixels and character dimensions.

## Boundaries and evidence

Defaults: 8 MiB inline bytes and 4 million pixels. Configurable hard ceilings: 32 MiB, 16 million pixels, 128×64 characters. Base64, byte count and SHA-256 are checked. Images use only the declared supported decoder, undergo integrity validation and reject animation. Terminal controls, bidi controls and invisible format characters are removed; markup/ANSI is not interpreted. Only standard Run output and Session input media slots are selected, not lookalike objects in tool results. The catalog is capped at 256 items and fails without presenting a partial catalog.

Export path checks are not a sandbox against a malicious local process with directory-write privileges. Concurrent directory replacement races are not eliminated using cross-platform handle-relative APIs; use directories you control. Digests establish consistency, not provenance. Snapshots, terminal scrollback and exported files may contain sensitive content; clearing a widget does not erase external system history.

Focused verification covers real PNG ASCII output and WAV, consent, size/digest/MIME/control safeguards, no-overwrite export, Session input/Run output selection, custom templates, stale async result suppression, and actual replay-to-panel wiring. No external services, playback, full-suite run, dependency installation or release was performed for this work.

Reserved, not implemented: color/high-resolution terminal protocols, waveforms/playback, more codecs, explicitly authorized remote fetching, optional native application opening and isolated decoder processes.
