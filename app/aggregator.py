"""按蔬菜名称合并，斤数相加。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.parser import ParsedItem, normalize_name


@dataclass
class DetailRow:
    """明细行。"""

    source_image: str
    name: str
    quantity: float | None
    unit_raw: str | None
    jin: float | None
    remark: str
    include_in_summary: bool = True
    is_subtract: bool = False


@dataclass
class SummaryRow:
    """汇总行：名称 | 单位(斤) | 斤数。"""

    name: str
    unit: str
    jin: float


def build_detail_rows(
    source_image: str, items: list[ParsedItem]
) -> list[DetailRow]:
    """将解析结果转为明细行。"""
    rows: list[DetailRow] = []
    for it in items:
        rows.append(
            DetailRow(
                source_image=source_image,
                name=it.name,
                quantity=it.quantity,
                unit_raw=it.unit_raw,
                jin=it.jin,
                remark=it.remark,
                include_in_summary=it.include_in_summary,
                is_subtract=it.is_subtract,
            )
        )
    return rows


def aggregate(detail_rows: list[DetailRow]) -> list[SummaryRow]:
    """按名称合并，仅汇总有折合斤数且允许汇总的行。"""
    totals: dict[str, float] = defaultdict(float)
    for row in detail_rows:
        if row.jin is None or not row.include_in_summary:
            continue
        key = normalize_name(row.name)
        # normalize_name 对多菜名可能返回清洗串；优先用 split 后单名
        from app.parser import split_vegetable_names

        parts = split_vegetable_names(row.name)
        key = parts[0] if len(parts) == 1 else (parts[0] if parts else key)
        if not key:
            continue
        totals[key] += row.jin

    result = [
        SummaryRow(name=name, unit="斤", jin=round(total, 3))
        for name, total in totals.items()
        if abs(total) > 1e-9  # 减到 0 的不显示
    ]
    result.sort(key=lambda r: r.name)
    return result
