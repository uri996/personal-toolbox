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


def email_period_pdf() -> bytes:
    """Sample M: an email address immediately followed by a Chinese full stop.

    Regression cover for the V1.1 report that the trailing ``。`` after a Latin
    email address could disappear during conversion.
    """
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)
    page.insert_font(fontname=LATIN_FONT)
    page.insert_text(
        (72, 100),
        "如需帮助请发送邮件至 user@example.com。",
        fontsize=13,
        fontname=CJK_FONT,
    )

    # Same visual line, but the address is a separate Latin-font span and the
    # full stop is its own CJK span (a common real-world PDF structure).
    x = 72
    label = "联系邮箱："
    page.insert_text((x, 140), label, fontsize=13, fontname=CJK_FONT)
    x += pymupdf.get_text_length(label, fontname=CJK_FONT, fontsize=13)
    address = "user@example.com"
    page.insert_text((x, 140), address, fontsize=13, fontname=LATIN_FONT)
    x += pymupdf.get_text_length(address, fontname=LATIN_FONT, fontsize=13)
    page.insert_text((x, 140), "。", fontsize=13, fontname=CJK_FONT)

    # A wrapped sentence whose closing full stop opens the next line.
    page.insert_text(
        (72, 180),
        "换行后句号位于行首：user@example.com",
        fontsize=13,
        fontname=CJK_FONT,
    )
    page.insert_text((72, 198), "。", fontsize=13, fontname=CJK_FONT)
    return _save(document)


# --- Scanned (image-only) fixtures used by the OCR tests ---------------------
# Each fixture first draws text with MuPDF's built-in fonts, renders that page
# to a raster image, and then embeds only the image into a fresh PDF. The
# result has no text layer at all, so it behaves like a real scan.

SCAN_DPI = 150
# Scans are usually stored as JPEG; PNG would push the fixtures past the
# 3 MiB upload limit enforced by the service.
SCAN_JPEG_QUALITY = 90


def _to_jpeg(pixmap) -> bytes:
    return pixmap.tobytes("jpeg", jpg_quality=SCAN_JPEG_QUALITY)


def _render_text_png(lines, *, width: float = 595, height: float = 842) -> bytes:
    """Render text lines to a JPEG that looks like a scan."""
    document = pymupdf.open()
    page = document.new_page(width=width, height=height)
    next_y = 0
    expected = []
    for text, x, y, size, font_name in lines:
        font = pymupdf.Font(fontname=font_name)
        next_y = _write_scan_text(page, text, x, max(y, next_y), size, font)
        expected.append(text)
    assert page.get_text().replace("\n", "") == "".join(expected)
    pixmap = page.get_pixmap(dpi=SCAN_DPI, alpha=False)
    data = _to_jpeg(pixmap)
    document.close()
    return data


def _image_only_pdf(images) -> bytes:
    """Build a PDF whose pages contain only the given image bytes."""
    document = pymupdf.open()
    for image_bytes in images:
        page = document.new_page()
        page.insert_image(page.rect, stream=image_bytes)
    return _save(document)


def scanned_chinese_pdf() -> bytes:
    """Sample F: a purely Chinese document without any text layer."""
    return _image_only_pdf(
        [
            _render_text_png(
                [
                    ("示例季度运营报告", 72, 100, 24, CJK_FONT),
                    ("第一段：本季度示例业务保持稳定。", 72, 160, 15, CJK_FONT),
                    ("第二段：各项指标均为虚构数据。", 72, 200, 15, CJK_FONT),
                    ("第三段：用于验证中文扫描识别。", 72, 240, 15, CJK_FONT),
                ]
            )
        ]
    )


def scanned_english_pdf() -> bytes:
    """Sample G: an English-only scan with digits and punctuation."""
    return _image_only_pdf(
        [
            _render_text_png(
                [
                    ("Quarterly Report 2026", 72, 100, 24, LATIN_FONT),
                    ("Revenue reached 128 units, up 12 percent.", 72, 160, 15, LATIN_FONT),
                    ("Contact: user@example.com.", 72, 200, 15, LATIN_FONT),
                    ("Reference code: A-1024.", 72, 240, 15, LATIN_FONT),
                ]
            )
        ]
    )


