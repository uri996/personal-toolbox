"""Post-process DOCX output to normalize fonts and conservative line spacing.

pdf2docx copies raw PDF span font names (e.g. ``Heiti``, ``ABCDEF+SimSun``,
``Droid Sans Fallback``) directly into ``w:rFonts`` for ascii, hAnsi and
eastAsia. Those names usually do not exist on the reader's machine, so
Word/WPS substitutes an arbitrary font, which breaks CJK rendering and can
make glyphs overlap. This module rewrites only font declarations and unsafe
exact line heights; text, styles and document structure are left untouched.
"""

import io
import logging
import re
import zipfile

from docx import Document
from docx.oxml.ns import qn

from .errors import ConversionFailedError

LOGGER = logging.getLogger(__name__)

DEFAULT_LATIN_FONT = "Arial"
DEFAULT_CJK_FONT = "宋体"

# Prefix used by PDF subset embedded fonts, e.g. "ABCDEF+SimSun".
_SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")

# Canonical font names that are safe to keep as-is.
_LATIN_CANONICAL = {
    "arial": "Arial",
    "times new roman": "Times New Roman",
    "calibri": "Calibri",
    "courier new": "Courier New",
    "cambria": "Cambria",
    "consolas": "Consolas",
    "georgia": "Georgia",
    "verdana": "Verdana",
    "tahoma": "Tahoma",
}

# Common Latin aliases found in PDFs -> canonical Windows-available fonts.
_LATIN_ALIASES = {
    "helvetica": "Arial",
    "helvetica neue": "Arial",
    "helvet": "Arial",
    "liberation sans": "Arial",
    "dejavu sans": "Arial",
    "nimbus sans": "Arial",
    "nimbussans": "Arial",
    "arialmt": "Arial",
    "times": "Times New Roman",
    "timesnewroman": "Times New Roman",
    "timesnewromanpsmt": "Times New Roman",
    "liberation serif": "Times New Roman",
    "dejavu serif": "Times New Roman",
    "nimbus roman": "Times New Roman",
    "courier": "Courier New",
    "couriernew": "Courier New",
    "liberation mono": "Courier New",
    "dejavu sans mono": "Courier New",
    "nimbus mono": "Courier New",
}

# Canonical CJK fonts available on a typical Chinese Windows / WPS install.
_CJK_CANONICAL = {
    "宋体": "宋体",
    "黑体": "黑体",
    "微软雅黑": "微软雅黑",
    "等线": "等线",
    "楷体": "楷体",
    "仿宋": "仿宋",
}

# CJK aliases, including MuPDF built-in names and common open-source CJK fonts.
_CJK_ALIASES = {
    "simsun": "宋体",
    "nsimsun": "宋体",
    "songti": "宋体",
    "songti sc": "宋体",
    "songti tc": "宋体",
    "stsong": "宋体",
    "stsongti": "宋体",
    "stsongti-sc": "宋体",
    "noto serif cjk sc": "宋体",
    "source han serif sc": "宋体",
    "simhei": "黑体",
    "heiti": "黑体",
    "heiti sc": "黑体",
    "heiti tc": "黑体",
    "stheiti": "黑体",
    "stheiti sc": "黑体",
    "stheiti light": "黑体",
    "microsoft yahei": "微软雅黑",
    "ms yahei": "微软雅黑",
    "yahei": "微软雅黑",
    "noto sans cjk sc": "微软雅黑",
    "source han sans sc": "微软雅黑",
    "droid sans fallback": "微软雅黑",
    "wenquanyi zen hei": "微软雅黑",
    "wenquanyi micro hei": "微软雅黑",
    "dengxian": "等线",
    "kaiti": "楷体",
    "kaiti sc": "楷体",
    "stkaiti": "楷体",
    "stkaiti sc": "楷体",
    "fangsong": "仿宋",
    "stfangsong": "仿宋",
    "stfangsong sc": "仿宋",
    "mingliu": "宋体",
    "pmingliu": "宋体",
}

# Font style suffixes that should not affect family recognition.
_STYLE_SUFFIXES = (
    "-regular",
    "-bold",
    "-italic",
    "-bolditalic",
    "-oblique",
    "-boldoblique",
    " regular",
    " bold",
    " italic",
    " light",
    " medium",
    " semibold",
    ",bold",
    ",italic",
)


# Space-stripped lookup tables so compact names like "NotoSansCJKsc" match.
_COMPACT_CJK = {key.replace(" ", ""): value for key, value in _CJK_ALIASES.items()}
_COMPACT_LATIN = {key.replace(" ", ""): value for key, value in _LATIN_ALIASES.items()}


