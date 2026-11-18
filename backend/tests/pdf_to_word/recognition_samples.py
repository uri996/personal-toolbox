"""Fictional dense dialogue scans with checked glyphs, bounds and distortions."""
import io
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

from .synthetic_pdfs import _image_only_pdf

DIALOGUE = (
    "“图书室今天为什么提前开门？”甲问，“因为我们要核对一份完全虚构的旧地图，所有数字都只是示例。”",
    "乙答道：“先别翻到末页。我已经把第一章、第二章和第三章逐一标记，未完成的条目仍然留在原处。”",
    "“记录上写的是赢得比赛，旁边那个字却是嬴。”甲指着练习纸说，“己、已、巳也要分别看清楚。”",
    "“你确定箱子里有七张纸吗？”乙说，“我数过一次，又重新数了一次，结果都是七张，没有增加或遗漏。”",
    "甲停了一会儿：“等到钟响……我们再继续。那条横线——请完整保留，不要把标点误当作正文。”",
    "“这张表上的日期是二〇二六年十一月，编号是 A-2048，金额 128 元，比例为 95%，全部都是虚构数据。”",
    "乙把纸放平：“短句也有意义。是吗？当然！如果只剩几个字，就应回到图像查看完整文字区域。”",
    "“门外传来三声敲门声。”甲继续念道，“第一声很轻，第二声稍重，第三声之后，走廊又恢复了安静。”",
    "“这里没有真实人物，也没有真实地址。”乙说，“我们只用这段新写的对话检查扫描识别和段落顺序。”",
    "甲问：“先核对页眉还是页脚？”乙答：“都要核对。第十二节后面是第十三节，不能跳过其中一节。”",
    "“末尾还有一句长话，靠近正文右侧边界。”甲说，“请把句首、句中和句尾都读出来，再检查相邻两行。”",
    "乙写下两组表达：“5 - 3 = 2；1 2 3。符号之间的空格属于原始内容，不应通过猜测把它们合并。”",
    "“书名是《虚构观察手册》（示例版），附录用【甲】【乙】标记。”甲说，“中文单引号‘示例’也要保留。”",
    "“如果两次识别给出不同结果怎么办？”乙问。甲答：“记录分歧，保留证据，不能凭语义编造一句新话。”",
    "甲最后确认：“本章到此结束。下一页将继续讨论清晰、模糊和轻微倾斜的图像，所有样本使用同一段原文。”",
    "乙合上记录本：“未到约定时间，大家就在室内等待；到了约定时间，便按照纸上已经写明的次序行动。”",
)


@dataclass(frozen=True)
class ScanSample:
    name: str
    pdf: bytes
    expected_pages: tuple[tuple[str, ...], ...]
    rows: tuple[tuple[tuple[str, tuple[float, ...]], ...], ...]


def _draw_checked(page, text, x, y, size, font):
    writer = pymupdf.TextWriter(page.rect)
    line = ""
    for character in text:
        assert font.has_glyph(ord(character)), f"fixture glyph missing: {character!r}"
        if font.text_length(line + character, fontsize=size) > page.rect.width - x - 36:
            writer.append((x, y), line, font=font, fontsize=size)
            y += size * 1.6
            line = ""
        line += character
    assert y + size < 775, "fixture would overlap footer or leave the page"
    writer.append((x, y), line, font=font, fontsize=size)
    writer.write_text(page)
    return y + size * 1.6


