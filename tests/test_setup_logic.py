"""Tests for the TUI's pure logic — browser/selection state, candidate
enumeration off fake manifests, spec round-trips through the CORE parser,
and plan argv (no Textual, no capabilities involved)."""

import json
import re
from pathlib import Path

from cjm_transcription_core.cli import build_parser as core_build_parser
from cjm_transcription_core.cli import parse_transcriber_spec
from cjm_transcription_tui.candidates import (candidate_directives, discover_capability,
                                              instance_id_for, model_axis, spec_string,
                                              transcription_manifests)
from cjm_transcription_tui.cli import build_parser, plan_argv
from cjm_transcription_tui.sources import SourceBrowser
from cjm_transcription_tui.state import load_state, save_state, state_path


def _write_manifest(d, name, methods, props):
    """Minimal capability-manifest json with just the fields enumeration reads."""
    (d / f"{name}.json").write_text(json.dumps({
        "code": {"name": name,
                 "structural_surface": {"methods": [{"name": m} for m in methods]},
                 "config_schema": {"properties": props}}}))


def test_candidate_enumeration(tmp_path):
    _write_manifest(tmp_path, "cjm-capability-whisper", ["transcribe", "cancel"],
                    {"model": {"enum": ["tiny", "base"], "default": "base"}})
    _write_manifest(tmp_path, "cjm-capability-voxtral-hf", ["transcribe"],
                    {"model_id": {"enum": ["org/Mini-3B", "org/Small-24B"],
                                  "default": "org/Mini-3B"}})
    # surface-matched: a media tool (no transcribe method) and an adapter unit
    # (no code section) must both stay out of the candidate space
    _write_manifest(tmp_path, "cjm-capability-ffmpeg", ["convert", "segment_audio"], {})
    (tmp_path / "adapter-transcription-x.json").write_text(json.dumps({"unit": "adapter"}))

    assert set(transcription_manifests(str(tmp_path))) == {
        "cjm-capability-whisper", "cjm-capability-voxtral-hf"}
    rows = candidate_directives(str(tmp_path))
    assert len(rows) == 4  # 2 whisper models + 2 voxtral models
    # the DEFAULT model keeps the bare capability name (stage-5/cache continuity)
    assert {r["instance_id"] for r in rows if r["default"]} == {
        "cjm-capability-whisper", "cjm-capability-voxtral-hf"}
    assert {r["instance_id"] for r in rows if not r["default"]} == {
        "whisper--tiny", "voxtral-hf--Small-24B"}
    # the model axis key is data-derived per capability, not hard-coded
    named = {r["instance_id"]: r for r in rows if not r["default"]}
    assert named["whisper--tiny"]["config"] == {"model": "tiny"}
    assert named["voxtral-hf--Small-24B"]["config"] == {"model_id": "org/Small-24B"}


def test_spec_round_trip_and_instance_ids(tmp_path):
    _write_manifest(tmp_path, "cjm-capability-whisper", ["transcribe"],
                    {"model": {"enum": ["tiny", "large-v3"], "default": "tiny"}})
    _write_manifest(tmp_path, "cjm-capability-voxtral-hf", ["transcribe"],
                    {"model_id": {"enum": ["mistralai/Voxtral-Small-24B-2507"],
                                  "default": None}})
    for r in candidate_directives(str(tmp_path)):
        # every directive the TUI can produce must survive the CORE parser
        # unchanged — the hand-off contract with cjm-transcription-core run
        assert parse_transcriber_spec(spec_string(r)) == {
            "capability": r["capability"], "instance_id": r["instance_id"],
            "config": r["config"]}
        # and every derived id must satisfy the manager's CR-10 pattern
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", r["instance_id"])
    assert instance_id_for("cjm-capability-voxtral-hf",
                           "mistralai/Voxtral-Small-24B-2507") == \
        "voxtral-hf--Voxtral-Small-24B-2507"
    assert model_axis({"config_schema": {"properties": {"device": {"enum": ["cpu"]}}}}) is None


