import io
import logging
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from models import Resume

logging.basicConfig(level=logging.INFO)

MAX_PAGES = 2
CANVAS_MAX_BULLETS_PER_EXPERIENCE = 6

DENSITY_PROFILES = [
    {
        "name": "two_page",
        "margin": 0.36,
        "name_size": 18,
        "normal_size": 8.2,
        "normal_leading": 9.6,
        "section_size": 9.3,
        "bullet_size": 8.0,
        "bullet_leading": 9.3,
        "exp_items": 7,
        "exp_bullets": 2,
        "project_items": 1,
        "project_bullets": 1,
        "skills": 14,
        "summary_chars": 420,
        "bullet_chars": 165,
        "page_break_after_exp_items": 2,
    },
    {
        "name": "minimal",
        "margin": 0.32,
        "name_size": 17,
        "normal_size": 7.8,
        "normal_leading": 9.0,
        "section_size": 8.8,
        "bullet_size": 7.6,
        "bullet_leading": 8.8,
        "exp_items": 7,
        "exp_bullets": 2,
        "project_items": 1,
        "project_bullets": 1,
        "skills": 12,
        "summary_chars": 360,
        "bullet_chars": 145,
        "page_break_after_exp_items": 2,
    },
    {
        "name": "fit_two_pages",
        "margin": 0.28,
        "name_size": 16,
        "normal_size": 7.4,
        "normal_leading": 8.4,
        "section_size": 8.3,
        "bullet_size": 7.2,
        "bullet_leading": 8.2,
        "exp_items": 7,
        "exp_bullets": 1,
        "project_items": 0,
        "project_bullets": 0,
        "skills": 10,
        "summary_chars": 260,
        "bullet_chars": 125,
        "education_items": 1,
        "certification_items": 0,
        "language_items": 0,
        "tech_items": 0,
        "page_break_after_exp_items": 2,
    },
    {
        "name": "last_resort_fit",
        "margin": 0.24,
        "name_size": 15,
        "normal_size": 6.9,
        "normal_leading": 7.8,
        "section_size": 7.8,
        "bullet_size": 6.8,
        "bullet_leading": 7.6,
        "exp_items": 7,
        "exp_bullets": 1,
        "project_items": 0,
        "project_bullets": 0,
        "skills": 8,
        "summary_chars": 200,
        "bullet_chars": 95,
        "education_items": 1,
        "certification_items": 0,
        "language_items": 0,
        "tech_items": 0,
        "page_break_after_exp_items": 2,
    },
]


def _has_value(value) -> bool:
    return bool(value) and value != "NA"


def _clean_text(value) -> str:
    if not value:
        return ""
    text = str(value).replace("\r", "\n")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1].strip()
    return text


def _clip(text: str, max_chars: int) -> str:
    text = _clean_text(text)
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rsplit(" ", 1)[0].rstrip(".,;:")
    return f"{clipped}."


