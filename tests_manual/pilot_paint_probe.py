"""Headless paint-path pilot for the setup TUI (67335f7d: pilot probe, not
pytest, is the verification layer for TUI paint strings — pytest can't see a
MarkupError or a style bleed). Drives the REAL app through the sources and
candidates stages with Textual's run_test pilot and reads the painted Statics;
the compare stage needs a live capability stack, so it stops at the gate.

    python tests_manual/pilot_paint_probe.py [manifests_dir]
"""

import asyncio
import sys
import tempfile
from pathlib import Path

from textual.widgets import Static
from cjm_transcription_tui.app import TranscriptionApp


async def drive(start_dir: Path, manifests_dir: str) -> None:
    """Walk sources -> candidates -> back -> quit, asserting stage + paint."""
    app = TranscriptionApp(manifests_dir, start_dir=str(start_dir))
    async with app.run_test() as pilot:
        def paint() -> str:
            # Textual 8: Static.renderable is gone; render() returns the content
            return str(app.query_one("#main", Static).render())

        assert app.stage == "sources"
        assert "Selected (0" in paint(), paint()
        await pilot.press("enter")            # cursor starts on ep1.mp3 -> select
        assert len(app.browser.selected) == 1, app.browser.selected
        assert "[x]" in paint() and "Selected (1" in paint()
        await pilot.press("a")                # cwd as an (unexpanded) folder source
        assert len(app.browser.selected) == 2

        await pilot.press("n")                # -> candidates
        assert app.stage == "candidates", app.stage
        body = paint()
        assert "cjm-capability-whisper" in body, body[:400]
        assert "(default)" in body
        picked_before = list(app.cand_picked)
        await pilot.press("enter")            # toggle the focused row
        assert app.cand_picked != picked_before

        await pilot.press("b")                # back to sources
        assert app.stage == "sources"
        await pilot.press("n")                # forward again (state kept)
        assert app.stage == "candidates"
        await pilot.press("q")                # quit (no stack open yet: no-op teardown)
    assert app.return_value is None           # quit without a confirmed plan
    print("pilot OK: sources + candidates paint, stage nav, selection state")


def main() -> None:
    """Stage a throwaway media dir, then drive the app against real manifests."""
    manifests_dir = sys.argv[1] if len(sys.argv) > 1 else ".cjm/manifests"
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        (tmp / "ep1.mp3").write_bytes(b"x")
        asyncio.run(drive(tmp, manifests_dir))


if __name__ == "__main__":
    main()
