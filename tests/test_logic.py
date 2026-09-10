"""解析与汇总、账本逻辑自测。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.aggregator import build_detail_rows
from app.parser import OcrBox, clean_vegetable_name, parse_boxes, parse_line, parse_plain_texts
from app.storage import Ledger
from app.units import to_jin
import app.parser as parser_mod


def _isolate_custom_veg() -> Path:
    """测试用空自定义词库，避免本机 data/custom_vegetables.json 干扰。"""
    td = Path(tempfile.mkdtemp(prefix="veg_custom_"))
    parser_mod._CUSTOM_PATH_OVERRIDE = td / "custom_vegetables.json"
    parser_mod._custom_vegetables.clear()
    parser_mod._rebuild_vegetables()
    return td


def test_units() -> None:
    jin, ur = to_jin(3, "公斤")
    assert jin == 6 and not ur.assumed
    jin, ur = to_jin(10, None)
    assert jin == 10 and ur.assumed


def test_clean_name() -> None:
    _isolate_custom_veg()
    assert clean_vegetable_name("硬菜生姜") == "生姜"
    assert clean_vegetable_name("京葱（大葱）") == "京葱"
    assert clean_vegetable_name("分拣单") == ""
    assert clean_vegetable_name("R水菜") == ""
    assert clean_vegetable_name("水菜") == ""
    assert clean_vegetable_name("商品名称") == ""
    assert clean_vegetable_name("出海单不能少货质量注意") == ""
    assert clean_vegetable_name("广东菜心") == "广东菜心"
    assert clean_vegetable_name("筒蒿菜") == "茼蒿菜"
    assert clean_vegetable_name("面手工牛肉面") == ""
    assert clean_vegetable_name("椒炒饭") == ""
    assert clean_vegetable_name("酸菜鱼") == ""
    # 自由文本仍严格：词库外且不像菜名后缀的不收
    assert clean_vegetable_name("香椿") == ""
    assert clean_vegetable_name("宫保鸡丁") == ""
    assert clean_vegetable_name("红烧肉") == ""
    # 词库内 / 像菜名后缀的仍可
    assert clean_vegetable_name("米苋") == "米苋"


def test_custom_vegetable_library() -> None:
    """用户自定义菜名写入词库后，自由文本识别应放行。"""
    from app.parser import (
        add_custom_vegetable,
        list_custom_vegetables,
        remove_custom_vegetable,
    )

    _isolate_custom_veg()
    assert clean_vegetable_name("香椿") == ""
    assert add_custom_vegetable("香椿") == "香椿"
    assert "香椿" in list_custom_vegetables()
    assert clean_vegetable_name("香椿") == "香椿"
    assert clean_vegetable_name("硬菜香椿") == "香椿"

    chat = [
        OcrBox("香椿3斤", [[80, 80], [140, 80], [140, 100], [80, 100]]),
    ]
    items = parse_boxes(chat)
    assert len(items) == 1
    assert items[0].name == "香椿"
    assert items[0].jin == 3

    assert remove_custom_vegetable("香椿") is True
    assert "香椿" not in list_custom_vegetables()
    assert clean_vegetable_name("香椿") == ""

    # 成品菜仍不可加入
    try:
        add_custom_vegetable("红烧肉")
        assert False, "应拒绝成品菜"
    except ValueError:
        pass

    # 内置菜名不重复写入自定义列表
    assert add_custom_vegetable("西红柿") == "西红柿"
    assert "西红柿" not in list_custom_vegetables()
    from app.parser import is_builtin_vegetable, list_builtin_vegetables

    assert is_builtin_vegetable("西红柿")
    builtins = list_builtin_vegetables()
    assert "西红柿" in builtins
    assert builtins == sorted(builtins)


def test_reject_stall_header_row() -> None:
    """档口表头残片 + 日期 05 不应变成菜名。"""
    from app.parser import parse_boxes, OcrBox

    row = [
        OcrBox("类", [[10, 118], [20, 118], [20, 130], [10, 130]]),
        OcrBox("05", [[70, 119], [90, 119], [90, 130], [70, 130]]),
        OcrBox("位", [[210, 118], [230, 118], [230, 130], [210, 130]]),
        OcrBox("选餐", [[330, 118], [360, 118], [360, 130], [330, 130]]),
        OcrBox("面手工牛肉面", [[1000, 118], [1100, 118], [1100, 130], [1000, 130]]),
        OcrBox("计", [[1500, 118], [1520, 118], [1520, 130], [1500, 130]]),
    ]
    items = parse_boxes(row)
    assert items == []


def test_chat_and_table() -> None:
    _isolate_custom_veg()
    chat = [
        OcrBox("茄子5斤", [[80, 80], [120, 80], [120, 100], [80, 100]]),
        OcrBox("黄瓜5斤", [[80, 110], [120, 110], [120, 130], [80, 130]]),
        OcrBox("藕2节", [[80, 60], [120, 60], [120, 75], [80, 75]]),
    ]
    items = parse_boxes(chat)
    by = {i.name: i for i in items}
    assert by["茄子"].jin == 5
    assert by["黄瓜"].jin == 5
    assert by["藕"].quantity == 2 and by["藕"].jin is None

    # 分拣单行：P硬菜 奶白菜 斤 6 6
    table = [
        OcrBox("P硬菜", [[20, 100], [40, 100], [40, 120], [20, 120]]),
        OcrBox("奶白菜", [[80, 100], [140, 100], [140, 120], [80, 120]]),
        OcrBox("斤", [[260, 100], [280, 100], [280, 120], [260, 120]]),
        OcrBox("6", [[500, 100], [520, 100], [520, 120], [500, 120]]),
        OcrBox("6", [[860, 100], [880, 100], [880, 120], [860, 120]]),
        OcrBox("P硬菜", [[20, 140], [40, 140], [40, 160], [20, 160]]),
        OcrBox("西红柿", [[80, 140], [140, 140], [140, 160], [80, 160]]),
        OcrBox("斤", [[260, 140], [280, 140], [280, 160], [260, 160]]),
        OcrBox("11", [[500, 140], [530, 140], [530, 160], [500, 160]]),
        OcrBox("31", [[860, 140], [890, 140], [890, 160], [860, 160]]),
    ]
    items = parse_boxes(table)
    by = {i.name: i for i in items}
    assert by["奶白菜"].jin == 6
    assert by["西红柿"].jin == 31

    # R水菜 + 广东菜心 + 公斤：应识别菜名并 ×2
    water = [
        OcrBox("R水菜", [[20, 138], [40, 138], [40, 150], [20, 150]]),
        OcrBox("广东菜心", [[90, 138], [150, 138], [150, 150], [90, 150]]),
        OcrBox("公斤", [[400, 140], [430, 140], [430, 152], [400, 152]]),
        OcrBox("2.5", [[500, 140], [530, 140], [530, 152], [500, 152]]),
        OcrBox("2.5", [[800, 140], [830, 140], [830, 152], [800, 152]]),
    ]
    items = parse_boxes(water)
    assert len(items) == 1
    assert items[0].name == "广东菜心"
    assert items[0].unit_raw == "公斤"
    assert items[0].jin == 5.0
    assert all(i.name != "水菜" for i in items)

    # R水菜 + 米苋 + 斤：词库内应识别预定合计
    mi = [
        OcrBox("R水菜", [[20, 100], [40, 100], [40, 120], [20, 120]]),
        OcrBox("米苋", [[80, 100], [140, 100], [140, 120], [80, 120]]),
        OcrBox("斤", [[200, 100], [230, 100], [230, 120], [200, 120]]),
        OcrBox("10", [[340, 100], [370, 100], [370, 120], [340, 120]]),
        OcrBox("25", [[500, 100], [530, 100], [530, 120], [500, 120]]),
        OcrBox("35", [[640, 100], [670, 100], [670, 120], [640, 120]]),
    ]
    items = parse_boxes(mi)
    assert len(items) == 1
    assert items[0].name == "米苋"
    assert items[0].jin == 35.0
    assert items[0].unit_raw == "斤"

    # 分拣单结构完整：未收录菜名可入库，并标待核
    xiangchun = [
        OcrBox("R水菜", [[20, 160], [40, 160], [40, 180], [20, 180]]),
        OcrBox("香椿", [[80, 160], [140, 160], [140, 180], [80, 180]]),
        OcrBox("斤", [[200, 160], [230, 160], [230, 180], [200, 180]]),
        OcrBox("8", [[640, 160], [670, 160], [670, 180], [640, 180]]),
    ]
    items = parse_boxes(xiangchun)
    assert len(items) == 1
    assert items[0].name == "香椿" and items[0].jin == 8.0
    assert "未收录菜名待核" in items[0].remark

    # 无分类的脏行：即使短中文也不放宽
    dirty = [
        OcrBox("选餐", [[80, 200], [120, 200], [120, 220], [80, 220]]),
        OcrBox("香椿", [[140, 200], [180, 200], [180, 220], [140, 220]]),
        OcrBox("计", [[200, 200], [220, 200], [220, 220], [200, 220]]),
    ]
    assert parse_boxes(dirty) == []


def test_parse() -> None:
    a = parse_line("西红柿 5斤")
    assert a and a.name == "西红柿" and a.jin == 5
    b = parse_line("土豆：3公斤")
    assert b and b.name == "土豆" and b.jin == 6


def test_replace_order_change() -> None:
    """改单：卷心菜10改上甘蓝10斤 → 减卷心菜 + 加甘蓝。"""
    from app.parser import parse_line_multi, parse_boxes, OcrBox

    items = parse_line_multi("卷心菜10改上甘蓝10斤")
    assert len(items) == 2
    sub, add = items
    assert sub.name == "卷心菜" and sub.is_subtract and sub.jin == 10
    assert add.name == "甘蓝" and not add.is_subtract and add.jin == 10
    assert add.unit_raw == "斤"
    # 左侧缺单位时，沿用右侧单位
    assert sub.unit_raw == "斤"

    boxes = [
        OcrBox("客服小丽18916172392", [[100, 30], [200, 30], [200, 50], [100, 50]]),
        OcrBox("ZQZY煲禾牛肉饭改单：", [[100, 60], [220, 60], [220, 80], [100, 80]]),
        OcrBox("卷心菜10改上甘蓝10斤", [[100, 80], [240, 80], [240, 100], [100, 100]]),
        OcrBox("@汤传玉", [[100, 110], [160, 110], [160, 130], [100, 130]]),
    ]
    items = parse_boxes(boxes)
    names = {(i.name, i.is_subtract, i.jin) for i in items}
    assert ("卷心菜", True, 10.0) in names
    assert ("甘蓝", False, 10.0) in names
    assert all("牛肉" not in i.name for i in items)


def test_stall_cancel() -> None:
    """档口取消 + 菜名：待填斤数的减项（不认档口名）。"""
    from app.parser import parse_line_multi, parse_boxes, OcrBox

    items = parse_line_multi("1040GY河南烩面 档口取消  香菜")
    assert len(items) == 1
    assert items[0].name == "香菜"
    assert items[0].is_subtract
    assert items[0].jin is None
    assert "档口取消" in items[0].remark

    boxes = [
        OcrBox("22号", [[40, 20], [80, 20], [80, 40], [40, 40]]),
        OcrBox("1040GY河南烩面 档口取消  香菜", [[100, 60], [300, 60], [300, 80], [100, 80]]),
        OcrBox("@汤传玉 .", [[100, 100], [180, 100], [180, 120], [100, 120]]),
    ]
    items = parse_boxes(boxes)
    assert len(items) == 1
    assert items[0].name == "香菜" and items[0].is_subtract
    assert all("烩面" not in i.name for i in items)


def test_ledger() -> None:
    path = Path(__file__).resolve().parent / "_test_ledger.xlsx"
    if path.exists():
        path.unlink()
    ledger = Ledger(path)
    details = build_detail_rows("a.jpg", parse_plain_texts(["西红柿 5斤", "生菜 1斤"]))
    assert ledger.append_details(details) == 2
    summary = {r.name: r.jin for r in ledger.summary()}
    assert summary["西红柿"] == 5
    path.unlink(missing_ok=True)


if __name__ == "__main__":
    test_units()
    test_clean_name()
    test_custom_vegetable_library()
    test_reject_stall_header_row()
    test_chat_and_table()
    test_parse()
    test_replace_order_change()
    test_stall_cancel()
    test_ledger()
    print("all tests passed")
