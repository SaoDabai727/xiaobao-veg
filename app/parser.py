"""从 OCR 文本解析蔬菜名称、数量、单位（按真实分拣单行结构）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.units import to_jin

MAX_JIN_FOR_SUMMARY = 5000.0


@dataclass
class ParsedItem:
    name: str
    quantity: float | None
    unit_raw: str | None
    jin: float | None
    unit_assumed: bool
    remark: str
    source_line: str = ""
    include_in_summary: bool = False
    is_subtract: bool = False  # 图片中识别到的减斤，需人工确认


@dataclass
class OcrBox:
    text: str
    box: list[list[float]] = field(default_factory=list)

    @property
    def cy(self) -> float:
        if not self.box:
            return 0.0
        ys = [p[1] for p in self.box]
        return sum(ys) / len(ys)

    @property
    def cx(self) -> float:
        if not self.box:
            return 0.0
        xs = [p[0] for p in self.box]
        return sum(xs) / len(xs)

    @property
    def right(self) -> float:
        if not self.box:
            return self.cx
        return max(p[0] for p in self.box)


_UNIT_ALT = r"(?:斤|市斤|公斤|千克|[kK][gG]|两)"
_QTY_UNIT = re.compile(rf"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_ALT})?")
_QTY_WITH_UNIT = re.compile(rf"(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>{_UNIT_ALT})")
_LEADING_INDEX = re.compile(r"^[\(（]?\d+[\)）.、．]\s*")
_NOISE_LINE = re.compile(r"^[\d\s\-_=+|\\/.,，。:：;；]+$")
_CAT_TOKEN = re.compile(r"^[PR]?(硬菜|软菜|精品菜|鲜菜|干菜|水菜)$")
_LEADING_NUM = re.compile(r"^(\d+(?:\.\d+)?)(.*)$")
_CHAT_LINE = re.compile(
    r"^(?P<name>[\u4e00-\u9fff·]+?)"
    r"(?P<qty>\d+(?:\.\d+)?)"
    r"(?P<unit>斤|市斤|公斤|千克|个|节|根|箱|两)?"
    r"(?P<tail>.*)$"
)

# 减斤 / 退货常见写法
_SUBTRACT_PATTERNS = (
    re.compile(
        r"减\s*(?P<name>[\u4e00-\u9fff·]{1,12}?)\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>斤|市斤|公斤|千克)?"
    ),
    re.compile(
        r"(?P<name>[\u4e00-\u9fff·]{1,12}?)\s*减\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>斤|市斤|公斤|千克)?"
    ),
    re.compile(
        r"减\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>斤|市斤|公斤|千克)?\s*(?P<name>[\u4e00-\u9fff·]{1,12})"
    ),
    re.compile(
        r"退(?:货|回)?\s*(?P<name>[\u4e00-\u9fff·]{1,12}?)\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>斤|市斤|公斤|千克)?"
    ),
    re.compile(
        r"(?P<name>[\u4e00-\u9fff·]{1,12}?)\s*退(?:货|回)?\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>斤|市斤|公斤|千克)?"
    ),
    re.compile(
        r"扣\s*(?P<name>[\u4e00-\u9fff·]{1,12}?)\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<unit>斤|市斤|公斤|千克)?"
    ),
)

_SUBTRACT_HINT = re.compile(r"减|退货|退回|扣减|少发")
_REPLACE_HINT = re.compile(r"改上|改成|换成|改为|改做")
_REPLACE_PATTERN = re.compile(
    r"(?P<old_name>[\u4e00-\u9fff·]{1,12}?)"
    r"(?P<old_qty>\d+(?:\.\d+)?)\s*(?P<old_unit>斤|市斤|公斤|千克)?"
    r"(?:改上|改成|换成|改为|改做)"
    r"(?P<new_name>[\u4e00-\u9fff·]{1,12}?)"
    r"(?P<new_qty>\d+(?:\.\d+)?)\s*(?P<new_unit>斤|市斤|公斤|千克)?"
)
_CANCEL_HINT = re.compile(r"档口取消")
_CANCEL_PATTERN = re.compile(
    r"档口取消\s*(?P<name>[\u4e00-\u9fff·*]{1,16})"
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^\d{1,2}:\d{2}$")
_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_]{4,}$")

_SKIP_TOKENS = frozenset(
    {
        "斤",
        "市斤",
        "公斤",
        "千克",
        "kg",
        "KG",
        "两",
        "散装",
        "见包装",
        "新鲜蔬菜",
        "物料规格",
        "主单位",
        "预定单位",
        "下单单位",
        "描述",
        "合计",
        "总计",
        "分拣单",
        "分拣单位",
        "二级分",
        "二级分类",
        "物料分类",
        "物料名称",
        "商品名称",
        "发货日期",
        "收货日期",
        "日期",
        "位",
        "日",
        "类",
        "F1",
        "T",
        "P",
        "R",
        "菜金",
        "奶制品",
        "物料分物料品物料名称",
        "客服",
        "客服号",
        "加单",
        "签名",
        "页码",
        "序号",
        "单位",
        "数量",
        "品名",
        "菜名",
        "名称",
        "清单",
        "明细",
        "汇总",
        "硬菜",
        "软菜",
        "水菜",
        "微信",
        "图片",
        "根根",
        "预定",
        "预定单",
        "大灶",
        "临港",
    }
)

_NON_VEGETABLE_NAMES = _SKIP_TOKENS | frozenset(
    {
        "分拣单",
        "分拣单位",
        "加单",
        "发货日期",
        "收货日期",
        "出库日期",
        "入库日期",
        "客户",
        "电话",
        "地址",
        "司机",
        "车牌",
        "仓库",
        "门店",
        "商品名称",
        "物料名称",
        "预定",
        "预定单",
        "水菜",
    }
)

# 表头 / 门店 / 口号 / 档口菜品等脏片段（命中即非菜名）
_JUNK_SUBSTRINGS = (
    "日期",
    "物料",
    "校区",
    "出海",
    "注意",
    "质量",
    "少货",
    "预定",
    "分拣",
    "商品",
    "餐饮",
    "餐厅",
    "美食",
    "快餐",
    "回民",
    "一楼",
    "二楼",
    "三楼",
    "门店",
    "大灶",
    "描述",
    "规格",
    "合计",
    "总计",
    "下单",
    "发货",
    "收货",
    "南溪苑",
    "外婆桥",
    "淮扬",
    "伊源",
    "临港",
    "选餐",
    "炒饭",
    "浇饭",
    "盖浇",
    "酸菜鱼",
    "牛肉面",
    "烩面",
    "手工面",
    "煎饼",
    "砂锅",
    "韩式",
    "港式",
    "辛鱼",
    "林记",
    "朱家",
)

# 自由文本/聊天：未知短词须长得像菜名（后缀白名单）
_VEG_LIKE = re.compile(
    r".+(菜|菇|瓜|椒|葱|蒜|姜|芋|笋|豆|薯|藕|茄|芹|心|苔|苗|耳|芽|苋|萝卜|玉米|白菜|生菜|豆腐|莴笋|莴苣|马蹄|荸荠)$"
    r"|^藕$|^姜$"
)

# 成品菜/档口菜品特征：分拣单行放行未知名时仍用来挡脏数据
_COOKED_DISH = re.compile(
    r"(炒饭|浇饭|盖浇|砂锅|煎饼|烩面|牛肉面|手工面|酸菜鱼|选餐|红烧|宫保|鱼香|糖醋|麻婆)"
    r"|(炒|炖|烩|炸|煮|蒸|煎|煲|焖|溜|爆|烤)"
    r"|.+(饭|面|汤|煲|饺|饼|糊|羹|翅|排|丁|肉)$"
)

_CATEGORY_PREFIXES = ("硬菜", "软菜", "鲜菜", "干菜", "水菜", "蔬菜", "精品菜")
_KEEP_LEADING_CAI = ("菜心", "菜花", "芥菜", "菠菜")

_NOISE_WORDS = (
    "新鲜",
    "精品",
    "特价",
    "特级",
    "有机",
    "散装",
    "箱装",
    "一份",
    "若干",
    "大约",
    "左右",
    "共计",
    "合计",
    "小计",
    "本地",
    "去皮",
    "带箱",
    "二级分",
    "一级分",
    "分类",
)

_BUILTIN_VEGETABLES = frozenset(
    {
        "上海青",
        "杭白菜",
        "杭茄",
        "奶白菜",
        "娃娃菜",
        "大娃娃菜",
        "卷心菜",
        "甘蓝",
        "牛心菜",
        "黄心菜",
        "白菜",
        "小白菜",
        "松花菜",
        "花菜",
        "有机花菜",
        "西兰花",
        "西葫芦",
        "西红柿",
        "番茄",
        "黄瓜",
        "胡萝卜",
        "白萝卜",
        "青萝卜",
        "莲藕",
        "藕带",
        "生姜",
        "大蒜",
        "蒜头",
        "蒜苔",
        "蒜苗",
        "蒜米",
        "蒜肉",
        "线椒",
        "青椒",
        "红椒",
        "彩椒",
        "美人椒",
        "牛角椒",
        "牛椒",
        "红杭椒",
        "尖椒",
        "洋葱",
        "大葱",
        "京葱",
        "小葱",
        "香葱",
        "紫薯",
        "红薯",
        "土豆",
        "黄心土豆",
        "南瓜",
        "老南瓜",
        "带皮甜玉米棒",
        "黄玉米棒",
        "甜玉米",
        "玉米棒",
        "玉米",
        "茄子",
        "豆角",
        "芹菜",
        "西芹",
        "香菜",
        "韭菜",
        "菠菜",
        "生菜",
        "油麦菜",
        "空心菜",
        "米苋",
        "菜心",
        "广东菜心",
        "青菜",
        "芥蓝",
        "苦瓜",
        "丝瓜",
        "冬瓜",
        "芋头",
        "荔浦芋",
        "山药",
        "藕",
        "蘑菇",
        "香菇",
        "平菇",
        "金针菇",
        "木耳",
        "豆芽",
        "豆腐",
        "莴笋",
        "莴苣",
        "包菜",
        "马蹄",
        "马蹄肉",
        "光荸荠",
        "荸荠",
        "茼蒿菜",
        "茼蒿",
        "鸡毛菜",
        "青大蒜",
        "青大蒜叶",
        "小菠菜",
    }
)

# 用户自定义（data/custom_vegetables.json）与内置合并为识别用 _VEGETABLES
_custom_vegetables: set[str] = set()
_CUSTOM_PATH_OVERRIDE: Path | None = None
_VEGETABLES: tuple[str, ...] = ()


def _rebuild_vegetables() -> None:
    global _VEGETABLES
    merged = set(_BUILTIN_VEGETABLES) | _custom_vegetables
    _VEGETABLES = tuple(sorted(merged, key=len, reverse=True))


_rebuild_vegetables()

_HEADER_WORDS = re.compile(
    r"^(蔬菜|菜名|名称|品名|数量|单位|斤数|重量|清单|明细|汇总|日期|时间|硬菜|软菜)$"
)
_JUNK_NAME = re.compile(r"^(蔬菜)+$|^类.*分$|^分.*类$")

# OCR 常见错字 → 标准菜名
_OCR_NAME_FIXES = {
    "筒蒿菜": "茼蒿菜",
    "筒蒿": "茼蒿",
    "同蒿菜": "茼蒿菜",
    "同蒿": "茼蒿",
    "大蒜苔": "蒜苔",
    "西兰化": "西兰花",
    "西胡芦": "西葫芦",
}


def _is_reasonable_qty(qty: float | None) -> bool:
    if qty is None:
        return False
    try:
        q = float(qty)
    except (TypeError, ValueError):
        return False
    if q <= 0 or q > MAX_JIN_FOR_SUMMARY:
        return False
    text = f"{q:.6f}".rstrip("0").rstrip(".")
    int_part = text.split(".", 1)[0].lstrip("-")
    return len(int_part) <= 5


def _box_rows(boxes: list[OcrBox], y_threshold: float = 12.0) -> list[list[OcrBox]]:
    if not boxes:
        return []
    ordered = sorted(boxes, key=lambda b: (b.cy, b.cx))
    rows: list[list[OcrBox]] = [[ordered[0]]]
    for box in ordered[1:]:
        if abs(box.cy - rows[-1][-1].cy) <= y_threshold:
            rows[-1].append(box)
        else:
            rows.append([box])
    return rows


def _strip_category_prefixes(text: str) -> str:
    if not text:
        return ""
    for prefix in sorted(_CATEGORY_PREFIXES, key=len, reverse=True):
        text = re.sub(rf"(?:{re.escape(prefix)})+", "", text)
    if text.startswith("菜") and not text.startswith(_KEEP_LEADING_CAI) and len(text) > 2:
        text = text[1:]
    return text


def custom_vegetables_path() -> Path:
    if _CUSTOM_PATH_OVERRIDE is not None:
        return _CUSTOM_PATH_OVERRIDE
    from app.storage import data_dir

    return data_dir() / "custom_vegetables.json"


def list_custom_vegetables() -> list[str]:
    return sorted(_custom_vegetables)


def list_builtin_vegetables() -> list[str]:
    """内置识别词库（只读）。"""
    return sorted(_BUILTIN_VEGETABLES)


def load_custom_vegetables(path: Path | None = None) -> list[str]:
    """从磁盘加载自定义菜名并合并进识别词库。"""
    global _custom_vegetables
    p = path or custom_vegetables_path()
    names: set[str] = set()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str) and item.strip():
                        names.add(item.strip())
            elif isinstance(raw, dict) and isinstance(raw.get("names"), list):
                for item in raw["names"]:
                    if isinstance(item, str) and item.strip():
                        names.add(item.strip())
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            names = set()
    _custom_vegetables = names
    _rebuild_vegetables()
    return list_custom_vegetables()


def _save_custom_vegetables(path: Path | None = None) -> None:
    p = path or custom_vegetables_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"names": sorted(_custom_vegetables)}
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_custom_vegetable_name(raw: str) -> str:
    """校验并规范化用户要加入词库的菜名；不合法则抛 ValueError。"""
    if not raw or not str(raw).strip():
        raise ValueError("请填写蔬菜名称")
    text = str(raw).strip().lstrip("*").rstrip("*")
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff" or ch == "·")
    text = _strip_category_prefixes(text).strip("·*")
    text = _OCR_NAME_FIXES.get(text, text)
    if not text:
        raise ValueError("请输入中文菜名")
    if len(text) > 8:
        raise ValueError("菜名过长（最多 8 字）")
    if text in _NON_VEGETABLE_NAMES or _HEADER_WORDS.match(text) or _JUNK_NAME.match(text):
        raise ValueError(f"「{text}」不是菜名，不能加入词库")
    if any(j in text for j in _JUNK_SUBSTRINGS):
        raise ValueError(f"「{text}」含无效内容，不能加入词库")
    if _COOKED_DISH.search(text):
        raise ValueError(f"「{text}」像成品菜，不能加入词库")
    return text


def add_custom_vegetable(name: str) -> str:
    """加入自定义词库并落盘。已在内置/自定义中则仍返回规范名。"""
    cleaned = normalize_custom_vegetable_name(name)
    if cleaned in _BUILTIN_VEGETABLES or cleaned in _custom_vegetables:
        return cleaned
    _custom_vegetables.add(cleaned)
    _rebuild_vegetables()
    _save_custom_vegetables()
    return cleaned


def remove_custom_vegetable(name: str) -> bool:
    """仅删除用户自定义项；内置词库不可删。"""
    key = (name or "").strip()
    if key not in _custom_vegetables:
        return False
    _custom_vegetables.discard(key)
    _rebuild_vegetables()
    _save_custom_vegetables()
    return True


def is_builtin_vegetable(name: str) -> bool:
    return (name or "").strip() in _BUILTIN_VEGETABLES


try:
    load_custom_vegetables()
except Exception:  # noqa: BLE001
    _rebuild_vegetables()


def _is_plausible_unknown_veg(text: str) -> bool:
    """未知短中文名是否可作原料菜（先挡表头/成品菜）。"""
    if not text or len(text) < 2 or len(text) > 6:
        return False
    if text in _NON_VEGETABLE_NAMES or _HEADER_WORDS.match(text) or _JUNK_NAME.match(text):
        return False
    if any(j in text for j in _JUNK_SUBSTRINGS):
        return False
    if _COOKED_DISH.search(text):
        return False
    return True


def clean_vegetable_name(raw: str, *, truncate: bool = True) -> str:
    if not raw:
        return ""
    text = raw.strip().lstrip("*").rstrip("*")
    text = re.sub(r"^P?(硬菜|软菜|精品菜|鲜菜|干菜|水菜)", "", text)
    text = re.sub(r"^R水菜", "", text)
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    text = re.sub(r"[￥¥]\s*\d+(?:\.\d+)?", "", text)
    text = re.sub(r"\d+(?:\.\d+)?\s*元", "", text)
    text = re.sub(rf"{_UNIT_ALT}", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+(?:\.\d+)?", "", text)
    text = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff" or ch == "·")
    for word in _NOISE_WORDS:
        if text.startswith(word) and len(text) > len(word) + 1:
            text = text[len(word) :]
        else:
            text = text.replace(word, "")
    text = _strip_category_prefixes(text).strip("·*")
    text = _OCR_NAME_FIXES.get(text, text)
    if not text or text in _NON_VEGETABLE_NAMES or _HEADER_WORDS.match(text) or _JUNK_NAME.match(text):
        return ""
    if any(j in text for j in _JUNK_SUBSTRINGS):
        return ""
    # 单字菜名仅保留词库中的（如「藕」）
    if len(text) <= 1:
        return text if text in _VEGETABLES else ""
    # 自由文本：未知名须像菜名后缀；过长多半是表头/口号
    if text not in _VEGETABLES:
        if len(text) > 6:
            return ""
        if not _VEG_LIKE.match(text):
            return ""
        if _COOKED_DISH.search(text):
            return ""
    if truncate and len(text) > 16:
        text = text[:16]
    return text


def split_vegetable_names(raw: str) -> list[str]:
    text = clean_vegetable_name(raw, truncate=False)
    if not text:
        return []
    found: list[str] = []
    remaining = text
    while remaining:
        matched = False
        for veg in _VEGETABLES:
            if remaining.startswith(veg):
                found.append(veg)
                remaining = remaining[len(veg) :]
                matched = True
                break
        if not matched:
            if (
                remaining in _VEGETABLES
                or (
                    _is_plausible_unknown_veg(remaining)
                    and _VEG_LIKE.match(remaining)
                )
            ):
                found.append(remaining)
            break
    seen: set[str] = set()
    out: list[str] = []
    for name in found:
        if name not in seen and name not in _NON_VEGETABLE_NAMES:
            seen.add(name)
            out.append(name)
    return out


def normalize_name(name: str) -> str:
    names = split_vegetable_names(name)
    if len(names) == 1:
        return names[0]
    if names:
        return names[0]
    return clean_vegetable_name(name)


def _clean_name_cell(text: str, *, allow_unknown: bool = False) -> str:
    """表格单元格菜名。allow_unknown 仅用于结构完整的分拣单行。"""
    t = text.strip().lstrip("*").rstrip("*")
    if not t or t in _SKIP_TOKENS:
        return ""
    if _CAT_TOKEN.match(t) or _DATE.match(t) or _TIME.match(t):
        return ""
    if _CODE.match(t) and not any("\u4e00" <= c <= "\u9fff" for c in t):
        return ""
    # 纯数字不是菜名
    if re.fullmatch(r"\d+(?:\.\d+)?", t.replace(" ", "")):
        return ""
    if t[0].isdigit():
        return ""
    cleaned = clean_vegetable_name(t, truncate=True)
    if cleaned:
        return cleaned
    if not allow_unknown:
        return ""
    # 分拣单结构完整时：干净短中文可入库（成品菜/脏词仍拒）
    only = re.sub(r"[（(][^）)]*[）)]", "", t)
    only = "".join(c for c in only if "\u4e00" <= c <= "\u9fff")
    only = _strip_category_prefixes(only).strip("*")
    if only in _VEGETABLES:
        return only
    if _is_plausible_unknown_veg(only):
        return only
    return ""


def _row_allows_unknown_name(tokens: list[tuple[float, str]]) -> bool:
    """像真实分拣单数据行才放行未知菜名：有分类，且有单位或数量。"""
    texts = [t for _, t in tokens]
    has_cat = any(
        _CAT_TOKEN.match(t) or t.startswith("P硬") or t.startswith("P精") for t in texts
    )
    if not has_cat:
        return False
    has_unit = any(t in ("斤", "市斤", "公斤", "千克", "kg", "KG") for t in texts)
    num_n = 0
    for t in texts:
        m = _LEADING_NUM.match(t.replace(" ", ""))
        if not m or not t[0].isdigit():
            continue
        raw_num = m.group(1)
        if "." not in raw_num and len(raw_num) >= 2 and raw_num.startswith("0"):
            continue
        if _is_reasonable_qty(float(raw_num)):
            num_n += 1
    return has_unit or num_n >= 1


def _make_item(
    name: str,
    qty: float | None,
    unit_raw: str | None,
    line: str,
    *,
    is_subtract: bool = False,
) -> ParsedItem | None:
    if not name or name in _NON_VEGETABLE_NAMES:
        return None
    if any(j in name for j in _JUNK_SUBSTRINGS):
        return None
    if qty is not None and not _is_reasonable_qty(qty):
        return ParsedItem(
            name=name,
            quantity=None,
            unit_raw=None,
            jin=None,
            unit_assumed=False,
            remark="斤数异常待核",
            source_line=line,
            include_in_summary=False,
            is_subtract=False,
        )
    if qty is None:
        # 无数量的表头/口号不再入库，避免污染明细
        return None
    jin, ur = to_jin(qty, unit_raw)
    if is_subtract:
        return ParsedItem(
            name=name,
            quantity=qty,
            unit_raw=ur.unit,
            jin=jin,
            unit_assumed=ur.assumed,
            remark="待确认减斤",
            source_line=line,
            include_in_summary=False,
            is_subtract=True,
        )
    remark = "单位假定" if ur.assumed else ""
    return ParsedItem(
        name=name,
        quantity=qty,
        unit_raw=ur.unit,
        jin=jin,
        unit_assumed=ur.assumed,
        remark=remark,
        source_line=line,
        include_in_summary=True,
        is_subtract=False,
    )


def parse_subtract_text(text: str) -> ParsedItem | None:
    """从含「减/退/扣」的文本解析减斤项。"""
    raw = re.sub(r"\s+", "", text.strip())
    if not raw or not _SUBTRACT_HINT.search(raw):
        return None
    # 改单句优先走 replace，避免「改」误触
    if _REPLACE_HINT.search(raw):
        return None
    for pat in _SUBTRACT_PATTERNS:
        m = pat.search(raw)
        if not m:
            continue
        name = _clean_name_cell(m.group("name"))
        qty = float(m.group("qty"))
        unit = m.groupdict().get("unit")
        if name and _is_reasonable_qty(qty):
            return _make_item(name, qty, unit, text, is_subtract=True)
    return None


def parse_replace_text(text: str) -> list[ParsedItem]:
    """解析「A10改上B10斤」类改单：返回 [减项, 加项]。"""
    raw = re.sub(r"\s+", "", text.strip())
    if not raw or not _REPLACE_HINT.search(raw):
        return []
    # 仅标题「…改单：」无具体菜名时跳过
    if re.fullmatch(r".*改单[:：]?$", raw) and not _REPLACE_PATTERN.search(raw):
        return []
    m = _REPLACE_PATTERN.search(raw)
    if not m:
        return []
    old_name = _clean_name_cell(m.group("old_name"))
    new_name = _clean_name_cell(m.group("new_name"))
    old_qty = float(m.group("old_qty"))
    new_qty = float(m.group("new_qty"))
    old_unit = m.group("old_unit")
    new_unit = m.group("new_unit")
    # 一侧缺单位时沿用另一侧
    if not old_unit and new_unit:
        old_unit = new_unit
    if not new_unit and old_unit:
        new_unit = old_unit
    if not old_name or not new_name:
        return []
    if not _is_reasonable_qty(old_qty) or not _is_reasonable_qty(new_qty):
        return []
    pair = f"{old_name}:{old_qty}:{new_name}:{new_qty}"
    sub = _make_item(old_name, old_qty, old_unit, text, is_subtract=True)
    add = _make_item(new_name, new_qty, new_unit, text, is_subtract=False)
    if not sub or not add:
        return []
    sub.remark = f"待确认改单|{pair}"
    add.remark = f"改单加项|{pair}"
    add.include_in_summary = False
    return [sub, add]


def parse_cancel_text(text: str) -> ParsedItem | None:
    """解析「档口取消 + 菜名」：只取菜名，斤数待弹窗填写。"""
    raw = re.sub(r"\s+", "", text.strip())
    if not raw or not _CANCEL_HINT.search(raw):
        return None
    # 去掉 @提及
    raw = re.sub(r"@[\u4e00-\u9fffA-Za-z0-9_]+.*$", "", raw)
    m = _CANCEL_PATTERN.search(raw)
    if not m:
        return None
    name = _clean_name_cell(m.group("name"))
    if not name:
        return None
    return ParsedItem(
        name=name,
        quantity=None,
        unit_raw=None,
        jin=None,
        unit_assumed=False,
        remark="待填斤数-档口取消",
        source_line=text,
        include_in_summary=False,
        is_subtract=True,
    )


def _parse_row_boxes(row: list[OcrBox]) -> list[ParsedItem]:
    """解析一行 OCR 框：菜名 + 最右侧合计数量；优先识别改单/减斤。"""
    boxes = sorted(row, key=lambda b: b.cx)
    tokens = [(b.cx, b.text.strip()) for b in boxes if b.text.strip()]
    if not tokens:
        return []

    line = " ".join(t for _, t in tokens)

    # 整行 / 单框先试改单，再试档口取消，再试减斤
    rep = parse_replace_text(line)
    if rep:
        return rep
    for _, t in tokens:
        rep = parse_replace_text(t)
        if rep:
            return rep

    cancel = parse_cancel_text(line)
    if cancel:
        return [cancel]
    for _, t in tokens:
        cancel = parse_cancel_text(t)
        if cancel:
            return [cancel]

    sub = parse_subtract_text(line)
    if sub:
        return [sub]
    for _, t in tokens:
        sub = parse_subtract_text(t)
        if sub:
            return [sub]

    # 表头行
    header_hits = sum(
        1
        for key in ("预定单位", "物料名称", "发货日期", "二级分类", "主单位", "描述")
        if key in line
    )
    if header_hits >= 1 and not any(_clean_name_cell(t) for _, t in tokens):
        return []
    if "分拣单" in line and not any(
        _CAT_TOKEN.match(t) or t.startswith("P硬") or t.startswith("P精") for _, t in tokens
    ):
        # 标题行
        if not any(_clean_name_cell(t) for _, t in tokens):
            return []

    allow_unknown = _row_allows_unknown_name(tokens)
    names: list[str] = []
    nums: list[tuple[float, float]] = []  # cx, qty
    unit: str | None = None

    for cx, t in tokens:
        if _CAT_TOKEN.match(t):
            continue
        if t in _SKIP_TOKENS:
            if t in ("公斤", "千克", "kg", "KG"):
                unit = "公斤"
            elif t in ("斤", "市斤"):
                unit = "斤"
            continue
        if _DATE.match(t) or _TIME.match(t):
            continue
        # 门店编码列
        if re.fullmatch(r"\d{6,}", t):
            continue
        if _CODE.match(t) and not any("\u4e00" <= c <= "\u9fff" for c in t):
            continue

        # 数量：10(5.00;6.00;) / 5(蒜米) / 2个 / 8.5
        # 跳过日期残片「05」「09」等前导零整数
        m = _LEADING_NUM.match(t.replace(" ", ""))
        if m and t[0].isdigit():
            raw_num = m.group(1)
            if (
                "." not in raw_num
                and len(raw_num) >= 2
                and raw_num.startswith("0")
            ):
                continue
            q = float(raw_num)
            rest = m.group(2) or ""
            if "公斤" in rest or "kg" in rest.lower():
                unit = "公斤"
            elif "斤" in rest:
                unit = unit or "斤"
            # 「2个」仍记录数字，单位保持行内斤/公斤；个不计为重量单位
            if _is_reasonable_qty(q):
                nums.append((cx, q))
            continue

        # 单框聊天：茄子5斤 / 藕2节 / 白菜3个@某人（聊天走严格菜名，不放宽）
        cm = _CHAT_LINE.match(t.replace(" ", ""))
        if cm and cm.group("name") and cm.group("qty"):
            n = _clean_name_cell(cm.group("name"), allow_unknown=False)
            q = float(cm.group("qty"))
            u = cm.group("unit")
            tail = cm.group("tail") or ""
            # 尾部若还有很多汉字，可能不是聊天短句
            if len(re.findall(r"[\u4e00-\u9fff]", tail)) > 4:
                pass
            elif n and _is_reasonable_qty(q):
                if u in ("个", "节", "根", "箱"):
                    return [
                        ParsedItem(
                            name=n,
                            quantity=q,
                            unit_raw=u,
                            jin=None,
                            unit_assumed=False,
                            remark=f"单位为{u}，未折斤",
                            source_line=t,
                            include_in_summary=False,
                        )
                    ]
                item = _make_item(n, q, u or unit, t)
                return [item] if item else []

        name = _clean_name_cell(t, allow_unknown=allow_unknown)
        if name:
            names.append(name)

    if not names:
        return []

    # 多菜名同行：优先词库菜名；否则取最长
    veg_names = [n for n in names if n in _VEGETABLES]
    primary = max(veg_names or names, key=len)

    qty = nums[-1][1] if nums else None
    if unit is None and qty is not None:
        unit = "斤"

    item = _make_item(primary, qty, unit, line)
    if item and primary not in _VEGETABLES:
        note = "未收录菜名待核"
        item.remark = f"{item.remark}；{note}" if item.remark else note
    return [item] if item else []


def parse_boxes(boxes: list[OcrBox]) -> list[ParsedItem]:
    """主入口：按行解析分拣单 / 聊天清单。"""
    if not boxes:
        return []
    # 表格行距较密，阈值 12；手写可再兜底
    items: list[ParsedItem] = []
    for row in _box_rows(boxes, y_threshold=12.0):
        items.extend(_parse_row_boxes(row))
    if len(items) >= 2:
        return _dedupe_keep_order(items)

    items2: list[ParsedItem] = []
    for row in _box_rows(boxes, y_threshold=20.0):
        items2.extend(_parse_row_boxes(row))
    best = items2 if len(items2) > len(items) else items
    if best:
        return _dedupe_keep_order(best)

    # 最后兜底：整图按文本行
    return parse_plain_texts([b.text for b in boxes])


def _dedupe_keep_order(items: list[ParsedItem]) -> list[ParsedItem]:
    """同一菜名多次出现要保留（不同单累加），不做去重。"""
    return items


def parse_line(line: str) -> ParsedItem | None:
    items = parse_line_multi(line)
    return items[0] if items else None


def parse_line_multi(line: str) -> list[ParsedItem]:
    text = line.strip()
    if not text or _NOISE_LINE.match(text):
        return []
    text = _LEADING_INDEX.sub("", text)

    replaced = parse_replace_text(text)
    if replaced:
        return replaced

    cancel = parse_cancel_text(text)
    if cancel:
        return [cancel]

    sub = parse_subtract_text(text)
    if sub:
        return [sub]

    # 聊天格式（不含改单；改单已在上面处理）
    compact = re.sub(r"\s+", "", text)
    if _REPLACE_HINT.search(compact):
        return []
    cm = _CHAT_LINE.match(compact)
    if cm:
        name = clean_vegetable_name(cm.group("name"))
        qty = float(cm.group("qty"))
        unit = cm.group("unit")
        if unit in ("个", "节", "根", "箱"):
            unit = None
        item = _make_item(name, qty, unit, line)
        return [item] if item else []

    # 通用：名称+数量
    m = _QTY_WITH_UNIT.search(text) or None
    matches = list(_QTY_UNIT.finditer(text))
    qty = unit = None
    name_src = text
    if m:
        qty = float(m.group("qty"))
        unit = m.group("unit")
        name_src = (text[: m.start()] + text[m.end() :]).strip()
    else:
        for mm in reversed(matches):
            q = float(mm.group("qty"))
            if _is_reasonable_qty(q):
                qty = q
                unit = mm.group("unit")
                name_src = (text[: mm.start()] + text[mm.end() :]).strip()
                break

    names = split_vegetable_names(name_src)
    if not names:
        n = clean_vegetable_name(name_src)
        names = [n] if n else []
    if not names:
        return []
    result: list[ParsedItem] = []
    for i, name in enumerate(names):
        q = qty if i == len(names) - 1 else None
        item = _make_item(name, q, unit if q is not None else None, line)
        if item:
            result.append(item)
    return result


def parse_plain_texts(texts: list[str]) -> list[ParsedItem]:
    items: list[ParsedItem] = []
    for text in texts:
        for part in re.split(r"[\n|;；]", text):
            items.extend(parse_line_multi(part.strip()))
    return items


# 兼容旧测试 / 导出
def cluster_lines(boxes: list[OcrBox], y_threshold: float = 22.0) -> list[str]:
    rows = _box_rows(boxes, y_threshold)
    lines: list[str] = []
    for row in rows:
        parts = [b.text.strip() for b in sorted(row, key=lambda x: x.cx) if b.text.strip()]
        if parts:
            lines.append(" ".join(parts))
    return lines
