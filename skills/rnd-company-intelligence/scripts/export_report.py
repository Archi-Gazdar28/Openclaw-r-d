#!/usr/bin/env python3
"""
export_report.py — writes output.md and/or output.pdf from an already-rendered
report (the same markdown + chart images shown in chat) to the user's
Downloads folder, for the rnd-company-intelligence skill.

This only runs when the user explicitly asks to download/save/export — see
"Output & delivery" in SKILL.md. It never runs automatically.

Usage
-----
  export --format md|pdf|both --title "..." --markdown-file path/to/rendered.md
         [--charts-dir path/to/charts] [--out-dir ~/Downloads]
         [--overwrite]

Behavior
--------
- Default --out-dir is the platform Downloads folder:
    macOS/Linux: ~/Downloads
    Windows:     %USERPROFILE%\\Downloads
  If that folder doesn't exist or isn't writable, falls back to
  ~/.openclaw/workspace/reports/_exports/ and says so in the JSON output
  (the calling agent is responsible for relaying that to the user).
- Refuses to silently overwrite an existing output.md/output.pdf unless
  --overwrite is passed; otherwise returns a "file_exists" error so the
  calling agent can ask the user how to proceed.
- The PDF renderer is a small, dependency-light markdown -> PDF converter
  (headings, paragraphs, bullet lists, pipe tables, and images) built on
  reportlab. It is intentionally plain (black/white/gray) per SKILL.md's
  "Document styling" section, not a full CommonMark implementation.

Dependencies: reportlab>=4.0.0
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# Path resolution
# --------------------------------------------------------------------------

def _downloads_dir() -> Path:
    home = Path.home()
    if platform.system() == "Windows":
        return Path(os.environ.get("USERPROFILE", str(home))) / "Downloads"
    return home / "Downloads"


def _fallback_dir() -> Path:
    return Path.home() / ".openclaw" / "workspace" / "reports" / "_exports"


def _resolve_out_dir(requested: str | None) -> tuple[Path, bool]:
    """Returns (directory, used_fallback)."""
    target = Path(requested).expanduser() if requested else _downloads_dir()
    try:
        target.mkdir(parents=True, exist_ok=True)
        # Writability probe
        probe = target / ".write_test"
        probe.touch()
        probe.unlink()
        return target, False
    except Exception:
        fallback = _fallback_dir()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback, True


# --------------------------------------------------------------------------
# Markdown -> PDF (plain, reportlab-based)
# --------------------------------------------------------------------------

def _parse_markdown_blocks(md_text: str) -> list[dict]:
    """Very small block-level markdown parser: headings, paragraphs, bullet
    lists, pipe tables, and image references. Good enough for the
    machine-generated report markdown this skill produces; not a general
    CommonMark parser."""
    lines = md_text.splitlines()
    blocks: list[dict] = []
    i = 0
    paragraph_buf: list[str] = []

    def flush_paragraph():
        if paragraph_buf:
            text = " ".join(paragraph_buf).strip()
            if text:
                blocks.append({"type": "paragraph", "text": text})
            paragraph_buf.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            flush_paragraph()
            i += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            blocks.append({"type": "heading", "level": level, "text": heading_match.group(2).strip()})
            i += 1
            continue

        image_match = re.match(r"^!\[(.*?)\]\((.*?)\)\s*$", stripped)
        if image_match:
            flush_paragraph()
            blocks.append({"type": "image", "alt": image_match.group(1), "path": image_match.group(2)})
            i += 1
            continue

        if stripped.startswith("*") and stripped.endswith("*") and stripped.count("*") == 2:
            flush_paragraph()
            blocks.append({"type": "caption", "text": stripped.strip("*")})
            i += 1
            continue

        if re.match(r"^[-*]\s+", stripped):
            flush_paragraph()
            items = []
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            blocks.append({"type": "bullet_list", "items": items})
            continue

        if stripped.startswith("|"):
            flush_paragraph()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            rows = []
            for tl in table_lines:
                if re.match(r"^\|[\s:|-]+\|$", tl):
                    continue  # separator row
                cells = [c.strip() for c in tl.strip("|").split("|")]
                rows.append(cells)
            if rows:
                blocks.append({"type": "table", "rows": rows})
            continue

        paragraph_buf.append(stripped)
        i += 1

    flush_paragraph()
    return blocks


def _strip_inline_markdown(text: str) -> str:
    # Escape XML special chars first so reportlab's mini-XML markup parser
    # doesn't choke on a literal '&' (e.g. "R&D") or stray '<'/'>'.
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r'<link href="\2" color="#000000">\1</link>', text)
    return text


def _build_pdf(title: str, md_text: str, charts_dir: str | None, out_path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
        Image as RLImage,
    )

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle", fontSize=18, leading=22, spaceAfter=16, textColor=colors.black
        )
    )
    styles.add(
        ParagraphStyle(
            name="H1Plain", fontSize=15, leading=19, spaceBefore=14, spaceAfter=8, textColor=colors.black
        )
    )
    styles.add(
        ParagraphStyle(
            name="H2Plain", fontSize=13, leading=16, spaceBefore=12, spaceAfter=6, textColor=colors.black
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyPlain", fontSize=10, leading=14, spaceAfter=6, textColor=colors.black
        )
    )
    styles.add(
        ParagraphStyle(
            name="CaptionPlain", fontSize=8, leading=10, spaceAfter=10, textColor=colors.HexColor("#555555")
        )
    )

    blocks = _parse_markdown_blocks(md_text)
    base_dir = Path(charts_dir).expanduser().parent if charts_dir else Path(".")

    story = []
    title_rendered = False
    if blocks and blocks[0]["type"] == "heading" and blocks[0]["level"] == 1:
        story.append(Paragraph(_strip_inline_markdown(blocks[0]["text"]), styles["ReportTitle"]))
        story.append(Spacer(1, 0.1 * inch))
        blocks = blocks[1:]
        title_rendered = True
    if not title_rendered:
        story.append(Paragraph(_strip_inline_markdown(title), styles["ReportTitle"]))
        story.append(Spacer(1, 0.1 * inch))

    for block in blocks:
        btype = block["type"]
        if btype == "heading":
            style = styles["H1Plain"] if block["level"] <= 2 else styles["H2Plain"]
            story.append(Paragraph(_strip_inline_markdown(block["text"]), style))
        elif btype == "paragraph":
            story.append(Paragraph(_strip_inline_markdown(block["text"]), styles["BodyPlain"]))
        elif btype == "caption":
            story.append(Paragraph(_strip_inline_markdown(block["text"]), styles["CaptionPlain"]))
        elif btype == "bullet_list":
            for item in block["items"]:
                story.append(
                    Paragraph("&bull;&nbsp;&nbsp;" + _strip_inline_markdown(item), styles["BodyPlain"])
                )
            story.append(Spacer(1, 0.05 * inch))
        elif btype == "table":
            rows = block["rows"]
            if not rows:
                continue
            tbl = Table(rows, hAlign="LEFT")
            tbl.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#808080")),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F2F2")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(tbl)
            story.append(Spacer(1, 0.1 * inch))
        elif btype == "image":
            img_path = (base_dir / block["path"]).resolve()
            if img_path.exists():
                # Scale to ~80% of usable page width, preserving aspect ratio.
                max_width = LETTER[0] - 1.6 * inch
                try:
                    img = RLImage(str(img_path))
                    aspect = img.imageHeight / float(img.imageWidth)
                    img.drawWidth = max_width * 0.8
                    img.drawHeight = img.drawWidth * aspect
                    story.append(img)
                except Exception:
                    story.append(
                        Paragraph(f"[image could not be embedded: {block['path']}]", styles["CaptionPlain"])
                    )
            else:
                story.append(
                    Paragraph(f"[image not found: {block['path']}]", styles["CaptionPlain"])
                )

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.8 * inch,
        rightMargin=0.8 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=title,
    )
    doc.build(story)


# --------------------------------------------------------------------------
# Command
# --------------------------------------------------------------------------

def cmd_export(args: argparse.Namespace) -> dict:
    md_path = Path(args.markdown_file).expanduser()
    if not md_path.exists():
        return {"error": "markdown_file_not_found", "detail": str(md_path)}

    md_text = md_path.read_text(encoding="utf-8")

    out_dir, used_fallback = _resolve_out_dir(args.out_dir)

    written = {}
    skipped_existing = []

    want_md = args.format in ("md", "both")
    want_pdf = args.format in ("pdf", "both")

    if want_md:
        md_out = out_dir / "output.md"
        if md_out.exists() and not args.overwrite:
            skipped_existing.append(str(md_out))
        else:
            md_out.write_text(md_text, encoding="utf-8")
            written["md"] = str(md_out)

    if want_pdf:
        pdf_out = out_dir / "output.pdf"
        if pdf_out.exists() and not args.overwrite:
            skipped_existing.append(str(pdf_out))
        else:
            try:
                _build_pdf(args.title, md_text, args.charts_dir, pdf_out)
                written["pdf"] = str(pdf_out)
            except ImportError as exc:
                return {
                    "error": "missing_dependency",
                    "detail": f"Install with: pip install reportlab --break-system-packages ({exc})",
                }
            except Exception as exc:  # noqa: BLE001
                return {"error": "pdf_generation_failed", "detail": str(exc)}

    return {
        "out_dir": str(out_dir),
        "used_fallback_dir": used_fallback,
        "written": written,
        "skipped_existing": skipped_existing,
        "hint": (
            "skipped_existing files were left untouched; re-run with --overwrite "
            "or save under a more specific filename if the user confirms."
            if skipped_existing
            else None
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_report.py",
        description="Write output.md / output.pdf to the Downloads folder on explicit user request.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("export", help="Export a rendered report to md/pdf")
    p.add_argument("--format", choices=["md", "pdf", "both"], required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--markdown-file", required=True, help="Path to the exact markdown rendered in chat")
    p.add_argument("--charts-dir", default=None, help="Folder containing chart PNGs referenced by the markdown")
    p.add_argument("--out-dir", default=None, help="Override output directory (defaults to Downloads)")
    p.add_argument("--overwrite", action="store_true")
    p.set_defaults(func=cmd_export)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    output = args.func(args)
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if isinstance(output, dict) and "error" in output:
        sys.exit(1)


if __name__ == "__main__":
    main()
