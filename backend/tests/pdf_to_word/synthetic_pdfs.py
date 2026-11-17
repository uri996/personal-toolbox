"""Synthetic, privacy-safe PDF fixtures generated with PyMuPDF.

All content is fictional and neutral. No real documents, personal data or
system font files are used; only MuPDF built-in fonts are referenced.
"""

import io

import pymupdf

# MuPDF built-in CJK font for simplified Chinese. pdf2docx reports its spans
# with the raw font name "Heiti", which is exactly the kind of unresolvable
# font name that Word/WPS cannot map to an installed font.
CJK_FONT = "china-s"
LATIN_FONT = "helv"
LATIN_BOLD_FONT = "hebo"


def _save(document: pymupdf.Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def chinese_paragraphs_pdf() -> bytes:
    """Sample A: several plain Chinese paragraphs with punctuation."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)
    page.insert_text(
        (72, 90), "示例季度运营报告", fontsize=18, fontname=CJK_FONT
    )
    page.insert_text(
        (72, 140),
        "第一段：本季度示例业务保持稳定，各项指标均为虚构数据。",
        fontsize=12,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 170),
        "第二段：包含标点符号，如逗号、句号。以及数字 2026 和百分比 95%。",
        fontsize=12,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 200),
        "第三段：用于验证多段落中文内容在转换后保持完整。",
        fontsize=12,
        fontname=CJK_FONT,
    )
    return _save(document)


def mixed_language_pdf() -> bytes:
    """Sample B: Chinese, English, technical terms, digits and symbols."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)
    page.insert_text(
        (72, 90),
        "Mixed 中英混排 with FastAPI、DOCX 和 Python 3.14。",
        fontsize=12,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 120),
        "版本号 v1.1，日期 2026-11-17，邮箱格式 user@example.com。",
        fontsize=12,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 150),
        "符号测试：100%、A/B、(括号)、[方括号]、#标签。",
        fontsize=12,
        fontname=CJK_FONT,
    )
    return _save(document)


def styled_pdf() -> bytes:
    """Sample C: blue heading, bold text, different sizes, black body."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)
    page.insert_font(fontname=LATIN_FONT)
    page.insert_font(fontname=LATIN_BOLD_FONT)
    blue = (0, 0, 0.8)
    page.insert_text(
        (72, 90),
        "蓝色标题示例",
        fontsize=20,
        fontname=CJK_FONT,
        color=blue,
    )
    page.insert_text(
        (72, 130),
        "Bold Heading",
        fontsize=14,
        fontname=LATIN_BOLD_FONT,
        color=blue,
    )
    page.insert_text(
        (72, 160),
        "普通黑色正文，字号较小，用于对比样式保留情况。",
        fontsize=10.5,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 185),
        "Regular body text",
        fontsize=10.5,
        fontname=LATIN_FONT,
    )
    return _save(document)


def table_pdf() -> bytes:
    """Sample D: a simple two-column table with Chinese, English and dates."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)

    left, top = 72, 100
    col_widths = (160, 220)
    row_height = 32
    rows = (
        ("指标名称", "示例数值"),
        ("季度收入", "128 万元"),
        ("更新日期", "2026-11-17"),
        ("Owner", "Example Team"),
    )

    total_width = sum(col_widths)
    total_height = row_height * len(rows)
    for index in range(len(rows) + 1):
        y = top + index * row_height
        page.draw_line((left, y), (left + total_width, y), width=0.8)
    x_positions = (left, left + col_widths[0], left + total_width)
    for x in x_positions:
        page.draw_line((x, top), (x, top + total_height), width=0.8)

    for row_index, (first, second) in enumerate(rows):
        y = top + row_index * row_height + 21
        page.insert_text(
            (left + 8, y), first, fontsize=11, fontname=CJK_FONT
        )
        page.insert_text(
            (left + col_widths[0] + 8, y),
            second,
            fontsize=11,
            fontname=CJK_FONT,
        )
    return _save(document)


def report_pdf() -> bytes:
    """Sample E: report-like structure with title, sections, list and table."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)
    page.insert_text(
        (72, 80), "示例项目周报", fontsize=20, fontname=CJK_FONT
    )
    page.insert_text(
        (72, 110), "报告日期：2026-11-17", fontsize=10, fontname=CJK_FONT
    )
    page.insert_text(
        (72, 150), "一、本周进展", fontsize=14, fontname=CJK_FONT
    )
    page.insert_text(
        (72, 175),
        "1. 完成示例模块的接口联调。",
        fontsize=11,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 198),
        "2. 修复虚构环境下的字体显示问题。",
        fontsize=11,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 240), "二、下周计划", fontsize=14, fontname=CJK_FONT
    )
    page.insert_text(
        (72, 265),
        "继续验证 Conversion Quality 与 Editable Structure。",
        fontsize=11,
        fontname=CJK_FONT,
    )
    page.insert_text(
        (72, 300), "三、风险说明", fontsize=14, fontname=CJK_FONT
    )
    page.insert_text(
        (72, 325),
        "本报告全部内容为自动化测试所用的虚构示例。",
        fontsize=11,
        fontname=CJK_FONT,
    )
    return _save(document)
