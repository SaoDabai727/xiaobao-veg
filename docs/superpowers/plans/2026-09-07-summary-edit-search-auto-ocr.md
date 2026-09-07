# 汇总可编辑 · 菜名搜索 · 条件自动识别 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让汇总页可直接改斤数（差额写入手工调整明细）、表格上方可按菜名过滤并上下条跳转、选图在无跳过提示时自动开始识别。

**Architecture:** 纯逻辑放进新建 `app/sheet_ops.py`（斤数解析/差额、行过滤、匹配索引、是否自动识别），GUI 只在 `app/main.py` 接线：汇总启用 `edit_cell` + `extra_bindings("end_edit_cell")`，搜索用内存全量数据 + `set_sheet_data` 过滤视图，`_add_images` 按条件调用 `_start_recognize`。账本写入复用现有 `Ledger.adjust_jin`。

**Tech Stack:** Python 3、CustomTkinter、tksheet、openpyxl（经 `Ledger`）

## Global Constraints

- 汇总仅「斤数」列可编辑；菜名/单位只读
- 改斤数 = 目标值 − 旧值 → `adjust_jin(name, delta)`；不依赖「保存表格修改」
- 允许改为 `0`；不允许负数；非法输入恢复原值
- 搜索：一个关键字作用于当前标签页；明细额外匹配「来源图片」
- 自动识别：仅当 `added >= 1` 且本次 `skipped` 为空；有跳过则提示手动点「开始识别」
- 不改菜名合并逻辑；不新建独立校正页

---

## File map

| File | Responsibility |
|------|----------------|
| `app/sheet_ops.py`（新建） | 纯函数：解析目标斤数、过滤行、循环索引、是否自动识别 |
| `app/main.py` | 汇总编辑绑定、搜索栏 UI、过滤/跳转、条件自动识别 |
| `tests/test_sheet_ops.py`（新建） | `sheet_ops` 与「汇总改数 → 账本」集成断言 |
| `README.md` | 补充汇总可改、搜索、自动识别说明（最后一步） |

---

### Task 1: 纯逻辑 `sheet_ops` + 测试

**Files:**
- Create: `app/sheet_ops.py`
- Create: `tests/test_sheet_ops.py`
- Modify: none yet

**Interfaces:**
- Produces:
  - `parse_target_jin(raw: object) -> tuple[float | None, str]`  
    成功返回 `(value, "")`；失败返回 `(None, reason)`。`value` 必须 `>= 0`。
  - `jin_delta(old: float, new: float) -> float`  
    `|delta| < 1e-9` 时返回 `0.0`。
  - `row_matches(row: list, keyword: str, *, name_col: int, also_cols: list[int] | None = None) -> bool`
  - `filter_row_indices(rows: list[list], keyword: str, *, name_col: int, also_cols: list[int] | None = None) -> list[int]`  
    空关键字返回全部索引 `list(range(len(rows)))`。
  - `next_match_index(n: int, current: int | None, *, forward: bool) -> int | None`  
    `n==0` → `None`；否则在 `0..n-1` 循环。
  - `should_auto_recognize(added: int, skipped_count: int) -> bool`  
    `added >= 1 and skipped_count == 0`。

- [ ] **Step 1: Write the failing tests**

创建 `tests/test_sheet_ops.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_sheet_ops.py -v
```

Expected: FAIL（`ModuleNotFoundError: app.sheet_ops` 或导入错误）

- [ ] **Step 3: Implement `app/sheet_ops.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_sheet_ops.py -v
```

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```powershell
git add app/sheet_ops.py tests/test_sheet_ops.py
git commit -m "feat: add sheet_ops helpers for summary edit and search"
```

---

### Task 2: 汇总页斤数可编辑并写差额

**Files:**
- Modify: `app/main.py`（汇总 Sheet 绑定、`_reload_sheets` 样式、新增 `_on_summary_cell_edited`）
- Test: 手工 GUI；逻辑已由 Task 1 的 `test_summary_edit_writes_adjust_detail` 覆盖

**Interfaces:**
- Consumes: `parse_target_jin`, `jin_delta`；`Ledger.adjust_jin(name, delta, remark="")`
- Produces: 汇总「斤数」列编辑后自动入库并刷新

- [ ] **Step 1: 放开汇总编辑绑定，名称/单位只读**

在 `_build_ui` 里创建 `self._sheet_summary` 之后，把只读绑定改成可编辑斤数：

