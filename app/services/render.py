"""
PowerPoint/PDF/thumbnail rendering with consistent typography and safer layout.
Function signatures remain compatible with the existing Temporal activities.
"""
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION


FONT_NAME = "Liberation Sans"
SLIDE_WIDTH = 13.333
SLIDE_HEIGHT = 7.5
LEFT = 0.65
RIGHT = 0.65
CONTENT_WIDTH = SLIDE_WIDTH - LEFT - RIGHT
TITLE_TOP = 0.38
TITLE_HEIGHT = 0.72
CONTENT_TOP = 1.38
CONTENT_BOTTOM = 6.75
FOOTER_Y = 7.12


def rgb(color):
    value = str(color or "#0F172A").lstrip("#")
    if len(value) != 6:
        value = "0F172A"
    return RGBColor(int(value[:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def clean_text(value):
    if value is None:
        return ""
    value = str(value).replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    return "\n".join(" ".join(line.split()) for line in value.split("\n")).strip()


def estimate_lines(text, width, font_size):
    """Approximate wrapped line count to budget space before placing text."""
    text = clean_text(text)
    if not text:
        return 1
    # Conservative estimate; final PowerPoint/LibreOffice rendering can vary.
    chars_per_line = max(12, int(width * 10.5 * 12 / max(font_size, 1)))
    total = 0
    for paragraph in text.split("\n"):
        if not paragraph:
            total += 1
            continue
        words = paragraph.split()
        line_length = 0
        lines = 1
        for word in words:
            if line_length == 0:
                line_length = len(word)
            elif line_length + 1 + len(word) <= chars_per_line:
                line_length += 1 + len(word)
            else:
                lines += 1
                line_length = len(word)
        total += lines
    return max(1, total)


def textbox(slide, text, x, y, width, height, size, color,
            bold=False, align=None, valign=MSO_ANCHOR.TOP):
    shape = slide.shapes.add_textbox(
        Inches(x), Inches(y), Inches(max(width, 0.1)), Inches(max(height, 0.12))
    )
    frame = shape.text_frame
    frame.clear()
    frame.word_wrap = True
    frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    frame.vertical_anchor = valign
    frame.margin_left = Inches(0.04)
    frame.margin_right = Inches(0.04)
    frame.margin_top = Inches(0.025)
    frame.margin_bottom = Inches(0.025)

    lines = clean_text(text).split("\n")
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.text = line
        paragraph.font.name = FONT_NAME
        paragraph.font.size = Pt(size)
        paragraph.font.color.rgb = rgb(color)
        paragraph.font.bold = bold
        paragraph.space_before = Pt(0)
        paragraph.space_after = Pt(3)
        paragraph.line_spacing = 1.0
        if align is not None:
            paragraph.alignment = align
    return shape


def add_band(slide, y, height, color):
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, Inches(y), Inches(SLIDE_WIDTH), Inches(height)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb(color)
    shape.line.fill.background()
    return shape


def add_header(slide, title, primary):
    add_band(slide, 0, 0.13, primary)
    textbox(
        slide, clean_text(title) or "Presentation",
        LEFT, TITLE_TOP, CONTENT_WIDTH, TITLE_HEIGHT,
        25, primary, bold=True,
    )


def add_footer(slide, index, total):
    textbox(
        slide, f"{index:02d} / {total:02d}",
        SLIDE_WIDTH - 1.5, FOOTER_Y, 0.9, 0.2, 9, "#64748B",
        align=PP_ALIGN.RIGHT,
    )


def add_chart(slide, chart_data, primary):
    if not isinstance(chart_data, dict):
        return False
    labels = chart_data.get("labels")
    values = chart_data.get("values")
    if not isinstance(labels, list) or not isinstance(values, list):
        return False
    if len(labels) < 2 or len(labels) != len(values):
        return False

    try:
        numeric_values = [float(value) for value in values]
        if not all(math.isfinite(value) for value in numeric_values):
            return False

        data = CategoryChartData()
        data.categories = [clean_text(label)[:50] for label in labels]
        data.add_series("Value", numeric_values)
        chart_type = str(chart_data.get("type", "bar")).lower()
        if chart_type == "line":
            kind = XL_CHART_TYPE.LINE
        elif chart_type == "pie":
            kind = XL_CHART_TYPE.PIE
        else:
            kind = XL_CHART_TYPE.COLUMN_CLUSTERED

        chart = slide.shapes.add_chart(
            kind, Inches(0.85), Inches(1.55), Inches(11.65), Inches(4.95), data
        ).chart
        chart.has_title = True
        chart.chart_title.text_frame.text = clean_text(chart_data.get("title", "Chart"))
        for paragraph in chart.chart_title.text_frame.paragraphs:
            paragraph.font.name = FONT_NAME
            paragraph.font.size = Pt(16)
            paragraph.font.bold = True
            paragraph.font.color.rgb = rgb(primary)

        chart.has_legend = chart_type == "pie"
        if chart.has_legend:
            chart.legend.position = XL_LEGEND_POSITION.BOTTOM
            chart.legend.include_in_layout = True
        else:
            chart.has_legend = False
            chart.value_axis.has_major_gridlines = True
        return True
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return False


def add_timeline(slide, timeline, primary, secondary, text_color):
    if not isinstance(timeline, list):
        return
    events = [item for item in timeline[:6] if isinstance(item, dict)]
    if len(events) < 2:
        return

    x_start, x_end, line_y = 1.0, SLIDE_WIDTH - 1.0, 5.25
    line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(x_start), Inches(line_y),
        Inches(x_end - x_start), Inches(0.035),
    )
    line.fill.solid()
    line.fill.fore_color.rgb = rgb(secondary)
    line.line.fill.background()
    interval = (x_end - x_start) / (len(events) - 1)

    for index, event in enumerate(events):
        x = x_start + index * interval
        dot = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(x - 0.075), Inches(line_y - 0.06),
            Inches(0.15), Inches(0.15),
        )
        dot.fill.solid()
        dot.fill.fore_color.rgb = rgb(primary)
        dot.line.fill.background()
        textbox(slide, event.get("date", ""), x - 0.55, line_y - 0.45,
                1.10, 0.30, 9, primary, bold=True, align=PP_ALIGN.CENTER)
        textbox(slide, event.get("label", ""), x - 0.70, line_y + 0.20,
                1.40, 0.85, 9, text_color, align=PP_ALIGN.CENTER)



def set_slide_background(slide, theme):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = rgb(theme.get("background", "#FFFFFF"))


def add_kpis(slide, items, primary, text_color):
    items = [item for item in items[:4] if isinstance(item, dict)]
    if not items:
        return False
    gap = 0.18
    width = (CONTENT_WIDTH - gap * (len(items) - 1)) / len(items)
    for i, item in enumerate(items):
        x = LEFT + i * (width + gap)
        card = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(2.0),
            Inches(width), Inches(2.0)
        )
        card.fill.solid()
        card.fill.fore_color.rgb = rgb("#1E293B" if text_color == "#F8FAFC" else "#F1F5F9")
        card.line.fill.background()
        textbox(slide, clean_text(item.get("value", ""))[:35], x + 0.12, 2.35,
                width - 0.24, 0.65, 24, primary, bold=True, align=PP_ALIGN.CENTER)
        textbox(slide, clean_text(item.get("label", ""))[:70], x + 0.12, 3.05,
                width - 0.24, 0.65, 11, text_color, align=PP_ALIGN.CENTER)
    return True


