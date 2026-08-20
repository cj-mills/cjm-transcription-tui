"""The console-script driver: run the setup TUI, then hand the confirmed plan
to the HEADLESS core CLI in-process (terminal restored first). The whole
launch surface — build_parser, resolve_settings, hand_off — lives in
cjm_transcription_core.launch (spine absorption 12f342f1) and is imported
here, so this shell and the Qt shell cannot drift on the reproducibility
contract; only the app in the middle differs."""

from cjm_transcription_core.launch import build_parser, hand_off, resolve_settings

from .app import TranscriptionApp


def main() -> int:  # Console-script entry point (cjm-transcription-tui)
    """Resolve the shared setup surface, run the Textual setup app, then hand
    the confirmed plan off headless — resolve_settings + hand_off carry the
    ladder and the tail, shared verbatim with the Qt shell's driver (DEC
    dcf8a712: a resolution drift between shells would fork the
    reproducibility contract)."""
    args = build_parser().parse_args()
    s = resolve_settings(args)
    app = TranscriptionApp(s["manifests_dir"], start_dir=s["start_dir"],
                           runs_dir=s["runs_dir"],
                           initial_sources=args.paths or None,
                           sysmon_capability=s["sysmon_capability"],
                           graph_capability=s["graph_capability"],
                           graph_db_path=s["graph_db_path"],
                           initial_picks=s["state"].get("picked_instance_ids"),
                           initial_bookmarks=s["state"].get("bookmarks"),
                           preprocessing_capability=s["preprocessing_capability"],
                           diarization_capability=s["diarization_capability"],
                           max_segment_duration=args.max_segment_duration)
    return hand_off(app.run(), args)