```python
self._style_sheet(self._sheet_summary, readonly=False)
self._sheet_summary.enable_bindings(
    "single_select",
    "drag_select",
    "column_width_resize",
    "copy",
    "arrowkeys",
    "edit_cell",
)
self._sheet_summary.extra_bindings(
    [("end_edit_cell", self._on_summary_cell_edited)]
)
```

在 `_reload_sheets` 末尾（`set_sheet_data` / `_fit_columns` / `_style_sheet` 之后）锁定前两列：

```python
try:
    nrows = len(d2 or [])
    self._sheet_summary.readonly_columns(columns=[0, 1], readonly=True)
    if nrows:
        # 斤数列保持可编辑（列索引 2）
        self._sheet_summary.readonly_columns(columns=[2], readonly=False)
except Exception:
    pass
```

注意：`_reload_sheets` 里原先 `self._style_sheet(self._sheet_summary, readonly=True)` 改为 `readonly=False`（`readonly` 参数目前只影响注释语义/未来扩展，绑定以 `enable_bindings` 为准）。

- [ ] **Step 2: 实现 `_on_summary_cell_edited`**

在 `App` 中新增方法（放在 `_reload_sheets` 附近）：

```python
def _on_summary_cell_edited(self, event=None) -> None:
    if self._busy or self._sheet_summary is None:
        return
    try:
        # tksheet EventDataDict：row/column 为数据行列
        row = int(event.row)
        col = int(event.column)
    except Exception:
        return
    if col != 2:
        return
    data = self._sheet_summary.get_sheet_data()
    if row < 0 or row >= len(data):
        return
    name = str(data[row][0] or "").strip()
    if not name:
        return
    # 编辑前的旧值：从账本汇总取更稳；若取不到则用单元格历史
    old_map = {r.name: float(r.jin or 0) for r in self._ledger.summary()}
    old = float(old_map.get(name, 0))
    new, err = parse_target_jin(data[row][2])
    if err:
        messagebox.showwarning("提示", err)
        self._reload_sheets()
        self._reapply_search_filter()
        return
    assert new is not None
    if new < 0:
        messagebox.showwarning("提示", "斤数不能为负")
        self._reload_sheets()
        self._reapply_search_filter()
        return
    delta = jin_delta(old, new)
    if delta == 0.0:
        return
    try:
        self._ledger.adjust_jin(name, delta, remark="汇总改数")
        self._reload_sheets()
        self._reapply_search_filter()
        self._status.configure(text=f"已调整：{name} {delta:+g} 斤")
    except Exception as exc:
        traceback.print_exc()
        messagebox.showerror("错误", f"调整失败：{exc}")
        self._reload_sheets()
        self._reapply_search_filter()
```

在文件顶部增加：

```python
from app.sheet_ops import (
    filter_row_indices,
    jin_delta,
    next_match_index,
    parse_target_jin,
    should_auto_recognize,
)
```

临时先加空实现，避免 NameError（Task 3 再写全）：

```python
def _reapply_search_filter(self) -> None:
    return
```

- [ ] **Step 3: 手工验证**

Run: `python run.py`

1. 账本有「西红柿」若干斤 → 汇总改成更大/更小数 → 状态栏显示差额；明细出现「手工调整」  
2. 改为 `0` 成功；输入 `abc` / `-1` 弹提示并恢复  
3. 双击菜名列无法改（或改完被只读拦住）

- [ ] **Step 4: Commit**

```powershell
git add app/main.py
git commit -m "feat: allow editing summary jin with adjust_jin delta"
```

---

### Task 3: 搜索栏（过滤 + 上一条/下一条）

**Files:**
- Modify: `app/main.py`（工具栏与 Tab 之间加搜索条；过滤状态；标签切换）

**Interfaces:**
- Consumes: `filter_row_indices`, `next_match_index`
- Produces: `self._search_var`, `self._detail_full`, `self._summary_full`, `self._match_pos`

- [ ] **Step 1: 在 `__init__` / `_build_ui` 增加搜索状态**

在 `App.__init__`（`_busy` 旁）增加：

```python
self._detail_full: list[list] = []
self._summary_full: list[list] = []
self._match_pos: int | None = None
```

在 `tool` 与 `self._tabs` 之间插入搜索栏（`right` 容器内、`self._tabs.pack` 之前）：