def scanned_mixed_language_pdf() -> bytes:
    """Sample H: a scan mixing Chinese, English, digits and symbols."""
    return _image_only_pdf(
        [
            _render_text_png(
                [
                    ("中英混排扫描示例", 72, 100, 22, CJK_FONT),
                    ("日期 2026-11-17，版本 v1.2。", 72, 160, 15, CJK_FONT),
                    ("Example text with numbers 95%.", 72, 200, 15, CJK_FONT),
                    ("符号：100%、A/B、(括号)。", 72, 240, 15, CJK_FONT),
                ]
            )
        ]
    )


def mixed_pages_pdf() -> bytes:
    """Sample I: page 1 is digital text, page 2 is a scan."""
    document = pymupdf.open()
    first = document.new_page()
    first.insert_font(fontname=CJK_FONT)
    first.insert_text((72, 100), "第一页为普通文字页。", fontsize=18, fontname=CJK_FONT)
    first.insert_text(
        (72, 150), "该段落应保持原生文字不被栅格化。", fontsize=13, fontname=CJK_FONT
    )
    image_bytes = _render_text_png(
        [("第二页为扫描图片页。", 72, 120, 20, CJK_FONT), ("Scan only content.", 72, 170, 15, LATIN_FONT)]
    )
    second = document.new_page()
    second.insert_image(second.rect, stream=image_bytes)
    return _save(document)


def same_page_image_text_pdf() -> bytes:
    """Sample J: native text plus an embedded image that carries text."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)
    page.insert_text((72, 100), "原生文字段落，应当保留。", fontsize=16, fontname=CJK_FONT)
    page.insert_text((72, 135), "Native line 2026.", fontsize=13, fontname=CJK_FONT)
    image_bytes = _render_text_png(
        [("图片中的文字。", 60, 80, 18, CJK_FONT), ("Image-only note.", 60, 120, 14, LATIN_FONT)],
        width=500,
        height=400,
    )
    page.insert_image(pymupdf.Rect(60, 400, 560, 800), stream=image_bytes)
    return _save(document)


def structured_scanned_pdf() -> bytes:
    """Sample K: an image scan with a title, list and a simple table."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_font(fontname=CJK_FONT)
    page.insert_text((72, 90), "示例结构文档", fontsize=22, fontname=CJK_FONT)
    page.insert_text((72, 140), "一、要点列表", fontsize=15, fontname=CJK_FONT)
    page.insert_text((90, 175), "1. 第一项示例内容。", fontsize=13, fontname=CJK_FONT)
    page.insert_text((90, 205), "2. 第二项示例内容。", fontsize=13, fontname=CJK_FONT)

    left, top = 72, 260
    col_widths = (150, 180)
    row_height = 34
    rows = (("项目", "说明"), ("编号", "A-1024"), ("状态", "示例"))
    total_width = sum(col_widths)
    for index in range(len(rows) + 1):
        y = top + index * row_height
        page.draw_line((left, y), (left + total_width, y), width=0.8)
    for x in (left, left + col_widths[0], left + total_width):
        page.draw_line((x, top), (x, top + row_height * len(rows)), width=0.8)
    for row_index, (first, second) in enumerate(rows):
        y = top + row_index * row_height + 22
        page.insert_text((left + 8, y), first, fontsize=12, fontname=CJK_FONT)
        page.insert_text(
            (left + col_widths[0] + 8, y), second, fontsize=12, fontname=CJK_FONT
        )
    image_bytes = _to_jpeg(page.get_pixmap(dpi=SCAN_DPI, alpha=False))
    document.close()
    return _image_only_pdf([image_bytes])


def illustration_only_pdf() -> bytes:
    """Sample L: a scan-like page with shapes but no text."""
    document = pymupdf.open()
    page = document.new_page()
    page.draw_rect(pymupdf.Rect(80, 120, 300, 300), color=(0, 0, 0), fill=(0.2, 0.4, 0.8))
    page.draw_circle(pymupdf.Point(420, 220), 80, color=(0, 0, 0), fill=(0.9, 0.5, 0.1))
    page.draw_line((80, 400), (520, 400), width=3)
    image_bytes = _to_jpeg(page.get_pixmap(dpi=SCAN_DPI, alpha=False))
    document.close()
    return _image_only_pdf([image_bytes])


