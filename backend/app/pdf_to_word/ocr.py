"""Recognize image regions while retaining every nonempty engine string."""

import math
import threading
from dataclasses import dataclass, replace

import pymupdf

from .errors import (
    OcrFailedError,
    OcrPageLimitError,
    OcrUnavailableError,
    PdfResourceLimitError,
)

OCR_DPI = 200
MAX_RENDER_SIDE = 3500
MAX_RENDER_PIXELS = 8_000_000
MAX_TOTAL_RENDER_PIXELS = 80_000_000
MAX_OCR_PAGES = 10
LOW_CONFIDENCE = 0.5
NATIVE_OVERLAP_RATIO = 0.5


@dataclass(frozen=True)
class LineCandidate:
    text: str
    score: float
    rotation: int
    polarity_inverted: bool
    eligible: bool


@dataclass(frozen=True)
class LineReview:
    original_text: str
    original_score: float
    image: bytes
    reason: str
    retried: bool = False
    recovered: bool = False
    candidate_text: str | None = None
    method: str | None = None
    attempts: int = 0
    initial_rotation: int | None = None
    orientation_score: float | None = None
    selected_rotation: int | None = None
    candidates: tuple[LineCandidate, ...] = ()


@dataclass(frozen=True)
class OcrLine:
    text: str
    bbox: tuple[float, float, float, float]
    score: float | None = 1.0
    geometry_valid: bool = True
    review: LineReview | None = None

    @property
    def unresolved_review(self) -> bool:
        """Keep accepted recovery evidence internal; unresolved lines need review."""
        return self.review is not None and not self.review.recovered

    @property
    def uncertain(self) -> bool:
        return self.score is None or self.score < LOW_CONFIDENCE or not self.geometry_valid or self.unresolved_review


@dataclass(frozen=True)
class OcrPage:
    lines: tuple[OcrLine, ...] = ()
    native_pdf: bytes | None = None
    fallback_image: bytes | None = None
    attempted: bool = False
    failed_regions: int = 0
    empty_regions: int = 0
    duplicate_lines: int = 0
    rejected_lines: tuple[OcrLine, ...] = ()

    @property
    def partial(self) -> bool:
        return bool(
            self.failed_regions
            or self.empty_regions
            or self.rejected_lines
            or any(line.uncertain for line in self.lines)
        )


@dataclass(frozen=True)
class OcrDocument:
    pages: tuple[OcrPage, ...]

    @property
    def needed(self) -> bool:
        return any(page.attempted for page in self.pages)

    @property
    def status(self) -> str:
        if any(page.partial for page in self.pages):
            return "partial"
        return "applied" if self.needed else "not-needed"


_engine: object | None = None
_engine_lock = threading.Lock()
_recognition_lock = threading.Lock()


def _get_engine() -> object:
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr import RapidOCR
                from .line_review import ReviewedEngine

                # Retain low-score output. Uncertainty is reported to callers.
                base = RapidOCR(
                    params={
                        "Global.text_score": 0.0,
                        "Global.max_side_len": MAX_RENDER_SIDE,
                        # PP-OCRv6 predictions change when a neighboring line
                        # changes batch padding width. Normalize each line
                        # independently so page composition cannot alter it.
                        "Rec.rec_batch_num": 1,
                        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                    }
                )
                _engine = ReviewedEngine(base)
            except Exception as error:
                raise OcrUnavailableError from error
        return _engine


def reset_engine() -> None:
    global _engine
    with _engine_lock:
        _engine = None


def ocr_image(image_bytes: bytes, *, engine: object | None = None) -> list[OcrLine]:
    recognizer = engine if engine is not None else _get_engine()
    try:
        with _recognition_lock:
            result = recognizer(image_bytes)  # type: ignore[operator]
    except Exception as error:
        raise OcrFailedError from error

    texts = getattr(result, "txts", None)
    boxes = getattr(result, "boxes", None)
    scores = getattr(result, "scores", None)
    reviews = getattr(result, "line_reviews", ())
    texts = () if texts is None else texts
    boxes = () if boxes is None else boxes
    scores = () if scores is None else scores
    lines = []
    for index, text in enumerate(texts):
        review = reviews[index] if index < len(reviews) else None
        if not text and review is None:
            continue
        valid = True
        try:
            points = boxes[index]
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            bbox = (min(xs), min(ys), max(xs), max(ys))
            valid = (
                all(math.isfinite(value) for value in bbox)
                and bbox[2] > bbox[0]
                and bbox[3] > bbox[1]
            )
        except (IndexError, TypeError, ValueError):
            valid = False
        if not valid:
            # Keep text in engine order if geometry is unavailable.
            bbox = (0.0, float(index), 1.0, float(index + 1))
        score = None
        if index < len(scores) and scores[index] is not None:
            candidate = float(scores[index])
            if math.isfinite(candidate) and 0 <= candidate <= 1:
                score = candidate
        lines.append(OcrLine(text, bbox, score, valid, review))
    if any(not line.geometry_valid for line in lines):
        return lines
    return _sort_reading_order(lines)


def _sort_reading_order(lines: list[OcrLine]) -> list[OcrLine]:
    ordered = sorted(lines, key=lambda line: (line.bbox[1], line.bbox[0]))
    rows: list[list[OcrLine]] = []
    for line in ordered:
        height = max(line.bbox[3] - line.bbox[1], 1.0)
        if rows:
            previous = rows[-1][0]
            tolerance = 0.6 * max(height, previous.bbox[3] - previous.bbox[1])
            if abs(line.bbox[1] - previous.bbox[1]) <= tolerance:
                rows[-1].append(line)
                continue
        rows.append([line])
    return [line for row in rows for line in sorted(row, key=lambda item: item.bbox[0])]


