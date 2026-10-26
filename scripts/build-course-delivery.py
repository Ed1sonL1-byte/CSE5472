#!/usr/bin/env python3
"""Render the course documents and package source plus compact public evidence.

PDF rendering needs ReportLab. Packaging alone uses the Python standard library.
The bundle never contains raw runs, local toolchain paths, or unrelated untracked files.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import stat
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PDF_NAMES = ("seedbridge-project-report.pdf", "seedbridge-project-update.pdf")
NEW_FILES = (
    "STAGE5_TECH_PLAN.md", "STAGE5_ACCEPTANCE.md",
    "scripts/build-course-delivery.py", "scripts/verify-course-delivery.py",
    "scripts/review-stage4-archive.py", "tests/unit/test_stage4_archive_review.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inline(value: str) -> str:
    """Translate the small, explicit inline Markdown subset used by these sources."""
    value = html.escape(value)
    value = re.sub(r"\[([^\]]+)\]\((https://[^\s)]+)\)",
                   r'<link href="\2" color="#174C70">\1</link>', value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    return value


def render_pdf(source: Path, output: Path, *, update: bool = False) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import (Flowable, KeepTogether, PageBreak, Paragraph,
                                    SimpleDocTemplate, Spacer, Table, TableStyle)

    navy = colors.HexColor("#17364D")
    body_size, leading = (11.0, 13.0) if update else (11.0, 14.0)
    body = ParagraphStyle("body", fontName="Times-Roman", fontSize=body_size,
                          leading=leading, textColor=colors.HexColor("#18212A"),
                          spaceAfter=7 if update else 8, alignment=TA_LEFT)
    title = ParagraphStyle("title", parent=body, fontName="Helvetica-Bold",
                           fontSize=14 if update else 23, leading=18 if update else 28,
                           textColor=navy, spaceAfter=9)
    subtitle = ParagraphStyle("subtitle", parent=body, fontName="Helvetica",
                              fontSize=13, leading=16, textColor=navy, spaceAfter=11)
    heading = ParagraphStyle("heading", parent=body, fontName="Helvetica-Bold",
                             fontSize=11.7, leading=15, spaceBefore=5,
                             spaceAfter=7, textColor=navy, keepWithNext=True)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=11, firstLineIndent=-9,
                            spaceAfter=5)
    cell = ParagraphStyle("cell", parent=body, fontSize=9.5, leading=12, spaceAfter=0)
    caption = ParagraphStyle("caption", parent=body, fontSize=9.2, leading=12,
                             textColor=colors.HexColor("#455565"), spaceAfter=9)

    class Workflow(Flowable):
        def __init__(self):
            super().__init__()
            self.width, self.height = 504, 72

        def draw(self):
            canvas = self.canv
            labels = [("Medusa", "executed prefix"), ("Halmos", "one input"),
                      ("Foundry", "fresh replay"), ("Medusa", "native replay"),
                      ("Property", "repair check"), ("Evidence", "audit/report")]
            width, gap, y = 76.5, 9, 23
            for index, pair in enumerate(labels):
                x = index * (width + gap)
                canvas.setFillColor(colors.HexColor("#EFF4F7"))
                canvas.setStrokeColor(colors.HexColor("#C3D3DF"))
                canvas.roundRect(x, y, width, 39, 4, stroke=1, fill=1)
                canvas.setFillColor(navy)
                canvas.setFont("Helvetica-Bold", 9)
                canvas.drawCentredString(x + width / 2, y + 24, pair[0])
                canvas.setFont("Helvetica", 8)
                canvas.drawCentredString(x + width / 2, y + 10, pair[1])
                if index < len(labels) - 1:
                    canvas.setStrokeColor(navy)
                    canvas.line(x + width + 1, y + 19, x + width + gap - 1, y + 19)
                    canvas.line(x + width + gap - 3, y + 21, x + width + gap - 1, y + 19)
                    canvas.line(x + width + gap - 3, y + 17, x + width + gap - 1, y + 19)
            canvas.setFont("Times-Italic", 9)
            canvas.setFillColor(colors.HexColor("#455565"))
            canvas.drawString(0, 8, "Figure 1. The safety workflow preserves evidence across concrete and symbolic execution.")

    def table(rows: list[list[str]]):
        count = len(rows[0])
        if any(len(row) != count for row in rows):
            raise ValueError("inconsistent Markdown table")
        widths = ({2: [148, 356], 3: [234, 135, 135], 4: [218, 95, 95, 96],
                   5: [198, 72, 65, 79, 90]}).get(count, [504 / count] * count)
        parsed = [[Paragraph(inline(text), cell) for text in row] for row in rows]
        result = Table(parsed, colWidths=widths, repeatRows=1, hAlign="LEFT")
        result.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7EEF3")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FA")]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.HexColor("#A9BDC9")),
        ]))
        return result

    story = []
    lines = source.read_text(encoding="utf-8").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        index += 1
        if not line:
            continue
        if line == "<!-- PAGEBREAK -->":
            story.append(PageBreak())
        elif line == "<!-- WORKFLOW -->":
            story.append(Workflow())
        elif line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), heading))
        elif line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), subtitle))
        elif line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), title))
        elif line.startswith("| "):
            rows = [line]
            while index < len(lines) and lines[index].strip().startswith("|"):
                rows.append(lines[index].strip())
                index += 1
            parsed = [[value.strip() for value in row.strip("|").split("|")]
                      for row in rows if not re.fullmatch(r"[| :\-]+", row)]
            story.extend([table(parsed), Spacer(1, 8)])
        elif line.startswith("- "):
            story.append(Paragraph("&#8226; " + inline(line[2:]), bullet))
        else:
            paragraph = [line]
            while index < len(lines) and lines[index].strip():
                if lines[index].lstrip().startswith(("#", "|", "- ", "<!--")):
                    break
                paragraph.append(lines[index].strip())
                index += 1
            text = " ".join(paragraph)
            style = caption if text.startswith("**Table ") else body
            story.append(Paragraph(inline(text), style))

    def page_decoration(canvas, document):
        if update:
            return
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D0D9E0"))
        canvas.line(54, 39, 558, 39)
        canvas.setFillColor(colors.HexColor("#556574"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(54, 26, "CSE 5472 | SeedBridge | Edison Li")
        canvas.drawRightString(558, 26, str(document.page))
        canvas.restoreState()

    def stable_canvas(*args, **kwargs):
        kwargs["invariant"] = 1
        return Canvas(*args, **kwargs)

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=letter, rightMargin=54, leftMargin=54,
                            topMargin=48 if update else 49, bottomMargin=54,
                            title="CSE 5472 Project Update" if update else "SeedBridge Project Report",
                            author="Edison Li", pageCompression=1)
    doc.build(story, onFirstPage=page_decoration, onLaterPages=page_decoration,
              canvasmaker=stable_canvas)


def package(output: Path) -> dict:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    selected = set(filter(None, tracked))
    selected.update(name for name in NEW_FILES if (ROOT / name).is_file())
    for directory in ("delivery", "evidence/stage5"):
        if (ROOT / directory).is_dir():
            selected.update(path.relative_to(ROOT).as_posix()
                            for path in (ROOT / directory).rglob("*")
                            if path.is_file() and path.name != ".DS_Store")
    selected.update("output/pdf/" + name for name in PDF_NAMES)
    # Never recursively ingest artifacts, local runs, generated caches, or machine config,
    # even if someone later stages one of them by mistake.
    blocked = ("runs/", ".venv/", ".bin/", "tmp/", ".git/", "__pycache__/")
    files = []
    for name in sorted(selected):
        if name.startswith(blocked) or "/__pycache__/" in name:
            continue
        if name == "configs/toolchain.local.json" or name == "COURSE_MANIFEST.json":
            continue
        if name.startswith("artifacts/") and name != "artifacts/README.md" and not name.startswith("artifacts/stage"):
            continue
        if name.endswith((".tar.gz", ".zip", ".pyc")):
            continue
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"packaged path is absent or not a regular file: {name}")
        files.append({"path": name, "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    required = {"delivery/FINAL_REPORT.md", "delivery/PROJECT_UPDATE.md",
                "scripts/verify-course-delivery.py", "delivery/REPRODUCIBILITY.md"}
    if not required.issubset(row["path"] for row in files):
        raise ValueError("course sources or verification guide are incomplete")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = {"schema_version": 1, "base_git_commit": base,
                "source_state": "Current working-tree files; base commit is provenance, not the hash of new delivery files.",
                "scope": "Source, course materials, compact public evidence. Full raw archives are separate.",
                "files": files}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for row in files:
            path = ROOT / row["path"]
            info = zipfile.ZipInfo(row["path"], date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (path.stat().st_mode & 0o777)) << 16
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo("COURSE_MANIFEST.json", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(info, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    digest = sha256(output)
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n")
    return {"path": str(output), "sha256": digest, "size_bytes": output.stat().st_size,
            "file_count": len(files), "base_git_commit": base}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pdf-only", action="store_true")
    group.add_argument("--package-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/seedbridge-course-delivery.zip")
    args = parser.parse_args()
    result = {}
    if not args.package_only:
        render_pdf(ROOT / "delivery/FINAL_REPORT.md", ROOT / "output/pdf" / PDF_NAMES[0])
        render_pdf(ROOT / "delivery/PROJECT_UPDATE.md", ROOT / "output/pdf" / PDF_NAMES[1], update=True)
        result["pdfs"] = ["output/pdf/" + name for name in PDF_NAMES]
    if not args.pdf_only:
        result["package"] = package(args.output.resolve())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
