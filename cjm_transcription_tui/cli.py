"""The console-script driver: run the setup TUI, then hand the confirmed plan to
the HEADLESS core CLI in-process (terminal restored first). The equivalent
cjm-transcription-core command prints before execution — every TUI-confirmed run
is reproducible by copy-paste, and --plan-only stops at the printout.
"""

import argparse
import shlex
from typing import Any, Dict, List

from cjm_transcription_core.cli import main as core_main

from .app import TranscriptionApp


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
    p.add_argument("--manifests-dir", default=".cjm/manifests",
                   help="Capability manifests directory")
    p.add_argument("--start-dir", default=".",
                   help="Browser root for the sources stage")
    p.add_argument("--sysmon-capability", default=None,
                   help="monitor capability for GPU attribution (loads first in the "
                        "comparison stack; also forwarded to the confirmed run)")
    p.add_argument("--max-segment-duration", type=float, default=220.0,
                   help="Segment wall-clock cap (probe AND forwarded run)")
    p.add_argument("--graph-capability", default=None,
                   help="Forwarded to the confirmed run (graph emission)")
    p.add_argument("--graph-db-path", default=None,
                   help="Forwarded to the confirmed run (requires --graph-capability)")
    p.add_argument("--preprocessing-capability", default=None,
                   help="Forwarded to the confirmed run (e.g. cjm-capability-demucs)")
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
    if args.graph_capability:
        argv += ["--graph-capability", args.graph_capability]
        if args.graph_db_path:
            argv += ["--graph-db-path", args.graph_db_path]
    if args.preprocessing_capability:
        argv += ["--preprocessing-capability", args.preprocessing_capability]
    if args.actor:
        argv += ["--actor", args.actor]
    return argv


def main() -> int:  # Console-script entry point (cjm-transcription-tui)
    """Run the setup app; on a confirmed plan, print + exec the headless run."""
    args = build_parser().parse_args()
    app = TranscriptionApp(args.manifests_dir, start_dir=args.start_dir,
                           initial_sources=args.paths or None,
                           sysmon_capability=args.sysmon_capability,
                           max_segment_duration=args.max_segment_duration)
    plan = app.run()
    if not plan:
        print("no run confirmed")
        return 0
    argv = plan_argv(plan, args)
    print(f"pair: lightweight={plan['lightweight']}  accuracy={plan['accuracy']}")
    print("handing off: " + shlex.join(["cjm-transcription-core"] + argv))
    if args.plan_only:
        return 0
    return core_main(argv)
