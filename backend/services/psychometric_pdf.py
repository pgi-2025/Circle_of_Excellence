"""PDF rendering for psychometric reports (reportlab). `private=True` adds admin-only details."""
import io
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

GREEN, GOLD, INK, SOFT, LINE = colors.HexColor("#2E7D32"), colors.HexColor("#B8860B"), colors.HexColor("#1A2313"), colors.HexColor("#5C6650"), colors.HexColor("#EAE3C4")
INTEGRITY_COLOR = {"clear": GREEN, "review": GOLD, "flagged": colors.HexColor("#C0392B")}


def _bar(score, width=95 * mm):
    d = Drawing(width, 9)
    d.add(Rect(0, 0, width, 9, fillColor=LINE, strokeColor=None))
    d.add(Rect(0, 0, width * max(0, min(100, score)) / 100, 9, fillColor=GREEN if score >= 60 else GOLD, strokeColor=None))
    return d


def _fmt_date(iso):
    return (iso or "")[:10]


def build_pdf(rep: dict, private: bool = False) -> bytes:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=10, leading=14, textColor=INK)
    small = ParagraphStyle("s", parent=body, fontSize=8.5, textColor=SOFT)
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=20, textColor=GREEN, alignment=0, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12.5, textColor=GREEN, spaceBefore=12, spaceAfter=5)
    P = lambda t, st=body: Paragraph(escape(str(t if t is not None else "-")), st)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title="Campus Ambassador Psychometric Report", author="Circle of Excellence")
    el = [Paragraph("Campus Ambassador Psychometric Report", h1), P("Circle of Excellence", small), Spacer(1, 8)]

    head = [[P("Candidate", small), P(rep["candidate_name"], body), P("Assessment date", small), P(_fmt_date(rep["assessment_date"]), body)],
            [P("Overall score", small), Paragraph(f'<font size="18" color="#2E7D32"><b>{rep["overall_score"]}%</b></font>', body),
             P("Completion", small), P(rep["completion_status"], body)]]
    t = Table(head, colWidths=[28 * mm, 60 * mm, 32 * mm, 54 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                           ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFDF5")), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    el += [t, Paragraph("Dimension scores", h2)]

    rows = [[P(d["label"], body), _bar(d["score"]), P(f'{d["score"]}%', body)] for d in rep["dimensions"]]
    dt = Table(rows, colWidths=[52 * mm, 100 * mm, 20 * mm])
    dt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE)]))
    el.append(dt)

    el.append(Paragraph("Strengths", h2))
    for s in rep["strengths"] or [{"label": "None identified", "score": "-", "text": ""}]:
        el.append(P(f'{s["label"]} ({s["score"]}%): {s["text"]}' if s["text"] else s["label"]))
        el.append(Spacer(1, 3))
    el.append(Paragraph("Development areas", h2))
    for s in rep["development_areas"] or [{"label": "No major development areas identified", "score": "-", "text": ""}]:
        el.append(P(f'{s["label"]} ({s["score"]}%): {s["text"]}' if s["text"] else s["label"]))
        el.append(Spacer(1, 3))

    el.append(Paragraph("Overall assessment", h2))
    el.append(P(rep["summary"]))

    el.append(Paragraph("Integrity monitoring", h2))
    col = INTEGRITY_COLOR.get(rep["integrity_status"], INK).hexval()[2:]
    el.append(Paragraph(f'<font color="#{col}"><b>{escape(rep["integrity_label"])}</b></font>', body))
    el.append(P("Integrity monitoring records browser-side events (tab switches, focus loss, fullscreen exit, copy/paste and similar) "
                "and cannot guarantee that no assistance was used. It is an indicator for human review, not proof.", small))

    if private:
        c = rep["candidate"]
        el.append(Paragraph("Candidate details (admin only)", h2))
        info = [[P(k, small), P(c.get(f))] for k, f in (("Email", "email"), ("Phone", "phone"), ("College", "college"), ("Department", "department"),
                                                          ("Year", "year"), ("City", "city"), ("Social", "social"), ("Students reachable", "reach"))]
        it = Table(info, colWidths=[38 * mm, 134 * mm])
        it.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        el.append(it)
        el.append(Paragraph(f'Violations ({rep["violation_count"]})', h2))
        if rep["violations"]:
            vt = Table([[P("Time (UTC)", small), P("Type", small), P("Detail", small)]] +
                       [[P((v["occurred_at"] or "")[:19].replace("T", " ")), P(v["kind"]), P(v.get("detail") or "")] for v in rep["violations"][:60]],
                       colWidths=[42 * mm, 38 * mm, 92 * mm])
            vt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            el.append(vt)
        else:
            el.append(P("None recorded."))
        for n in rep.get("integrity_notes") or []:
            el.append(P("- " + n, small))

    doc.build(el)
    return buf.getvalue()
