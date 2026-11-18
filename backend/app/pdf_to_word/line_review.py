"""Optical checks for severely shortened OCR lines and bounded local review."""
import cv2
import numpy as np

from .ocr import LineCandidate, LineReview

MAX_LOCAL_RETRIES = 4
MAX_SHORT_OUTPUT_CHARS = 12


def line_evidence(image, text):
    """Use occupied ink, not empty span width, to avoid flagging spaced text."""
    count = len("".join(text.split()))
    height, width = image.shape[:2]
    if count > MAX_SHORT_OUTPUT_CHARS or height < 8 or width / height < 8:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    border = np.concatenate((gray[0], gray[-1], gray[:, 0], gray[:, -1]))
    dark = float(np.mean(border < 100)) >= 0.8
    normalized = 255 - gray if dark else gray
    _, ink = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    # Exclude long rules that could otherwise make a short underlined word
    # appear to occupy a whole line.
    rules = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(width // 3, height * 4), 1)),
    )
    ink = cv2.subtract(ink, rules)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    valid = [
        index for index, (_, _, _, component_height, area) in enumerate(stats[1:], 1)
        if component_height >= max(4, height * 0.25) and area >= max(4, height * 0.1)
    ]
    if len(valid) < 12:
        return None
    mask = np.isin(labels, valid)
    rows = np.flatnonzero(mask.any(axis=1))
    if not len(rows):
        return None
    ink_height = int(rows[-1] - rows[0] + 1)
    occupied_columns = int(mask.any(axis=0).sum())
    glyph_units = occupied_columns / max(ink_height, 1)
    if ink_height < 6 or glyph_units < 12 or count > glyph_units / 3:
        return None
    return {"dark_background": dark, "glyph_units": glyph_units,
            "components": len(valid), "output_characters": count}


def _plausible_candidate(text, score, initial_text, glyph_units):
    """Require optical length recovery AND usable confidence, not just length."""
    length = len("".join(text.split()))
    initial_length = len("".join(initial_text.split()))
    return (
        length >= max(12, initial_length * 3)
        and glyph_units * 0.8 <= length <= glyph_units * 1.8 + 4
        and 0.8 <= score <= 1.0
    )


def _initial_orientation(base, classified, index):
    """Record the actual classifier decision; its confidence is not correctness."""
    try:
        label, score = classified.cls_res[index]
        threshold = float(base.cfg.Cls.cls_thresh)
        return (180 if label == "180" and score > threshold else 0), float(score)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None, None


class ReviewedEngine:
    """Keep RapidOCR detection/cropping intact, reviewing only optical outliers."""

    def __init__(self, base):
        self.base = base

    def __getattr__(self, name):
        return getattr(self.base, name)

    def __call__(self, image_bytes):
        original = self.base.load_img(image_bytes)
        image, operations = self.base.preprocess_img(original)
        detected, classified, recognized, crops = self.base.run_ocr_steps(image, operations)
        texts = getattr(recognized, "txts", None)
        reviews = {}
        if texts is not None and len(crops) == len(texts):
            texts = list(texts)
            scores = list(recognized.scores)
            retries = 0
            for index, (source, text) in enumerate(zip(crops, texts)):
                evidence = line_evidence(source, text)
                if evidence is None:
                    continue
                encoded, png = cv2.imencode(".png", source)
                if not encoded:
                    # A missing source image must never accompany a success.
                    raise RuntimeError("cannot preserve suspicious OCR region")
                candidate = None
                accepted = False
                retried = False
                attempts = 0
                candidates = []
                selected_rotation = None
                initial_rotation, orientation_score = _initial_orientation(self.base, classified, index)
                dark = evidence["dark_background"]
                # For white backgrounds the classified direction has already
                # been recognized. Evaluate only its opposite, directly through
                # Rec so the same faulty classifier cannot flip it back.
                # Polarity normalization changes the input, so evaluate both
                # normalized directions instead of assuming its orientation.
                rotations = (0, 180) if dark or initial_rotation is None else (180 - initial_rotation,)
                method = "polarity+orientation" if dark else "orientation"
                reason = "short output contradicts occupied ink"
                if retries + len(rotations) <= MAX_LOCAL_RETRIES:
                    retried = True
                    normalized = cv2.bitwise_not(source) if dark else source
                    complete = True
                    for rotation in rotations:
                        retries += 1
                        attempts += 1
                        try:
                            oriented = cv2.rotate(normalized, cv2.ROTATE_180) if rotation else normalized
                            local = self.base.recognize_txt([oriented])
                            candidate = local.txts[0]
                            score = float(local.scores[0])
                            candidates.append(LineCandidate(
                                candidate, score, rotation, dark,
                                _plausible_candidate(candidate, score, text, evidence["glyph_units"]),
                            ))
                        except Exception:
                            # Failed comparisons do not authorize choosing the
                            # one surviving result; retain the initial + source.
                            complete = False
                    eligible = [item for item in candidates if item.eligible]
                    if complete and eligible and len({item.text for item in eligible}) == 1:
                        selected = max(eligible, key=lambda item: item.score)
                        candidate = selected.text
                        texts[index] = candidate
                        scores[index] = selected.score
                        selected_rotation = selected.rotation
                        accepted = True
                    elif not complete:
                        reason = "local direction comparison failed"
                    elif len({item.text for item in eligible}) > 1:
                        reason = "both directions have conflicting plausible text"
                    else:
                        reason = "neither local direction is optically plausible"
                else:
                    reason = "local recognition budget exhausted"
                reviews[index] = LineReview(
                    original_text=text,
                    original_score=float(recognized.scores[index]),
                    image=png.tobytes(),
                    retried=retried,
                    recovered=accepted,
                    candidate_text=candidate,
                    reason=reason,
                    method=method,
                    attempts=attempts,
                    initial_rotation=initial_rotation,
                    orientation_score=orientation_score,
                    selected_rotation=selected_rotation,
                    candidates=tuple(candidates),
                )
            recognized.txts = tuple(texts)
            recognized.scores = tuple(scores)
        else:
            texts = ()
        # Keep detected-but-empty reviewed regions. RapidOCR otherwise removes
        # them before callers can preserve the source or report uncertainty.
        preserve_empty = any(not texts[index].strip() for index in reviews)
        original_boxes = None
        if preserve_empty and getattr(detected, "boxes", None) is not None:
            original_boxes = np.asarray(detected.boxes).copy()
        result = self.base.build_final_output(original, detected, classified, recognized, crops, operations)
        valid = [index for index, text in enumerate(texts) if text.strip() or index in reviews]
        if original_boxes is not None:
            from rapidocr.utils.process_img import map_boxes_to_original

            height, width = original.shape[:2]
            mapped = map_boxes_to_original(original_boxes, operations, height, width)
            result.boxes = mapped[valid]
            result.txts = tuple(texts[index] for index in valid)
            result.scores = tuple(scores[index] for index in valid)
        result.line_reviews = tuple(reviews.get(index) for index in valid)
        return result