def _normalize_bullet_key(text: str) -> str:
    text = _clean_text(text).lower()
    text = re.sub(r"^[\-*\u2022]+\s*", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_bullets(text: str, max_items: int, max_chars: int) -> list[str]:
    text = (text or "").replace("\r", "\n").strip()
    if not text or text == "NA":
        return []

    raw_items = []
    if "\n" in text:
        raw_items = [line.strip(" -*\u2022\u25aa\u25ab\u25e6\t") for line in text.splitlines()]
    else:
        normalized = re.sub(r"\s+", " ", text)
        raw_items = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", normalized)

    bullets = []
    seen = set()
    for item in raw_items:
        cleaned = _clip(item, max_chars)
        key = _normalize_bullet_key(cleaned)
        if cleaned and key and key not in seen:
            if not cleaned.endswith((".", "!", "?")):
                cleaned += "."
            bullets.append(cleaned)
            seen.add(key)
        if len(bullets) >= max_items:
            break
    return bullets


def _wrap_text(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    words = _clean_text(text).split()
    if not words:
        return []

    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if pdfmetrics.stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_wrapped_text(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    max_width: float,
    font_name: str = "Helvetica",
    font_size: float = 8.0,
    leading: float = 9.0,
    max_lines: int | None = None,
) -> float:
    pdf.setFont(font_name, font_size)
    lines = _wrap_text(text, font_name, font_size, max_width)
    if max_lines is not None:
        lines = lines[:max_lines]
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _draw_section(pdf: canvas.Canvas, title: str, x: float, y: float, width: float) -> float:
    pdf.setFillColor(colors.HexColor("#1D4ED8"))
    pdf.setFont("Helvetica-Bold", 10.2)
    pdf.drawString(x, y, title)
    y -= 2.5
    pdf.setStrokeColor(colors.HexColor("#9AA4B2"))
    pdf.setLineWidth(0.45)
    pdf.line(x, y, x + width, y)
    pdf.setFillColor(colors.black)
    return y - 9.5


def _draw_experience_item(
    pdf: canvas.Canvas,
    exp,
    x: float,
    y: float,
    width: float,
    bullet_count: int = CANVAS_MAX_BULLETS_PER_EXPERIENCE,
) -> float:
    title = _clean_text(exp.job_title)
    dates = ""
    if _has_value(exp.start_date) and _has_value(exp.end_date):
        dates = f"{_clean_text(exp.start_date)} - {_clean_text(exp.end_date)}"
    elif _has_value(exp.start_date):
        dates = f"{_clean_text(exp.start_date)} - Present"

    pdf.setFillColor(colors.black)
    pdf.setFont("Helvetica-Bold", 8.8)
    pdf.drawString(x, y, title)
    if dates:
        pdf.setFont("Helvetica", 7.8)
        pdf.drawRightString(x + width, y, dates)
    y -= 9.4

    company_parts = []
    if _has_value(exp.company):
        company_parts.append(_clean_text(exp.company))
    if _has_value(exp.location):
        company_parts.append(_clean_text(exp.location))
    if company_parts:
        pdf.setFont("Helvetica", 7.8)
        pdf.setFillColor(colors.HexColor("#374151"))
        pdf.drawString(x, y, " | ".join(company_parts))
        y -= 8.8

    pdf.setFillColor(colors.black)
    bullets = _split_bullets(exp.description, bullet_count, 170)
    for bullet in bullets:
        wrapped = _wrap_text(bullet, "Helvetica", 7.7, width - 12)
        if not wrapped:
            continue
        pdf.setFont("Helvetica", 7.7)
        pdf.drawString(x + 4, y, "-")
        pdf.drawString(x + 12, y, wrapped[0])
        y -= 8.5
        for line in wrapped[1:2]:
            pdf.drawString(x + 12, y, line)
            y -= 8.5
    return y - 3.5


def _draw_education(pdf: canvas.Canvas, resume_data: Resume, x: float, y: float, width: float) -> float:
    education = [edu for edu in (resume_data.education or []) if _has_value(edu.degree) or _has_value(edu.institution)]
    if not education:
        return y
    y = _draw_section(pdf, "EDUCATION", x, y, width)
    for edu in education[:2]:
        degree = _clean_text(edu.degree)
        if _has_value(edu.field_of_study):
            degree = f"{degree}, {_clean_text(edu.field_of_study)}" if degree else _clean_text(edu.field_of_study)
        years = ""
        if _has_value(edu.start_year) and _has_value(edu.end_year):
            years = f"{_clean_text(edu.start_year)} - {_clean_text(edu.end_year)}"
        elif _has_value(edu.end_year):
            years = _clean_text(edu.end_year)
        pdf.setFont("Helvetica-Bold", 8.0)
        pdf.drawString(x, y, degree)
        if years:
            pdf.setFont("Helvetica", 7.5)
            pdf.drawRightString(x + width, y, years)
        y -= 8.8
        if _has_value(edu.institution):
            pdf.setFont("Helvetica", 7.5)
            pdf.drawString(x, y, _clean_text(edu.institution))
            y -= 8.8
    return y - 2


def _draw_certifications(pdf: canvas.Canvas, resume_data: Resume, x: float, y: float, width: float) -> float:
    certifications = [cert for cert in (resume_data.certifications or []) if _has_value(cert.name) or _has_value(cert.issuer)]
    if not certifications:
        return y
    y = _draw_section(pdf, "CERTIFICATIONS", x, y, width)
    cert_text = []
    for cert in certifications[:4]:
        item = _clean_text(cert.name)
        if _has_value(cert.issuer):
            item = f"{item} - {_clean_text(cert.issuer)}" if item else _clean_text(cert.issuer)
        if _has_value(cert.year):
            item = f"{item} ({_clean_text(cert.year)})"
        if item:
            cert_text.append(item)
    return _draw_wrapped_text(pdf, "; ".join(cert_text), x, y, width, "Helvetica", 7.7, 8.8, max_lines=2)


def _build_canvas_two_page_pdf(resume_data: Resume) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter, pageCompression=0)
    page_width, page_height = letter
    margin = 0.46 * inch
    content_width = page_width - (2 * margin)

    def draw_header(y: float, include_summary: bool = False) -> float:
        if _has_value(resume_data.name):
            pdf.setFont("Helvetica-Bold", 20)
            pdf.drawCentredString(page_width / 2, y, _clean_text(str(resume_data.name)).upper())
            y -= 12

        contact_parts = [_clean_text(value) for value in [resume_data.email, resume_data.phone, resume_data.location] if _has_value(value)]
        if contact_parts:
            pdf.setFont("Helvetica", 8.2)
            pdf.drawCentredString(page_width / 2, y, " | ".join(contact_parts))
            y -= 10

        if resume_data.links and _has_value(resume_data.links.linkedin):
            pdf.setFillColor(colors.HexColor("#1D4ED8"))
            pdf.setFont("Helvetica", 7.8)
            pdf.drawCentredString(page_width / 2, y, "LinkedIn")
            pdf.setFillColor(colors.black)
            y -= 11

        if include_summary and _has_value(resume_data.summary):
            y = _draw_section(pdf, "PROFESSIONAL SUMMARY", margin, y, content_width)
            y = _draw_wrapped_text(
                pdf,
                _clip(resume_data.summary, 520),
                margin,
                y,
                content_width,
                "Helvetica",
                8.1,
                9.2,
                max_lines=4,
            )
            y -= 4

        return y

    y = draw_header(page_height - margin, include_summary=True)

    skills = [_clean_text(skill) for skill in (resume_data.skills or []) if _has_value(skill)]
    if skills:
        y = _draw_section(pdf, "CORE SKILLS", margin, y, content_width)
        y = _draw_wrapped_text(pdf, ", ".join(skills[:20]), margin, y, content_width, "Helvetica", 7.9, 9.0, max_lines=3)
        y -= 4

    experiences = [exp for exp in (resume_data.experience or []) if _has_value(exp.job_title) or _has_value(exp.description)]
    page_one_experiences = experiences[:5]
    page_two_experiences = experiences[5:7]

    y = _draw_section(pdf, "PROFESSIONAL EXPERIENCE", margin, y, content_width)
    for exp in page_one_experiences:
        y = _draw_experience_item(pdf, exp, margin, y, content_width)

    pdf.showPage()

    y = page_height - margin
    for exp in page_two_experiences:
        y = _draw_experience_item(pdf, exp, margin, y, content_width)

    if y > (1.25 * inch):
        y = _draw_education(pdf, resume_data, margin, y, content_width)
    if y > (0.9 * inch):
        _draw_certifications(pdf, resume_data, margin, y, content_width)

    pdf.save()
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_clean_text(text)), style)


