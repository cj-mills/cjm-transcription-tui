"""Source-selection state for the picker stage: a keyboard file browser plus the
run's ORDERED source list (files and folder sources mix; order is run order).

Pure logic, Textual-free — tests drive it directly, the app only paints it
(the correction-TUI lesson: the paint path is verified by pilot probe, so
everything that CAN live below the paint path SHOULD). Folder sources stay
folders here; the core CLI's expand_sources does the recursive expansion at
run time, keeping the TUI and headless runs byte-identical in behavior.
"""

from pathlib import Path
from typing import List, Optional

from cjm_transcription_core.cli import MEDIA_SUFFIXES


class SourceBrowser:
    """Keyboard file-browser + ordered selection state for the sources stage.

    entries() lists the cwd's visible subdirectories first, then its media files
    (both sorted) — the browsable universe. enter() descends a focused directory
    or toggles a focused file into the run's ordered selection; add_folder()
    selects the focused directory (or the cwd itself) AS a folder source, kept
    unexpanded so expand_sources owns the recursion at run time. Selection is an
    ORDERED list of absolute path strings (run order = pick order); toggling an
    already-selected path removes it (files and folders alike).
    """

    def __init__(self, start_dir: str = "."):
        self.cwd = Path(start_dir).resolve()
        self.cursor = 0
        self.selected: List[str] = []
        self._cache_cwd: Optional[Path] = None  # entries() cache key (None = cold)
        self._cache: List[Path] = []            # cached listing (dirs then files)
        self._cache_keys: List[str] = []        # resolved() strings, row-aligned

    def entries(self) -> List[Path]:
        """The cwd's browsable rows: visible dirs, then media files (sorted).

        CACHED per cwd (drive-2 finding 3a3db22c): navigation calls this on
        EVERY input event, and a full re-enumeration (iterdir + a stat per
        child + sorts) per free-spin wheel tick froze the UI on cold/large
        directories. enter()/up() invalidate by changing cwd; refresh() drops
        the cache explicitly (the app calls it on re-entering the stage)."""
        if self._cache_cwd != self.cwd:
            try:
                children = list(self.cwd.iterdir())
            except OSError:
                children = []
            dirs = sorted(c for c in children
                          if c.is_dir() and not c.name.startswith("."))
            files = sorted(c for c in children if c.is_file()
                           and c.suffix.lower() in MEDIA_SUFFIXES)
            self._cache = dirs + files
            self._cache_keys = [str(p.resolve()) for p in self._cache]
            self._cache_cwd = self.cwd
        return self._cache

    def entry_keys(self) -> List[str]:
        """Resolved-path keys row-aligned with entries() — the selection
        membership check without a per-row resolve() (each one is a syscall)."""
        self.entries()
        return self._cache_keys

    def refresh(self) -> None:
        """Drop the listing cache: the next entries() re-enumerates the cwd."""
        self._cache_cwd = None

    def focused(self) -> Path | None:
        """The entry under the cursor (None on an empty directory)."""
        rows = self.entries()
        if not rows:
            return None
        self.cursor = max(0, min(self.cursor, len(rows) - 1))
        return rows[self.cursor]

    def move(self, delta: int) -> None:
        """Move the cursor by delta, clamped to the entry list."""
        rows = self.entries()
        if rows:
            self.cursor = max(0, min(self.cursor + delta, len(rows) - 1))

    def enter(self) -> None:
        """Descend into a focused directory; toggle-select a focused file."""
        target = self.focused()
        if target is None:
            return
        if target.is_dir():
            self.cwd = target
            self.cursor = 0
        else:
            self.toggle(target)

    def up(self) -> None:
        """Ascend to the parent directory."""
        self.cwd = self.cwd.parent
        self.cursor = 0

    def toggle(self, path: Path) -> None:
        """Add a path to the ordered selection, or remove it if already picked."""
        key = str(path.resolve())
        if key in self.selected:
            self.selected.remove(key)
        else:
            self.selected.append(key)

    def add_folder(self) -> None:
        """Select the focused directory (or the cwd itself) as a FOLDER source."""
        target = self.focused()
        folder = target if (target is not None and target.is_dir()) else self.cwd
        self.toggle(folder)
