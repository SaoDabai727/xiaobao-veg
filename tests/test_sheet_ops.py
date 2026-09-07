"""汇总改数 / 搜索 / 自动识别纯逻辑。"""

from __future__ import annotations

from pathlib import Path

from app.aggregator import DetailRow
from app.sheet_ops import (
    filter_row_indices,
    jin_delta,
    next_match_index,
    parse_target_jin,
    row_matches,
    should_auto_recognize,
)
from app.storage import Ledger


def test_parse_target_jin() -> None:
    assert parse_target_jin("12.5") == (12.5, "")
    assert parse_target_jin("0") == (0.0, "")
    assert parse_target_jin(" 8 ") == (8.0, "")
    v, err = parse_target_jin("")
    assert v is None and err
    v, err = parse_target_jin("abc")
    assert v is None and err
    v, err = parse_target_jin("-1")
    assert v is None and "负" in err


def test_jin_delta() -> None:
    assert jin_delta(10, 13) == 3
    assert jin_delta(10, 7) == -3
    assert jin_delta(10, 10) == 0.0
    assert jin_delta(10, 10.0000000001) == 0.0


def test_filter_and_match() -> None:
    rows = [
        ["西红柿", "斤", 5],
        ["生菜", "斤", 2],
        ["番茄炒蛋用西红柿", "斤", 1],
    ]
    assert filter_row_indices(rows, "番茄", name_col=0) == [2]
    assert filter_row_indices(rows, "西红柿", name_col=0) == [0, 2]
    assert filter_row_indices(rows, "", name_col=0) == [0, 1, 2]
    assert filter_row_indices(rows, "XYZ", name_col=0) == []

    detail = [["1", "t", "a.jpg", "生菜", 1, "斤", 1, ""]]
    assert row_matches(detail[0], "a.jpg", name_col=3, also_cols=[2])
    assert not row_matches(detail[0], "b.jpg", name_col=3, also_cols=[2])


def test_next_match_index() -> None:
    assert next_match_index(0, None, forward=True) is None
    assert next_match_index(3, None, forward=True) == 0
    assert next_match_index(3, 0, forward=True) == 1
    assert next_match_index(3, 2, forward=True) == 0
    assert next_match_index(3, 0, forward=False) == 2


def test_should_auto_recognize() -> None:
    assert should_auto_recognize(2, 0) is True
    assert should_auto_recognize(1, 1) is False
    assert should_auto_recognize(0, 0) is False
    assert should_auto_recognize(0, 3) is False


def test_summary_edit_writes_adjust_detail() -> None:
    path = Path(__file__).resolve().parent / "_test_summary_edit.xlsx"
    if path.exists():
        path.unlink()
    ledger = Ledger(path)
    ledger.append_details(
        [
            DetailRow(
                source_image="a.jpg",
                name="西红柿",
                quantity=10,
                unit_raw="斤",
                jin=10,
                remark="",
                include_in_summary=True,
            )
        ]
    )
    old = 10.0
    new, err = parse_target_jin("13")
    assert err == "" and new is not None
    delta = jin_delta(old, new)
    assert delta == 3
    assert ledger.adjust_jin("西红柿", delta, remark="汇总改数")
    by = {r.name: r.jin for r in ledger.summary()}
    assert by["西红柿"] == 13
    recs = ledger.load_records()
    assert any(
        r.get("source") == "手工调整" and float(r.get("jin") or 0) == 3 for r in recs
    )
    path.unlink(missing_ok=True)
