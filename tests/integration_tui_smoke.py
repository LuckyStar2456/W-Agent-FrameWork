"""Explicit wide/narrow TUI smoke with reviewable SVG screenshots."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from w_agent.tui import WAgentTui


async def main(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="wagent-tui-smoke-") as directory:
        app = WAgentTui(directory)
        async with app.run_test(size=(120, 42)) as pilot:
            await pilot.pause()
            banner = app.query_one("#home-banner")
            assert str(banner.content).count("█") > 100
            assert "づ" in str(banner.content)
            (output / "tui-wide.svg").write_text(app.export_screenshot(), encoding="utf-8")
            await pilot.resize_terminal(45, 30)
            await pilot.pause()
            assert "W-AGENT" in str(banner.content)
            assert "█" not in str(banner.content)
            assert "(｡•ᴗ•｡)" in str(banner.content)
            (output / "tui-narrow.svg").write_text(app.export_screenshot(), encoding="utf-8")
            await pilot.resize_terminal(120, 42)
            await pilot.pause()
            assert str(banner.content).count("█") > 100
    print(json.dumps({"wide": "passed", "narrow": "passed", "resize_back": "passed"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args().output))
