"""The transcription-workflow TUI: run setup as three keyboard stages, then a
headless hand-off (work item be4627c7; comparison shape per DEC db200725).

The app is a DRIVER over the core's own vocabulary — it imports expand_sources /
load_capabilities / PipelineConfig / the pipeline probe blocks instead of
reimplementing any of them, so everything the TUI does has an exact headless
equivalent. Correction-TUI presentation lessons carried over: spans-only Rich
styling (base styles bleed), no markup parsing of content strings (bare [/]
would MarkupError), AUTO_FOCUS None so bindings own the keys.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from cjm_substrate.core.manager import CapabilityManager
from cjm_substrate.core.queue import JobQueue
from cjm_transcription_core.cli import expand_sources, load_capabilities
from cjm_transcription_core.models import PipelineConfig
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from .candidates import candidate_directives, spec_string
from .probe import SegmentProbe
from .sources import SourceBrowser
from .viewport import visible_slice


class TranscriptionApp(App):
    """Transcription-run setup, v0 thinnest slice: three keyboard stages over one
    Static pane (SOURCES -> CANDIDATES -> COMPARE), then exit with a run plan.

    SOURCES walks the filesystem (SourceBrowser: dirs descend, media files toggle
    into the ORDERED selection, `a` picks a whole folder as a folder-source).
    CANDIDATES toggles rows of the manifest-derived (capability, MODEL) space.
    COMPARE stands the picked instances up side by side (CR-10 multi-instance
    loads via the core CLI's own load_capabilities), cuts the first selected
    source with the real pipeline blocks, and transcribes ONE segment across
    every candidate — walk segments with [ ], mark the pair with l / a, and
    enter confirms. The capability stack opens ON the Textual event loop
    (correction-TUI precedent); the blocking model loads ride asyncio.to_thread
    so paint stays alive. The app never runs the FULL pipeline itself — confirm
    exits with the plan and the driver hands off to the headless core CLI, so
    TUI-launched runs are byte-identical to hand-launched ones (journal,
    manifest, caches).
    """

    AUTO_FOCUS = None

    CSS = """
    #main { height: 1fr; }
    #status { dock: bottom; height: 1; }
    """

    BINDINGS = [
        Binding("j", "move(1)", "down"),
        Binding("down", "move(1)", "down", show=False),
        Binding("k", "move(-1)", "up"),
        Binding("up", "move(-1)", "up", show=False),
        Binding("enter", "select", "select/confirm"),
        Binding("space", "select", "select", show=False),
        Binding("backspace", "updir", "parent dir"),
        Binding("a", "key_a", "add folder / mark accuracy"),
        Binding("l", "mark_light", "mark lightweight"),
        Binding("n", "next_stage", "next stage"),
        Binding("b", "prev_stage", "back"),
        Binding("left_square_bracket", "segment(-1)", "prev segment", key_display="["),
        Binding("right_square_bracket", "segment(1)", "next segment", key_display="]"),
        Binding("r", "rerun", "re-probe segment"),
        Binding("escape", "cancel_probe", "cancel probe", show=False, priority=True),
        Binding("q", "quit_app", "quit"),
    ]

    def __init__(self, manifests_dir: str,               # Capability manifests directory
                 *, start_dir: str = ".",                # Browser root for the sources stage
                 initial_sources: Optional[List[str]] = None,  # Pre-selected paths (CLI args)
                 sysmon_capability: Optional[str] = None,      # Monitor for GPU attribution (CR-7)
                 graph_capability: Optional[str] = None,       # Journal target (None = NOT JOURNALED)
                 graph_db_path: Optional[str] = None,          # Caller-wins graph db override
                 initial_picks: Optional[List[str]] = None,    # Persisted candidate instance ids
                 max_segment_duration: float = 220.0):   # Segment wall-clock cap (probe + plan)
        super().__init__()
        self.manifests_dir = manifests_dir
        self.sysmon_capability = sysmon_capability
        self.graph_capability = graph_capability
        self.graph_db_path = graph_db_path
        self.max_segment_duration = max_segment_duration
        self.browser = SourceBrowser(start_dir)
        for p in initial_sources or []:
            self.browser.toggle(Path(p))
        self.candidates = candidate_directives(manifests_dir)
        self.cand_cursor = 0
        self.cand_picked: List[int] = [i for i, c in enumerate(self.candidates)
                                       if c["default"]]
        if initial_picks:
            wanted = set(initial_picks)
            restored = [i for i, c in enumerate(self.candidates)
                        if c["instance_id"] in wanted]
            if restored:
                self.cand_picked = restored
        self.stage = "sources"
        self.busy: Optional[str] = None   # Non-None = a probe/load is in flight (message)
        self.error: Optional[str] = None
        # Compare-stage state (populated by _enter_compare)
        self.manager = None
        self.queue = None
        self.probe: Optional[SegmentProbe] = None
        self.loaded_ids: List[str] = []
        self.seg_index = 0
        self.seg_count = 0
        self.rows: List[Dict[str, Any]] = []
        self.row_cursor = 0
        self.marks: Dict[str, Optional[str]] = {"lightweight": None, "accuracy": None}
        # Repaint coalescing + background-unload state (drive-2 ergonomics batch)
        self._paint_timer = None                          # Non-None = a repaint tick is armed
        self._paint_dirty = False                         # A request landed while armed
        self._unload_task: Optional[asyncio.Task] = None  # In-flight background teardown

    def compose(self) -> ComposeResult:
        yield Static(id="main")
        yield Static(id="status")

    def on_mount(self) -> None:
        self._paint()

    def on_resize(self, event) -> None:
        self._paint()

    # ---- painting (spans only — a base style on a composed row bleeds) ----

    REPAINT_INTERVAL = 1 / 30  # Coalescing window: at most ~30 full repaints/s

    def _paint(self) -> None:
        """Request a repaint, coalescing bursts (drive-2 ergonomics).

        Held-key navigation used to queue one full-pane Text rebuild PER key
        event — the key rate outran the rebuilds and the cursor jumped when
        the backlog flushed. State updates stay per-event (cheap); the pane
        rebuild is throttled: the first request paints immediately, requests
        inside the window mark dirty, and a trailing tick repaints, so a
        burst always ends on a fresh frame."""
        if self._paint_timer is not None:
            self._paint_dirty = True
            return
        self._paint_now()
        self._paint_timer = self.set_timer(self.REPAINT_INTERVAL, self._paint_tick)

    def _paint_tick(self) -> None:
        """Trailing edge of the repaint throttle: repaint if a request queued."""
        self._paint_timer = None
        if self._paint_dirty:
            self._paint_dirty = False
            self._paint_now()
            self._paint_timer = self.set_timer(self.REPAINT_INTERVAL, self._paint_tick)

    def _paint_now(self) -> None:
        pane = {"sources": self._paint_sources,
                "candidates": self._paint_candidates,
                "compare": self._paint_compare}[self.stage]()
        self.query_one("#main", Static).update(pane)
        status = Text()
        # The journal chip is ALWAYS visible (drive-1: an unjournaled run must
        # take an explicit opt-out, and the state must be impossible to miss).
        if self.graph_capability:
            status.append(f" journal→{self.graph_capability} ", style="green")
        else:
            status.append(" NOT JOURNALED ", style="bold red")
        if self._unload_task is not None:
            status.append(" unloading previous stack… ", style="yellow")
        if self.error:
            status.append(f" {self.error} ", style="bold red")
        elif self.busy:
            status.append(f" {self.busy} ", style="yellow")
        else:
            hints = {
                "sources": "enter descend/toggle · a folder-source · backspace up · n next · q quit",
                "candidates": "enter/space toggle · n compare · b back · q quit",
                "compare": "[ ] segment · l lightweight · a accuracy · r re-probe · enter confirm+run · b back · q quit",
            }[self.stage]
            status.append(f" {self.stage.upper()}  ·  {hints}", style="dim")
        # The one-line dock cannot wrap — long busy/error strings truncated
        # here silently (drive-2 DoD check 5a682f6f); now they ellipsize, and
        # the compare pane carries the FULL busy/error text.
        status.truncate(max(20, self.size.width), overflow="ellipsis")
        self.query_one("#status", Static).update(status)

    def _paint_sources(self) -> Text:
        out = Text()
        out.append(f" {self.browser.cwd}\n", style="bold")
        rows = self.browser.entries()
        self.browser.cursor = max(0, min(self.browser.cursor, max(0, len(rows) - 1)))
        # Cursor-windowed listing (drive-2: long directories ran off-screen).
        # The selected section keeps a small fixed tail; entries get the rest.
        height = max(4, self.size.height - 1)
        sel = self.browser.selected
        sel_shown = min(len(sel), 4)
        entry_budget = max(3, height - 3 - sel_shown - (1 if len(sel) > sel_shown else 0))
        start, end, above, below = visible_slice(len(rows), self.browser.cursor,
                                                 entry_budget)
        keys = self.browser.entry_keys()
        sel_set = set(sel)
        if above:
            out.append(f"   … {above} above\n", style="dim")
        for i in range(start, end):
            entry = rows[i]
            focus = (i == self.browser.cursor)
            picked = keys[i] in sel_set
            out.append(" > " if focus else "   ", style="bold cyan" if focus else "dim")
            out.append("[x] " if picked else "[ ] ", style="green" if picked else "dim")
            name = entry.name + ("/" if entry.is_dir() else "")
            out.append(name, style="bold" if focus else ("" if entry.is_file() else "blue"))
            out.append("\n")
        if below:
            out.append(f"   … {below} below\n", style="dim")
        if not rows:
            out.append("   (no subdirectories or media files)\n", style="dim")
        out.append(f"\n Selected ({len(sel)}, run order):\n", style="bold")
        if len(sel) > sel_shown:
            out.append(f"   … {len(sel) - sel_shown} earlier\n", style="dim")
        for s in sel[len(sel) - sel_shown:]:
            kind = "dir " if Path(s).is_dir() else "file"
            out.append(f"   {kind}  {s}\n", style="green")
        return out

    def _paint_candidates(self) -> Text:
        out = Text()
        out.append(" Candidate (capability, MODEL) instances — manifest-derived\n\n",
                   style="bold")
        if not self.candidates:
            out.append(f"   no transcription capabilities under {self.manifests_dir}\n",
                       style="red")
        # Cursor-windowed rows (drive-2); each distinct capability inside the
        # window repaints its group header, so the budget reserves one line per
        # group for the worst case.
        n_groups = len({c["capability"] for c in self.candidates})
        budget = max(3, max(4, self.size.height - 1) - 2 - n_groups)
        start, end, above, below = visible_slice(len(self.candidates),
                                                 self.cand_cursor, budget)
        if above:
            out.append(f"   … {above} above\n", style="dim")
        last_cap = None
        for i in range(start, end):
            c = self.candidates[i]
            if c["capability"] != last_cap:
                out.append(f" {c['capability']}\n", style="blue")
                last_cap = c["capability"]
            focus = (i == self.cand_cursor)
            picked = i in self.cand_picked
            out.append(" > " if focus else "   ", style="bold cyan" if focus else "dim")
            out.append("[x] " if picked else "[ ] ", style="green" if picked else "dim")
            label = c["model"] if c["model"] is not None else "(no model axis)"
            out.append(str(label), style="bold" if focus else "")
            if c["default"]:
                out.append("  (default)", style="dim")
            out.append(f"  -> {c['instance_id']}\n", style="dim")
        if below:
            out.append(f"   … {below} below\n", style="dim")
        return out

    def _paint_compare(self) -> Text:
        out = Text()
        src = self._probe_source() or "?"
        out.append(f" {Path(src).name}", style="bold")
        out.append(f"   segment {self.seg_index + 1}/{self.seg_count}\n\n", style="dim")
        if self.busy:
            # The status dock ellipsizes (one line, no wrap) — the FULL busy
            # text, blocked-candidate detail included, wraps here where it
            # stays readable (DoD check 5a682f6f).
            out.append(f" {self.busy}\n\n", style="yellow")
        row_budget = max(3, (max(4, self.size.height - 1) - 4) // 2)
        start, end, above, below = visible_slice(len(self.rows), self.row_cursor,
                                                 row_budget)
        if above:
            out.append(f"   … {above} above\n", style="dim")
        for i in range(start, end):
            row = self.rows[i]
            focus = (i == self.row_cursor)
            marks = []
            if self.marks["lightweight"] == row["instance_id"]:
                marks.append("L")
            if self.marks["accuracy"] == row["instance_id"]:
                marks.append("A")
            out.append(" > " if focus else "   ", style="bold cyan" if focus else "dim")
            out.append(f"[{','.join(marks) or ' '}] ",
                       style="green" if marks else "dim")
            out.append(row["instance_id"], style="bold" if focus else "")
            out.append(f"  {row['chars']} chars", style="dim")
            prof = row.get("profile") or {}
            if prof:
                out.append(
                    f"  ~{prof['duration_s_mean']:.1f}s/seg"
                    f"  gpu {prof['gpu_mb_peak']:.0f}MB"
                    f"  rss {prof['rss_mb_peak']:.0f}MB"
                    f"  (n={prof['samples']})", style="dim")
            out.append("\n")
        if below:
            out.append(f"   … {below} below\n", style="dim")
        if self.rows and 0 <= self.row_cursor < len(self.rows):
            out.append("\n")
            out.append(self.rows[self.row_cursor]["text"] or "(empty transcript)")
            out.append("\n")
        if self.error:
            # The one-line status dock CROPS long errors (stress-drive finding:
            # a composition failure dict died at 40 chars) — the pane wraps, so
            # the FULL error always lands here.
            out.append("\n")
            out.append(self.error, style="red")
            out.append("\n")
        return out

    # ---- stage actions (single key vocabulary, stage-dispatched) ----

    def action_move(self, delta: int) -> None:
        if self.busy:
            return
        if self.stage == "sources":
            self.browser.move(delta)
        elif self.stage == "candidates":
            if self.candidates:
                self.cand_cursor = max(0, min(self.cand_cursor + delta,
                                              len(self.candidates) - 1))
        elif self.rows:
            self.row_cursor = max(0, min(self.row_cursor + delta, len(self.rows) - 1))
        self._paint()

    def on_mouse_scroll_down(self, event) -> None:
        """Wheel = the j/k cursor walk (drive-2: the wheel did nothing)."""
        self.action_move(1)

    def on_mouse_scroll_up(self, event) -> None:
        self.action_move(-1)

    async def action_select(self) -> None:
        if self.busy:
            return
        if self.stage == "sources":
            self.browser.enter()
        elif self.stage == "candidates":
            if self.candidates:
                if self.cand_cursor in self.cand_picked:
                    self.cand_picked.remove(self.cand_cursor)
                else:
                    self.cand_picked.append(self.cand_cursor)
        else:
            await self._confirm()
            return
        self._paint()

    def action_updir(self) -> None:
        if self.stage == "sources" and not self.busy:
            self.browser.up()
            self._paint()

    def action_key_a(self) -> None:
        if self.busy:
            return
        if self.stage == "sources":
            self.browser.add_folder()
        elif self.stage == "compare" and self.rows:
            self.marks["accuracy"] = self.rows[self.row_cursor]["instance_id"]
        self._paint()

    def action_mark_light(self) -> None:
        if self.stage == "compare" and self.rows and not self.busy:
            self.marks["lightweight"] = self.rows[self.row_cursor]["instance_id"]
            self._paint()

    async def action_next_stage(self) -> None:
        if self.busy:
            return
        self.error = None
        if self.stage == "sources":
            if not self.browser.selected:
                self.error = "select at least one source first"
            else:
                self.stage = "candidates"
        elif self.stage == "candidates":
            if not self.cand_picked:
                self.error = "pick at least one candidate instance"
            else:
                await self._enter_compare()
                return
        self._paint()

    async def action_prev_stage(self) -> None:
        if self.busy:
            return
        self.error = None
        if self.stage == "candidates":
            self.stage = "sources"
            # Re-entering the browser is the one moment external changes
            # (new recordings) should show up — navigation itself stays cached.
            self.browser.refresh()
        elif self.stage == "compare":
            # Switch stages IMMEDIATELY — the serial model unloads were the
            # felt delay (drive-2) — and tear the stack down in the background.
            self._teardown_in_background()
            self.stage = "candidates"
        self._paint()

    def action_segment(self, delta: int) -> None:
        if self.stage == "compare" and self.seg_count and not self.busy:
            self.seg_index = max(0, min(self.seg_index + delta, self.seg_count - 1))
            self.run_worker(self._run_compare(), exclusive=True)

    def action_rerun(self) -> None:
        if self.stage == "compare" and self.probe is not None and not self.busy:
            self.probe._rows.pop(self.seg_index, None)
            self.run_worker(self._run_compare(), exclusive=True)

    async def action_cancel_probe(self) -> None:
        if self.probe is not None and self.busy:
            await self.probe.cancel_active()

    async def action_quit_app(self) -> None:
        await self._teardown_stack()
        self.exit(None)

    # ---- the capability stack + probe (compare stage) ----

    def _probe_source(self) -> Optional[str]:
        """The file the probe samples: first file of the expanded selection."""
        try:
            return expand_sources(self.browser.selected)[0]
        except (SystemExit, IndexError):
            return None

    def _picked_directives(self) -> List[Dict[str, Any]]:
        return [self.candidates[i] for i in sorted(self.cand_picked)]

    async def _enter_compare(self) -> None:
        source = self._probe_source()
        if source is None:
            self.error = "no media file in the selection"
            self._paint()
            return
        self.stage = "compare"
        self.rows = []
        self.marks = {"lightweight": None, "accuracy": None}
        picks = self._picked_directives()
        ids = [d["instance_id"] for d in picks]
        if self._unload_task is not None:
            # A background teardown from a prior b-gesture still holds VRAM —
            # loading on top of it would double-book the card.
            self.busy = "waiting for the previous stack to finish unloading..."
            self._paint()
            try:
                await self._unload_task
            except Exception:
                pass
        self.busy = f"loading {len(picks)} candidate instance(s) — model loads can take a while..."
        self._paint()
        try:
            cfg = PipelineConfig(transcriber_capabilities=ids, assume_yes=True,
                                 max_segment_duration=self.max_segment_duration)
            manager = CapabilityManager(search_paths=[Path(self.manifests_dir)],
                                        sysmon_capability_name=self.sysmon_capability)
            directives: List[Any] = (
                ([self.sysmon_capability] if self.sysmon_capability else [])
                + [cfg.ffmpeg_capability, cfg.vad_capability] + picks)
            await asyncio.to_thread(load_capabilities, manager, directives)
            self.manager = manager
            self.loaded_ids = [d["instance_id"] if isinstance(d, dict) else d
                               for d in directives]
            self.queue = JobQueue(deps=manager,
                                  sysmon_capability_name=self.sysmon_capability)
            await self.queue.start()
            self.probe = SegmentProbe(manager, self.queue, cfg, source, ids)
            self.busy = "cutting segments (convert -> VAD -> boundaries -> cut)..."
            self._paint()
            self.seg_count = await self.probe.prepare()
            self.seg_index = min(self.seg_index, max(0, self.seg_count - 1))
            self.busy = None
            if self.seg_count == 0:
                self.error = "no segments cut from the probe source"
                self._paint()
                return
            self.run_worker(self._run_compare(), exclusive=True)
        except Exception as e:
            self.busy = None
            self.error = f"stack open failed: {e}"
            await self._teardown_stack()
            self.stage = "candidates"
            self._paint()

    async def _run_compare(self) -> None:
        if self.probe is None:
            return
        # A new probe run owns the error slot — stale failure text under fresh
        # rows made a SUCCESSFUL re-run read as failed (stress-drive 2, 00:16:55
        # completed while the pane still showed the 00:11:59 error).
        self.error = None
        base = (f"transcribing segment {self.seg_index + 1}/{self.seg_count} "
                f"across {len(self.probe.transcriber_ids)} candidate(s)...")
        self.busy = base
        self._paint()
        watcher = asyncio.create_task(self._watch_blocked(base))
        try:
            self.rows = await self.probe.compare(self.seg_index)
            self.row_cursor = min(self.row_cursor, max(0, len(self.rows) - 1))
            self.busy = None
        except Exception as e:
            self.busy = None
            self.error = f"probe failed: {e}"
        finally:
            watcher.cancel()
        self._paint()

    async def _watch_blocked(self, base: str) -> None:
        """Append queue block reasons to the busy line while a compare runs.

        A candidate blocked on resident-held VRAM used to pend with no visible
        cause — the operator stared at the same busy line indefinitely (finding
        c5bbd511, the admission deadlock repro). The queue now keeps
        job.block_reason current (BLOCK_REASON_CHANGED); this poll is the read
        model — 2s cadence is plenty for a status line, and cancellation in
        _run_compare's finally bounds it to the compare's lifetime."""
        while True:
            await asyncio.sleep(2.0)
            if self.queue is None or self.busy is None:
                continue
            try:
                pending = self.queue.get_pending()
            except Exception:
                continue
            blocked = [(j.capability_instance_id, j.block_reason)
                       for j in pending if getattr(j, "block_reason", None)]
            if blocked:
                detail = " · ".join(f"{iid} {reason}" for iid, reason in blocked)
                self.busy = f"{base} ⏳ blocked: {detail}"
            else:
                self.busy = base
            self._paint()

    def _detach_stack(self):  # -> (queue, manager, loaded_ids), state cleared
        """Hand the live stack to a teardown path and clear the compare state."""
        queue, manager, ids = self.queue, self.manager, self.loaded_ids
        self.queue = None
        self.manager = None
        self.probe = None
        self.loaded_ids = []
        return queue, manager, ids

    async def _teardown_of(self, queue, manager, ids) -> None:
        """Stop a queue, then unload its instances in reverse load order."""
        if queue is not None:
            try:
                await queue.stop()
            except Exception:
                pass
        if manager is not None:
            for iid in reversed(ids):
                try:
                    await asyncio.to_thread(manager.unload_capability, iid)
                except Exception:
                    pass

    def _teardown_in_background(self) -> None:
        """Detach the compare stack and unload it on a background task.

        The b-gesture returns to candidates instantly; the status chip shows
        while the task drains. Anything that needs the VRAM actually FREE
        (_enter_compare's reload, every exit path via _teardown_stack) awaits
        _unload_task first, so a reload can never race the frees. Back-to-back
        b/n gestures chain: each new task awaits the previous one."""
        queue, manager, ids = self._detach_stack()
        if queue is None and manager is None:
            return
        task = asyncio.create_task(
            self._background_unload(self._unload_task, queue, manager, ids))
        task.add_done_callback(self._unload_done)
        self._unload_task = task

    async def _background_unload(self, prev, queue, manager, ids) -> None:
        if prev is not None:
            try:
                await prev
            except Exception:
                pass
        await self._teardown_of(queue, manager, ids)

    def _unload_done(self, task) -> None:
        # Only the CURRENT task clears the chip — a chained predecessor
        # finishing must not blank the state while a successor still drains.
        if self._unload_task is task:
            self._unload_task = None
            try:
                self._paint()
            except Exception:
                pass  # the exit paths await the task, then tear the DOM down

    async def _teardown_stack(self) -> None:
        queue, manager, ids = self._detach_stack()
        if self._unload_task is not None:
            try:
                await self._unload_task
            except Exception:
                pass
        await self._teardown_of(queue, manager, ids)

    async def _confirm(self) -> None:
        light = self.marks["lightweight"]
        acc = self.marks["accuracy"]
        if not light or not acc:
            self.error = "mark BOTH lightweight (l) and accuracy (a) before confirming"
            self._paint()
            return
        by_id = {d["instance_id"]: d for d in self._picked_directives()}
        pair = [by_id[light]] + ([by_id[acc]] if acc != light else [])
        plan = {
            "sources": list(self.browser.selected),
            "transcribers": [spec_string(d) for d in pair],
            "lightweight": light,
            "accuracy": acc,
            "max_segment_duration": self.max_segment_duration,
            "sysmon_capability": self.sysmon_capability,
            "graph_capability": self.graph_capability,
            "graph_db_path": self.graph_db_path,
            "manifests_dir": self.manifests_dir,
            # Persistence payload (state.py): choices the operator never retypes.
            "picked_instance_ids": [d["instance_id"] for d in self._picked_directives()],
            "last_cwd": str(self.browser.cwd),
        }
        await self._teardown_stack()
        self.exit(plan)