def strip_subset_prefix(name: str) -> str:
    """Remove the PDF subset prefix such as ``ABCDEF+`` from a font name."""
    return _SUBSET_PREFIX.sub("", name or "")


def _normalize_key(name: str) -> str:
    key = strip_subset_prefix(name).strip().lower()
    for suffix in _STYLE_SUFFIXES:
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    # Collapse separators so "NotoSansCJKsc-Regular" style names match too.
    return re.sub(r"[\s_]+", " ", key)


def map_latin_font(name: str | None) -> str | None:
    """Map a raw font name to a canonical Latin font, or None if not Latin."""
    if not name:
        return None
    key = _normalize_key(name)
    if key in _CJK_CANONICAL or key in _CJK_ALIASES or key.replace(" ", "") in _COMPACT_CJK:
        return None
    if key in _LATIN_CANONICAL:
        return _LATIN_CANONICAL[key]
    if key in _LATIN_ALIASES:
        return _LATIN_ALIASES[key]
    return _COMPACT_LATIN.get(key.replace(" ", ""))


def map_cjk_font(name: str | None) -> str | None:
    """Map a raw font name to a canonical CJK font, or None if not CJK."""
    if not name:
        return None
    key = _normalize_key(name)
    if key in _CJK_CANONICAL:
        return _CJK_CANONICAL[key]
    if key in _CJK_ALIASES:
        return _CJK_ALIASES[key]
    return _COMPACT_CJK.get(key.replace(" ", ""))


def resolve_run_fonts(names: list[str | None]) -> tuple[str, str]:
    """Resolve (latin, cjk) font pair from a run's declared font names.

    Recognized fonts are preserved through canonical mapping; unrecognized or
    missing names fall back to deterministic defaults.
    """
    latin = DEFAULT_LATIN_FONT
    cjk = DEFAULT_CJK_FONT
    for name in names:
        mapped_latin = map_latin_font(name)
        if mapped_latin:
            latin = mapped_latin
            break
    for name in names:
        mapped_cjk = map_cjk_font(name)
        if mapped_cjk:
            cjk = mapped_cjk
            break
    return latin, cjk


def _set_run_fonts(r_pr, latin: str, cjk: str) -> None:
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = r_pr.makeelement(qn("w:rFonts"), {})
        r_pr.insert(0, r_fonts)
    # Theme attributes would override explicit names; drop them.
    for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        if r_fonts.get(qn(attr)) is not None:
            del r_fonts.attrib[qn(attr)]
    r_fonts.set(qn("w:ascii"), latin)
    r_fonts.set(qn("w:hAnsi"), latin)
    r_fonts.set(qn("w:eastAsia"), cjk)
    r_fonts.set(qn("w:cs"), latin)


def _normalize_runs(document: Document) -> None:
    """Normalize every run in the body (paragraphs, tables, nested tables)."""
    for run in document.element.body.iter(qn("w:r")):
        r_pr = run.find(qn("w:rPr"))
        if r_pr is None:
            r_pr = run.makeelement(qn("w:rPr"), {})
            run.insert(0, r_pr)
        r_fonts = r_pr.find(qn("w:rFonts"))
        names: list[str | None] = []
        if r_fonts is not None:
            names = [
                r_fonts.get(qn("w:ascii")),
                r_fonts.get(qn("w:hAnsi")),
                r_fonts.get(qn("w:eastAsia")),
            ]
        latin, cjk = resolve_run_fonts(names)
        _set_run_fonts(r_pr, latin, cjk)


def _normalize_style_defaults(document: Document) -> None:
    """Ensure document defaults and the Normal style use safe fonts.

    Runs without explicit fonts inherit from these, so CJK text must not fall
    back to a theme font that the reader cannot resolve.
    """
    styles_element = document.styles.element
    r_pr_nodes = []

    doc_defaults = styles_element.find(qn("w:docDefaults"))
    if doc_defaults is not None:
        r_pr_default = doc_defaults.find(qn("w:rPrDefault"))
        if r_pr_default is not None:
            r_pr = r_pr_default.find(qn("w:rPr"))
            if r_pr is None:
                r_pr = r_pr_default.makeelement(qn("w:rPr"), {})
                r_pr_default.append(r_pr)
            r_pr_nodes.append(r_pr)

    for style in styles_element.findall(qn("w:style")):
        if style.get(qn("w:styleId")) != "Normal":
            continue
        r_pr = style.find(qn("w:rPr"))
        if r_pr is None:
            r_pr = style.makeelement(qn("w:rPr"), {})
            style.append(r_pr)
        r_pr_nodes.append(r_pr)

    for r_pr in r_pr_nodes:
        r_fonts = r_pr.find(qn("w:rFonts"))
        names: list[str | None] = []
        if r_fonts is not None:
            names = [
                r_fonts.get(qn("w:ascii")),
                r_fonts.get(qn("w:hAnsi")),
                r_fonts.get(qn("w:eastAsia")),
            ]
        latin, cjk = resolve_run_fonts(names)
        _set_run_fonts(r_pr, latin, cjk)