def add_table(slide, table_data, primary, text_color):
    if not isinstance(table_data, dict):
        return False
    headers = table_data.get("headers")
    rows = table_data.get("rows")
    if not isinstance(headers, list) or not isinstance(rows, list) or not headers:
        return False
    headers = [clean_text(x)[:50] for x in headers[:6]]
    rows = [r[:len(headers)] for r in rows[:8] if isinstance(r, list)]
    if not rows:
        return False
    shape = slide.shapes.add_table(len(rows) + 1, len(headers),
        Inches(LEFT), Inches(1.65), Inches(CONTENT_WIDTH), Inches(min(4.7, 0.42 * (len(rows) + 1))))
    table = shape.table
    for col in range(len(headers)):
        table.columns[col].width = Inches(CONTENT_WIDTH / len(headers))
    for row_idx in range(len(rows) + 1):
        for col_idx in range(len(headers)):
            cell = table.cell(row_idx, col_idx)
            cell.text = headers[col_idx] if row_idx == 0 else clean_text(rows[row_idx - 1][col_idx] if col_idx < len(rows[row_idx - 1]) else "")[:100]
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(primary if row_idx == 0 else ("#1E293B" if text_color == "#F8FAFC" else "#F8FAFC"))
            for para in cell.text_frame.paragraphs:
                para.font.name = FONT_NAME
                para.font.size = Pt(10)
                para.font.bold = row_idx == 0
                para.font.color.rgb = rgb("#FFFFFF" if row_idx == 0 else text_color)
    return True