# --- Content quality fixtures -----------------------------------------------
# These fixtures ship a known ground truth so tests can measure character
# accuracy, punctuation retention and line coverage instead of only checking
# that a few keywords survive. Every sentence is fictional.

PUNCTUATION_LINES = [
    "引号测试：“双引号”与‘单引号’都应保留。",
    "省略号与破折号：等待……然后——继续。",
    "书名与括号：《示例手册》（试用版）、【内部资料】。",
    "句读测试：问号？叹号！分号；冒号：顿号、逗号，句号。",
    "序号测试：第一章、第二节、（三）、四、五、六。",
    "混排测试：版本 v1.2，日期 2026-11-17，完成率 95%，编号 A-1024。",
    "形近字测试：己已巳、未末、戊戌、日曰、人入。",
    "生僻字测试：魑魅魍魉饕餮耄耋。",
]

DENSE_PARAGRAPHS = [
    "示例业务说明：本文档用于验证密集中文段落的识别完整性，全部内容均为虚构。",
    "第一部分介绍背景：系统需要把扫描件转换为可编辑文本，并保持阅读顺序正确。",
    "第二部分说明范围：仅处理本次上传的文件，不保存原文，也不向外部服务发送内容。",
    "第三部分描述流程：先渲染页面，再识别文字，随后写入文字层，最后生成文档。",
    "第四部分列出限制：单次请求最多识别十页，超出时需要拆分文件后重新提交。",
    "第五部分记录结果：识别成功时直接下载，部分失败时保留文件并给出明确提示。",
    "第六部分补充说明：段落之间的空行不参与识别，但正文内容必须完整保留。",
    "第七部分强调重点：不能因为标点错误就忽略整句丢失，两者需要分别统计。",
    "第八部分给出示例：示例编号 A-1024，示例日期 2026-11-17，示例比例 95%。",
    "第九部分说明结论：本页内容仅用于自动化测试，不代表任何真实业务数据。",
]

LONG_REPORT_PAGES = [
    [
        ("示例技术说明", 18),
        ("第一章　总体说明", 14),
        ("第一条　本文件用于验证扫描文档的文字识别质量，全部内容均为虚构示例。", 11),
        ("第二条　阅读顺序应自上而下、自左而右，不得出现段落跳跃或整段缺失。", 11),
        ("第三条　标点符号包括：“双引号”、‘单引号’、《书名号》、（圆括号）。", 11),
        ("第四条　省略号……与破折号——都应保留；问号？叹号！句号。逗号，顿号、都要正确。", 11),
    ],
    [
        ("第二章　操作流程", 14),
        ("第五条　流程分为三段：准备、执行、复核……每一步都需要记录结果并签字确认。", 11),
        ("第六条　如遇异常——包括中断、重复、超时——应停止操作并上报，不得自行处理。", 11),
        ("第七条　示例编号为 A-1024，版本号 v1.2，日期 2026-11-17，完成率 95%。", 11),
        ("第八条　常见字：示例报告数据统计结果分析；生僻字：魑魅魍魉饕餮耄耋。", 11),
    ],
    [
        ("第三章　对话示例", 14),
        ("问：识别结果是否完整？", 11),
        ("答：需要逐段核对，不能只看关键短语是否存在。", 11),
        ("问：如果出现形近字怎么办？", 11),
        ("答：应记录原文与识别结果，逐字比对后判断是模型误差还是链路损坏。", 11),
        ("注：本页文字长度不同，用于检查短行与长行混合时的行序。", 11),
    ],
    [
        ("第四章　数据示例", 14),
        ("第九条　季度收入为 128 万元，同比增长 12%，环比下降 3%。", 11),
        ("第十条　各项指标均为虚构数据，不代表任何真实业务。", 11),
        ("第十一条　编号规则：A-1024、B-2048、C-4096，均为示例值。", 11),
    ],
    [
        ("第五章　复核要求", 14),
        ("第十二条　复核人员应逐段朗读并核对，确保没有整段遗漏。", 11),
        ("第十三条　如发现缺字，应在备注中记录位置与数量，不得直接补写原文。", 11),
        ("第十四条　复核完成后由两人签字，签字栏见附录。", 11),
    ],
    [
        ("第六章　附录", 14),
        ("附录一：术语表（示例）", 11),
        ("附录二：修订记录——2026-10-01 初稿；2026-11-17 修订。", 11),
        ("附录三　联系方式 user@example.com。", 11),
        ("全文结束。", 11),
    ],
]