```python
search_bar = ctk.CTkFrame(right, fg_color="transparent")
search_bar.pack(fill="x", padx=12, pady=(4, 4))
ctk.CTkLabel(search_bar, text="查菜名", font=ui_font(13, "bold")).pack(
    side="left", padx=(0, 8)
)
self._search_var = ctk.StringVar(value="")
self._search_entry = ctk.CTkEntry(
    search_bar,
    textvariable=self._search_var,
    width=220,
    height=34,
    font=ui_font(14),
    placeholder_text="输入菜名关键字…",
)
self._search_entry.pack(side="left", padx=(0, 6))
self._search_entry.bind("<KeyRelease>", lambda _e: self._on_search_changed())
ctk.CTkButton(
    search_bar, text="上一条", width=72, height=34, font=ui_font(13),
    command=lambda: self._goto_match(forward=False),
).pack(side="left", padx=(0, 4))
ctk.CTkButton(
    search_bar, text="下一条", width=72, height=34, font=ui_font(13),
    command=lambda: self._goto_match(forward=True),
).pack(side="left", padx=(0, 4))
ctk.CTkButton(
    search_bar, text="清空", width=64, height=34, font=ui_font(13),
    fg_color="#6c757d", hover_color="#5a6268",
    command=self._clear_search,
).pack(side="left")
```

绑定 Tab 切换（CustomTkinter Tabview 用 `configure(command=...)` 若可用；否则在 `_on_search_changed` 被调用时读 `self._tabs.get()`）。推荐在 `_build_ui` 末尾：

```python
try:
    self._tabs.configure(command=lambda _=None: self._on_search_changed())
except Exception:
    pass
```

- [ ] **Step 2: `_reload_sheets` 保存全量并应用过滤**

在设置 sheet data 前保存：

```python
self._detail_full = [list(r) for r in (d1 or [])]
self._summary_full = [list(r) for r in (d2 or [])]
```

先 `set_sheet_data` 全量，再调用 `self._reapply_search_filter()`（不要在过滤前写死状态栏「明细 N 行」被冲掉也行：过滤后再设状态栏或保留全量统计）。

推荐状态栏在无搜索时：`明细 {len(d1)} 行 · 汇总 {len(d2)} 种`；有搜索时由 `_reapply_search_filter` / `_goto_match` 覆盖为匹配提示。

- [ ] **Step 3: 实现过滤与跳转**

```python
def _current_sheet_ctx(self) -> tuple[Sheet, list[list], int, list[int] | None]:
    """返回 (sheet, full_rows, name_col, also_cols)。"""
    tab = self._tabs.get()
    if tab == "明细":
        assert self._sheet_detail is not None
        return self._sheet_detail, self._detail_full, 3, [2]
    assert self._sheet_summary is not None
    return self._sheet_summary, self._summary_full, 0, None


def _clear_search(self) -> None:
    self._search_var.set("")
    self._match_pos = None
    self._on_search_changed()


def _on_search_changed(self) -> None:
    self._match_pos = None
    self._reapply_search_filter()


def _reapply_search_filter(self) -> None:
    if self._sheet_detail is None or self._sheet_summary is None:
        return
    keyword = self._search_var.get() if hasattr(self, "_search_var") else ""
    sheet, full, name_col, also = self._current_sheet_ctx()
    idxs = filter_row_indices(full, keyword, name_col=name_col, also_cols=also)
    view = [full[i] for i in idxs]
    sheet.set_sheet_data(view, reset_col_positions=False, reset_row_positions=True)
    try:
        sheet.set_all_row_heights(ROW_H)
    except Exception:
        pass
    if (keyword or "").strip() == "":
        return
    if not idxs:
        self._status.configure(text="未找到")
    else:
        self._status.configure(text=f"第 1/{len(idxs)} 条候选 · 点下一条定位")
        # 不强制改 match_pos；等用户点上下条


def _goto_match(self, *, forward: bool) -> None:
    keyword = self._search_var.get()
    sheet, full, name_col, also = self._current_sheet_ctx()
    idxs = filter_row_indices(full, keyword, name_col=name_col, also_cols=also)
    n = len(idxs)
    if n == 0:
        self._status.configure(text="未找到")
        return
    self._match_pos = next_match_index(n, self._match_pos, forward=forward)
    assert self._match_pos is not None
    # 视图行号即 0..n-1
    r = self._match_pos
    try:
        sheet.deselect("all")
        sheet.select_row(r)
        sheet.see(row=r, keep_yscroll=False)
    except Exception:
        try:
            sheet.set_currently_selected(r, 0)
        except Exception:
            pass
    self._status.configure(text=f"第 {self._match_pos + 1}/{n} 条")
```