def _relax_cramped_exact_line_spacing(document: Document) -> None:
    """Convert exact line heights smaller than the font size to atLeast.

    pdf2docx derives exact line heights from PDF line bounding boxes. After a
    font substitution those heights can be smaller than the glyphs, clipping
    or overlapping text. ``atLeast`` keeps the intended spacing while letting
    the line grow to fit the actual font.
    """
    for paragraph in document.element.body.iter(qn("w:p")):
        p_pr = paragraph.find(qn("w:pPr"))
        if p_pr is None:
            continue
        spacing = p_pr.find(qn("w:spacing"))
        if spacing is None or spacing.get(qn("w:lineRule")) != "exact":
            continue
        line = spacing.get(qn("w:line"))
        if line is None:
            continue
        try:
            line_twips = int(line)
        except ValueError:
            continue
        max_half_points = 0
        for run in paragraph.iter(qn("w:r")):
            r_pr = run.find(qn("w:rPr"))
            if r_pr is None:
                continue
            sz = r_pr.find(qn("w:sz"))
            if sz is None:
                continue
            try:
                max_half_points = max(max_half_points, int(sz.get(qn("w:val"))))
            except (TypeError, ValueError):
                continue
        # half-points -> twips: sz/2 pt * 20 = sz * 10
        if max_half_points and line_twips < max_half_points * 10:
            spacing.set(qn("w:lineRule"), "atLeast")


def normalize_docx(docx_bytes: bytes) -> bytes:
    """Normalize fonts and unsafe exact line heights in a DOCX file.

    Only ``w:rFonts`` declarations and cramped exact line heights are changed.
    Text, bold/italic, font size, color, tables and structure are preserved.
    """
    document = Document(io.BytesIO(docx_bytes))
    _normalize_runs(document)
    _normalize_style_defaults(document)
    _relax_cramped_exact_line_spacing(document)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _is_valid_docx(docx_bytes: bytes) -> bool:
    """Return True when the bytes form a readable DOCX package."""
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
            if archive.testzip() is not None:
                return False
        document = Document(io.BytesIO(docx_bytes))
        return document.element.body is not None
    except Exception:
        return False


def normalize_docx_with_status(docx_bytes: bytes) -> tuple[bytes, bool]:
    """Normalize a DOCX and report whether font repair succeeded.

    Font repair is an enhancement, not part of the conversion contract: a
    valid DOCX must stay downloadable even when repair fails.

    Returns:
        ``(data, normalized)``. ``normalized`` is True when the repaired
        document was produced. When repair fails but the original output is a
        valid DOCX, the original bytes are returned with ``normalized=False``
        so the caller can still offer the file with a warning.

    Raises:
        ConversionFailedError: repair failed and the original output is not a
            readable DOCX package either, so no safe file can be returned.
    """
    try:
        normalized = normalize_docx(docx_bytes)
        if not _is_valid_docx(normalized):
            raise ValueError("normalized DOCX is not readable")
        original = Document(io.BytesIO(docx_bytes))
        repaired = Document(io.BytesIO(normalized))
        original_text = [
            (node.tag, node.text) for node in original.element.body.iter()
            if node.tag in {qn("w:t"), qn("w:tab"), qn("w:br")}
        ]
        repaired_text = [
            (node.tag, node.text) for node in repaired.element.body.iter()
            if node.tag in {qn("w:t"), qn("w:tab"), qn("w:br")}
        ]
        if original_text != repaired_text:
            raise ValueError("font normalization changed document content")
        return normalized, True
    except Exception as error:
        LOGGER.exception("DOCX font normalization failed; falling back to original output")
        if not _is_valid_docx(docx_bytes):
            raise ConversionFailedError from error
        return docx_bytes, False


__all__ = [
    "DEFAULT_CJK_FONT",
    "DEFAULT_LATIN_FONT",
    "map_cjk_font",
    "map_latin_font",
    "normalize_docx",
    "normalize_docx_with_status",
    "resolve_run_fonts",
    "strip_subset_prefix",
]
