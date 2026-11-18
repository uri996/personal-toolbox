
"""Inspect the cached OCR model on synthetic fixtures only.

Run from backend with python -m spikes.pdf_to_word.recognition_quality.
Outputs stay under the repository's ignored recognition.local directory by default.
"""
import argparse
import hashlib
import io
import json
import time
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from docx import Document

from app.pdf_to_word import ocr
from app.pdf_to_word.ocr_docx import build_ocr_docx, paragraph_texts
from tests.pdf_to_word import synthetic_pdfs as samples
from tests.pdf_to_word.recognition_samples import dialogue_sample, reference_rows
from tests.pdf_to_word.quality_metrics import character_errors, compact, contiguous_line_error

PUNCTUATION = "“”‘’…—《》？！。，、；：（）【】'\".!?,;:-()[]"


def cases():
    report = [
        [samples.REPORT_HEADER.format(page=index + 1), *[text for text, _ in page], samples.REPORT_FOOTER]
        for index, page in enumerate(samples.LONG_REPORT_PAGES)
    ]
    registry = {
        "punctuation": (samples.punctuation_scan_pdf, [samples.PUNCTUATION_LINES]),
        "report": (samples.long_report_scan_pdf, report),
        "dense": (samples.dense_chinese_scan_pdf, [samples.DENSE_PARAGRAPHS]),
        "hidden": (samples.hidden_text_layer_scan_pdf, [samples.DENSE_PARAGRAPHS[:4]]),
    }
    for variant in ("clean", "low-dpi", "compressed", "blur", "skew", "scaled"):
        sample = dialogue_sample(variant)
        registry[sample.name] = (lambda data=sample.pdf: data, sample.expected_pages)
    return registry


def digest(image):
    return hashlib.sha256(image.tobytes()).hexdigest()[:16]


class SessionTrace:
    def __init__(self, session, shapes):
        self.session = session
        self.shapes = shapes

    def __call__(self, tensor):
        self.shapes.append(list(tensor.shape))
        return self.session(tensor)

    def __getattr__(self, name):
        return getattr(self.session, name)


