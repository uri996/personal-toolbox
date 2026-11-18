"""Focused real-model probes for collapsed long lines, using fictional text."""
import io
import json
import time

import cv2
import numpy as np
import pymupdf
from PIL import Image, ImageFilter

from app.pdf_to_word import ocr
from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts
from docx import Document
from tests.pdf_to_word.quality_metrics import compact, character_errors
from tests.pdf_to_word.synthetic_pdfs import _image_only_pdf
from .recognition_quality import TracedEngine

LONG_LINES = (
    "甲说：“请把窗边的蓝色盒子放回书架，再按纸上的说明检查每一盏灯。”",
    "乙答：“我会先检查标签，再核对编号，最后确认所有条目都没有遗漏。”",
)


def fixture(variant):
    regions = []
    with pymupdf.open() as source:
        page = source.new_page()
        font = pymupdf.Font(fontname="china-s")
        for index, spacing in enumerate((1.6, 1.1, 1.0, 0.95, 0.9)):
            top = 90 + index * 118
            writer = pymupdf.TextWriter(page.rect)
            for line_index, text in enumerate(LONG_LINES):
                assert font.text_length(text, fontsize=11) < 495
                writer.append((48, top + line_index * 11 * spacing), text, font=font, fontsize=11)
            writer.write_text(page)
            regions.append({"name": f"spacing-{spacing}", "expected": list(LONG_LINES),
                            "bbox": [40, top - 15, 560, top + 34]})
        writer = pymupdf.TextWriter(page.rect)
        for index, text in enumerate(("OK", "Good day", "2026", "1          2          3", "A          B          C")):
            y = 720 + index * 18
            writer.append((48, y), text, font=font, fontsize=11)
            regions.append({"name": f"control-{index}", "expected": [text], "bbox": [40, y - 15, 560, y + 4]})
        writer.write_text(page)
        assert compact(page.get_text()) == compact("".join(text for region in regions for text in region["expected"]))
        pixmap = page.get_pixmap(dpi=110 if variant == "low-dpi" else 150, alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        if variant == "blur":
            image = image.filter(ImageFilter.GaussianBlur(0.45))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=70 if variant == "compressed" else 90)
    return _image_only_pdf([buffer.getvalue()]), regions


def page_probe(output):
    output.mkdir(parents=True, exist_ok=True)
    traced = TracedEngine(ocr._get_engine(), output)
    report = {}
    for variant in ("clear", "low-dpi", "blur", "compressed"):
        data, regions = fixture(variant)
        start = time.perf_counter()
        prepared = ocr.recognize_pdf(data, engine=traced)
        result = build_ocr_docx(prepared)
        final = paragraph_texts(Document(io.BytesIO(result.docx)))
        assert final == [line.text for line in prepared.pages[0].lines]
        frame = traced.frames[-1]
        height, width = frame["page_size"][:2]
        evaluated = []
        for region in regions:
            x0, y0, x1, y1 = region["bbox"]
            observed = []
            boxes = []
            for index, (polygon, text) in enumerate(zip(frame["boxes"], frame["texts"])):
                points = np.asarray(polygon)
                cy = float(points[:, 1].mean()) * 842 / height
                if y0 <= cy <= y1:
                    observed.append(text)
                    boxes.append(index)
            expected = compact("".join(region["expected"]))
            actual = compact("".join(observed))
            errors = character_errors(expected, actual)
            item = {**region, "observed": observed, "box_ids": boxes, "cer": errors.cer}
            evaluated.append(item)
            print(variant, region["name"], len(expected), len(actual), round(errors.cer, 4), repr(observed), flush=True)
        report[variant] = {"seconds": time.perf_counter() - start, "regions": evaluated, "frame": frame}
    (output / "probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")