def add_two_columns(slide, columns, primary, text_color):
    columns = [c for c in columns[:2] if isinstance(c, dict)]
    if len(columns) != 2:
        return False
    gap = 0.35
    width = (CONTENT_WIDTH - gap) / 2
    for i, col in enumerate(columns):
        x = LEFT + i * (width + gap)
        textbox(slide, clean_text(col.get("title", f"Column {i+1}"))[:80],
                x, CONTENT_TOP, width, 0.45, 17, primary, bold=True)
        body = clean_text(col.get("body", ""))
        bullets = col.get("bullets", [])
        if not isinstance(bullets, list):
            bullets = [str(bullets)]
        text = "\n".join([body] + ["• " + clean_text(b) for b in bullets[:4] if clean_text(b)])
        textbox(slide, text[:1800], x, CONTENT_TOP + 0.55, width, 4.4, 13, text_color)
    return True


def add_matched_background(slide, theme, width, height):
    match = theme.get("background_match")
    if not match:
        return
    from io import BytesIO
    from app.services.theme_match import backdrop
    data = backdrop(match["image"], theme["background"], width, height)
    if data:
        slide.shapes.add_picture(BytesIO(data), 0, 0, Inches(width), Inches(height))


def render_pptx(slides, theme, resolved, path, options):
    if (theme or {}).get("design_version") == 2:
        from app.services.designed_render import render_designed
        return render_designed(slides, theme, resolved, path, options or {})
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width = Inches(SLIDE_WIDTH)
    prs.slide_height = Inches(SLIDE_HEIGHT)
    blank_layout = prs.slide_layouts[6]

    theme = theme or {}
    primary = theme.get("primary", "#1D4ED8")
    secondary = theme.get("secondary", "#60A5FA")
    text_color = theme.get("text", "#0F172A")
    options = options or {}
    total = len(slides)

    for index, data in enumerate(slides, start=1):
        data = data if isinstance(data, dict) else {}
        slide = prs.slides.add_slide(blank_layout)
        set_slide_background(slide, theme)
        add_matched_background(slide, theme, SLIDE_WIDTH, SLIDE_HEIGHT)
        layout = str(data.get("layout_variant", "bullets")).lower()
        layout = {"hero":"title", "comparison":"table", "kpi_split":"kpi"}.get(layout, layout)
        add_header(slide, data.get("title", "Presentation"), primary)

        if layout == "title":
            title_align = PP_ALIGN.CENTER if theme.get("title_style", "center") == "center" else PP_ALIGN.LEFT
            title_x = 1.0 if title_align == PP_ALIGN.CENTER else LEFT + 0.25
            textbox(slide, clean_text(data.get("title", "Presentation")),
                    title_x, 2.1, SLIDE_WIDTH - 2.0, 1.35, 32, primary,
                    bold=True, align=title_align, valign=MSO_ANCHOR.MIDDLE)
            subtitle = clean_text(data.get("body") or ((data.get("bullets") or [""])[0]))
            if subtitle:
                textbox(slide, subtitle[:300], title_x, 3.65, SLIDE_WIDTH - 3.0,
                        1.0, 16, text_color, align=title_align)
            chart_added = True
        elif layout == "table" and add_table(slide, data.get("table"), primary, text_color):
            chart_added = True
        elif layout == "kpi" and add_kpis(slide, data.get("kpis", []), primary, text_color):
            chart_added = True
        elif layout == "two_column" and add_two_columns(slide, data.get("columns", []), primary, text_color):
            chart_added = True
        else:
            chart_added = add_chart(slide, data.get("chart"), primary)
        if not chart_added:
            y = CONTENT_TOP
            body = clean_text(data.get("body", ""))
            if body:
                lines = estimate_lines(body, CONTENT_WIDTH, 15)
                height = min(max(0.42, lines * 0.27 + 0.12), 1.35)
                textbox(slide, body, LEFT, y, CONTENT_WIDTH, height, 15, text_color)
                y += height + 0.12

            bullets = data.get("bullets", [])
            if not isinstance(bullets, list):
                bullets = [str(bullets)] if bullets else []

            for bullet in bullets[:5]:
                bullet = clean_text(bullet)
                if not bullet:
                    continue
                available = CONTENT_BOTTOM - y
                if available < 0.34:
                    break
                width = CONTENT_WIDTH - 0.15
                lines = estimate_lines(bullet, width, 15)
                desired = max(0.38, lines * 0.28 + 0.10)
                height = min(desired, available)
                textbox(
                    slide, "\u2022  " + bullet, LEFT + 0.08, y,
                    width, height, 15, text_color,
                )
                y += height + 0.12

            timeline = data.get("timeline")
            if isinstance(timeline, list) and len(timeline) > 1 and y < 4.45:
                add_timeline(slide, timeline, primary, secondary, text_color)

        add_footer(slide, index, total)
        if options.get("speaker_notes") and data.get("speaker_notes"):
            try:
                slide.notes_slide.notes_text_frame.text = clean_text(data["speaker_notes"])
            except (AttributeError, ValueError):
                pass

    prs.core_properties.title = "AI Generated Presentation"
    prs.core_properties.subject = "Generated presentation"
    prs.save(str(path))
    return path


