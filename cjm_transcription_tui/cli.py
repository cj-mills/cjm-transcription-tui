"""The console-script driver: run the setup TUI, then hand the confirmed plan to
the HEADLESS core CLI in-process (terminal restored first). The equivalent
cjm-transcription-core command prints before execution — every TUI-confirmed run
is reproducible by copy-paste, and --plan-only stops at the printout.
"""

import argparse
import os
import shlex
from typing import Any, Dict, List

from cjm_substrate.core.workspace import resolve_workspace
from cjm_transcription_core.cli import main as core_main

from .app import TranscriptionApp
from .candidates import discover_capability
from .state import load_state, save_state


def build_parser() -> argparse.ArgumentParser:  # Configured CLI parser
    """The TUI driver's argument surface (setup options + core-run passthrough)."""
    p = argparse.ArgumentParser(
        prog="cjm-transcription-tui",
        description="Run-setup TUI for the headless transcription pipeline: pick "
                    "sources/folders, stand up candidate (capability, MODEL) instances, "
                    "compare them on real segments, mark the lightweight/accuracy pair — "
                    "the confirmed run is handed to cjm-transcription-core.")
    p.add_argument("paths", nargs="*",
                   help="Pre-selected source files/folders (add more in-app)")
    p.add_argument("--manifests-dir", default=None,
                   help="Capability manifests directory (default: the workspace's "
                        ".cjm/manifests when one is active, else .cjm/manifests under the cwd)")
    p.add_argument("--workspace", default=None,
                   help="Workspace root (5daadfc4; default: CJM_WORKSPACE env, else upward walk "
                        "from cwd). Supplies manifests/runs/browse defaults and is exported so "
                        "the core hand-off + capability workers resolve workspace-scoped paths")
    p.add_argument("--start-dir", default=".",
                   help="Browser root for the sources stage")
    p.add_argument("--sysmon-capability", default=None,
                   help="monitor capability for GPU attribution (loads first in the "
                        "comparison stack; also forwarded to the confirmed run; "
                        "default: last-used, else auto-discovered from manifests)")
    p.add_argument("--no-sysmon", action="store_true",
                   help="Explicitly disable the monitor (overrides state + discovery)")
    p.add_argument("--max-segment-duration", type=float, default=220.0,
                   help="Segment wall-clock cap (probe AND forwarded run)")
    p.add_argument("--graph-capability", default=None,
                   help="Graph-storage capability for run emission (default: last-used, "
                        "else auto-discovered from manifests — journaling is ON by default)")
    p.add_argument("--no-graph", action="store_true",
                   help="Explicitly disable graph emission — the run will NOT be journaled "
                        "(overrides state + discovery; the status line stays red)")
    p.add_argument("--graph-db-path", default=None,
                   help="Explicit graph db path (default: last-used, else the capability's "
                        "configured db_path)")
    p.add_argument("--preprocessing-capability", default=None,
                   help="Forwarded to the confirmed run (e.g. cjm-capability-demucs)")
    p.add_argument("--diarization-capability", default=None,
                   help="Speaker-diarization capability for the confirmed run (default: "
                        "last-used, else auto-discovered from manifests — the rung is ON "
                        "by default; the in-app s toggle flips it per run)")
    p.add_argument("--no-diarization", action="store_true",
                   help="Start with the diarization rung OFF (overrides state + discovery; "
                        "the s toggle can re-enable a discovered capability in-app)")
    p.add_argument("--actor", default=None,
                   help="Forwarded journal attribution (default: cli:<user>)")
    p.add_argument("--plan-only", action="store_true",
                   help="Print the equivalent headless command and exit WITHOUT running it")
    return p


