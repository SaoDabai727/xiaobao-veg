"""单位识别与换算为斤。"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 单位别名 → 相对「斤」的乘数
_UNIT_FACTORS: dict[str, float] = {
    "斤": 1.0,
    "市斤": 1.0,
    "公斤": 2.0,
    "千克": 2.0,
    "kg": 2.0,
    "KG": 2.0,
    "Kg": 2.0,
    "两": 0.1,
}

# 按长度降序匹配，避免「公斤」被「斤」抢先截断
_UNIT_PATTERN = re.compile(
    r"(斤|市斤|公斤|千克|[kK][gG]|两)",
)


@dataclass(frozen=True)
class UnitResult:
    """单位解析结果。"""

    unit: str  # 规范化后的原始单位名（展示用）
    factor: float  # 换算到斤的乘数
    assumed: bool  # 是否因无法识别而假定为斤


def normalize_unit(raw: str | None) -> UnitResult:
    """识别单位；无法识别时默认按斤，并标记 assumed。"""
    if not raw:
        return UnitResult(unit="斤", factor=1.0, assumed=True)

    text = raw.strip()
    if not text:
        return UnitResult(unit="斤", factor=1.0, assumed=True)

    match = _UNIT_PATTERN.search(text)
    if not match:
        return UnitResult(unit="斤", factor=1.0, assumed=True)

    key = match.group(1)
    # 统一大小写展示
    if key.lower() == "kg":
        display = "kg"
        factor = 2.0
    else:
        display = key
        factor = _UNIT_FACTORS.get(key, 1.0)

    return UnitResult(unit=display, factor=factor, assumed=False)


def to_jin(quantity: float, unit_raw: str | None) -> tuple[float, UnitResult]:
    """将数量换算为斤，返回 (折合斤数, 单位结果)。"""
    ur = normalize_unit(unit_raw)
    return quantity * ur.factor, ur
