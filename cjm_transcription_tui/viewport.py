"""Cursor-windowed viewport math for the setup TUI's list panes (drive-2
ergonomics batch, work item 1e5f8e5d).

Pure logic, Textual-free (the sources.py precedent: everything that CAN live
below the paint path SHOULD). Every stage paints a flat list that can outgrow
the terminal — drive 1 rendered long directory listings entirely off-screen.
The correction TUI's center-pinned lesson generalizes here to uniform-height
rows: keep the CURSOR row inside the visible window and let the list flow past
it. Also the seed of the shared tui-kit viewport component (work item aafce2c6
opened the N>=2 demand gate).
"""

from typing import Tuple


def visible_slice(
    count: int,   # Total rows in the list
    cursor: int,  # Focused row index (kept inside the returned window)
    budget: int,  # Screen lines available INCLUDING the two indicator lines
) -> Tuple[int, int, int, int]:  # (start, end, hidden_above, hidden_below)
    """Clamped cursor-centered window over a flat list: paint rows[start:end].

    The cursor row sits at the window's center until the window hits either
    end of the list (the correction-TUI center pin, generalized to
    uniform-height rows). When the list overflows the budget, two lines are
    reserved for the caller's "… N above" / "… N below" indicator rows, so
    painting the hidden-row counts never blows the budget.
    """
    if count <= 0 or budget <= 0:
        return 0, 0, 0, max(0, count)
    if count <= budget:
        return 0, count, 0, 0
    inner = max(1, budget - 2)
    start = max(0, min(cursor - inner // 2, count - inner))
    end = start + inner
    return start, end, start, count - end


def tail(
    s: str,      # The string to clamp (paths: the end is the readable part)
    width: int,  # Max characters INCLUDING the leading ellipsis
) -> str:  # s unchanged, or an ellipsis + its last width-1 characters
    """Clamp a string to width keeping its END.

    The row discipline's complement for path-like strings: a filename's tail
    is what the operator reads, so clamping cuts the front (tail-ellipsis
    truncation cuts the wrong end for cwd headers and selected-source rows).
    """
    if width <= 0:
        return ""
    if len(s) <= width:
        return s
    if width == 1:
        return "…"
    return "…" + s[-(width - 1):]
