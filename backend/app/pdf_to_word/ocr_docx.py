"""Content-first OCR output with exact text checks after serialization."""

import io
from copy import deepcopy

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from PIL import Image

from .converter import ConversionOutcome, convert_pdf_to_docx
from .errors import ConversionFailedError
from .font_normalizer import normalize_docx_with_status
from .ocr import OcrDocument


def paragraph_texts(document) -> list[str]:
    """Include tables/hyperlinks in body order, preserving tabs and line breaks."""
    texts = []
    for paragraph in document.element.body.iter(qn("w:p")):
        parts = []
        for node in paragraph.iter():
            if node.tag == qn("w:t"):
                parts.append(node.text or "")
            elif node.tag == qn("w:tab"):
                parts.append("\t")
            elif node.tag == qn("w:br") and node.get(qn("w:type")) != "page":
                parts.append("\n")
        texts.append("".join(parts))
    return texts


def _append_native_page(target, source) -> None:
    """Import the image and hyperlink relationships emitted by pdf2docx."""
    relationship_ids = {}
    for child in source.element.body:
        if child.tag == qn("w:sectPr"):
            continue
        element = deepcopy(child)
        for node in element.iter():
            for attribute, value in list(node.attrib.items()):
                if not attribute.startswith("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"):
                    continue
                if value not in relationship_ids:
                    relationship = source.part.rels[value]
                    if relationship.is_external:
                        new_id = target.part.relate_to(relationship.target_ref, relationship.reltype, is_external=True)
                    elif relationship.reltype.endswith("/image"):
                        new_id, _ = target.part.get_or_add_image(io.BytesIO(relationship.target_part.blob))
                    else:
                        raise ConversionFailedError
                    relationship_ids[value] = new_id
                node.set(attribute, relationship_ids[value])
        target.element.body.insert_element_before(element, "w:sectPr")
    section = target.sections[-1]._sectPr
    section.clear()
    for child in source.sections[-1]._sectPr:
        section.append(deepcopy(child))


def build_ocr_docx(prepared: OcrDocument) -> ConversionOutcome:
    document = Document()
    expected = []
    fonts_normalized = True
    try:
        for index, page in enumerate(prepared.pages):
            if index:
                document.add_section(WD_SECTION_START.NEW_PAGE)
                expected.append("")
            if page.native_pdf is not None:
                outcome = convert_pdf_to_docx(page.native_pdf)
                fonts_normalized = fonts_normalized and outcome.fonts_normalized
                native = Document(io.BytesIO(outcome.docx))
                _append_native_page(document, native)
                expected.extend(paragraph_texts(native))
                continue
            section = document.sections[-1]
            section.page_width = Inches(8.27)
            section.page_height = Inches(11.69)
            section.left_margin = section.right_margin = Inches(0.65)
            section.top_margin = section.bottom_margin = Inches(0.65)
            for line in page.lines:
                paragraph = document.add_paragraph()
                run = paragraph.add_run(line.text)
                run.font.size = Pt(11)
                expected.append(line.text.replace("\r", "\n"))
                if line.unresolved_review:
                    review = line.review
                    note = "此行识别存疑，请对照原图复核。初次识别：" + (review.original_text or "（未识别出文字）")
                    if hasattr(document, "add_comment"):
                        document.add_comment(run, text=note, author="Personal Toolbox")
                    else:
                        # Compatibility with the older python-docx versions
                        # allowed by pdf2docx's declared dependency.
                        document.add_paragraph(note)
                        expected.append(note)
                    with Image.open(io.BytesIO(review.image)) as source:
                        width, height = source.size
                    factor = min(6.9 / width, 2.0 / height)
                    document.add_paragraph().add_run().add_picture(
                        io.BytesIO(review.image), width=Inches(width * factor), height=Inches(height * factor)
                    )
                    expected.append("")
            if page.fallback_image is not None:
                with Image.open(io.BytesIO(page.fallback_image)) as image:
                    width, height = image.size
                factor = min(6.9 / width, 9.8 / height)
                document.add_paragraph().add_run().add_picture(
                    io.BytesIO(page.fallback_image), width=Inches(width * factor), height=Inches(height * factor)
                )
                expected.append("")
        buffer = io.BytesIO()
        document.save(buffer)
        original = buffer.getvalue()
        # Word represents CR as a line break. Verify text before the optional
        # enhancement, then retain this valid original if enhancement changes it.
        if paragraph_texts(Document(io.BytesIO(original))) != expected:
            raise ConversionFailedError
        normalized, normalized_ok = normalize_docx_with_status(original)
        if paragraph_texts(Document(io.BytesIO(normalized))) != expected:
            normalized, normalized_ok = original, False
        return ConversionOutcome(normalized, fonts_normalized and normalized_ok, prepared.status)
    except ConversionFailedError:
        raise
    except Exception as error:
        raise ConversionFailedError from error
