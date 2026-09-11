"""桌面入口：识别入库到真实 Excel，内置表格页编辑，按需导出。"""

from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk
from tksheet import Sheet

from app import APP_NAME, __version__
from app.aggregator import build_detail_rows
from app.ocr_engine import OcrEngine
from app.parser import (
    PENDING_NEW_VEG_REMARK,
    add_custom_vegetable,
    is_builtin_vegetable,
    list_builtin_vegetables,
    list_custom_vegetables,
    normalize_custom_vegetable_name,
    parse_boxes,
    remove_custom_vegetable,
)
from app.sheet_ops import (
    filter_row_indices,
    jin_delta,
    next_match_index,
    parse_target_jin,
    should_auto_recognize,
)
from app.storage import DETAIL_HEADERS, SUMMARY_HEADERS, Ledger, app_root
from app.updater import (
    ReleaseInfo,
    check_for_update,
    download_release_asset,
    extract_release_zip,
    fetch_latest_release,
    format_download_progress,
    install_root,
    is_newer,
    prepare_update_workdir,
    spawn_apply_and_exit,
)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

# 中文界面统一用雅黑，避免 CustomTkinter 默认英文字体导致中文发虚、错位
UI_FONT = "Microsoft YaHei UI"
ROW_H = 38


def ui_font(size: int = 13, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=UI_FONT, size=size, weight=weight)