@lru_cache(maxsize=6)
def dialogue_sample(variant="clean") -> ScanSample:
    variants = {"clean", "low-dpi", "compressed", "blur", "skew", "scaled"}
    if variant not in variants:
        raise ValueError(variant)
    images, expected_pages, physical_pages = [], [], []
    sizes = (9, 12) if variant == "clean" else (9,)
    for page_index, size in enumerate(sizes):
        with pymupdf.open() as source:
            page = source.new_page()
            font = pymupdf.Font(fontname="china-s")
            header = f"虚构对话扫描样本 第 {page_index + 1} 页"
            footer = "全部文字均为本项目新写的虚构内容。"
            _draw_checked(page, header, 48, 42, 9, font)
            expected = [header, "第一章　纸上地图与复核记录"]
            y = _draw_checked(page, expected[-1], 48, 76, 14, font)
            count = 42 if size == 9 else 12
            for index in range(count):
                text = f"（{index + 1}）" + DIALOGUE[index % len(DIALOGUE)]
                y = _draw_checked(page, text, 48, y, size, font)
                expected.append(text)
            # Footer is separate from body-height checks.
            writer = pymupdf.TextWriter(page.rect)
            writer.append((48, 805), footer, font=font, fontsize=9)
            writer.write_text(page)
            expected.append(footer)
            assert page.get_text().replace("\n", "") == "".join(expected)
            rows = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line["spans"])
                    rows.append((text, tuple(line["bbox"])))
            dpi = 110 if variant == "low-dpi" else 150
            pixmap = page.get_pixmap(dpi=dpi, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            transform = np.array([[dpi / 72, 0, 0], [0, dpi / 72, 0], [0, 0, 1]], dtype=float)
            if variant == "scaled":
                factor = 0.8
                image = image.resize((round(image.width * factor), round(image.height * factor)), Image.Resampling.LANCZOS)
                transform = np.diag([factor, factor, 1]) @ transform
            if variant == "blur":
                image = image.filter(ImageFilter.GaussianBlur(0.6))
            if variant == "skew":
                import cv2

                rotation = cv2.getRotationMatrix2D((image.width / 2, image.height / 2), 0.7, 1)
                pixels = cv2.warpAffine(np.asarray(image), rotation, image.size,
                                        flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
                image = Image.fromarray(pixels)
                transform = np.vstack([rotation, [0, 0, 1]]) @ transform
            transformed_rows = []
            for row_text, (x0, y0, x1, y1) in rows:
                corners = np.array([[x0, y0, 1], [x1, y0, 1], [x1, y1, 1], [x0, y1, 1]]).T
                mapped = transform @ corners
                assert mapped[0].min() >= 2 and mapped[1].min() >= 2
                assert mapped[0].max() < image.width - 2 and mapped[1].max() < image.height - 2
                bounds = (
                    mapped[0].min() * page.rect.width / image.width,
                    mapped[1].min() * page.rect.height / image.height,
                    mapped[0].max() * page.rect.width / image.width,
                    mapped[1].max() * page.rect.height / image.height,
                )
                transformed_rows.append((row_text, bounds))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=45 if variant == "compressed" else 85)
            images.append(buffer.getvalue())
            expected_pages.append(tuple(expected))
            physical_pages.append(tuple(transformed_rows))
    return ScanSample(f"dialogue-{variant}", _image_only_pdf(images), tuple(expected_pages), tuple(physical_pages))



def reference_rows(name):
    """Physical source rows, using the same font and drawing code as fixtures."""
    from . import synthetic_pdfs as source_samples

    if name.startswith("dialogue-"):
        return dialogue_sample(name.removeprefix("dialogue-")).rows
    if name == "report":
        pages = source_samples.LONG_REPORT_PAGES
    elif name == "punctuation":
        pages = [[(text, 14) for text in source_samples.PUNCTUATION_LINES]]
    elif name == "dense":
        pages = [[(text, 12) for text in source_samples.DENSE_PARAGRAPHS]]
    elif name == "hidden":
        pages = [[(text, 12) for text in source_samples.DENSE_PARAGRAPHS[:4]]]
    else:
        raise ValueError(name)
    layouts = []
    with pymupdf.open() as document:
        for index, lines in enumerate(pages):
            page = document.new_page()
            font = pymupdf.Font(fontname="china-s")
            if name == "report":
                source_samples._write_scan_text(page, source_samples.REPORT_HEADER.format(page=index + 1), 64, 46, 9, font)
            y = 96 if name == "hidden" else 84
            for text, size in lines:
                if name == "hidden":
                    page.insert_text((64, y), text, fontsize=size, fontname="china-s")
                    y += 22
                else:
                    y = source_samples._write_scan_text(page, text, 64, y, size, font)
            if name == "report":
                source_samples._write_scan_text(page, source_samples.REPORT_FOOTER, 64, 806, 9, font)
            rows = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line["spans"])
                    rows.append((text, tuple(line["bbox"])))
            layouts.append(tuple(rows))
    return tuple(layouts)