class TracedEngine:
    def __init__(self, engine, output):
        self.engine = engine
        self.base = getattr(engine, "base", engine)
        self.output = output
        self.frames = []
        self.current = None
        detector = self.base._load_det_model()
        recognizer = self.base._load_rec_model()
        self.detector_shapes = []
        detector.session = SessionTrace(detector.session, self.detector_shapes)
        self.recognizer_shapes = []
        recognizer.session = SessionTrace(recognizer.session, self.recognizer_shapes)
        self.classify = self.base.cls_and_rotate
        self.base.cls_and_rotate = self.cls_and_rotate
        self.recognize = self.base.recognize_txt
        self.base.recognize_txt = self.recognize_txt
        self.resize = recognizer.resize_norm_img
        recognizer.resize_norm_img = self.resize_norm_img

    def resize_norm_img(self, image, ratio):
        normalized = self.resize(image, ratio)
        key = digest(image)
        self.current["normalized"][key] = list(normalized.shape)
        restored = np.clip((normalized.transpose(1, 2, 0) + 1) * 127.5, 0, 255).astype(np.uint8)
        cv2.imwrite(str(self.output / f"{self.current['index']}-input-{key}.png"), restored)
        return normalized

    def cls_and_rotate(self, images):
        original_hashes = [digest(image) for image in images]
        rotated, result = self.classify(images)
        records = []
        for index, ((label, score), original, image) in enumerate(zip(result.cls_res, images, rotated)):
            changed = original_hashes[index] != digest(image)
            if changed:
                cv2.imwrite(str(self.output / f"{self.current['index']}-before-rotation-{index}.png"), original)
            records.append({"label": label, "score": float(score), "rotated": changed})
        if "classification" not in self.current:
            self.current["classification"] = records
        else:
            self.current.setdefault("review_classification", []).append(records)
        return rotated, result

    def recognize_txt(self, images):
        result = self.recognize(images)
        records = []
        call = self.current.get("recognition_calls", 0)
        self.current["recognition_calls"] = call + 1
        for index, (image, text, score) in enumerate(zip(images, result.txts, result.scores)):
            key = digest(image)
            suffix = "crop" if call == 0 else f"review-{call}"
            crop_path = self.output / f"{self.current['index']}-{suffix}-{index}.png"
            cv2.imwrite(str(crop_path), image)
            records.append({
                "text": text, "score": float(score), "size": list(image.shape),
                "ratio": image.shape[1] / image.shape[0], "hash": key,
                "normalized_size": self.current["normalized"].get(key), "crop": crop_path.name,
            })
        if call == 0:
            self.current["crops"] = records
        else:
            self.current.setdefault("local_recognition", []).append(records)
        return result

    def __call__(self, image):
        self.current = {"index": len(self.frames), "normalized": {}, "crops": []}
        self.detector_shapes.clear()
        self.recognizer_shapes.clear()
        result = self.engine(image)
        decoded = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
        frame = self.current
        frame["page_size"] = list(decoded.shape)
        frame["image_hash"] = digest(decoded)
        frame["detection_tensor_sizes"] = list(self.detector_shapes)
        frame["recognition_tensor_sizes"] = list(self.recognizer_shapes)
        frame["boxes"] = [] if result.boxes is None else np.asarray(result.boxes).tolist()
        frame["texts"] = [] if result.txts is None else list(result.txts)
        frame["scores"] = [] if result.scores is None else [float(value) for value in result.scores]
        frame["reviews"] = [
            None if review is None else {
                "original_text": review.original_text, "original_score": review.original_score,
                "candidate_text": review.candidate_text, "retried": review.retried,
                "recovered": review.recovered, "reason": review.reason,
            } for review in getattr(result, "line_reviews", ())
        ]
        overlay = decoded.copy()
        for index, box in enumerate(frame["boxes"]):
            polygon = np.asarray(box, dtype=np.int32)
            cv2.polylines(overlay, [polygon], True, (0, 0, 255), 1)
            cv2.putText(overlay, str(index), tuple(polygon[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 0), 1)
        cv2.imwrite(str(self.output / f"{frame['index']}-page.png"), overlay)
        self.frames.append(frame)
        return result


def measure(expected_pages, prepared, output_lines):
    expected = compact("".join(line for page in expected_pages for line in page))
    actual = compact("".join(output_lines))
    errors = character_errors(expected, actual)
    line_errors = [
        {"expected": line, "cer": contiguous_line_error(compact(line), actual)}
        for page in expected_pages for line in page
    ]
    expected_marks = "".join(char for char in expected if char in PUNCTUATION)
    actual_marks = "".join(char for char in actual if char in PUNCTUATION)
    marks = character_errors(expected_marks, actual_marks)
    confusable = "嬴赢己已巳未末"
    similar = character_errors(
        "".join(char for char in expected if char in confusable),
        "".join(char for char in actual if char in confusable),
    )
    duplicates = sum(
        max(actual.count(line) - expected.count(line), 0)
        for line in {compact(item) for page in expected_pages for item in page}
        if len(line) >= 6
    )
    return {
        "confusable_cer": similar.cer,
        "unexpected_duplicate_lines": duplicates,
        "paragraph_coverage": sum(compact(line) in actual for page in expected_pages for line in page) / len(line_errors),
        "cer": errors.cer, "substitutions": errors.substitutions,
        "deletions": errors.deletions, "insertions": errors.insertions,
        "worst_line_cer": max(item["cer"] for item in line_errors),
        "exact_line_recall": sum(compact(line) in actual for page in expected_pages for line in page) / len(line_errors),
        "punctuation_cer": marks.cer, "line_errors": line_errors,
        "output_lines": output_lines,
        "duplicate_lines_removed": sum(page.duplicate_lines for page in prepared.pages),
    }



def inspect_failed_crops(traced, report, output):
    """Controlled recognition-only checks on the already captured failing crops."""
    engine = traced.base
    engine.recognize_txt = traced.recognize
    recognizer = engine._load_rec_model()
    recognizer.resize_norm_img = traced.resize
    comparisons = []
    for name in ("punctuation", "report"):
        for frame in report["cases"][name]["frames"]:
            for crop in frame["crops"]:
                if not any(token in crop["text"] for token in ("等待", "流程分为", "省略号", "引号测试")):
                    continue
                image = cv2.imread(str(output / crop["crop"]))
                item = {"case": name, "original": crop, "variants": []}
                original_batch = recognizer.rec_batch_num
                for label, border, batch in [("individual", 0, 1), ("border-2", 2, 1), ("border-4", 4, 1)]:
                    recognizer.rec_batch_num = batch
                    candidate = cv2.copyMakeBorder(image, border, border, border, border, cv2.BORDER_CONSTANT, value=(255, 255, 255))
                    result = traced.recognize([candidate])
                    item["variants"].append({"variant": label, "text": result.txts[0], "score": float(result.scores[0])})
                recognizer.rec_batch_num = original_batch
                comparisons.append(item)
    return comparisons



def add_row_diagnostics(report):
    for name, case in report["cases"].items():
        actual = compact("".join(case["output_lines"]))
        layouts = reference_rows(name)
        full_rows = []
        for rows, frame in zip(layouts, case["frames"]):
            height, width = frame["page_size"][:2]
            boxes = []
            for polygon in frame["boxes"]:
                points = np.asarray(polygon)
                boxes.append(pymupdf.Rect(
                    float(points[:, 0].min()) * 595 / width,
                    float(points[:, 1].min()) * 842 / height,
                    float(points[:, 0].max()) * 595 / width,
                    float(points[:, 1].max()) * 842 / height,
                ))
            diagnosed = []
            for text, bbox in rows:
                row = pymupdf.Rect(bbox)
                intervals = []
                ids = []
                for index, box in enumerate(boxes):
                    overlap = row & box
                    if overlap.height <= min(row.height, box.height) * 0.4:
                        continue
                    if overlap.width > 0:
                        intervals.append((overlap.x0, overlap.x1))
                        ids.append(index)
                covered = 0.0
                right = row.x0
                for left, end in sorted(intervals):
                    covered += max(0.0, end - max(left, right))
                    right = max(right, end)
                diagnosed.append({
                    "expected": text, "source_bbox": bbox, "detected_box_ids": ids,
                    "horizontal_coverage": covered / row.width,
                    "exact_text_present": compact(text) in actual,
                })
            frame["source_rows"] = diagnosed
            full_rows.extend(diagnosed)
        case["exact_line_recall"] = sum(row["exact_text_present"] for row in full_rows) / len(full_rows)
        case["detected_line_recall"] = sum(row["horizontal_coverage"] >= 0.9 for row in full_rows) / len(full_rows)
        case["severely_damaged_paragraphs"] = sum(item["cer"] >= 0.5 for item in case["line_errors"])
        case["suspicious_short_outputs"] = sum(
            crop["ratio"] > 12 and len(compact(crop["text"])) <= 5
            for frame in case["frames"] for crop in frame["crops"]
        )


def save_comparison(report, output):
    before_path = output / "before-report.json"
    if not before_path.exists():
        return
    before = json.loads(before_path.read_text(encoding="utf-8"))
    add_row_diagnostics(before)
    before["parameters"].setdefault("rec_batch_num", 6)
    before_path.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
    comparison = {}
    for name, after in report["cases"].items():
        old = before["cases"][name]
        assert [frame["image_hash"] for frame in old["frames"]] == [
            frame["image_hash"] for frame in after["frames"]
        ], f"input pixels changed: {name}"
        keys = ["cer", "worst_line_cer", "exact_line_recall", "detected_line_recall",
                "paragraph_coverage", "punctuation_cer", "confusable_cer",
                "unexpected_duplicate_lines", "severely_damaged_paragraphs",
                "suspicious_short_outputs", "seconds"]
        comparison[name] = {
            "before": {key: old[key] for key in keys},
            "after": {key: after[key] for key in keys},
            "line_regressions": [
                {"expected": left["expected"], "before": left["cer"], "after": right["cer"]}
                for left, right in zip(old["line_errors"], after["line_errors"])
                if right["cer"] > left["cer"]
            ],
        }
    (output / "comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="spikes/pdf_to_word/recognition.local/baseline")
    parser.add_argument("--cases", nargs="+", default=["punctuation", "report", "dense", "hidden"])
    parser.add_argument("--max-side", type=int)
    parser.add_argument("--crop-experiments", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--catastrophic-probe", action="store_true")
    parser.add_argument("--line-crops", action="store_true")
    parser.add_argument("--styles", action="store_true")
    parser.add_argument("--evaluate-lines", action="store_true")
    parser.add_argument("--no-line-review", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    root = Path(__file__).resolve().parents[2]
    if not output.is_relative_to(root):
        raise ValueError("diagnostic output must stay inside backend")
    output.mkdir(parents=True, exist_ok=True)
    if args.catastrophic_probe:
        from .catastrophic_lines import main as probe
        probe(output / "severe", line_crops=args.line_crops, styles=args.styles,
              evaluate=args.evaluate_lines, no_review=args.no_line_review)
        return
    if args.analyze_only:
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        add_row_diagnostics(report)
        save_comparison(report, output)
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    engine = ocr._get_engine()
    if args.max_side:
        getattr(engine, "base", engine).max_side_len = args.max_side
    traced = TracedEngine(engine, output)
    report = {"parameters": {
        "max_side": engine.max_side_len,
        "det_limit": engine.cfg.Det.limit_side_len,
        "rec_batch_num": engine.cfg.Rec.rec_batch_num,
    }, "cases": {}}
    registry = cases()
    selected = list(args.cases)
    # The dense group also covers the controlled dialogue scan degradations.
    if "dense" in selected:
        selected.extend(name for name in registry if name.startswith("dialogue-"))
    for name in selected:
        factory, expected = registry[name]
        data = factory()
        first_frame = len(traced.frames)
        start = time.perf_counter()
        prepared = ocr.recognize_pdf(data, engine=traced)
        result = build_ocr_docx(prepared)
        output_lines = paragraph_texts(Document(io.BytesIO(result.docx)))
        recognized = []
        for index, page in enumerate(prepared.pages):
            if index:
                recognized.append("")
            for line in page.lines:
                recognized.append(line.text)
                if line.unresolved_review:
                    recognized.append("")
            if page.fallback_image:
                recognized.append("")
        assert output_lines == recognized
        metrics = measure(expected, prepared, output_lines)
        metrics["seconds"] = time.perf_counter() - start
        metrics["pdf_hash"] = hashlib.sha256(data).hexdigest()
        metrics["frames"] = traced.frames[first_frame:]
        report["cases"][name] = metrics
        print(name, json.dumps({key: metrics[key] for key in ["cer", "worst_line_cer", "exact_line_recall", "punctuation_cer", "seconds"]}), flush=True)
    if args.crop_experiments:
        report["crop_experiments"] = inspect_failed_crops(traced, report, output)
    add_row_diagnostics(report)
    save_comparison(report, output)
    if (output / "report.json").exists():
        (output / "previous-report.json").write_bytes((output / "report.json").read_bytes())
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