def plan_argv(
    plan: Dict[str, Any],       # The app's confirmed run plan (TranscriptionApp.exit value)
    args: argparse.Namespace,   # The TUI's parsed args (passthrough run options)
) -> List[str]:  # cjm-transcription-core argv (the reproducibility contract)
    """Render a confirmed plan as headless core-CLI argv.

    Everything the TUI decided (sources in pick order, the lightweight/accuracy
    pair as --transcriber specs) plus everything it merely passes through
    (graph emission, preprocessing, sysmon, actor) lands in ONE argv — printed
    before execution so any TUI run can be replayed by hand.
    """
    argv = ["run", *plan["sources"], "--yes",
            "--manifests-dir", plan["manifests_dir"],
            "--max-segment-duration", str(plan["max_segment_duration"])]
    for spec in plan["transcribers"]:
        argv += ["--transcriber", spec]
    if plan.get("sysmon_capability"):
        argv += ["--sysmon-capability", plan["sysmon_capability"]]
    if plan.get("graph_capability"):
        argv += ["--graph-capability", plan["graph_capability"]]
        if plan.get("graph_db_path"):
            argv += ["--graph-db-path", plan["graph_db_path"]]
    pre = plan.get("preprocessing_capability") or args.preprocessing_capability
    if pre:
        # The in-TUI A/B verdict (toggled ON at confirm) wins over the static
        # flag; toggled-off is indistinguishable from untouched, so the flag
        # stays the fallback for scripted runs.
        argv += ["--preprocessing-capability", pre]
    if "diarization_capability" in plan:
        # 450e7c78 parity: the operator SAW the diarization state at confirm, so
        # the argv carries the choice EXPLICITLY both ways — the printed command
        # replays identically even if the core's default ever drifts. Plans
        # without the key (scripted callers) keep the core's own default.
        if plan["diarization_capability"]:
            argv += ["--diarization-capability", plan["diarization_capability"]]
        else:
            argv += ["--no-diarization"]
    coll = plan.get("collection") or {}
    if coll.get("mode") == "named" and coll.get("title"):
        # The operator touched the field = a confirmation act (ae3464fc).
        argv += ["--collection", coll["title"]]
    elif coll.get("mode") == "off":
        argv += ["--no-collection"]
    # mode "auto" passes nothing: the core proposes per folder-source, exactly
    # as the same argv would hands-off.
    if args.workspace:
        # Explicit flag passes through so the printed command replays standalone;
        # env/walk-resolved workspaces replay via the same env/cwd.
        argv += ["--workspace", args.workspace]
    if args.actor:
        argv += ["--actor", args.actor]
    return argv


def main() -> int:  # Console-script entry point (cjm-transcription-tui)
    """Resolve settings (flags > persisted state > manifest discovery), run the
    setup app, persist the confirmed choices, then print + exec the headless run."""
    args = build_parser().parse_args()
    # 5daadfc4 workspace: resolve before anything reads paths; export so the
    # in-process core hand-off + capability workers are workspace-scoped.
    ws = resolve_workspace(explicit=args.workspace)
    if ws is not None:
        os.environ["CJM_WORKSPACE"] = str(ws.root)
    if args.manifests_dir is None:
        args.manifests_dir = (str(ws.substrate_data_dir / "manifests")
                              if ws is not None else ".cjm/manifests")
    state = load_state(args.manifests_dir)
    # Journaling-by-default (drive-1 finding): an unjournaled run takes an
    # EXPLICIT --no-graph, never a forgotten flag; sysmon likewise.
    graph_capability = None if args.no_graph else (
        args.graph_capability or state.get("graph_capability")
        or discover_capability(args.manifests_dir, "add_nodes"))
    graph_db_path = args.graph_db_path or state.get("graph_db_path")
    sysmon = None if args.no_sysmon else (
        args.sysmon_capability or state.get("sysmon_capability")
        or discover_capability(args.manifests_dir, "get_system_status"))
    # Diarization rides the same resolution ladder (flags > state > surface
    # discovery); default-ON matches the core rung — an undiarized run takes an
    # explicit --no-diarization or the in-app s toggle, never a forgotten flag.
    diarization = None if args.no_diarization else (
        args.diarization_capability or state.get("diarization_capability")
        or discover_capability(args.manifests_dir, "diarize"))
    start_dir = args.start_dir if args.start_dir != "." else (
        state.get("last_cwd") or (str(ws.root) if ws is not None else "."))
    app = TranscriptionApp(args.manifests_dir, start_dir=start_dir,
                           runs_dir=(str(ws.runs_dir) if ws is not None else "runs"),
                           initial_sources=args.paths or None,
                           sysmon_capability=sysmon,
                           graph_capability=graph_capability,
                           graph_db_path=graph_db_path,
                           initial_picks=state.get("picked_instance_ids"),
                           initial_bookmarks=state.get("bookmarks"),
                           preprocessing_capability=(
                               args.preprocessing_capability
                               or discover_capability(args.manifests_dir,
                                                      "separate_vocals")),
                           diarization_capability=diarization,
                           max_segment_duration=args.max_segment_duration)
    plan = app.run()
    if not plan:
        print("no run confirmed")
        return 0
    save_state(args.manifests_dir,
               graph_capability=plan["graph_capability"],
               graph_db_path=plan["graph_db_path"],
               sysmon_capability=plan["sysmon_capability"],
               diarization_capability=plan["diarization_capability"],
               picked_instance_ids=plan["picked_instance_ids"],
               last_cwd=plan["last_cwd"])
    argv = plan_argv(plan, args)
    print(f"pair: lightweight={plan['lightweight']}  accuracy={plan['accuracy']}")
    if not plan["graph_capability"]:
        print("WARNING: graph emission OFF — this run will NOT be journaled (--no-graph)")
    print("handing off: " + shlex.join(["cjm-transcription-core"] + argv))
    if args.plan_only:
        return 0
    return core_main(argv)
