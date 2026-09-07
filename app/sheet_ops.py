"""表格交互纯逻辑：汇总改数、搜索过滤、自动识别门控。"""

from __future__ import annotations


def parse_target_jin(raw: object) -> tuple[float | None, str]:
    text = "" if raw is None else str(raw).strip()
    if not text:
        return None, "请输入斤数"
    try:
        value = float(text)
    except ValueError:
        return None, "请输入有效数字"
    if value < 0:
        return None, "斤数不能为负"
    return value, ""


def jin_delta(old: float, new: float) -> float:
    delta = float(new) - float(old)
    return 0.0 if abs(delta) < 1e-9 else delta


def _cell_text(row: list, col: int) -> str:
    if col < 0 or col >= len(row) or row[col] is None:
        return ""
    return str(row[col]).strip()


def row_matches(
    row: list,
    keyword: str,
    *,
    name_col: int,
    also_cols: list[int] | None = None,
) -> bool:
    key = (keyword or "").strip().lower()
    if not key:
        return True
    cols = [name_col] + list(also_cols or [])
    for c in cols:
        if key in _cell_text(row, c).lower():
            return True
    return False


def filter_row_indices(
    rows: list[list],
    keyword: str,
    *,
    name_col: int,
    also_cols: list[int] | None = None,
) -> list[int]:
    return [
        i
        for i, row in enumerate(rows)
        if row_matches(row, keyword, name_col=name_col, also_cols=also_cols)
    ]


def next_match_index(n: int, current: int | None, *, forward: bool) -> int | None:
    if n <= 0:
        return None
    if current is None:
        return 0 if forward else n - 1
    if forward:
        return (current + 1) % n
    return (current - 1) % n


def should_auto_recognize(added: int, skipped_count: int) -> bool:
    return int(added) >= 1 and int(skipped_count) == 0
