# cjm-transcription-tui

<!-- generated from the context graph by `cjm-context-graph readme` — do not edit by hand; edit the graph (the urge to hand-edit = move it on-graph) -->

_No purpose recorded on-graph yet — author it with_ `assert 169694cd-2118-5390-a8b8-de26fb77c930 purpose "…"` _(or by the repo's entity key)._

## Modules

- **`cjm_transcription_tui.__init__`**
- **`cjm_transcription_tui.app`** — The transcription-workflow TUI: run setup as three keyboard stages, then a
- **`cjm_transcription_tui.candidates`** — Candidate (capability, MODEL)-instance enumeration for the comparison screen.
- **`cjm_transcription_tui.cli`** — The console-script driver: run the setup TUI, then hand the confirmed plan to
- **`cjm_transcription_tui.probe`** — Per-segment comparison probe: transcribe ONE VAD-cut segment across every
- **`cjm_transcription_tui.results`** — Past-run results for the setup TUI: the core's own runs/*.json manifests read
- **`cjm_transcription_tui.sources`** — Source-selection state for the picker stage: a keyboard file browser plus the
- **`cjm_transcription_tui.state`** — Sidecar TUI state: last-used run settings persisted across sessions (the

## API

### `cjm_transcription_tui.app`

- `TranscriptionApp` _class_ — Transcription-run setup, v0 thinnest slice: three keyboard stages over one

### `cjm_transcription_tui.candidates`

- `candidate_directives` _function_ — Expand every installed transcription capability into its candidate space.
- `discover_capability` _function_ — Pick a DEFAULT capability for a role by surface match.
- `instance_id_for` _function_ — Derive an addressable instance id for a non-default (capability, MODEL) pick.
- `manifests_with_method` _function_ — Enumerate installed capabilities whose structural surface lists `method`.
- `model_axis` _function_ — Find a capability's MODEL config axis in its config_schema.
- `spec_string` _function_ — Render a load directive back to the core CLI's --transcriber grammar.
- `transcription_manifests` _function_ — Enumerate installed transcription capabilities from their manifest files.

### `cjm_transcription_tui.cli`

- `build_parser` _function_ — The TUI driver's argument surface (setup options + core-run passthrough).
- `main` _function_ — Resolve settings (flags > persisted state > manifest discovery), run the
- `plan_argv` _function_ — Render a confirmed plan as headless core-CLI argv.

### `cjm_transcription_tui.probe`

- `SegmentProbe` _class_ — One source's cut segments + cached per-segment comparison results.

### `cjm_transcription_tui.results`

- `RunIndex` _class_ — runs/*.json manifests loaded newest-first + the lookups the TUI paints from.

### `cjm_transcription_tui.sources`

- `CollectionField` _class_ — Pre-run collection state for the sources stage (ae3464fc: the actor
- `SourceBrowser` _class_ — Keyboard file-browser + ordered selection state for the sources stage.

### `cjm_transcription_tui.state`

- `load_state` _function_ — Read this project's persisted TUI state.
- `save_state` _function_ — Merge updates into the persisted state and write it back (best-effort:
- `state_path` _function_ — Where this project's TUI state lives.

## Dependencies

**Depends on:** `cjm-substrate-tui-kit`, `cjm-transcription-core`, `textual`