def render_pdf(pptx, pdf):
    """Convert PPTX to PDF using a unique temporary LibreOffice profile."""
    pptx = Path(pptx).resolve()
    pdf = Path(pdf).resolve()
    if not pptx.exists():
        raise FileNotFoundError(f"PowerPoint file not found: {pptx}")
    pdf.parent.mkdir(parents=True, exist_ok=True)

    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        raise RuntimeError(
            "LibreOffice is not installed or is not on PATH. PDF export cannot run."
        )

    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile_dir, \
         tempfile.TemporaryDirectory(prefix="pdf_output_", dir=str(pdf.parent)) as output_dir:
        command = [
            executable,
            f"-env:UserInstallation={Path(profile_dir).resolve().as_uri()}",
            "--headless", "--convert-to", "pdf",
            "--outdir", output_dir, str(pptx),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, check=False, timeout=180
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("LibreOffice PDF conversion exceeded 180 seconds.") from exc

        generated = Path(output_dir) / f"{pptx.stem}.pdf"
        if result.returncode != 0 or not generated.exists():
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"LibreOffice PDF conversion failed (exit={result.returncode}): {detail}"
            )
        shutil.copy2(generated, pdf)

    if not pdf.exists() or pdf.stat().st_size == 0:
        raise RuntimeError(f"PDF output is missing or empty: {pdf}")
    return pdf


def render_thumbnails(pptx, outdir, pdf_path=None):
    pptx = Path(pptx).resolve()
    outdir = Path(outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if not pptx.exists():
        raise FileNotFoundError(f"PowerPoint file not found: {pptx}")

    poppler = shutil.which("pdftoppm")
    if not poppler:
        raise RuntimeError("pdftoppm is required for thumbnails; install Poppler.")

    with tempfile.TemporaryDirectory(prefix="ppt_thumbnails_") as temp_dir:
        temp = Path(temp_dir)
        reusable_pdf = Path(pdf_path).resolve() if pdf_path else None
        if reusable_pdf and reusable_pdf.exists() and reusable_pdf.stat().st_size > 0:
            pdf_for_images = reusable_pdf
        else:
            generated_pdf = temp / f"{pptx.stem}.pdf"
            render_pdf(pptx, generated_pdf)
            pdf_for_images = generated_pdf
        prefix = temp / "slide"
        subprocess.run(
            [poppler, "-png", "-r", "100", str(pdf_for_images), str(prefix)],
            check=True, capture_output=True, timeout=180,
        )
        images = sorted(temp.glob("slide-*.png"))
        output = []
        for index, image in enumerate(images, start=1):
            destination = outdir / f"{pptx.stem}_slide-{index:02d}.png"
            shutil.copy2(image, destination)
            output.append(str(destination))
    return output