def sheet_font(size: int = 14, weight: str = "normal") -> tuple[str, int, str]:
    return (UI_FONT, size, weight)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} · 图片转 Excel  v{__version__}")
        self.geometry("1180x760")
        self.minsize(900, 600)
        self._set_app_icon()

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("green")
        self._apply_system_fonts()

        self._images: list[Path] = []
        self._ocr = OcrEngine()
        self._ledger = Ledger()
        self._busy = False
        self._sheet_detail: Sheet | None = None
        self._sheet_summary: Sheet | None = None
        self._detail_full: list[list] = []
        self._summary_full: list[list] = []
        self._match_pos: int | None = None
        self._updating = False

        self._build_ui()
        self._reload_sheets()
        self.after(800, lambda: self._schedule_update_check(manual=False))

    def _resource_path(self, *parts: str) -> Path:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS).joinpath(*parts)
        return app_root().joinpath(*parts)

    def _set_app_icon(self) -> None:
        ico = self._resource_path("assets", "app.ico")
        png = self._resource_path("assets", "app.png")
        try:
            if ico.is_file():
                self.iconbitmap(default=str(ico))
        except Exception:  # noqa: BLE001
            pass
        try:
            src = png if png.is_file() else ico
            if src.is_file():
                img = Image.open(src).convert("RGBA")
                self._icon_photo = ImageTk.PhotoImage(img.resize((32, 32), Image.Resampling.LANCZOS))
                self.iconphoto(True, self._icon_photo)
        except Exception:  # noqa: BLE001
            pass

    def _apply_system_fonts(self) -> None:
        """系统弹窗 / 原生控件也走雅黑。"""
        for name in (
            "TkDefaultFont",
            "TkTextFont",
            "TkFixedFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
        ):
            try:
                f = tkfont.nametofont(name)
                size = int(f.cget("size"))
                f.configure(family=UI_FONT, size=max(size, 10))
            except Exception:  # noqa: BLE001
                pass

    def _build_ui(self) -> None:
        self.configure(fg_color="#f4f6f5")

        # 顶栏
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(14, 6))
        ctk.CTkLabel(
            top,
            text=APP_NAME,
            font=ui_font(22, "bold"),
            text_color="#1a3d2b",
        ).pack(side="left")
        self._status = ctk.CTkLabel(
            top, text="就绪", anchor="e", text_color="#5a6b60", font=ui_font(13)
        )
        self._status.pack(side="right")

        # 主区
        panes = ctk.CTkFrame(self, fg_color="transparent")
        panes.pack(fill="both", expand=True, padx=16, pady=4)

        # ----- 左侧 -----
        left = ctk.CTkFrame(panes, width=260, corner_radius=12, fg_color="#ffffff")
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)

        ctk.CTkLabel(
            left, text="已入库", font=ui_font(14, "bold"), text_color="#1a3d2b"
        ).pack(anchor="w", padx=14, pady=(14, 4))
        self._done_list = ctk.CTkTextbox(
            left, font=ui_font(13), height=200, fg_color="#f7faf8", corner_radius=8
        )
        self._done_list.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self._done_list.configure(state="disabled")

        ctk.CTkLabel(
            left, text="待识别", font=ui_font(14, "bold"), text_color="#1a3d2b"
        ).pack(anchor="w", padx=14, pady=(8, 4))
        self._img_list = ctk.CTkTextbox(
            left, font=ui_font(13), height=120, fg_color="#f7faf8", corner_radius=8
        )
        self._img_list.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._img_list.configure(state="disabled")

        self._img_label = ctk.CTkLabel(
            left, text="未选图片", text_color="#6b7c70", font=ui_font(12)
        )
        self._img_label.pack(anchor="w", padx=14, pady=(0, 6))

        ctk.CTkButton(
            left,
            text="添加图片",
            height=40,
            font=ui_font(14),
            fg_color="#2d6a4f",
            hover_color="#1b4332",
            command=self._add_images,
        ).pack(fill="x", padx=12, pady=(0, 8))

        self._recognize_btn = ctk.CTkButton(
            left,
            text="开始识别",
            height=52,
            font=ui_font(17, "bold"),
            fg_color="#e85d04",
            hover_color="#d00000",
            text_color="#ffffff",
            corner_radius=10,
            command=self._start_recognize,
        )
        self._recognize_btn.pack(fill="x", padx=12, pady=(0, 14))

        # ----- 右侧表格 -----
        right = ctk.CTkFrame(panes, corner_radius=12, fg_color="#ffffff")
        right.pack(side="left", fill="both", expand=True)

        tool = ctk.CTkFrame(right, fg_color="transparent")
        tool.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkButton(
            tool,
            text="减斤",
            width=76,
            height=36,
            font=ui_font(13),
            fg_color="#bc4749",
            hover_color="#a4161a",
            command=lambda: self._adjust_jin(sign=-1),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            tool,
            text="加斤",
            width=76,
            height=36,
            font=ui_font(13),
            fg_color="#2d6a4f",
            hover_color="#1b4332",
            command=lambda: self._adjust_jin(sign=1),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            tool,
            text="用 Excel 打开",
            width=118,
            height=36,
            font=ui_font(13),
            fg_color="#1d3557",
            hover_color="#0d1b2a",
            command=self._open_in_excel,
        ).pack(side="left", padx=(0, 6))

        self._export_btn = ctk.CTkButton(
            tool,
            text="导出",
            width=76,
            height=36,
            font=ui_font(13),
            fg_color="#457b9d",
            hover_color="#1d3557",
            command=self._export_ledger,
        )
        self._export_btn.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            tool,
            text="添加菜名至蔬菜库",
            width=148,
            height=36,
            font=ui_font(13),
            fg_color="#40916c",
            hover_color="#2d6a4f",
            command=self._manage_custom_vegetables,
        ).pack(side="left", padx=(0, 6))

        self._more_var = ctk.StringVar(value="更多…")
        more = ctk.CTkOptionMenu(
            tool,
            variable=self._more_var,
            values=[
                "更多…",
                "清空待识别",
                "移除已入库来源",
                "删除选中明细行",
                "保存表格修改",
                "刷新表格",
                "清洗菜名",
                "清空账本",
                "检查更新",
            ],
            width=138,
            height=36,
            font=ui_font(13),
            dropdown_font=ui_font(13),
            fg_color="#6c757d",
            button_color="#5a6268",
            command=self._on_more_action,
        )
        more.pack(side="right")

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
            search_bar,
            text="上一条",
            width=72,
            height=34,
            font=ui_font(13),
            command=lambda: self._goto_match(forward=False),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            search_bar,
            text="下一条",
            width=72,
            height=34,
            font=ui_font(13),
            command=lambda: self._goto_match(forward=True),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            search_bar,
            text="清空",
            width=64,
            height=34,
            font=ui_font(13),
            fg_color="#6c757d",
            hover_color="#5a6268",
            command=self._clear_search,
        ).pack(side="left")

        self._tabs = ctk.CTkTabview(
            right,
            fg_color="#ffffff",
            segmented_button_fg_color="#e9ecef",
            segmented_button_selected_color="#2d6a4f",
            segmented_button_selected_hover_color="#1b4332",
            segmented_button_unselected_color="#e9ecef",
            text_color="#1a3d2b",
        )
        self._tabs.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        tab_summary = self._tabs.add("汇总")
        tab_detail = self._tabs.add("明细")
        self._tabs.set("汇总")
        try:
            self._tabs._segmented_button.configure(font=ui_font(14, "bold"))
        except Exception:  # noqa: BLE001
            pass

        summary_host = ctk.CTkFrame(tab_summary, fg_color="#ffffff")
        summary_host.pack(fill="both", expand=True, padx=2, pady=2)
        self._sheet_summary = Sheet(
            summary_host,
            headers=SUMMARY_HEADERS,
            data=[],
            show_row_index=True,
            show_header=True,
            empty_horizontal=40,
            empty_vertical=80,
            font=sheet_font(15),
            header_font=sheet_font(14, "bold"),
            index_font=sheet_font(12),
        )
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
        self._sheet_summary.pack(fill="both", expand=True)

        detail_host = ctk.CTkFrame(tab_detail, fg_color="#ffffff")
        detail_host.pack(fill="both", expand=True, padx=2, pady=2)
        self._sheet_detail = Sheet(
            detail_host,
            headers=DETAIL_HEADERS,
            data=[],
            show_row_index=True,
            show_header=True,
            empty_horizontal=40,
            empty_vertical=80,
            font=sheet_font(14),
            header_font=sheet_font(13, "bold"),
            index_font=sheet_font(12),
        )
        self._style_sheet(self._sheet_detail, readonly=False)
        self._sheet_detail.enable_bindings(
            "single_select",
            "drag_select",
            "row_select",
            "column_width_resize",
            "arrowkeys",
            "copy",
            "cut",
            "paste",
            "delete",
            "undo",
            "edit_cell",
        )
        self._sheet_detail.pack(fill="both", expand=True)

        self._progress = ctk.CTkProgressBar(self, height=8, progress_color="#e85d04")
        self._progress.pack(fill="x", padx=16, pady=(0, 12))
        self._progress.set(0)

        self._refresh_img_list()
        self._refresh_done_list()
        try:
            self._tabs.configure(command=lambda _=None: self._on_search_changed())
        except Exception:  # noqa: BLE001
            pass

    def _style_sheet(self, sheet: Sheet, *, readonly: bool) -> None:
        """让内置表格更易读。"""
        try:
            sheet.change_theme("light green")
        except Exception:  # noqa: BLE001
            pass
        sheet.set_options(
            table_bg="#ffffff",
            table_fg="#1b1b1b",
            table_selected_cells_bg="#d8f3dc",
            table_selected_cells_fg="#1b1b1b",
            table_selected_rows_bg="#d8f3dc",
            header_bg="#2d6a4f",
            header_fg="#ffffff",
            header_selected_columns_bg="#1b4332",
            header_selected_columns_fg="#ffffff",
            index_bg="#f1f5f2",
            index_fg="#44554a",
            top_left_bg="#2d6a4f",
            top_left_fg="#ffffff",
            frame_bg="#ffffff",
            outline_thickness=0,
            show_horizontal_grid=True,
            show_vertical_grid=True,
            table_grid_fg="#dde5df",
            header_grid_fg="#2d6a4f",
            index_grid_fg="#dde5df",
        )
        try:
            sheet.default_row_height(ROW_H)
            sheet.set_all_row_heights(ROW_H)
        except Exception:  # noqa: BLE001
            pass

    def _on_more_action(self, choice: str) -> None:
        self._more_var.set("更多…")
        mapping = {
            "清空待识别": self._clear_images,
            "移除已入库来源": self._remove_done_source,
            "删除选中明细行": self._delete_selected_rows,
            "保存表格修改": self._save_sheet_to_ledger,
            "刷新表格": self._reload_sheets,
            "清洗菜名": self._cleanup_ledger,
            "清空账本": self._clear_ledger,
            "检查更新": lambda: self._schedule_update_check(manual=True),
        }
        fn = mapping.get(choice)
        if fn:
            fn()

    # ---------- Excel 表格 ----------
    def _reload_sheets(self) -> None:
        # 仅刷新汇总表，不做破坏性自动清洗（避免误删）
        try:
            self._ledger.refresh_summary_sheet()
        except Exception:  # noqa: BLE001
            traceback.print_exc()

        h1, d1 = self._ledger.sheet_matrix("明细")
        h2, d2 = self._ledger.sheet_matrix("汇总")
        assert self._sheet_detail is not None and self._sheet_summary is not None
        self._detail_full = [list(r) for r in (d1 or [])]
        self._summary_full = [list(r) for r in (d2 or [])]
        self._sheet_detail.headers(h1 or DETAIL_HEADERS)
        self._sheet_detail.set_sheet_data(
            d1 or [], reset_col_positions=True, reset_row_positions=True
        )
        self._fit_columns(self._sheet_detail, [70, 150, 160, 110, 80, 80, 90, 140])
        self._style_sheet(self._sheet_detail, readonly=False)

        self._sheet_summary.headers(h2 or SUMMARY_HEADERS)
        self._sheet_summary.set_sheet_data(
            d2 or [], reset_col_positions=True, reset_row_positions=True
        )
        self._fit_columns(self._sheet_summary, [220, 80, 120])
        self._style_sheet(self._sheet_summary, readonly=False)
        try:
            nrows = len(d2 or [])
            self._sheet_summary.readonly_columns(columns=[0, 1], readonly=True)
            if nrows:
                # 斤数列保持可编辑（列索引 2）
                self._sheet_summary.readonly_columns(columns=[2], readonly=False)
        except Exception:
            pass

        self._status.configure(
            text=f"明细 {len(d1)} 行 · 汇总 {len(d2)} 种"
        )
        self._refresh_done_list()
        self._reapply_search_filter()

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
            self._show_ledger_write_error("调整失败", exc)
            self._reload_sheets()
            self._reapply_search_filter()

    def _reapply_search_filter(self) -> None:
        if self._sheet_detail is None or self._sheet_summary is None:
            return
        if not hasattr(self, "_search_var"):
            return
        keyword = self._search_var.get()
        sheet, full, name_col, also = self._current_sheet_ctx()
        idxs = filter_row_indices(full, keyword, name_col=name_col, also_cols=also)
        view = [full[i] for i in idxs]
        sheet.set_sheet_data(view, reset_col_positions=False, reset_row_positions=True)
        try:
            sheet.set_all_row_heights(ROW_H)
        except Exception:  # noqa: BLE001
            pass
        if self._tabs.get() == "汇总":
            try:
                self._sheet_summary.readonly_columns(columns=[0, 1], readonly=True)
                if view:
                    self._sheet_summary.readonly_columns(columns=[2], readonly=False)
            except Exception:  # noqa: BLE001
                pass
        if (keyword or "").strip() == "":
            return
        if not idxs:
            self._status.configure(text="未找到")
        else:
            self._status.configure(text=f"第 1/{len(idxs)} 条候选 · 点下一条定位")

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
        keyword = self._search_var.get() if hasattr(self, "_search_var") else ""
        if (keyword or "").strip() == "":
            self._status.configure(
                text=(
                    f"明细 {len(self._detail_full)} 行 · "
                    f"汇总 {len(self._summary_full)} 种"
                )
            )

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
        r = self._match_pos
        try:
            sheet.deselect("all")
            sheet.select_row(r)
            sheet.see(row=r, keep_yscroll=False)
        except Exception:  # noqa: BLE001
            try:
                sheet.set_currently_selected(r, 0)
            except Exception:  # noqa: BLE001
                pass
        self._status.configure(text=f"第 {self._match_pos + 1}/{n} 条")

    def _fit_columns(self, sheet: Sheet, widths: list[int]) -> None:
        try:
            # 列数多于给定宽度时，用最后一档补齐，避免末列被压成 0
            try:
                ncols = len(sheet.headers()) if sheet.headers() else len(widths)
            except Exception:  # noqa: BLE001
                ncols = len(widths)
            if ncols > len(widths):
                pad = widths[-1] if widths else 100
                widths = list(widths) + [pad] * (ncols - len(widths))
            sheet.set_column_widths(widths[:ncols] if ncols else widths)
        except Exception:  # noqa: BLE001
            try:
                sheet.set_all_column_widths()
            except Exception:  # noqa: BLE001
                pass
        try:
            sheet.set_all_row_heights(ROW_H)
        except Exception:  # noqa: BLE001
            pass

    def _show_ledger_write_error(self, title: str, exc: BaseException) -> None:
        """账本写入失败提示；文件被 WPS/Excel 占用时给出可操作说明。"""
        traceback.print_exc()
        err_s = str(exc)
        locked = (
            isinstance(exc, PermissionError)
            or (
                isinstance(exc, OSError)
                and (
                    getattr(exc, "winerror", None) in (32, 5)
                    or getattr(exc, "errno", None) == 13
                )
            )
            or "Permission denied" in err_s
            or "Errno 13" in err_s
        )
        if locked:
            messagebox.showerror(
                title,
                "账本文件正被其他程序占用（常见：WPS、Excel 已打开该表）。\n"
                "请先关闭 WPS/Excel 后再试。\n\n"
                f"{self._ledger.path}",
                parent=self,
            )
            return
        messagebox.showerror(title, f"{exc}", parent=self)

    def _cleanup_ledger(self) -> None:
        """手动清洗：去硬菜前缀、拆粘连、剔非菜名、标异常斤数。"""
        if self._busy:
            return
        if not messagebox.askyesno(
            "清洗账本",
            "将清洗菜名前缀/粘连名，并剔除「客服、分拣单」等非菜名。\n继续？",
            parent=self,
        ):
            return
        try:
            n = self._ledger.cleanup_names()
            self._reload_sheets()
            messagebox.showinfo("完成", f"清洗完成，改动 {n} 处", parent=self)
        except Exception as exc:  # noqa: BLE001
            self._show_ledger_write_error("清洗失败", exc)

    def _save_sheet_to_ledger(self) -> None:
        if self._busy or self._sheet_detail is None:
            return
        try:
            data = self._sheet_detail.get_sheet_data()
            non_empty = [
                r
                for r in data
                if any(c is not None and str(c).strip() != "" for c in r)
            ]
            existing = self._ledger.load_records()
            if not non_empty and existing:
                if not messagebox.askyesno(
                    "警告",
                    "当前表格是空的，但账本里还有数据。\n继续保存会清空账本！是否仍要保存？",
                    parent=self,
                ):
                    return
            headers = list(self._sheet_detail.headers()) or DETAIL_HEADERS
            if headers and not isinstance(headers[0], str):
                headers = [str(h) for h in headers]
            self._ledger.save_detail_matrix([str(h) for h in headers], data)
            self._reload_sheets()
            messagebox.showinfo(
                "已保存", f"表格已写入真实 Excel：\n{self._ledger.path}", parent=self
            )
        except Exception as exc:  # noqa: BLE001
            self._show_ledger_write_error("保存失败", exc)

    def _delete_selected_rows(self) -> None:
        if self._busy or self._sheet_detail is None:
            return
        selected = self._sheet_detail.get_selected_rows()
        if not selected:
            cells = self._sheet_detail.get_selected_cells(get_rows=True)
            selected = {c[0] for c in cells} if cells else set()
        if not selected:
            messagebox.showinfo("提示", "请先在「明细」表中选中要删除的行")
            return
        rows = sorted(int(r) for r in selected)
        if not messagebox.askyesno(
            "确认", f"删除明细表中选中的 {len(rows)} 行？", parent=self
        ):
            return
        # 先保存当前编辑，再按行删
        try:
            data = self._sheet_detail.get_sheet_data()
            headers = [str(h) for h in (self._sheet_detail.headers() or DETAIL_HEADERS)]
            self._ledger.save_detail_matrix(headers, data)
            n = self._ledger.delete_selected_detail_rows(rows)
            self._reload_sheets()
            self._status.configure(text=f"已删除 {n} 行")
        except Exception as exc:  # noqa: BLE001
            self._show_ledger_write_error("删除失败", exc)

    def _open_in_excel(self) -> None:
        """用系统默认程序（Excel / WPS）打开真实账本文件。"""
        path = self._ledger.path
        if not path.exists():
            messagebox.showwarning("提示", "账本文件不存在")
            return
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            self._status.configure(text=f"已用系统 Excel 打开：{path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("错误", f"无法打开：{exc}")

    def _clear_ledger(self) -> None:
        if self._busy:
            return
        if not messagebox.askyesno(
            "确认清空",
            "清空内置 Excel 全部数据，且不可恢复？",
            parent=self,
        ):
            return
        try:
            self._ledger.clear_all()
            self._reload_sheets()
            self._status.configure(text="账本已清空")
            messagebox.showinfo("完成", "账本已清空。", parent=self)
        except Exception as exc:  # noqa: BLE001
            self._show_ledger_write_error("清空失败", exc)

    def _export_ledger(self) -> None:
        if self._busy:
            return
        records = self._ledger.load_records()
        if not records:
            messagebox.showinfo("提示", "账本为空")
            return
        save_path = filedialog.asksaveasfilename(
            title="导出 Excel 副本",
            defaultextension=".xlsx",
            filetypes=[("Excel 工作簿", "*.xlsx")],
            initialfile="蔬菜汇总导出.xlsx",
        )
        if not save_path:
            return
        try:
            # 先把界面编辑落盘
            if self._sheet_detail is not None:
                data = self._sheet_detail.get_sheet_data()
                headers = [str(h) for h in (self._sheet_detail.headers() or DETAIL_HEADERS)]
                self._ledger.save_detail_matrix(headers, data)
            out = self._ledger.export_to(save_path)
            messagebox.showinfo(
                "导出完成",
                f"已导出副本：\n{out}\n\n内置账本仍保留在：\n{self._ledger.path}",
                parent=self,
            )
        except Exception as exc:  # noqa: BLE001
            self._show_ledger_write_error("导出失败", exc)

    # ---------- 图片 ----------
    def _refresh_done_list(self) -> None:
        stats = self._ledger.list_source_image_stats()
        self._done_list.configure(state="normal")
        self._done_list.delete("1.0", "end")
        if not stats:
            self._done_list.insert("end", "（还没有入库过的图片）\n")
        else:
            self._done_list.insert("end", f"共 {len(stats)} 张已入库\n{'-' * 28}\n")
            for i, (name, time_str, count) in enumerate(stats, start=1):
                short_time = time_str[5:16] if len(time_str) >= 16 else time_str
                self._done_list.insert(
                    "end", f"{i}. {name}\n   {short_time} · {count}条\n"
                )
        self._done_list.configure(state="disabled")

    def _remove_done_source(self) -> None:
        """按序号删除某张已入库图片的全部明细。"""
        if self._busy:
            return
        stats = self._ledger.list_source_image_stats()
        if not stats:
            messagebox.showinfo("提示", "没有已入库图片")
            return
        dialog = ctk.CTkInputDialog(
            text=f"输入要移除的已入库序号 (1-{len(stats)})：\n将删除该图全部明细",
            title="移除已入库来源",
        )
        value = dialog.get_input()
        if not value:
            return
        try:
            idx = int(value.strip()) - 1
        except ValueError:
            messagebox.showwarning("提示", "请输入数字序号")
            return
        if not (0 <= idx < len(stats)):
            messagebox.showwarning("提示", "序号超出范围")
            return
        name, _, count = stats[idx]
        if not messagebox.askyesno(
            "确认",
            f"删除「{name}」的全部 {count} 条明细？\n汇总会相应减少。",
            parent=self,
        ):
            return
        try:
            n = self._ledger.delete_by_source(name)
            self._reload_sheets()
            messagebox.showinfo("完成", f"已移除 {n} 条（来源：{name}）", parent=self)
        except Exception as exc:  # noqa: BLE001
            self._show_ledger_write_error("移除失败", exc)

    def _refresh_img_list(self) -> None:
        self._img_list.configure(state="normal")
        self._img_list.delete("1.0", "end")
        if not self._images:
            self._img_list.insert("end", "（尚未添加）\n")
            self._img_label.configure(text="未选待识别图片")
        else:
            for i, p in enumerate(self._images, start=1):
                self._img_list.insert("end", f"{i}. {p.name}\n")
            self._img_label.configure(text=f"待识别 {len(self._images)} 张")
        self._img_list.configure(state="disabled")

    def _add_images(self) -> None:
        if self._busy:
            return
        paths = filedialog.askopenfilenames(
            title="选择蔬菜清单图片",
            filetypes=[
                ("图片", "*.jpg;*.jpeg;*.png;*.bmp;*.webp;*.tif;*.tiff"),
                ("所有文件", "*.*"),
            ],
        )
        imported = self._ledger.list_source_images()
        added = 0
        skipped: list[str] = []
        for p in paths:
            path = Path(p)
            if path.suffix.lower() not in IMAGE_EXTS:
                continue
            if path.name in imported:
                skipped.append(path.name)
                continue
            if path not in self._images and path.name not in {
                x.name for x in self._images
            }:
                self._images.append(path)
                added += 1
        self._refresh_img_list()
        self._refresh_done_list()
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

    def _clear_images(self) -> None:
        if self._busy:
            return
        self._images.clear()
        self._refresh_img_list()
        self._progress.set(0)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._recognize_btn.configure(state=state)
        self._export_btn.configure(state=state)

    def _manage_custom_vegetables(self) -> None:
        """添加菜名至蔬菜库；可查看/搜索内置词库（只读）。"""
        if self._busy:
            return
        import tkinter as tk

        win = ctk.CTkToplevel(self)
        win.title("添加菜名至蔬菜库")
        win.geometry("460x560")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text="把蔬菜库里没有的菜名加进来；下次识别就会认。内置词库可在下方查看。",
            font=ui_font(13),
            text_color="#4a5c52",
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(14, 6))

        tip = ctk.CTkLabel(win, text="", font=ui_font(12), text_color="#2d6a4f")
        tip.pack(anchor="w", padx=16, pady=(0, 4))

        tabs = ctk.CTkTabview(win, fg_color="#f7faf8")
        tabs.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        tab_custom = tabs.add("我添加的")
        tab_builtin = tabs.add("内置词库")

        def _make_listbox(parent: ctk.CTkFrame, *, multi: bool) -> tk.Listbox:
            lb_wrap = tk.Frame(parent, bg="#f7faf8")
            lb_wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))
            scrollbar = tk.Scrollbar(lb_wrap)
            scrollbar.pack(side="right", fill="y")
            lb = tk.Listbox(
                lb_wrap,
                font=(UI_FONT, 13),
                height=12,
                activestyle="dotbox",
                selectmode=tk.EXTENDED if multi else tk.BROWSE,
                yscrollcommand=scrollbar.set,
                bg="#ffffff",
                relief="flat",
                highlightthickness=1,
                highlightbackground="#dde5df",
            )
            lb.pack(side="left", fill="both", expand=True)
            scrollbar.config(command=lb.yview)
            return lb

        # —— 我添加的 ——
        entry_row = ctk.CTkFrame(tab_custom, fg_color="transparent")
        entry_row.pack(fill="x", padx=8, pady=(8, 6))
        name_entry = ctk.CTkEntry(
            entry_row, width=220, height=36, font=ui_font(14), placeholder_text="输入菜名…"
        )
        name_entry.pack(side="left", padx=(0, 8))
        custom_count = ctk.CTkLabel(
            tab_custom, text="", font=ui_font(12), text_color="#5a6b60", anchor="w"
        )
        custom_count.pack(fill="x", padx=10, pady=(0, 4))
        name_lb = _make_listbox(tab_custom, multi=True)

        def refresh_custom() -> None:
            names = list_custom_vegetables()
            name_lb.delete(0, tk.END)
            for n in names:
                name_lb.insert(tk.END, n)
            custom_count.configure(
                text=f"共 {len(names)} 个（可删除）；内置菜名不会出现在此列表"
            )

        def do_add() -> None:
            raw = name_entry.get().strip()
            try:
                cleaned = normalize_custom_vegetable_name(raw)
            except ValueError as exc:
                messagebox.showwarning("提示", str(exc), parent=win)
                return
            if is_builtin_vegetable(cleaned):
                tip.configure(text=f"「{cleaned}」已在内置词库中，无需添加")
                name_entry.delete(0, "end")
                tabs.set("内置词库")
                search_entry.delete(0, "end")
                search_entry.insert(0, cleaned)
                refresh_builtin()
                return
            if cleaned in list_custom_vegetables():
                tip.configure(text=f"「{cleaned}」已在「我添加的」列表中")
                name_entry.delete(0, "end")
                return
            add_custom_vegetable(cleaned)
            name_entry.delete(0, "end")
            refresh_custom()
            tip.configure(text=f"已加入「{cleaned}」，识别立即生效")
            self._status.configure(text=f"已添加菜名至蔬菜库：{cleaned}")

        def do_remove() -> None:
            sel = name_lb.curselection()
            if not sel:
                messagebox.showinfo("提示", "请先选中要删除的菜名", parent=win)
                return
            removed: list[str] = []
            for idx in reversed(sel):
                target = name_lb.get(idx)
                if remove_custom_vegetable(target):
                    removed.append(target)
            refresh_custom()
            if removed:
                tip.configure(
                    text=f"已删除 {len(removed)} 个：{'、'.join(removed[:5])}"
                )
                self._status.configure(text=f"已从蔬菜库删除 {len(removed)} 个菜名")

        ctk.CTkButton(
            entry_row,
            text="加入蔬菜库",
            width=100,
            height=36,
            font=ui_font(14),
            fg_color="#2d6a4f",
            hover_color="#1b4332",
            command=do_add,
        ).pack(side="left")

        # —— 内置词库 ——
        search_row = ctk.CTkFrame(tab_builtin, fg_color="transparent")
        search_row.pack(fill="x", padx=8, pady=(8, 6))
        search_entry = ctk.CTkEntry(
            search_row,
            width=220,
            height=36,
            font=ui_font(14),
            placeholder_text="搜索内置菜名…",
        )
        search_entry.pack(side="left", padx=(0, 8))
        builtin_count = ctk.CTkLabel(
            tab_builtin, text="", font=ui_font(12), text_color="#5a6b60", anchor="w"
        )
        builtin_count.pack(fill="x", padx=10, pady=(0, 4))
        builtin_lb = _make_listbox(tab_builtin, multi=False)
        all_builtin = list_builtin_vegetables()

        def refresh_builtin(_event: object | None = None) -> None:
            q = search_entry.get().strip()
            shown = [n for n in all_builtin if q in n] if q else all_builtin
            builtin_lb.delete(0, tk.END)
            for n in shown:
                builtin_lb.insert(tk.END, n)
            if q:
                builtin_count.configure(
                    text=f"匹配 {len(shown)} / 共 {len(all_builtin)} 个（只读，不可删除）"
                )
            else:
                builtin_count.configure(
                    text=f"共 {len(all_builtin)} 个（只读，不可删除）"
                )

        search_entry.bind("<KeyRelease>", refresh_builtin)

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(
            btn_row,
            text="删除选中",
            width=100,
            height=36,
            font=ui_font(13),
            fg_color="#bc4749",
            hover_color="#a4161a",
            command=do_remove,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row,
            text="关闭",
            width=80,
            height=36,
            font=ui_font(13),
            fg_color="#6c757d",
            hover_color="#5a6268",
            command=win.destroy,
        ).pack(side="right")

        name_entry.bind("<Return>", lambda _e: do_add())
        refresh_custom()
        refresh_builtin()
        name_entry.focus_set()

    def _adjust_jin(self, sign: int = -1) -> None:
        """手工加斤/减斤，写入一条明细（减斤为负数），汇总自动相加减。"""
        if self._busy:
            return
        title = "减斤" if sign < 0 else "加斤"
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("380x220")
        win.transient(self)
        win.grab_set()
        ctk.CTkLabel(win, text="蔬菜名称", font=ui_font(13, "bold")).pack(
            anchor="w", padx=16, pady=(16, 4)
        )
        name_entry = ctk.CTkEntry(win, width=320, height=36, font=ui_font(14))
        name_entry.pack(padx=16)
        ctk.CTkLabel(win, text="斤数（正数）", font=ui_font(13, "bold")).pack(
            anchor="w", padx=16, pady=(12, 4)
        )
        qty_entry = ctk.CTkEntry(win, width=320, height=36, font=ui_font(14))
        qty_entry.pack(padx=16)

        def ok() -> None:
            name = name_entry.get().strip()
            raw = qty_entry.get().strip()
            if not name:
                messagebox.showwarning("提示", "请填写蔬菜名称", parent=win)
                return
            try:
                qty = float(raw)
            except ValueError:
                messagebox.showwarning("提示", "请输入有效数字", parent=win)
                return
            if qty <= 0:
                messagebox.showwarning("提示", "请输入大于 0 的斤数", parent=win)
                return
            delta = -qty if sign < 0 else qty
            try:
                self._ledger.adjust_jin(name, delta)
            except Exception as exc:  # noqa: BLE001
                self._show_ledger_write_error(f"{title}失败", exc)
                return
            win.destroy()
            self._reload_sheets()
            self._tabs.set("汇总")
            self._status.configure(
                text=f"已{title}：{name} {delta:+g} 斤"
            )

        ctk.CTkButton(win, text="确定", width=120, height=36, font=ui_font(14), command=ok).pack(
            pady=16
        )

    def _start_recognize(self) -> None:
        if self._busy:
            return
        if not self._images:
            messagebox.showinfo("提示", "请先添加图片")
            return

        existing = self._ledger.list_source_images()
        dupes = [p.name for p in self._images if p.name in existing]
        replace_sources: set[str] = set()
        skip_sources: set[str] = set()
        if dupes:
            ans = messagebox.askyesnocancel(
                "发现重复图片",
                "以下图片已在账本中，再次导入会把斤数重复累加：\n\n"
                + "\n".join(dupes[:12])
                + ("\n…" if len(dupes) > 12 else "")
                + "\n\n【是】覆盖重导（删掉该图旧数据再写入）"
                + "\n【否】跳过这些已导入的图"
                + "\n【取消】不识别",
            )
            if ans is None:
                return
            if ans:
                replace_sources = set(dupes)
            else:
                skip_sources = set(dupes)

        images = [p for p in self._images if p.name not in skip_sources]
        if not images:
            messagebox.showinfo("提示", "没有需要识别的新图片")
            return

        self._set_busy(True)
        self._progress.set(0)
        self._status.configure(text="正在识别…")
        threading.Thread(
            target=self._recognize_worker,
            args=(images, replace_sources),
            daemon=True,
        ).start()

    def _recognize_worker(
        self, images: list[Path], replace_sources: set[str] | None = None
    ) -> None:
        errors: list[str] = []
        all_details = []
        total = len(images)
        try:
            dbg = self._ledger.path.parent / "last_ocr_debug.txt"
            dbg.write_text("", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        try:
            for i, img in enumerate(images):
                self._ui(
                    lambda i=i, img=img: (
                        self._progress.set(i / total),
                        self._status.configure(
                            text=f"识别中 ({i + 1}/{total})：{img.name}"
                        ),
                    )
                )
                try:
                    boxes = self._ocr.recognize(img)
                    try:
                        dbg = self._ledger.path.parent / "last_ocr_debug.txt"
                        with open(dbg, "a", encoding="utf-8") as f:
                            f.write(f"\n===== {img.name} =====\n")
                            for b in boxes:
                                f.write(f"{b.text}\t({b.cx:.0f},{b.cy:.0f})\n")
                    except Exception:  # noqa: BLE001
                        pass
                    items = parse_boxes(boxes)
                    all_details.extend(build_detail_rows(img.name, items))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{img.name}: {exc}")
                    traceback.print_exc()

            cancel_pending = [
                d
                for d in all_details
                if getattr(d, "is_subtract", False)
                and str(getattr(d, "remark", "") or "").startswith("待填斤数-档口取消")
            ]
            new_veg_pending = [
                d
                for d in all_details
                if str(getattr(d, "remark", "") or "") == PENDING_NEW_VEG_REMARK
            ]
            adds = [
                d
                for d in all_details
                if not getattr(d, "is_subtract", False)
                and not str(getattr(d, "remark", "") or "").startswith("改单加项")
                and str(getattr(d, "remark", "") or "") != PENDING_NEW_VEG_REMARK
            ]
            replace_adds = {
                str(getattr(d, "remark", "") or "").split("|", 1)[-1]: d
                for d in all_details
                if str(getattr(d, "remark", "") or "").startswith("改单加项|")
            }
            subs = [
                d
                for d in all_details
                if getattr(d, "is_subtract", False)
                and d.jin is not None
                and float(d.jin) > 0
                and not str(getattr(d, "remark", "") or "").startswith("待填斤数-档口取消")
            ]

            def done() -> None:
                added = 0
                confirmed_n = 0
                replace_n = 0
                cancel_n = 0
                new_veg_n = 0
                new_veg_lib_n = 0
                try:
                    if replace_sources:
                        for src in replace_sources:
                            self._ledger.delete_by_source(src)
                    if adds:
                        added += self._ledger.append_details(adds)
                    # 未收录新菜：询问是否真实蔬菜、是否写入蔬菜库
                    if new_veg_pending:
                        accepted, lib_added = self._confirm_new_vegetables(
                            new_veg_pending
                        )
                        new_veg_lib_n = lib_added
                        if accepted:
                            for row in accepted:
                                row.remark = "新菜(已确认)"
                                if row.jin is not None:
                                    row.include_in_summary = True
                            new_veg_n = self._ledger.append_details(accepted)
                            added += new_veg_n
                    # 档口取消：先填斤数，再作为减项写入
                    if cancel_pending:
                        filled = self._ask_cancel_quantities(cancel_pending)
                        if filled:
                            for row in filled:
                                row.jin = -abs(float(row.jin or 0))
                                row.quantity = row.jin
                                row.unit_raw = row.unit_raw or "斤"
                                row.remark = "档口取消(已确认)"
                                row.include_in_summary = True
                            cancel_n = self._ledger.append_details(filled)
                            added += cancel_n
                    if subs:
                        confirmed = self._confirm_subtract_rows(subs)
                        if confirmed:
                            to_write = []
                            for row in confirmed:
                                pair = ""
                                rem = str(getattr(row, "remark", "") or "")
                                if rem.startswith("待确认改单|"):
                                    pair = rem.split("|", 1)[-1]
                                row.jin = -abs(float(row.jin or 0))
                                row.quantity = row.jin
                                if pair and pair in replace_adds:
                                    row.remark = "改单-减(已确认)"
                                    add_row = replace_adds[pair]
                                    add_row.include_in_summary = True
                                    add_row.remark = "改单-加(已确认)"
                                    to_write.append(row)
                                    to_write.append(add_row)
                                    replace_n += 1
                                else:
                                    row.remark = "减斤(已确认)"
                                    to_write.append(row)
                                row.include_in_summary = True
                            confirmed_n = self._ledger.append_details(to_write)
                            added += confirmed_n
                    try:
                        self._ledger.cleanup_names()
                    except Exception:  # noqa: BLE001
                        traceback.print_exc()

                    self._progress.set(1)
                    self._images.clear()
                    self._refresh_img_list()
                    self._reload_sheets()
                    self._tabs.set("汇总")
                    self._set_busy(False)
                    msg = f"已写入明细 {added} 行。\n文件：{self._ledger.path}"
                    if new_veg_pending:
                        msg += (
                            f"\n新菜确认：入库 {new_veg_n} 条，"
                            f"写入蔬菜库 {new_veg_lib_n} 个，"
                            f"跳过 {len(new_veg_pending) - new_veg_n} 条。"
                        )
                    if cancel_pending:
                        msg += f"\n档口取消：确认减斤 {cancel_n} 条。"
                    if subs:
                        msg += (
                            f"\n减斤/改单：确认 {confirmed_n} 条写入"
                            f"（含改单 {replace_n} 组），"
                            f"跳过 {len(subs) - (confirmed_n - replace_n) if confirmed_n else len(subs)} 条减项。"
                        )
                    if replace_sources:
                        msg += f"\n已覆盖重导 {len(replace_sources)} 张图。"
                    if errors:
                        msg += "\n\n部分失败：\n" + "\n".join(errors[:8])
                    messagebox.showinfo("入库完成", msg)
                except Exception as exc:  # noqa: BLE001
                    traceback.print_exc()
                    self._set_busy(False)
                    self._show_ledger_write_error("入库失败", exc)

            self._ui(done)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()

            def fail() -> None:
                self._set_busy(False)
                self._status.configure(text="识别失败")
                self._show_ledger_write_error("处理失败", exc)

            self._ui(fail)

    def _ask_cancel_quantities(self, rows: list) -> list:
        """档口取消：弹窗填写要减的斤数；返回填了有效斤数的行。"""
        win = ctk.CTkToplevel(self)
        win.title("档口取消 · 填写减斤")
        win.geometry("520x420")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text="识别到「档口取消」菜名（不处理档口）。请填写要减去的斤数，留空则跳过：",
            wraplength=480,
            justify="left",
            font=ui_font(13),
        ).pack(anchor="w", padx=16, pady=(16, 8))

        frame = ctk.CTkScrollableFrame(win, width=480, height=260)
        frame.pack(fill="both", expand=True, padx=16, pady=4)

        entries: list[tuple] = []
        for row in rows:
            line = ctk.CTkFrame(frame, fg_color="transparent")
            line.pack(fill="x", pady=6)
            ctk.CTkLabel(
                line,
                text=f"【{row.source_image}】 {row.name}",
                font=ui_font(13),
                width=280,
                anchor="w",
            ).pack(side="left")
            ent = ctk.CTkEntry(line, width=100, height=34, font=ui_font(14), placeholder_text="斤数")
            ent.pack(side="right", padx=(8, 0))
            ctk.CTkLabel(line, text="斤", font=ui_font(13)).pack(side="right")
            entries.append((row, ent))

        result: list = []

        def on_ok() -> None:
            result.clear()
            for row, ent in entries:
                raw = ent.get().strip()
                if not raw:
                    continue
                try:
                    qty = float(raw)
                except ValueError:
                    messagebox.showwarning(
                        "提示", f"「{row.name}」斤数无效，请输入数字", parent=win
                    )
                    return
                if qty <= 0:
                    messagebox.showwarning(
                        "提示", f"「{row.name}」请输入大于 0 的斤数", parent=win
                    )
                    return
                row.jin = qty
                row.quantity = qty
                row.unit_raw = "斤"
                result.append(row)
            win.destroy()

        def on_skip() -> None:
            result.clear()
            win.destroy()

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(
            btns,
            text="跳过全部",
            width=100,
            height=34,
            font=ui_font(13),
            fg_color="gray50",
            command=on_skip,
        ).pack(side="left")
        ctk.CTkButton(
            btns,
            text="确认减斤",
            width=120,
            height=34,
            font=ui_font(13),
            command=on_ok,
        ).pack(side="right")

        win.wait_window()
        return result

    def _confirm_new_vegetables(self, rows: list) -> tuple[list, int]:
        """询问未收录菜名是否真实蔬菜并写入蔬菜库。

        返回 (确认入库的行, 新写入蔬菜库的菜名个数)。
        """
        by_name: dict[str, list] = {}
        for row in rows:
            key = str(getattr(row, "name", "") or "").strip()
            if not key:
                continue
            by_name.setdefault(key, []).append(row)
        if not by_name:
            return [], 0

        win = ctk.CTkToplevel(self)
        win.title("确认新菜名")
        win.geometry("620x460")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text=(
                "识别到以下名称不在蔬菜库中（已过滤明显脏词）。\n"
                "请确认是否为真实蔬菜：勾选后将写入蔬菜库，并完成本次入库；\n"
                "不勾选则视为脏数据，跳过不入库。"
            ),
            wraplength=580,
            justify="left",
            font=ui_font(13),
        ).pack(anchor="w", padx=16, pady=(16, 8))

        frame = ctk.CTkScrollableFrame(win, width=580, height=300)
        frame.pack(fill="both", expand=True, padx=16, pady=4)

        vars_rows: list[tuple] = []
        for name, group in sorted(by_name.items(), key=lambda x: x[0]):
            jin_sum = 0.0
            has_jin = False
            for r in group:
                if r.jin is not None:
                    jin_sum += float(r.jin)
                    has_jin = True
            srcs = sorted({str(getattr(r, "source_image", "") or "") for r in group})
            src_txt = "、".join(s for s in srcs if s)[:40]
            qty_txt = f"{jin_sum:g} 斤" if has_jin else f"{len(group)} 条"
            label = f"是真实蔬菜，写入蔬菜库：{name}　（{qty_txt}）"
            if src_txt:
                label += f"　· {src_txt}"

            var = ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(frame, text=label, variable=var, font=ui_font(13)).pack(
                anchor="w", pady=4
            )
            vars_rows.append((var, name, group))

        accepted: list = []
        lib_added = 0

        def select_all(flag: bool) -> None:
            for var, _, _ in vars_rows:
                var.set(flag)

        def on_ok() -> None:
            nonlocal lib_added
            for var, name, group in vars_rows:
                if not var.get():
                    continue
                try:
                    add_custom_vegetable(name)
                    lib_added += 1
                except ValueError as exc:
                    messagebox.showwarning(
                        "无法写入蔬菜库",
                        f"「{name}」：{exc}\n已跳过该项。",
                        parent=win,
                    )
                    continue
                accepted.extend(group)
            win.destroy()

        def on_skip() -> None:
            accepted.clear()
            win.destroy()

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(
            btns,
            text="全选",
            width=80,
            height=34,
            font=ui_font(13),
            fg_color="gray50",
            command=lambda: select_all(True),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns,
            text="全不选",
            width=80,
            height=34,
            font=ui_font(13),
            fg_color="gray50",
            command=lambda: select_all(False),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns,
            text="全部跳过",
            width=100,
            height=34,
            font=ui_font(13),
            fg_color="gray50",
            command=on_skip,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            btns,
            text="确认勾选项",
            width=120,
            height=34,
            font=ui_font(13),
            command=on_ok,
        ).pack(side="right")

        win.wait_window()
        return accepted, lib_added

    def _confirm_subtract_rows(self, rows: list) -> list:
        """弹窗确认图片中识别到的减斤项；返回用户勾选确认的行。"""
        win = ctk.CTkToplevel(self)
        win.title("确认减斤")
        win.geometry("560x440")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(
            win,
            text="图片中识别到以下「减斤 / 改单」记录，请勾选需要确认的项：",
            wraplength=520,
            justify="left",
            font=ui_font(13),
        ).pack(anchor="w", padx=16, pady=(16, 8))

        frame = ctk.CTkScrollableFrame(win, width=520, height=280)
        frame.pack(fill="both", expand=True, padx=16, pady=4)

        vars_rows: list[tuple] = []
        for row in rows:
            var = ctk.BooleanVar(value=True)
            rem = str(getattr(row, "remark", "") or "")
            if rem.startswith("待确认改单|") and "|" in rem:
                pair = rem.split("|", 1)[1]
                parts = pair.split(":")
                if len(parts) >= 4:
                    label = (
                        f"【{row.source_image}】改单：{parts[0]} -{parts[1]}斤"
                        f" → {parts[2]} +{parts[3]}斤"
                    )
                else:
                    label = f"【{row.source_image}】改单减 {row.name} {float(row.jin):g} 斤"
            else:
                label = f"【{row.source_image}】 {row.name}　减 {float(row.jin):g} 斤"
            ctk.CTkCheckBox(frame, text=label, variable=var, font=ui_font(13)).pack(
                anchor="w", pady=4
            )
            vars_rows.append((var, row))

        result: list = []

        def select_all(flag: bool) -> None:
            for var, _ in vars_rows:
                var.set(flag)

        def on_ok() -> None:
            for var, row in vars_rows:
                if var.get():
                    result.append(row)
            win.destroy()

        def on_cancel() -> None:
            result.clear()
            win.destroy()

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(
            btns,
            text="全选",
            width=80,
            height=34,
            font=ui_font(13),
            fg_color="gray50",
            command=lambda: select_all(True),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns,
            text="全不选",
            width=80,
            height=34,
            font=ui_font(13),
            fg_color="gray50",
            command=lambda: select_all(False),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns,
            text="取消减斤",
            width=100,
            height=34,
            font=ui_font(13),
            fg_color="gray50",
            command=on_cancel,
        ).pack(side="right", padx=(6, 0))
        ctk.CTkButton(
            btns,
            text="确认扣减勾选项",
            width=150,
            height=34,
            font=ui_font(13),
            command=on_ok,
        ).pack(side="right")

        win.wait_window()
        return result

    def _ui(self, fn) -> None:
        self.after(0, fn)

    # ---------- 云端升级 ----------
    def _schedule_update_check(self, manual: bool = False) -> None:
        if self._updating:
            if manual:
                messagebox.showinfo("检查更新", "正在更新中，请稍候。")
            return

        def worker() -> None:
            err: str | None = None
            info: ReleaseInfo | None = None
            try:
                if manual:
                    latest = fetch_latest_release()
                    if latest is None:
                        err = "暂时无法连接更新服务器，请稍后重试。"
                    elif not is_newer(latest.version, __version__):
                        err = f"当前已是最新版本（v{__version__}）。"
                    else:
                        info = latest
                else:
                    info = check_for_update()
            except Exception as exc:  # noqa: BLE001
                err = f"检查更新失败：{exc}" if manual else None

            def done() -> None:
                if err and manual:
                    messagebox.showinfo("检查更新", err)
                    return
                if info is not None:
                    self._prompt_and_install(info)

            self._ui(done)

        threading.Thread(target=worker, daemon=True).start()

    def _prompt_and_install(self, info: ReleaseInfo) -> None:
        notes = (info.notes or "").strip()
        if len(notes) > 400:
            notes = notes[:400] + "…"
        body = (
            f"发现新版本 v{info.version}（当前 v{__version__}）。\n\n"
            f"{notes}\n\n" if notes else f"发现新版本 v{info.version}（当前 v{__version__}）。\n\n"
        )
        body += "是否立即下载并更新？\n（账本 data/ 会保留）"
        if not messagebox.askyesno("发现新版本", body):
            return

        self._updating = True
        self._status.configure(text="正在下载更新… 0%")
        self._progress.set(0)
        work = prepare_update_workdir()
        zip_path = work / info.asset_name
        release_page = (
            f"https://github.com/SaoDabai727/xiaobao-veg/releases/tag/{info.tag}"
        )

        def worker() -> None:
            try:

                def on_progress(
                    done: int, total: int | None, speed: float | None
                ) -> None:
                    text, ratio = format_download_progress(done, total, speed)

                    def tick(t=text, r=ratio) -> None:
                        self._status.configure(text=t)
                        self._progress.set(r)

                    self._ui(tick)

                def on_status(msg: str) -> None:
                    self._ui(lambda m=msg: self._status.configure(text=m))

                download_release_asset(
                    info.download_url,
                    zip_path,
                    progress_cb=on_progress,
                    status_cb=on_status,
                )

                def installing() -> None:
                    self._status.configure(text="正在安装更新…")
                    self._progress.set(1)

                self._ui(installing)
                extract_dir = work / "extract"
                src_root = extract_release_zip(zip_path, extract_dir)
                dest = install_root()

                def launch() -> None:
                    self._status.configure(text="即将重启以完成更新…")
                    spawn_apply_and_exit(src_root, dest)

                self._ui(launch)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                err_txt = str(exc)

                def fail() -> None:
                    self._updating = False
                    self._progress.set(0)
                    self._status.configure(text="更新失败")
                    messagebox.showerror(
                        "更新失败",
                        f"{err_txt}\n\n"
                        f"也可浏览器打开手动下载：\n{release_page}\n"
                        f"下载 xiaobao-veg-v{info.version}.exe 覆盖原程序即可（data 文件夹勿删）。",
                    )

                self._ui(fail)

        threading.Thread(target=worker, daemon=True).start()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
