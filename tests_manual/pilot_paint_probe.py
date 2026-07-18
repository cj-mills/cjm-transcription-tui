"""Headless paint-path pilot for the setup TUI (67335f7d: pilot probe, not
pytest, is the verification layer for TUI paint strings — pytest can't see a
MarkupError or a style bleed). Drives the REAL app through the sources and
candidates stages with Textual's run_test pilot and reads the painted Statics;
the compare stage needs a live capability stack, so it stops at the gate.

    python tests_manual/pilot_paint_probe.py [manifests_dir]
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

from textual.widgets import Input, Static
from cjm_transcription_tui.app import TranscriptionApp
from cjm_transcription_tui.candidates import spec_string


async def drive(start_dir: Path, manifests_dir: str) -> None:
    """Walk sources -> candidates -> back -> quit, asserting stage + paint."""
    app = TranscriptionApp(manifests_dir, start_dir=str(start_dir))
    async with app.run_test() as pilot:
        def paint() -> str:
            # Textual 8: Static.renderable is gone; render() returns the content.
            # Repaints coalesce now (drive-2) — flush before reading so the
            # assertion never races the trailing tick.
            app._paint_now()
            return str(app.query_one("#main", Static).render())

        assert app.stage == "sources"
        assert "Selected (0" in paint(), paint()
        # journal chip: this probe passes no graph capability -> loud red state
        chip = str(app.query_one("#status", Static).render())
        assert "NOT JOURNALED" in chip, chip
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
        # The app WRITES sidecar state on quit (last_cwd) — drive a throwaway
        # COPY of the manifests so pilot runs never touch project state. The
        # copy lives BESIDE the media dir, not inside it (dirs sort first and
        # would steal the cursor from ep1.mp3).
        media = Path(td) / "media"
        media.mkdir()
        (media / "ep1.mp3").write_bytes(b"x")
        mcopy = Path(td) / "manifests"
        shutil.copytree(manifests_dir, mcopy)
        asyncio.run(drive(media, str(mcopy)))
        asyncio.run(drive_config(media, str(mcopy)))
        asyncio.run(drive_results(media, str(mcopy), Path(td) / "runs"))
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for i in range(60):
            (tmp / f"f{i:03d}.mp3").write_bytes(b"x")
        # Sorts first: the one-line row discipline must ellipsize it, never wrap
        (tmp / ("a" * 100 + ".mp3")).write_bytes(b"x")
        asyncio.run(drive_windowing(tmp))


# __main__ dispatch lives at the END of the file — regions append in order,
# and the dispatch must follow every driver it names.


async def drive_windowing(start_dir: Path) -> None:
    """A 60-file directory must window around the cursor, not run off-pane
    (drive-2 ergonomics: viewport windowing + wheel scroll + coalesced paint)."""
    app = TranscriptionApp(str(start_dir / "no-manifests"), start_dir=str(start_dir))
    async with app.run_test() as pilot:
        def paint() -> str:
            app._paint_now()
            return str(app.query_one("#main", Static).render())

        body = paint()
        assert "below" in body, body[:400]     # tail hidden behind the indicator
        assert "f000.mp3" in body              # near-cursor rows painted
        assert "f059.mp3" not in body          # far tail is NOT painted
        # One-line row discipline: the 100-char name (cursor row, sorts first)
        # is ellipsized, and NO pane line exceeds the pane width — wrapped rows
        # ate extra screen lines and pushed the pane tail off-screen.
        assert "…" in body, body[:400]
        assert "a" * 100 not in body
        assert max(len(ln) for ln in body.splitlines()) <= 80, \
            max(body.splitlines(), key=len)
        for _ in range(60):                    # held-j to the end (coalesced)
            app.action_move(1)
        assert app.browser.cursor == 60
        body = paint()
        assert "f059.mp3" in body and "above" in body, body[:400]
        app.on_mouse_scroll_up(None)           # wheel = the j/k cursor walk
        assert app.browser.cursor == 59
        await pilot.press("q")
    print("pilot OK: viewport windowing, wheel scroll, one-line rows, coalesced flush")


# ---- config sub-view driver (keystone widget half) ----


async def drive_config(start_dir: Path, manifests_dir: str) -> None:
    """The keystone config sub-view: a focused candidate's config_schema becomes
    editable rows (model axis excluded), closed sets cycle, open kinds take the
    transient Input, and overrides commit onto the directive + round-trip through
    spec_string to the headless grammar (the voxtral-small device=cpu case)."""
    app = TranscriptionApp(manifests_dir, start_dir=str(start_dir))
    async with app.run_test() as pilot:
        def paint() -> str:
            app._paint_now()
            return str(app.query_one("#main", Static).render())

        await pilot.press("enter")     # select ep1.mp3
        await pilot.press("n")         # -> candidates
        widx = next(i for i, c in enumerate(app.candidates)
                    if c["capability"] == "cjm-capability-whisper")
        for _ in range(widx):
            app.action_move(1)

        await pilot.press("c")         # -> config
        assert app.stage == "config", app.stage
        assert "config ·" in paint()
        keys = [f.key for f in app.form.fields]
        assert "model" not in keys and "device" in keys, keys   # axis excluded

        di = keys.index("device")
        for _ in range(di):
            await pilot.press("j")
        await pilot.press("enter")     # closed set cycles: auto -> cpu
        assert app.form.field("device").value == "cpu"
        body = paint()
        assert "cpu" in body and "*" in body, body[:400]

        ti = keys.index("temperature")
        while app.form_cursor < ti:
            await pilot.press("j")
        await pilot.press("enter")     # open kind -> transient Input
        assert app.form_editing and app.query_one("#editor", Input).display
        app.query_one("#editor", Input).value = "9.9"
        await pilot.press("enter")     # out of bounds: Input stays open, reason painted
        assert app.form_editing and app.error and "Temperature" in app.error, app.error
        app.query_one("#editor", Input).value = "0.4"
        await pilot.press("enter")     # in bounds: applies + closes
        assert not app.form_editing and app.form.field("temperature").value == 0.4

        bi = keys.index("beam_size")
        while app.form_cursor < bi:
            await pilot.press("j")
        await pilot.press("enter")
        app.query_one("#editor", Input).value = "9"
        await pilot.press("escape")    # escape-cancel: no apply
        assert not app.form_editing and app.form.field("beam_size").value == 5

        await pilot.press("b")         # commit onto the directive, back to picker
        assert app.stage == "candidates"
        cfg = app.candidates[widx]["config"]
        assert cfg.get("device") == "cpu" and cfg.get("temperature") == 0.4
        assert "beam_size" not in cfg
        assert "[cfg]" in paint()      # picker flags the tuned candidate
        spec = spec_string(app.candidates[widx])
        assert "device=cpu" in spec and "temperature=0.4" in spec, spec

        await pilot.press("c")         # re-entry re-seeds the edited values
        assert app.form.field("device").value == "cpu"
        assert app.form.field("temperature").value == 0.4
        await pilot.press("b")
        await pilot.press("q")
    assert app.return_value is None
    print("pilot OK: config sub-view — schema rows, cycle, Input parse/validate,"
          " escape-cancel, overrides commit + spec round-trip, re-seed")


async def drive_results(start_dir: Path, manifests_dir: str, runs_dir: Path) -> None:
    """Results layer (6768bafb): prior-run chip, hash-check notice, bookmark
    star + cycle, and the runs list -> drilled-run -> segment-text walk."""
    import json
    from cjm_substrate.utils.hashing import hash_file

    import numpy as np
    import soundfile as sf

    src = start_dir / "ep1.mp3"
    digest = hash_file(str(src))
    runs_dir.mkdir(exist_ok=True)
    wav = runs_dir / "seg0000.wav"  # a REAL model-input WAV for the p gesture
    sf.write(str(wav), np.zeros(3200, dtype="float32"), 16000)
    (runs_dir / "run_x.json").write_text(json.dumps({
        "format": "cjm-transcription-core/run-manifest",
        "run_id": "run_x", "created_at": 100.0,
        "config": {"transcriber_capabilities": ["cjm-capability-whisper"]},
        "sources": [{"source_path": str(src), "content_hash": digest,
                     "segments": [{"index": 0, "start": 0.0, "end": 2.0,
                                   "model_input_path": str(wav),
                                   "transcripts": {"cjm-capability-whisper":
                                                   {"text": "pilot transcript"}}},
                                  {"index": 1, "start": 2.0, "end": 3.0,
                                   "model_input_path": str(runs_dir / "gone.wav"),
                                   "transcripts": {"cjm-capability-whisper":
                                                   {"text": "second segment"}}}]}]}))
    app = TranscriptionApp(manifests_dir, start_dir=str(start_dir),
                           runs_dir=str(runs_dir))
    async with app.run_test() as pilot:
        def paint() -> str:
            app._paint_now()
            return str(app.query_one("#main", Static).render())

        def status() -> str:
            app._paint_now()
            return str(app.query_one("#status", Static).render())

        # prior-run chip: path-keyed count painted on the browser row at mount
        assert "·1 run" in paint(), paint()
        # hash-check the focused file (cursor starts on ep1.mp3)
        await pilot.press("h")
        await pilot.pause()
        assert "content in 1 prior run(s)" in status(), status()
        # bookmark the cwd (★ in header) and cycle back to it with '
        await pilot.press("m")
        assert "★" in paint(), paint()
        await pilot.press("apostrophe")
        assert app.browser.cwd == start_dir.resolve()
        # results view: list -> drill -> per-transcriber segment text -> unwind
        await pilot.press("v")
        assert app.stage == "results", app.stage
        body = paint()
        assert "run_x" in body and "1 source(s)" in body, body[:300]
        await pilot.press("enter")
        body = paint()
        assert "pilot transcript" in body and "segment 1/2" in body, body[:400]
        # p plays the manifest segment's recorded model-input WAV (drive-4
        # follow-up: hear problem areas before the correction TUI)
        await pilot.press("p")
        assert app.player is not None, "player never created"
        assert app.error is None, app.error
        await pilot.press("p")             # toggle: stop
        assert not app.player.playing
        await pilot.press("right_square_bracket")   # -> segment 2 (missing WAV)
        await pilot.press("p")
        assert app.error and "not on disk" in app.error, app.error
        app.error = None
        await pilot.press("b")             # drilled -> runs list
        assert app.results_run is None
        await pilot.press("b")             # runs list -> sources
        assert app.stage == "sources", app.stage
        await pilot.press("q")
    assert app.return_value is None
    print("pilot OK: results drill + playback, prior-run chip, hash-check, bookmark star")


# Entry-point dispatch — LAST region on purpose (main names every driver above,
# so the __main__ call must follow their definitions).
if __name__ == "__main__":
    main()
