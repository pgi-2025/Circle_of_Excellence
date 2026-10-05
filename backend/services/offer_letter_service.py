"""Offer letters (PDF) for interns and campus ambassadors.

Layout replicates the Plant Green Inertia offer letter: letterhead image as the page
background, "OFFER LETTER" title, right-aligned date, To / Subject / body, work details,
"Warm Regards" block, then an acceptance page. Only the wording changes per audience.

Edit the wording in the two `_intern_*` / `_ambassador_*` functions below; layout lives in `_render`.
"""
import io
import os
import re
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Frame, NextPageTemplate, PageBreak, PageTemplate, Paragraph, Spacer

from services.supabase_client import get_supabase

LETTERHEAD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "offer_letterhead.jpg")
COMPANY = "Plant Green Inertia Pvt. Ltd."
PAGE_W, PAGE_H = letter  # 612 x 792, same as the original

# --- layout constants measured from the original letter (points) ---
LEFT, RIGHT_EDGE = 72, 610  # text wraps at 610 (page is 612 wide)
TITLE_CENTER_EDGE = 615  # original centres the title across 72..615
BOTTOM = 62  # keeps text clear of the footer band
P1_TOP, P2_TOP = 147, 158  # distance from page top to the first line on page 1 / page 2
DATE_RIGHT = 555.7  # right edge of the date line

_IST = timezone(timedelta(hours=5, minutes=30))
_BASE = dict(fontName="Times-Roman", fontSize=11, leading=12.65, spaceAfter=12)
BODY = ParagraphStyle("body", **_BASE)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Times-Bold", fontSize=13, leading=14.95, alignment=TA_CENTER, rightIndent=RIGHT_EDGE - TITLE_CENTER_EDGE, spaceAfter=11)
DATE = ParagraphStyle("date", parent=BODY, alignment=TA_RIGHT, rightIndent=RIGHT_EDGE - DATE_RIGHT, spaceAfter=12)
HEAD12 = ParagraphStyle("head12", parent=BODY, fontName="Times-Bold", fontSize=12, leading=13.8, spaceAfter=12)
SIGNATORY = ParagraphStyle("signatory", parent=HEAD12, spaceAfter=15)


def _e(v):
    return escape(str(v).strip())


def _ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _to_ist(iso):
    try:
        s = (iso or "").strip()
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_IST)
    except Exception:  # noqa: BLE001 - missing/odd timestamp: fall back to today
        return datetime.now(_IST)


def _dates(iso):
    d = _to_ist(iso)
    return d.strftime("%d/%m/%Y"), f"{_ordinal(d.day)} {d.strftime('%B %Y')}"


def _render(d: dict) -> bytes:
    """d keys: name, address_lines, subject, role, kind_word, paras (list of markup strings),
    details (list of (label, value)), closing_noun, letter_date."""
    buf = io.BytesIO()

    def bg(canv, _doc):
        # Header + footer are the same letterhead image drawn twice, each clipped to its own strip
        # (placement copied from the original PGI offer letter PDF, so the bands land identically).
        canv.saveState()
        p = canv.beginPath(); p.rect(1.875, 661.5, 608.25, 129); canv.clipPath(p, stroke=0, fill=0)
        canv.drawImage(LETTERHEAD, 1.875, 43.696, width=608.25, height=746.804)
        canv.restoreState()
        canv.saveState()
        p = canv.beginPath(); p.rect(1.5, 11.428, 609, 60); canv.clipPath(p, stroke=0, fill=0)
        canv.drawImage(LETTERHEAD, 1.5, 11.428, width=609, height=794.668)
        canv.restoreState()

    def frame(top):
        return Frame(LEFT, BOTTOM, RIGHT_EDGE - LEFT, PAGE_H - top - BOTTOM, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)

    doc = BaseDocTemplate(buf, pagesize=letter, title=f"Offer Letter - {d['name']}", author=COMPANY)
    doc.addPageTemplates([
        PageTemplate(id="p1", frames=[frame(P1_TOP)], onPage=bg, autoNextPageTemplate="p2"),
        PageTemplate(id="p2", frames=[frame(P2_TOP)], onPage=bg),
    ])

    name = _e(d["name"])
    P = lambda t, st=BODY: Paragraph(t, st)
    el = [
        P("<b>OFFER LETTER</b>", TITLE),
        P(f"<b>Date:</b> {d['letter_date']}", DATE),
        P("<b>To:</b><br/><b>" + name + "</b>" + "".join(f"<br/>{_e(x)}" for x in d["address_lines"])),
        P(f"<b>Subject: {_e(d['subject'])}</b>"),
        P(f"Dear {name},"),
    ]
    el += [P(p) for p in d["paras"]]
    el.append(P("<br/>".join(f"<b>{_e(k)}:</b> {_e(v)}" for k, v in d["details"])))
    el.append(P(
        f"You are expected to maintain professional conduct and comply with all company policies, confidentiality requirements, "
        f"and ethical standards throughout your {d['closing_noun']}. We are pleased to welcome you to {COMPANY} "
        f"and look forward to your valuable contributions to our organization."
    ))
    el.append(P("Kindly confirm your acceptance of this offer by signing below and returning a copy of this letter."))
    el.append(Spacer(1, 0.5))
    el.append(P(f"<b>Warm Regards,<br/>{COMPANY}</b>"))
    # page 2: acceptance
    el += [
        PageBreak(),
        P("Authorized Signatory", SIGNATORY),
        P("Acceptance of Offer", HEAD12),
        P(f"I, <b>{name}</b>, hereby accept the offer of {d['kind_word']} as <b>{_e(d['role'])}</b> "
          f"and agree to the terms and conditions stated in this letter."),
        P("Signature:", HEAD12),
        P("Date:", HEAD12),
    ]
    doc.build(el)
    return buf.getvalue()