REPORT_HEADER = "示例内部资料  第 {page} 页"
REPORT_FOOTER = "全部内容为虚构示例，仅用于自动化测试。"


def _scan_document(pages, *, header: str | None = None, footer: str | None = None) -> bytes:
    """Render styled text lines onto pages, then keep only their raster image."""
    document = pymupdf.open()
    images = []
    for index, lines in enumerate(pages):
        page = document.new_page()
        font = pymupdf.Font(fontname=CJK_FONT)
        expected = []
        if header:
            heading = header.format(page=index + 1)
            _write_scan_text(page, heading, 64, 46, 9, font)
            expected.append(heading)
        y = 84.0
        for text, size in lines:
            y = _write_scan_text(page, text, 64, y, size, font)
            expected.append(text)
        if footer:
            _write_scan_text(page, footer, 64, 806, 9, font)
            expected.append(footer)
        actual = page.get_text().replace("\n", "")
        assert actual == "".join(expected), "synthetic scan changed its ground truth"
        images.append(_to_jpeg(page.get_pixmap(dpi=SCAN_DPI, alpha=False)))
    document.close()
    return _image_only_pdf(images)


def _write_scan_text(page, text, x, y, size, font):
    """Wrap with actual font metrics and verify the embedded Unicode mapping."""
    writer = pymupdf.TextWriter(page.rect)
    line = ""
    for character in text:
        assert font.has_glyph(ord(character)), f"fixture font cannot draw {character!r}"
        if font.text_length(line + character, fontsize=size) > page.rect.width - x - 36:
            writer.append((x, y), line, font=font, fontsize=size)
            y += size * 1.85
            line = ""
        line += character
    assert y + size < page.rect.height - 20, "fixture exceeds page height"
    writer.append((x, y), line, font=font, fontsize=size)
    writer.write_text(page)
    return y + size * 1.85


def punctuation_scan_pdf() -> bytes:
    """Sample N: punctuation, numerals and look-alike characters as a scan."""
    return _scan_document([[(line, 14) for line in PUNCTUATION_LINES]])


def dense_chinese_scan_pdf() -> bytes:
    """Sample O: a dense one-page Chinese scan with ten full paragraphs."""
    return _scan_document([[(line, 12) for line in DENSE_PARAGRAPHS]])


def long_report_scan_pdf() -> bytes:
    """Sample P: a six-page Chinese scan with header, footer and sections."""
    return _scan_document(
        LONG_REPORT_PAGES, header=REPORT_HEADER, footer=REPORT_FOOTER
    )


HIDDEN_LAYER_NOTE = "旧的错误文字层占位内容，不应出现在转换结果中。"


def hidden_text_layer_scan_pdf() -> bytes:
    """Sample Q: a scan carrying a wrong invisible text layer.

    Scanners and PDF editors often add a hidden text layer. Such a layer must
    not make the page look like digital text, otherwise the visible page is
    never recognized.
    """
    source = pymupdf.open()
    page = source.new_page()
    page.insert_font(fontname=CJK_FONT)
    y = 96
    for line in DENSE_PARAGRAPHS[:4]:
        page.insert_text((64, y), line, fontsize=12, fontname=CJK_FONT)
        y += 22
    image = _to_jpeg(page.get_pixmap(dpi=SCAN_DPI, alpha=False))
    source.close()

    document = pymupdf.open()
    page = document.new_page()
    page.insert_image(page.rect, stream=image)
    page.insert_font(fontname=CJK_FONT)
    page.insert_text(
        (64, 100),
        HIDDEN_LAYER_NOTE,
        fontsize=12,
        fontname=CJK_FONT,
        render_mode=3,
    )
    return document.tobytes()
