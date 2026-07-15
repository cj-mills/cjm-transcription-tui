# cjm-transcription-tui

Transcription-workflow TUI driver over `cjm-transcription-core`'s headless pipeline.

v0 flow (one keyboard-first Textual app, three stages):

1. **Sources** — pick audio/video files and/or folders (folders expand to every media
   file under them, recursive + sorted, via the core's `expand_sources`).
2. **Candidates** — stand up candidate **(capability, MODEL) instances** enumerated
   from the capability manifests' config schemas (e.g. the whisper family,
   voxtral mini vs small) through the substrate's CR-10 multi-instance loading.
3. **Compare** — transcribe ONE VAD-cut segment of a chosen source across every
   candidate side by side, walk segments to sample more, then mark the run's
   **lightweight** and **accuracy** pair and confirm.

On confirm the app exits and hands the equivalent `cjm-transcription-core run`
invocation to the headless CLI (printed first, for reproducibility), so runs stay
journaled + manifest-recorded exactly like hand-launched ones.

```bash
cjm-transcription-tui --manifests-dir .cjm/manifests [paths...]
```

Born on-graph: package content is authored as graph nodes and projected to `.py`
(the journal is the source of truth; these files are generated artifacts).