def test_source_browser_walk_and_selection(tmp_path):
    (tmp_path / "pod").mkdir()
    (tmp_path / "pod" / "ep1.mp3").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")   # non-media: not browsable
    (tmp_path / ".hidden").mkdir()               # hidden dir: not browsable

    b = SourceBrowser(str(tmp_path))
    assert [e.name for e in b.entries()] == ["pod", "b.wav"]
    b.enter()                                    # descend pod/
    assert b.cwd == (tmp_path / "pod").resolve()
    b.enter()                                    # toggle-select ep1.mp3
    assert b.selected == [str((tmp_path / "pod" / "ep1.mp3").resolve())]
    b.up()
    b.move(1)                                    # focus b.wav
    b.enter()                                    # select it (order = pick order)
    assert [Path(s).name for s in b.selected] == ["ep1.mp3", "b.wav"]
    b.enter()                                    # toggle again = deselect
    assert [Path(s).name for s in b.selected] == ["ep1.mp3"]
    b.move(-1)                                   # focus pod/ again
    b.add_folder()                               # folder-source, kept unexpanded
    assert b.selected[-1] == str((tmp_path / "pod").resolve())


def test_plan_argv_parses_in_the_core_cli(tmp_path):
    # graph/sysmon ride the PLAN (resolved flags > state > discovery in main);
    # only preprocessing/actor still pass through from the raw args
    args = build_parser().parse_args(["--actor", "tui:test"])
    src = tmp_path / "ep1.mp3"
    src.write_bytes(b"x")
    plan = {"sources": [str(src)],
            "transcribers": ["cjm-capability-whisper@whisper--tiny:model=tiny",
                             "cjm-capability-voxtral-hf"],
            "lightweight": "whisper--tiny", "accuracy": "cjm-capability-voxtral-hf",
            "max_segment_duration": 220.0, "sysmon_capability": None,
            "graph_capability": "cjm-capability-graph-sqlite",
            "graph_db_path": "/tmp/g.db",
            "manifests_dir": ".cjm/manifests"}
    argv = plan_argv(plan, args)
    # the hand-off contract: the rendered argv must parse in the CORE CLI
    parsed = core_build_parser().parse_args(argv)
    assert parsed.command == "run"
    assert parsed.audio == [str(src)]
    assert parsed.yes is True
    assert parsed.transcriber == plan["transcribers"]
    assert parsed.graph_capability == "cjm-capability-graph-sqlite"
    assert parsed.graph_db_path == "/tmp/g.db"
    assert parsed.actor == "tui:test"
    assert parsed.sysmon_capability is None


def test_state_roundtrip_and_role_discovery(tmp_path):
    manifests = tmp_path / "manifests"
    manifests.mkdir()
    # role discovery is surface-based: graph storage = add_nodes, monitor =
    # get_system_status; a transcriber must match NEITHER role
    _write_manifest(manifests, "cjm-capability-graph-sqlite",
                    ["add_nodes", "add_edges", "find_nodes_by_label"], {})
    _write_manifest(manifests, "cjm-capability-monitor-nvidia",
                    ["get_system_status", "list_processes"], {})
    _write_manifest(manifests, "cjm-capability-whisper", ["transcribe"], {})
    assert discover_capability(str(manifests), "add_nodes") == "cjm-capability-graph-sqlite"
    assert discover_capability(str(manifests), "get_system_status") == "cjm-capability-monitor-nvidia"
    assert discover_capability(str(manifests), "no_such_method") is None

    # state sidecar lands NEXT TO the manifests dir and round-trips merges
    assert load_state(str(manifests)) == {}
    save_state(str(manifests), graph_capability="cjm-capability-graph-sqlite",
               picked_instance_ids=["whisper--tiny"])
    save_state(str(manifests), last_cwd="/data/podcasts")
    state = load_state(str(manifests))
    assert state == {"graph_capability": "cjm-capability-graph-sqlite",
                     "picked_instance_ids": ["whisper--tiny"],
                     "last_cwd": "/data/podcasts"}
    assert state_path(str(manifests)).parent == tmp_path