def clear_crop(text, fontname="china-s", size=9, margin=2):
    font = pymupdf.Font(fontname=fontname)
    with pymupdf.open() as source:
        width = font.text_length(text, fontsize=size) + 24
        page = source.new_page(width=width, height=size * 3)
        writer = pymupdf.TextWriter(page.rect)
        writer.append((12, size * 1.5), text, font=font, fontsize=size)
        writer.write_text(page)
        assert page.get_text().replace("\n", "") == text
        pixmap = page.get_pixmap(dpi=150, alpha=False)
        image = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width, 3)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    ys, xs = np.where(gray < 150)
    ink = image[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return cv2.copyMakeBorder(ink[:, :, ::-1].copy(), margin, margin, margin, margin,
                              cv2.BORDER_CONSTANT, value=(255, 255, 255))


def line_probe(output):
    from tests.pdf_to_word.recognition_samples import DIALOGUE

    output.mkdir(parents=True, exist_ok=True)
    engine = ocr._get_engine()
    samples = []
    for font in ("china-s", "china-ss"):
        for size in (9, 12):
            for margin in (0, 3):
                for index, text in enumerate(DIALOGUE):
                    crop = clear_crop(text, font, size, margin)
                    samples.append((f"{font}-{size}-{margin}-{index}", text, crop))
    classified, classes = engine.cls_and_rotate([item[2] for item in samples])
    report = {"orientation": [], "length": []}
    for (name, text, original), rotated, (label, score) in zip(samples, classified, classes.cls_res):
        if label != "180":
            continue
        baseline = engine.recognize_txt([original])
        altered = engine.recognize_txt([rotated])
        item = {
            "name": name, "expected": text, "class": label, "class_score": float(score),
            "rotated": bool(not np.array_equal(original, rotated)),
            "upright": baseline.txts[0], "classified": altered.txts[0],
            "upright_score": float(baseline.scores[0]), "classified_score": float(altered.scores[0]),
        }
        report["orientation"].append(item)
        cv2.imwrite(str(output / f"orientation-{name}.png"), original)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    base = LONG_LINES[0]
    for count in (1, 2, 3, 4):
        text = base * count
        crop = clear_crop(text)
        result = engine.recognize_txt([crop])
        observed = result.txts[0]
        item = {"expected": text, "observed": observed, "score": float(result.scores[0]),
                "shape": list(crop.shape), "cer": character_errors(compact(text), compact(observed)).cer}
        report["length"].append(item)
        cv2.imwrite(str(output / f"length-{count}.png"), crop)
        print("length", len(text), len(observed), json.dumps(item, ensure_ascii=False), flush=True)
    (output / "line-probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("orientation_samples", len(samples), "nonzero_angle_predictions", len(report["orientation"]), flush=True)


def main(output, *, line_crops=False, styles=False, evaluate=False, no_review=False):
    if evaluate:
        return evaluate_fixed_samples(output, no_review=no_review)
    if styles:
        return style_probe(output)
    if line_crops:
        return line_probe(output)
    return page_probe(output)


def style_probe(output):
    variants = [
        ("normal", (0, 0, 0), None, None),
        ("inverted", (1, 1, 1), (0, 0, 0), None),
        ("gray-paper", (0, 0, 0), (0.75, 0.75, 0.75), None),
        ("light-text", (0.6, 0.6, 0.6), None, None),
        ("underline", (0, 0, 0), None, 1),
        ("ruled-paper", (0, 0, 0), None, -3),
    ]
    regions = []
    with pymupdf.open() as source:
        page = source.new_page()
        font = pymupdf.Font(fontname="china-s")
        for index, (name, color, fill, ruling) in enumerate(variants):
            baseline = 90 + index * 105
            if fill is not None:
                page.draw_rect(pymupdf.Rect(43, baseline - 14, 545, baseline + 4), fill=fill, color=fill)
            writer = pymupdf.TextWriter(page.rect)
            writer.append((48, baseline), LONG_LINES[0], font=font, fontsize=11)
            writer.write_text(page, color=color)
            if ruling is not None:
                page.draw_line((43, baseline + ruling), (545, baseline + ruling), color=(0.45, 0.45, 0.45), width=0.3)
            regions.append({"name": name, "expected": LONG_LINES[0], "y0": baseline - 18, "y1": baseline + 15})
        pixmap = page.get_pixmap(dpi=150, alpha=False)
        data = _image_only_pdf([pixmap.tobytes("jpeg", jpg_quality=90)])
    traced = TracedEngine(ocr._get_engine(), output)
    prepared = ocr.recognize_pdf(data, engine=traced)
    frame = traced.frames[-1]
    height, width = frame["page_size"][:2]
    report = []
    for region in regions:
        texts = []
        for polygon, text in zip(frame["boxes"], frame["texts"]):
            cy = float(np.asarray(polygon)[:, 1].mean()) * 842 / height
            if region["y0"] <= cy <= region["y1"]:
                texts.append(text)
        observed = "".join(texts)
        item = {**region, "observed": observed, "cer": character_errors(compact(region["expected"]), compact(observed)).cer}
        report.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    candidate_checks = []
    for index, crop in enumerate(frame["crops"]):
        if len(compact(crop["text"])) > 5:
            continue
        original = cv2.imread(str(output / crop["crop"]))
        if frame["classification"][index]["rotated"]:
            original = cv2.rotate(original, cv2.ROTATE_180)
        for name, candidate in [("original-orientation", original), ("polarity-normalized", 255 - original)]:
            classified, angles = traced.classify([candidate])
            result = traced.recognize(classified)
            candidate_checks.append({"variant": name, "text": result.txts[0], "score": float(result.scores[0]),
                                     "angle": str(angles.cls_res[0]), "shape": list(candidate.shape)})
    print("local_candidates", json.dumps(candidate_checks, ensure_ascii=False), flush=True)
    (output / "style-probe.json").write_text(json.dumps({"regions": report, "frame": frame, "candidates": candidate_checks}, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_fixed_samples(output, *, no_review=False):
    from tests.pdf_to_word.catastrophic_samples import severe_sample

    folder = output / ("evaluation-before" if no_review else "evaluation-after")
    folder.mkdir(parents=True, exist_ok=True)
    engine = ocr._get_engine()
    if no_review:
        engine = getattr(engine, "base", engine)
    traced = TracedEngine(engine, folder)
    report = {}
    for variant in ("clear", "low-dpi", "compressed", "dark-gray"):
        sample, regions = severe_sample(variant)
        start = time.perf_counter()
        prepared = ocr.recognize_pdf(sample.pdf, engine=traced)
        outcome = build_ocr_docx(prepared)
        (folder / f"{variant}.docx").write_bytes(outcome.docx)
        final = paragraph_texts(Document(io.BytesIO(outcome.docx)))
        expected_output = []
        for line in prepared.pages[0].lines:
            expected_output.append(line.text)
            if line.unresolved_review:
                expected_output.append("")
        assert final == expected_output
        evaluated = []
        for name, truth, (x0, y0, x1, y1) in regions:
            selected = [line for line in prepared.pages[0].lines if y0 <= (line.bbox[1] + line.bbox[3]) / 2 <= y1]
            actual = "".join(line.text for line in selected)
            initial = "".join(line.review.original_text if line.review else line.text for line in selected)
            error = character_errors(compact(truth), compact(actual))
            original_error = character_errors(compact(truth), compact(initial))
            catastrophe = len(compact(truth)) >= 20 and error.cer >= 0.5
            reviewed = [line.review for line in selected if line.review is not None]
            evaluated.append({
                "name": name, "expected": truth, "observed": actual, "initial": initial,
                "cer": error.cer, "initial_cer": original_error.cer, "catastrophic": catastrophe,
                "flagged": bool(reviewed), "retried": any(item.retried for item in reviewed),
                "improved": bool(reviewed) and error.cer < original_error.cer,
                "false_positive": bool(reviewed) and original_error.cer < 0.5,
            })
        expected_text = compact("".join(item[1] for item in regions))
        actual_text = compact("".join(final))
        errors = character_errors(expected_text, actual_text)
        metrics = {
            "seconds": time.perf_counter() - start,
            "cer": errors.cer,
            "worst_line_cer": max(item["cer"] for item in evaluated),
            "worst_long_line_cer": max(item["cer"] for item in evaluated if len(compact(item["expected"])) >= 20),
            "catastrophic_lines": sum(item["catastrophic"] for item in evaluated),
            "false_positives": sum(item["false_positive"] for item in evaluated),
            "local_retries": sum(item["retried"] for item in evaluated),
            "real_improvements": sum(item["improved"] for item in evaluated),
            "status": prepared.status, "regions": evaluated, "frame": traced.frames[-1],
        }
        report[variant] = metrics
        print(variant, json.dumps({key: metrics[key] for key in ["cer", "worst_long_line_cer", "catastrophic_lines", "false_positives", "local_retries", "real_improvements", "seconds"]}), flush=True)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
