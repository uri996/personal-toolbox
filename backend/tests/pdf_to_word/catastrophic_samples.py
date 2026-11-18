"""Checked synthetic long lines and short-text controls for local OCR review."""
from functools import lru_cache
import io

import pymupdf
from PIL import Image

from .recognition_samples import ScanSample
from .synthetic_pdfs import _image_only_pdf

LONG_TEXT = "甲说：“请把窗边的蓝色盒子放回书架，再按纸上的说明检查每一盏灯。”"


@lru_cache(maxsize=4)
def severe_sample(variant="clear"):
    styles = (
        ("normal", (0, 0, 0), None, None),
        ("inverted", (1, 1, 1), (0, 0, 0), None),
        ("gray-paper", (0, 0, 0), (0.75, 0.75, 0.75), None),
        ("light-text", (0.6, 0.6, 0.6), None, None),
        ("underline", (0, 0, 0), None, 1),
        ("ruled-paper", (0, 0, 0), None, -3),
    )
    expected = []
    rows = []
    with pymupdf.open() as source:
        page = source.new_page()
        font = pymupdf.Font(fontname="china-s")
        for index, (name, color, fill, ruling) in enumerate(styles):
            baseline = 75 + index * 92
            if fill is not None:
                page.draw_rect(pymupdf.Rect(43, baseline - 14, 545, baseline + 4), fill=fill, color=fill)
            writer = pymupdf.TextWriter(page.rect)
            writer.append((48, baseline), LONG_TEXT, font=font, fontsize=11)
            writer.write_text(page, color=color)
            if ruling is not None:
                page.draw_line((43, baseline + ruling), (545, baseline + ruling), color=(0.45, 0.45, 0.45), width=0.3)
            expected.append(LONG_TEXT)
            rows.append((name, LONG_TEXT, (40, baseline - 18, 560, baseline + 15)))
        writer = pymupdf.TextWriter(page.rect)
        controls = ("OK", "Good day", "2026", "1          2          3",
                    "A          B          C", "甲          乙          丙")
        for index, text in enumerate(controls):
            baseline = 665 + index * 24
            writer.append((48, baseline), text, font=font, fontsize=11)
            expected.append(text)
            rows.append((f"control-{index}", text, (40, baseline - 18, 560, baseline + 8)))
        writer.write_text(page)
        assert page.get_text().replace("\n", "") == "".join(expected)
        dpi = 110 if variant == "low-dpi" else 150
        pixmap = page.get_pixmap(dpi=dpi, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        if variant == "dark-gray":
            # A full-page contrast change preserves the same shapes and bounds.
            import numpy as np
            image = Image.fromarray((np.asarray(image).astype(float) * 0.8 + 20).astype("uint8"))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=60 if variant == "compressed" else 90)
    sample = ScanSample(f"severe-{variant}", _image_only_pdf([buffer.getvalue()]),
                        (tuple(expected),), (tuple((text, bounds) for _, text, bounds in rows),))
    return sample, tuple(rows)

