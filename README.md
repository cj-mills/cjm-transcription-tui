# cjm-transcription-tui

<!-- generated from the context graph by `cjm-context-graph readme` — do not edit by hand; edit the graph (the urge to hand-edit = move it on-graph) -->

_No purpose recorded on-graph yet — author it with_ `assert 169694cd-2118-5390-a8b8-de26fb77c930 purpose "…"` _(or by the repo's entity key)._

## Modules

- **`cjm_transcription_tui.__init__`**
- **`cjm_transcription_tui.app`** — The transcription-workflow TUI: run setup as three keyboard stages, then a
- **`cjm_transcription_tui.cli`** — The console-script driver: run the setup TUI, then hand the confirmed plan

## API

### `cjm_transcription_tui.app`

- `TranscriptionApp` _class_ — Transcription-run setup, v0 thinnest slice: three keyboard stages over one

### `cjm_transcription_tui.cli`

- `main` _function_ — Resolve the shared setup surface, run the Textual setup app, then hand

## Dependencies

**Depends on:** `cjm-substrate-tui-kit`, `cjm-transcription-core`, `textual`