若汇总在过滤视图下编辑斤数：`_on_summary_cell_edited` 已按**当前视图行**取菜名，再 `adjust_jin` + `_reload_sheets` + `_reapply_search_filter`，正确。

- [ ] **Step 4: 手工验证**

1. 汇总输入「西红柿」→ 只显示匹配行；下一条循环高亮；清空恢复  
2. 切到明细，同一关键字过滤菜名；用图片文件名关键字也能命中  
3. 无匹配显示「未找到」；上下条无崩溃

- [ ] **Step 5: Commit**

```powershell
git add app/main.py
git commit -m "feat: add vegetable name search filter and navigation"
```

---

### Task 4: 条件自动识别

**Files:**
- Modify: `app/main.py` 的 `_add_images`

**Interfaces:**
- Consumes: `should_auto_recognize(added, skipped_count)`
- Produces: 无跳过且有新图时调用 `_start_recognize()`

- [ ] **Step 1: 改 `_add_images` 结尾**

将现有：

```python
if skipped:
    messagebox.showinfo(...)
elif added:
    self._status.configure(text=f"已加入待识别 {added} 张")
```

替换为：

```python
if skipped:
    messagebox.showinfo(
        "已跳过重复图片",
        "以下图片已在左侧「已入库」列表中，已自动跳过，避免重复识别：\n\n"
        + "\n".join(skipped[:15])
        + ("\n…" if len(skipped) > 15 else "")
        + f"\n\n新加入待识别：{added} 张",
    )
    if added:
        self._status.configure(
            text=f"已加入 {added} 张（有跳过），请点「开始识别」"
        )
elif added:
    self._status.configure(text=f"已加入 {added} 张，开始识别…")

if should_auto_recognize(added, len(skipped)):
    self._start_recognize()
```

- [ ] **Step 2: 手工验证**

1. 选从未入库的图 → 选完后自动进入识别进度（无需点按钮）  
2. 混入已入库同名图 → 出现跳过提示，**不**自动识别；待识别仍有新图；点「开始识别」可继续  
3. 全部重复跳过 → 不自动识别  
4. 识别中 busy 时无法再添加（现有）

- [ ] **Step 3: 跑回归测试**

```powershell
$env:PYTHONPATH="."
python -m pytest tests/test_sheet_ops.py tests/test_logic.py -v
```

Expected: PASS

- [ ] **Step 4: Commit**

```powershell
git add app/main.py
git commit -m "feat: auto-recognize after add when no skips"
```

---

### Task 5: README 与收尾核对

**Files:**
- Modify: `README.md` 功能/使用步骤

- [ ] **Step 1: 更新 README 对应段落**

在「功能」增加：

- 汇总页可直接改「斤数」（自动记加减明细）
- 表格上方可搜菜名（过滤 + 上一条/下一条）
- 添加新图且无重复跳过时自动开始识别

在「使用步骤」改为：

1. 添加图片（无重复跳过时自动识别；有跳过则再点「开始识别」）
2. …
3. 在「汇总」页查看/直接改斤数；也可用「减斤」「加斤」；顶部搜索框快速找菜

- [ ] **Step 2: 对照设计文档清单勾选**

对照 `docs/superpowers/specs/2026-09-07-summary-edit-search-auto-ocr-design.md`：

- [ ] 汇总只改斤数 + 差额明细  
- [ ] 非法/负数恢复  
- [ ] 搜索过滤 + 上下条  
- [ ] 明细可按来源图匹配  
- [ ] 条件自动识别（C）  
- [ ] 「开始识别」仍可用  

- [ ] **Step 3: Commit**

```powershell
git add README.md
git commit -m "docs: document summary edit, search, and auto-recognize"
```

---

## Spec coverage (self-review)

| Spec 项 | Task |
|---------|------|
| 汇总改斤数 → adjust_jin 差额 | Task 1 + 2 |
| 不允许负/非法恢复；允许 0 | Task 1 + 2 |
| 搜索过滤 + 上下条 + 状态栏 | Task 3 |
| 明细来源图片匹配 | Task 3（`also_cols=[2]`） |
| 共用关键字、切 Tab 重过滤 | Task 3（`command` / `_on_search_changed`） |
| 无跳过才自动识别 | Task 4 |
| 有跳过提示手动识别 | Task 4 |
| README | Task 5 |

无 TBD/占位符；`parse_target_jin` / `should_auto_recognize` 命名在各 Task 一致。