def _section(story, title: str, style_section: ParagraphStyle):
    story.append(Paragraph(title, style_section))
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.6,
            color=colors.HexColor("#9AA4B2"),
            spaceBefore=0,
            spaceAfter=3,
        )
    )


def _make_styles(profile):
    styles = getSampleStyleSheet()
    primary = colors.HexColor("#1D4ED8")
    text = colors.HexColor("#111827")
    muted = colors.HexColor("#4B5563")

    return {
        "name": ParagraphStyle(
            name="Name",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=profile["name_size"],
            leading=profile["name_size"] + 1,
            alignment=TA_CENTER,
            spaceAfter=2,
            textColor=text,
        ),
        "contact": ParagraphStyle(
            name="Contact",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=profile["normal_size"] - 0.2,
            leading=profile["normal_leading"],
            alignment=TA_CENTER,
            textColor=muted,
            spaceAfter=1,
        ),
        "section": ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=profile["section_size"],
            leading=profile["section_size"] + 1,
            alignment=TA_LEFT,
            spaceBefore=5,
            spaceAfter=1,
            textColor=primary,
        ),
        "normal": ParagraphStyle(
            name="NormalCompact",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=profile["normal_size"],
            leading=profile["normal_leading"],
            textColor=text,
            spaceAfter=1,
        ),
        "job_title": ParagraphStyle(
            name="JobTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=profile["normal_size"] + 0.7,
            leading=profile["normal_leading"],
            textColor=text,
            spaceAfter=0,
        ),
        "dates": ParagraphStyle(
            name="Dates",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=profile["normal_size"] - 0.4,
            leading=profile["normal_leading"],
            alignment=TA_RIGHT,
            textColor=muted,
        ),
        "muted": ParagraphStyle(
            name="Muted",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=profile["normal_size"] - 0.2,
            leading=profile["normal_leading"],
            textColor=muted,
            spaceAfter=1,
        ),
        "bullet": ParagraphStyle(
            name="Bullet",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=profile["bullet_size"],
            leading=profile["bullet_leading"],
            leftIndent=9,
            firstLineIndent=-6,
            textColor=text,
            spaceAfter=0.8,
        ),
    }


