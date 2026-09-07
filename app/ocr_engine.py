"""RapidOCR 封装（rapidocr >= 3.x）。"""

from __future__ import annotations

from pathlib import Path

from app.parser import OcrBox


class OcrEngine:
    """懒加载 RapidOCR，避免启动 GUI 时立刻加载模型。"""

    def __init__(self) -> None:
        self._ocr = None

    def _ensure(self) -> None:
        if self._ocr is not None:
            return
        from rapidocr import RapidOCR

        self._ocr = RapidOCR()

    def recognize(self, image_path: str | Path) -> list[OcrBox]:
        """对单张图片做 OCR，返回带坐标文本框。"""
        self._ensure()
        path = str(image_path)
        result = self._ocr(path)

        boxes: list[OcrBox] = []
        if result is None:
            return boxes

        # rapidocr 3.x: RapidOCROutput(boxes, txts, scores)
        txts = getattr(result, "txts", None)
        box_arr = getattr(result, "boxes", None)
        if not txts:
            # 兼容旧版 list 返回：[[box, text, score], ...]
            if isinstance(result, (list, tuple)):
                for item in result:
                    if not item or len(item) < 2:
                        continue
                    box_pts, text = item[0], item[1]
                    if not text or not str(text).strip():
                        continue
                    pts = [[float(p[0]), float(p[1])] for p in box_pts]
                    boxes.append(OcrBox(text=str(text).strip(), box=pts))
            return boxes

        for i, text in enumerate(txts):
            if not text or not str(text).strip():
                continue
            pts: list[list[float]] = []
            if box_arr is not None and i < len(box_arr):
                raw = box_arr[i]
                pts = [[float(p[0]), float(p[1])] for p in raw]
            boxes.append(OcrBox(text=str(text).strip(), box=pts))
        return boxes