def _clean_program(name):
    return re.sub(r"\s+intern(ship)?$", "", (name or "Internship Program").strip(), flags=re.I) or "Internship Program"


# ----------------------------------------------------------------------------------------------
# Interns
# ----------------------------------------------------------------------------------------------
def _intern_letter(user: dict, enr: dict) -> bytes:
    prog = enr.get("programs") or {}
    role = f"{_clean_program(prog.get('name'))} Intern"
    letter_date, start = _dates(enr.get("enrolled_at"))
    weeks, mode = prog.get("duration_weeks"), (prog.get("mode") or "Remote")
    duration = f"{weeks}-week " if weeks else ""
    lines = [x for x in (user.get("college"), user.get("email")) if x]
    return _render({
        "name": user.get("full_name") or user.get("email") or "Intern",
        "address_lines": lines,
        "subject": f"Offer of Internship \u2013 {role}",
        "role": role,
        "kind_word": "internship",
        "closing_noun": "internship",
        "letter_date": letter_date,
        "paras": [
            f"We are pleased to offer you the position of <b>{_e(role)}</b> at <b>{COMPANY}</b> through the Circle of "
            f"Excellence Internship Program. Your internship will commence on <b>{start}</b>.",
            f"You will undergo a <b>{duration}{_e(mode.lower())} training internship</b>, during which you will progress through "
            f"the program milestones: enrollment confirmation, an onboarding call with your mentor, two project milestones "
            f"and a final capstone project.",
            f"Upon successful completion of all program milestones, you will be awarded a verifiable Internship Certificate "
            f"by {COMPANY}",
            f"As an Intern, your responsibilities will include attending the onboarding call, completing the assigned projects "
            f"and milestones within the program timeline, documenting your work, and other program-related activities "
            f"assigned by your mentor.",
        ],
        "details": [("Work Location", mode), ("Working Hours", "As per the program schedule"), ("Working Days", "As per the program schedule")],
    })


def get_intern_offer_letter(user_id: str):
    """Returns (pdf_bytes, filename). Only for enrolled interns whose enrollment is paid or free."""
    supa = get_supabase()
    rows = (
        supa.table("enrollments").select("*, programs(name, duration_weeks, mode)")
        .eq("user_id", user_id).order("enrolled_at", desc=True).limit(1).execute().data
    )
    if not rows:
        raise ValueError("No internship enrollment found.")
    enr = rows[0]
    if enr.get("payment_status") not in ("paid", "free"):
        raise PermissionError("Your offer letter is available once your enrollment payment is confirmed.")
    user = supa.table("users").select("full_name, email, college").eq("id", user_id).single().execute().data or {}
    return _intern_letter(user, enr), _filename("Internship_Offer_Letter", user.get("full_name"))


# ----------------------------------------------------------------------------------------------
# Campus ambassadors
# ----------------------------------------------------------------------------------------------
def _ambassador_letter(amb: dict) -> bytes:
    letter_date, start = _dates(amb.get("created_at"))
    college, city = (amb.get("college") or "").strip(), (amb.get("city") or "").strip()
    at_college = f" at <b>{_e(college)}</b>" if college else " on your campus"
    location = ", ".join(x for x in (college, city) if x) or "Your college campus"
    return _render({
        "name": amb.get("full_name") or "Campus Ambassador",
        "address_lines": [x for x in (college, city, amb.get("email")) if x],
        "subject": "Offer of Engagement \u2013 Campus Ambassador",
        "role": "Campus Ambassador",
        "kind_word": "engagement",
        "closing_noun": "engagement",
        "letter_date": letter_date,
        "paras": [
            f"We are pleased to offer you the position of <b>Campus Ambassador</b> at <b>{COMPANY}</b>, representing the "
            f"Circle of Excellence Internship Program{at_college}. Your engagement will commence on <b>{start}</b>.",
            f"Your Ambassador Code is <b>{_e(amb.get('ambassador_code') or '-')}</b>. Students who register using your code are "
            f"credited to you as referrals. This is a voluntary, reward-based engagement: you will earn XP for referrals, "
            f"campaigns and events, redeemable for rewards, and you will be eligible for a verifiable Campus Ambassador Certificate.",
            "As a Campus Ambassador, your responsibilities will include promoting our internship programs on your campus, "
            "helping students discover opportunities, participating in the campaigns and events assigned to you, and other "
            "ambassador activities assigned by the company.",
        ],
        "details": [("Work Location", location), ("Working Hours", "Flexible, alongside your academics"), ("Working Days", "Flexible")],
    })


def get_ambassador_offer_letter(ambassador_id: str):
    """Returns (pdf_bytes, filename). Ambassador accounts only exist after approval."""
    supa = get_supabase()
    amb = supa.table("ambassadors").select("*").eq("id", ambassador_id).single().execute().data
    if not amb:
        raise ValueError("Ambassador not found.")
    return _ambassador_letter(amb), _filename("Campus_Ambassador_Offer_Letter", amb.get("full_name"))


def _filename(prefix, name):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_")
    return f"{prefix}_{slug}.pdf" if slug else f"{prefix}.pdf"