def _build_story(resume_data: Resume, doc: SimpleDocTemplate, profile) -> list:
    style = _make_styles(profile)
    available_width = letter[0] - doc.leftMargin - doc.rightMargin
    story = []

    if _has_value(resume_data.name):
        story.append(_paragraph(str(resume_data.name).upper(), style["name"]))

    contact_parts = []
    for value in [resume_data.email, resume_data.phone, resume_data.location]:
        if _has_value(value):
            contact_parts.append(_clean_text(value))
    if contact_parts:
        story.append(_paragraph(" | ".join(contact_parts), style["contact"]))

    links = []
    if resume_data.links:
        for label, url in [
            ("LinkedIn", resume_data.links.linkedin),
            ("GitHub", resume_data.links.github),
            ("Portfolio", resume_data.links.portfolio),
        ]:
            if _has_value(url):
                clean_url = _clean_text(url)
                href = clean_url if clean_url.startswith("http") else f"https://{clean_url}"
                links.append(f'<u><a href="{escape(href)}"><font color="#1D4ED8">{label}</font></a></u>')
    if links:
        story.append(Paragraph(" | ".join(links), style["contact"]))

    if _has_value(resume_data.summary):
        _section(story, "PROFESSIONAL SUMMARY", style["section"])
        story.append(_paragraph(_clip(resume_data.summary, profile["summary_chars"]), style["normal"]))

    skills = [_clean_text(skill) for skill in (resume_data.skills or []) if _has_value(skill)]
    if skills:
        _section(story, "CORE SKILLS", style["section"])
        story.append(_paragraph(", ".join(skills[: profile["skills"]]), style["normal"]))

    experiences = [exp for exp in (resume_data.experience or []) if _has_value(exp.job_title) or _has_value(exp.description)]
    if experiences:
        _section(story, "PROFESSIONAL EXPERIENCE", style["section"])
        visible_experiences = experiences[: profile["exp_items"]]
        break_after = profile.get("page_break_after_exp_items")
        for index, exp in enumerate(visible_experiences, start=1):
            title = _clean_text(exp.job_title)
            dates = ""
            if _has_value(exp.start_date) and _has_value(exp.end_date):
                dates = f"{_clean_text(exp.start_date)} - {_clean_text(exp.end_date)}"
            elif _has_value(exp.start_date):
                dates = f"{_clean_text(exp.start_date)} - Present"

            header = Table(
                [[_paragraph(title, style["job_title"]), _paragraph(dates, style["dates"])]],
                colWidths=[available_width * 0.68, available_width * 0.32],
            )
            header.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 1),
                    ]
                )
            )
            story.append(header)

            company_parts = []
            if _has_value(exp.company):
                company_parts.append(_clean_text(exp.company))
            if _has_value(exp.location):
                company_parts.append(_clean_text(exp.location))
            if company_parts:
                story.append(_paragraph(" | ".join(company_parts), style["muted"]))

            for bullet in _split_bullets(exp.description, profile["exp_bullets"], profile["bullet_chars"]):
                story.append(Paragraph(f"- {escape(bullet)}", style["bullet"]))
            story.append(Spacer(1, 0.035 * inch))
            if (
                break_after
                and index == break_after
                and len(visible_experiences) > break_after
            ):
                story.append(PageBreak())

    education = [edu for edu in (resume_data.education or []) if _has_value(edu.degree) or _has_value(edu.institution)]
    projects = [proj for proj in (resume_data.projects or []) if _has_value(proj.name) or _has_value(proj.description)]
    certifications = [cert for cert in (resume_data.certifications or []) if _has_value(cert.name) or _has_value(cert.issuer)]
    languages = [_clean_text(lang) for lang in (resume_data.languages or []) if _has_value(lang)]

    if education:
        _section(story, "EDUCATION", style["section"])
        for edu in education[: profile.get("education_items", 2)]:
            degree = _clean_text(edu.degree)
            if _has_value(edu.field_of_study):
                degree = f"{degree}, {_clean_text(edu.field_of_study)}" if degree else _clean_text(edu.field_of_study)
            years = ""
            if _has_value(edu.start_year) and _has_value(edu.end_year):
                years = f"{_clean_text(edu.start_year)} - {_clean_text(edu.end_year)}"
            elif _has_value(edu.end_year):
                years = _clean_text(edu.end_year)
            row = Table(
                [[_paragraph(degree, style["normal"]), _paragraph(years, style["dates"])]],
                colWidths=[available_width * 0.72, available_width * 0.28],
            )
            row.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            story.append(row)
            if _has_value(edu.institution):
                story.append(_paragraph(edu.institution, style["muted"]))

    if projects:
        _section(story, "PROJECTS", style["section"])
        for proj in projects[: profile["project_items"]]:
            if _has_value(proj.name):
                story.append(_paragraph(proj.name, style["job_title"]))
            for bullet in _split_bullets(proj.description, profile["project_bullets"], profile["bullet_chars"]):
                story.append(Paragraph(f"- {escape(bullet)}", style["bullet"]))
            tech = [_clean_text(item) for item in (proj.technologies or []) if _has_value(item)]
            if tech:
                story.append(_paragraph(f"Technologies: {', '.join(tech[: profile.get('tech_items', 8)])}", style["muted"]))

    certification_limit = profile.get("certification_items", 4)
    if certifications and certification_limit > 0:
        _section(story, "CERTIFICATIONS", style["section"])
        cert_text = []
        for cert in certifications[:certification_limit]:
            item = _clean_text(cert.name)
            if _has_value(cert.issuer):
                item = f"{item} - {_clean_text(cert.issuer)}" if item else _clean_text(cert.issuer)
            if _has_value(cert.year):
                item = f"{item} ({_clean_text(cert.year)})"
            if item:
                cert_text.append(item)
        if cert_text:
            story.append(_paragraph("; ".join(cert_text), style["normal"]))

    language_limit = profile.get("language_items", len(languages))
    if languages and language_limit > 0:
        _section(story, "LANGUAGES", style["section"])
        story.append(_paragraph(", ".join(languages[:language_limit]), style["normal"]))

    return story