def _native_lines(page) -> list[OcrLine]:
    lines = []
    for span in page.get_texttrace():
        if span.get("type") == 3 or span.get("opacity", 1) == 0:
            continue
        text = "".join(chr(char[0]) for char in span.get("chars", ()))
        if text:
            lines.append(OcrLine(text, tuple(span["bbox"])))
    return lines


def _image_rects(page) -> list[tuple[float, float, float, float]]:
    # Includes inline images and every occurrence of a reused image, without
    # decoding the original image. No area threshold discards small text.
    rects = []
    for image in page.get_image_info():
        rect = pymupdf.Rect(image["bbox"]) & page.rect
        if not rect.is_empty and tuple(rect) not in rects:
            rects.append(tuple(rect))
    return rects


def _intersection_ratio(rect, others) -> float:
    area = pymupdf.Rect(rect).get_area()
    if area <= 0:
        return 0.0
    ratios = (
        (pymupdf.Rect(rect) & pymupdf.Rect(other)).get_area() / area
        for other in others
    )
    return max(ratios, default=0.0)


def _is_duplicate(line: OcrLine, existing: list[OcrLine]) -> bool:
    if not line.geometry_valid:
        return False
    # Geometry and exact content must both agree. Spaces can distinguish
    # numeric fields, so they are not normalized even for duplicate detection.
    return bool(line.text) and any(
        line.text == other.text
        and _intersection_ratio(line.bbox, [other.bbox]) >= NATIVE_OVERLAP_RATIO
        for other in existing
    )


def _xml_text_supported(text: str) -> bool:
    return all(
        character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
        for character in text
    )


@dataclass
class RenderBudget:
    pixels: int = 0

    def render(self, page, *, clip=None, dpi: int = OCR_DPI) -> tuple[bytes, float, float]:
        rect = (pymupdf.Rect(clip) & page.rect) if clip is not None else page.rect
        if rect.is_empty or not all(math.isfinite(value) for value in rect):
            raise PdfResourceLimitError
        # Headroom accounts for MuPDF integer bounding-box rounding.
        scale = min(
            dpi / 72,
            (MAX_RENDER_SIDE - 2) / max(rect.width, rect.height),
            math.sqrt((MAX_RENDER_PIXELS - 4 * MAX_RENDER_SIDE) / rect.get_area()),
        )
        width = math.ceil(rect.width * scale) + 2
        height = math.ceil(rect.height * scale) + 2
        pixels = width * height
        if pixels > MAX_RENDER_PIXELS or self.pixels + pixels > MAX_TOTAL_RENDER_PIXELS:
            raise PdfResourceLimitError
        self.pixels += pixels
        pixmap = page.get_pixmap(clip=clip, matrix=pymupdf.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png"), rect.width / pixmap.width, rect.height / pixmap.height


def recognize_pdf(
    pdf_bytes: bytes,
    *,
    engine: object | None = None,
    max_pages: int = MAX_OCR_PAGES,
) -> OcrDocument:
    """Collect page content and failure information for direct DOCX output.

    An empty region is uncertain, not evidence that all text was detected.
    Detection omissions and confident model mistakes need a reference transcript.
    """
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as source:
        plan = []
        for page in source:
            native = _native_lines(page)
            images = _image_rects(page)
            # Rendering also handles outlined/vector text with no image objects.
            regions = images if native else [tuple(page.rect)]
            plan.append((native, regions))
        if sum(bool(regions) for _, regions in plan) > max_pages:
            raise OcrPageLimitError

        budget = RenderBudget()
        pages = []
        for index, (native, regions) in enumerate(plan):
            page = source[index]
            if not regions:
                with pymupdf.open() as single:
                    single.insert_pdf(source, from_page=index, to_page=index)
                    pages.append(OcrPage(native_pdf=single.tobytes()))
                continue
            lines = list(native)
            rejected = []
            failed = empty = duplicates = 0
            for rect in regions:
                image, scale_x, scale_y = budget.render(page, clip=rect)
                try:
                    recognized = ocr_image(image, engine=engine)
                except OcrFailedError:
                    failed += 1
                    continue
                if not recognized:
                    empty += 1
                for line in recognized:
                    if not _xml_text_supported(line.text):
                        # XML cannot represent this string. Keep its raw value
                        # in the result, report partial, and attach the source.
                        rejected.append(line)
                        continue
                    x0, y0, x1, y1 = line.bbox
                    positioned = replace(
                        line,
                        bbox=(
                            x0 * scale_x + rect[0],
                            y0 * scale_y + rect[1],
                            x1 * scale_x + rect[0],
                            y1 * scale_y + rect[1],
                        ),
                    )
                    if _is_duplicate(positioned, lines):
                        duplicates += 1
                        if positioned.review is not None:
                            # Keep one text line, but retain review evidence
                            # even when an overlapping native line agrees.
                            duplicate_index = next(
                                index for index, other in enumerate(lines)
                                if _is_duplicate(positioned, [other])
                            )
                            if lines[duplicate_index].review is None:
                                lines[duplicate_index] = replace(
                                    lines[duplicate_index], review=positioned.review
                                )
                    else:
                        lines.append(positioned)
            fallback = None
            if failed or empty or rejected:
                fallback, _, _ = budget.render(page)
            if all(line.geometry_valid for line in lines):
                lines = _sort_reading_order(lines)
            pages.append(
                OcrPage(
                    tuple(lines),
                    fallback_image=fallback,
                    attempted=True,
                    failed_regions=failed,
                    empty_regions=empty,
                    duplicate_lines=duplicates,
                    rejected_lines=tuple(rejected),
                )
            )
        return OcrDocument(tuple(pages))