def _build_pdf(resume_data: Resume, profile) -> tuple[bytes, int]:
    buffer = io.BytesIO()
    margin = profile["margin"] * inch
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
    )

    page_count = {"value": 1}

    class CountingCanvas(canvas.Canvas):
        def showPage(self):
            page_count["value"] += 1
            super().showPage()

        def save(self):
            super().save()

    story = _build_story(resume_data, doc, profile)
    doc.build(story, canvasmaker=CountingCanvas)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes, page_count["value"]


def create_resume_pdf(resume_data: Resume) -> bytes:
    """
    Generates a concise ATS-friendly PDF resume from the provided Resume data object.
    The primary builder emits exactly two pages with a deterministic layout.
    """
    try:
        return _build_canvas_two_page_pdf(resume_data)
    except Exception as exc:
        logging.error("Error building deterministic two-page PDF: %s", exc)

    last_pdf = b""
    last_pages = 0
    best_under_limit_pdf = b""
    best_under_limit_pages = 0

    for profile in DENSITY_PROFILES:
        try:
            pdf_bytes, pages = _build_pdf(resume_data, profile)
            logging.info("PDF generated with %s profile: %s page(s).", profile["name"], pages)
            last_pdf, last_pages = pdf_bytes, pages
            if pages == MAX_PAGES or (
                profile.get("page_break_after_exp_items") and pages == MAX_PAGES + 1
            ):
                return pdf_bytes
            if pages < MAX_PAGES and not best_under_limit_pdf:
                best_under_limit_pdf = pdf_bytes
                best_under_limit_pages = pages
        except Exception as exc:
            logging.error("Error building PDF with %s profile: %s", profile["name"], exc)
            raise

    if best_under_limit_pdf:
        logging.warning(
            "Generated resume stayed at %s page(s) after all layouts; returning best under-limit version.",
            best_under_limit_pages,
        )
        return best_under_limit_pdf

    emergency_profile = {
        **DENSITY_PROFILES[-1],
        "name": "emergency_fit",
        "margin": 0.2,
        "name_size": 13,
        "normal_size": 6.2,
        "normal_leading": 6.9,
        "section_size": 7.0,
        "bullet_size": 6.1,
        "bullet_leading": 6.8,
        "exp_items": 1,
        "exp_bullets": 0,
        "project_items": 0,
        "project_bullets": 0,
        "skills": 4,
        "summary_chars": 120,
        "bullet_chars": 60,
        "education_items": 0,
        "certification_items": 0,
        "language_items": 0,
        "tech_items": 0,
    }
    pdf_bytes, pages = _build_pdf(resume_data, emergency_profile)
    logging.warning("PDF generated with %s profile: %s page(s).", emergency_profile["name"], pages)
    if pages <= MAX_PAGES:
        return pdf_bytes

    contact_only_resume = resume_data.model_copy(deep=True)
    contact_only_resume.summary = ""
    contact_only_resume.skills = []
    contact_only_resume.experience = []
    contact_only_resume.education = []
    contact_only_resume.projects = []
    contact_only_resume.certifications = []
    contact_only_resume.languages = []
    pdf_bytes, pages = _build_pdf(contact_only_resume, emergency_profile)
    logging.error(
        "Resume content exceeded %s pages even after emergency trimming; returned contact-only fallback with %s page(s).",
        MAX_PAGES,
        pages,
    )
    return pdf_bytes
