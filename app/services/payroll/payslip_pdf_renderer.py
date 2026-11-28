"""Corporate A4 Enterprise Salary Slip PDF Renderer using ReportLab & bundled Unicode fonts."""
from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.payroll.payslip_formatter import (
    amount_in_words,
    format_currency,
    quantize_money,
)

logger = logging.getLogger(__name__)

_FONTS_REGISTERED = False
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"
FONT_BOLD_ITALIC = "Helvetica-BoldOblique"


def _ensure_fonts_registered() -> tuple[str, str, str, str]:
    """Register bundled DejaVuSans Unicode fonts (supporting ₹ U+20B9) once per process."""
    global _FONTS_REGISTERED, FONT_REGULAR, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC
    if _FONTS_REGISTERED:
        return FONT_REGULAR, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC

    # Prefer bundled repo fonts under app/assets/fonts
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    font_dir = os.path.join(app_dir, "assets", "fonts")
    candidates = {
        "regular": os.path.join(font_dir, "DejaVuSans.ttf"),
        "bold": os.path.join(font_dir, "DejaVuSans-Bold.ttf"),
        "italic": os.path.join(font_dir, "DejaVuSans-Oblique.ttf"),
        "bold_italic": os.path.join(font_dir, "DejaVuSans-BoldOblique.ttf"),
    }
    if all(os.path.isfile(p) for p in candidates.values()):
        try:
            pdfmetrics.registerFont(TTFont("OFC360Sans", candidates["regular"]))
            pdfmetrics.registerFont(TTFont("OFC360Sans-Bold", candidates["bold"]))
            pdfmetrics.registerFont(TTFont("OFC360Sans-Italic", candidates["italic"]))
            pdfmetrics.registerFont(TTFont("OFC360Sans-BoldItalic", candidates["bold_italic"]))
            registerFontFamily(
                "OFC360Sans",
                normal="OFC360Sans",
                bold="OFC360Sans-Bold",
                italic="OFC360Sans-Italic",
                boldItalic="OFC360Sans-BoldItalic",
            )
            FONT_REGULAR = "OFC360Sans"
            FONT_BOLD = "OFC360Sans-Bold"
            FONT_ITALIC = "OFC360Sans-Italic"
            FONT_BOLD_ITALIC = "OFC360Sans-BoldItalic"
            _FONTS_REGISTERED = True
            return FONT_REGULAR, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC
        except Exception as exc:
            logger.warning("Failed registering bundled DejaVuSans fonts, falling back: %s", exc)

    _FONTS_REGISTERED = True
    return FONT_REGULAR, FONT_BOLD, FONT_ITALIC, FONT_BOLD_ITALIC


def _safe_hex_color(value: str | None, fallback: str) -> colors.Color:
    try:
        if value:
            return colors.HexColor(str(value).strip())
    except Exception:
        pass
    return colors.HexColor(fallback)


class _PayslipNumberedCanvas(rl_canvas.Canvas):
    """Two-pass A4 canvas drawing confidential footer, page X of Y, and optional DRAFT watermark."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._meta = kwargs.pop("payslip_meta", {})
        super().__init__(*args, **kwargs)
        self._saved_page_states: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_chrome(total_pages)
            rl_canvas.Canvas.showPage(self)
        rl_canvas.Canvas.save(self)

    def _draw_chrome(self, total_pages: int) -> None:
        page_w, page_h = A4
        margin_x = 15 * mm
        meta = self._meta
        font_reg, font_bold, _, _ = _ensure_fonts_registered()

        # Draft watermark when unfinalized
        if meta.get("is_draft"):
            self.saveState()
            self.translate(page_w / 2.0, page_h / 2.0)
            self.rotate(38)
            self.setFillColor(colors.Color(0.55, 0.58, 0.65, alpha=0.14))
            self.setFont(font_bold, 64)
            self.drawCentredString(0, 0, "DRAFT — PROVISIONAL")
            self.restoreState()

        # Footer divider line & metadata
        self.saveState()
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.6)
        self.line(margin_x, 14.5 * mm, page_w - margin_x, 14.5 * mm)

        self.setFillColor(colors.HexColor("#64748B"))
        self.setFont(font_reg, 6.8)
        footer_decl = str(
            meta.get("footer_declaration")
            or "This is a confidential payroll document intended solely for the authorized employee."
        )
        company_name = str(meta.get("company_name") or "")
        doc_ref = str(meta.get("document_id") or meta.get("payslip_number") or "")
        gen_dt = str(meta.get("generated_display") or "")

        left_line1 = footer_decl[:105]
        self.drawString(margin_x, 11.2 * mm, left_line1)

        left_parts = [p for p in [company_name, f"Ref: {doc_ref}" if doc_ref else "", f"Generated: {gen_dt}" if gen_dt else ""] if p]
        self.setFont(font_reg, 6.5)
        self.drawString(margin_x, 7.6 * mm, "  |  ".join(left_parts)[:115])

        self.setFont(font_bold, 6.8)
        self.drawRightString(page_w - margin_x, 11.2 * mm, f"Page {self._pageNumber} of {total_pages}")

        if meta.get("show_ofc360_footer", True):
            self.setFont(font_reg, 6.5)
            self.drawRightString(page_w - margin_x, 7.6 * mm, "Powered by OFC360 Payroll Management System")

        self.restoreState()


def _load_image_flowable(
    asset_url_or_path: str | None,
    *,
    max_width: float,
    max_height: float,
) -> Optional[Image]:
    """Load an image strictly from safe local UPLOAD_DIR with aspect-ratio scaling."""
    from app.services.payroll.payslip_settings_service import resolve_safe_local_image_path

    resolved = resolve_safe_local_image_path(asset_url_or_path)
    if not resolved:
        return None
    try:
        reader = ImageReader(resolved)
        iw, ih = reader.getSize()
        if iw <= 0 or ih <= 0:
            return None
        scale = min(max_width / float(iw), max_height / float(ih), 1.0)
        return Image(resolved, width=iw * scale, height=ih * scale)
    except Exception as exc:
        logger.warning("Skipping unreadable local image asset %s: %s", asset_url_or_path, exc)
        return None


def _initials_badge(company_name: str, primary_color: colors.Color) -> Drawing:
    """Create a clean corporate monogram Drawing when no logo image is configured."""
    words = [w for w in str(company_name or "CO").strip().split() if w and w[0].isalnum()]
    initials = "".join(w[0].upper() for w in words[:2]) or "CO"
    if len(initials) == 1 and words and len(words[0]) > 1:
        initials = words[0][:2].upper()

    size = 13.5 * mm
    d = Drawing(size, size)
    from reportlab.graphics.shapes import Rect, String

    d.add(Rect(0, 0, size, size, rx=2.2 * mm, ry=2.2 * mm, fillColor=primary_color, strokeColor=None))
    font_reg, font_bold, _, _ = _ensure_fonts_registered()
    d.add(
        String(
            size / 2.0,
            size * 0.34,
            initials,
            textAnchor="middle",
            fontName=font_bold,
            fontSize=12.5,
            fillColor=colors.white,
        )
    )
    return d


def _qr_drawing(url: str, size_pt: float = 20 * mm, accent_hex: str = "#182C43") -> Drawing:
    """Render a crisp vector QR code linking strictly to the verification endpoint."""
    qr = QrCodeWidget(url, barFillColor=_safe_hex_color(accent_hex, "#182C43"), barBorder=1)
    bounds = qr.getBounds()
    w = max(1.0, bounds[2] - bounds[0])
    h = max(1.0, bounds[3] - bounds[1])
    d = Drawing(size_pt, size_pt, transform=[size_pt / w, 0, 0, size_pt / h, 0, 0])
    d.add(qr)
    return d


def validate_financial_reconciliation(snapshot: dict[str, Any]) -> None:
    """Verify exact Decimal parity across itemized earnings, deductions, and net payable."""
    earnings_items = snapshot.get("earnings", [])
    deduction_items = snapshot.get("deductions", [])
    totals = snapshot.get("totals", {})

    expected_gross = quantize_money(totals.get("gross_earnings"))
    expected_ded = quantize_money(totals.get("total_deductions"))
    expected_net = quantize_money(totals.get("net_pay"))

    calc_gross = quantize_money(sum((quantize_money(item.get("amount")) for item in earnings_items), Decimal("0.00")))
    calc_ded = quantize_money(sum((quantize_money(item.get("amount")) for item in deduction_items), Decimal("0.00")))

    if calc_gross != expected_gross:
        raise ValueError(
            f"Payslip reconciliation mismatch: itemized earnings ({calc_gross}) != gross_earnings ({expected_gross})"
        )
    if calc_ded != expected_ded:
        raise ValueError(
            f"Payslip reconciliation mismatch: itemized deductions ({calc_ded}) != total_deductions ({expected_ded})"
        )
    if quantize_money(expected_gross - expected_ded) != expected_net:
        raise ValueError(
            f"Payslip reconciliation mismatch: gross ({expected_gross}) - deductions ({expected_ded}) != net_pay ({expected_net})"
        )


def render_enterprise_payslip_pdf(snapshot: dict[str, Any]) -> bytes:
    """Render a complete corporate A4 Portrait Salary Slip PDF directly from snapshot data."""
    validate_financial_reconciliation(snapshot)
    font_reg, font_bold, font_italic, _ = _ensure_fonts_registered()

    company = snapshot.get("company", {})
    employee = snapshot.get("employee", {})
    bank_stat = snapshot.get("bank_statutory", {})
    attendance = snapshot.get("attendance", {})
    totals = snapshot.get("totals", {})
    earnings = snapshot.get("earnings", [])
    deductions = snapshot.get("deductions", [])
    employer_contribs = snapshot.get("employer_contributions", [])
    ytd = snapshot.get("ytd_summary")
    hr_info = snapshot.get("hr_support", {})
    signatory = snapshot.get("signatory", {})
    verification = snapshot.get("verification", {})
    options = snapshot.get("display_options", {})

    currency = str(totals.get("currency") or "INR").upper()
    primary_hex = str(company.get("primary_color") or "#182C43")
    secondary_hex = str(company.get("secondary_color") or "#F5F7FA")
    accent_hex = str(company.get("accent_color") or "#0B665C")

    c_primary = _safe_hex_color(primary_hex, "#182C43")
    c_secondary_bg = _safe_hex_color(secondary_hex, "#F5F7FA")
    c_text_primary = colors.HexColor("#17212F")
    c_text_secondary = colors.HexColor("#64748B")
    c_border = colors.HexColor("#E2E8F0")
    c_accent_net = _safe_hex_color(accent_hex, "#0B665C")

    page_w, page_h = A4
    margin_x = 15 * mm
    usable_w = page_w - 2 * margin_x  # 180 mm

    base_styles = getSampleStyleSheet()
    s_company_title = ParagraphStyle(
        "OFCCompanyTitle", parent=base_styles["Normal"],
        fontName=font_bold, fontSize=12.5, leading=15, textColor=c_primary, alignment=TA_LEFT,
    )
    s_company_sub = ParagraphStyle(
        "OFCCompanySub", parent=base_styles["Normal"],
        fontName=font_reg, fontSize=7.4, leading=10, textColor=c_text_secondary, alignment=TA_LEFT,
    )
    s_slip_title = ParagraphStyle(
        "OFCSlipTitle", parent=base_styles["Normal"],
        fontName=font_bold, fontSize=12.5, leading=15, textColor=c_primary, alignment=TA_RIGHT,
    )
    s_slip_sub = ParagraphStyle(
        "OFCSlipSub", parent=base_styles["Normal"],
        fontName=font_reg, fontSize=7.6, leading=10.5, textColor=c_text_secondary, alignment=TA_RIGHT,
    )
    s_sec_hdr = ParagraphStyle(
        "OFCSecHdr", parent=base_styles["Normal"],
        fontName=font_bold, fontSize=7.4, leading=9.5, textColor=c_primary,
    )
    s_lbl = ParagraphStyle(
        "OFCLbl", parent=base_styles["Normal"],
        fontName=font_reg, fontSize=7.3, leading=9.5, textColor=c_text_secondary,
    )
    s_val = ParagraphStyle(
        "OFCVal", parent=base_styles["Normal"],
        fontName=font_bold, fontSize=7.5, leading=9.8, textColor=c_text_primary,
    )
    s_tbl_hdr_l = ParagraphStyle(
        "OFCTblHdrL", parent=base_styles["Normal"],
        fontName=font_bold, fontSize=7.5, leading=10, textColor=colors.white, alignment=TA_LEFT,
    )
    s_tbl_hdr_r = ParagraphStyle(
        "OFCTblHdrR", parent=base_styles["Normal"],
        fontName=font_bold, fontSize=7.5, leading=10, textColor=colors.white, alignment=TA_RIGHT,
    )
    s_row_l = ParagraphStyle(
        "OFCRowL", parent=base_styles["Normal"],
        fontName=font_reg, fontSize=7.5, leading=10, textColor=c_text_primary, alignment=TA_LEFT,
    )
    s_row_r = ParagraphStyle(
        "OFCRowR", parent=base_styles["Normal"],
        fontName=font_reg, fontSize=7.5, leading=10, textColor=c_text_primary, alignment=TA_RIGHT,
    )
    s_row_bold_l = ParagraphStyle(
        "OFCRowBL", parent=s_row_l, fontName=font_bold, textColor=c_primary,
    )
    s_row_bold_r = ParagraphStyle(
        "OFCRowBR", parent=s_row_r, fontName=font_bold, textColor=c_primary,
    )
    s_small_muted = ParagraphStyle(
        "OFCSmallMuted", parent=base_styles["Normal"],
        fontName=font_reg, fontSize=7.0, leading=9.5, textColor=c_text_secondary,
    )
    s_small_italic = ParagraphStyle(
        "OFCSmallItalic", parent=base_styles["Normal"],
        fontName=font_italic, fontSize=6.9, leading=9.3, textColor=c_text_secondary,
    )

    buffer = io.BytesIO()
    payslip_num = str(verification.get("payslip_number") or employee.get("payslip_number") or "PAYSLIP")
    period_label = str(employee.get("period_label") or "")

    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=margin_x,
        rightMargin=margin_x,
        topMargin=13 * mm,
        bottomMargin=17.5 * mm,
        title=f"Salary Slip {period_label} - {payslip_num}",
        author=str(company.get("name") or "OFC360 Payroll"),
    )
    frame = Frame(margin_x, 17.5 * mm, usable_w, page_h - 30.5 * mm, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="main")
    doc.addPageTemplates([PageTemplate(id="PayslipPage", frames=[frame])])

    story: list[Any] = []

    # ── 1. HEADER SECTION (Company Logo/Monogram + Legal/Address + Slip Title/Number) ──
    company_display = str(company.get("name") or "Organization")
    legal_name = company.get("legal_name")
    logo_img = _load_image_flowable(company.get("logo_url"), max_width=24 * mm, max_height=14 * mm)
    left_visual: Any = logo_img if logo_img is not None else _initials_badge(company_display, c_primary)

    addr_parts = [
        p for p in [
            company.get("registered_address"),
            ", ".join(x for x in [company.get("city"), company.get("state"), company.get("postal_code")] if x),
            company.get("country"),
        ]
        if p
    ]
    contact_parts = [p for p in [company.get("official_email"), company.get("official_phone"), company.get("website")] if p]
    reg_parts = []
    if company.get("cin_number"):
        reg_parts.append(f"CIN: {company['cin_number']}")
    if company.get("gstin"):
        reg_parts.append(f"GSTIN: {company['gstin']}")
    if company.get("pf_establishment_code"):
        reg_parts.append(f"PF Code: {company['pf_establishment_code']}")
    if company.get("esic_registration_number"):
        reg_parts.append(f"ESIC Code: {company['esic_registration_number']}")

    co_lines = [Paragraph(escape(company_display), s_company_title)]
    if legal_name and str(legal_name).strip().lower() != company_display.strip().lower():
        co_lines.append(Paragraph(f"<i>{escape(str(legal_name))}</i>", s_company_sub))
    if addr_parts:
        co_lines.append(Paragraph(escape(" | ".join(addr_parts)), s_company_sub))
    if contact_parts:
        co_lines.append(Paragraph(escape("  •  ".join(contact_parts)), s_company_sub))
    if reg_parts:
        co_lines.append(Paragraph(escape("  |  ".join(reg_parts)), s_company_sub))

    co_text_tbl = Table([[line] for line in co_lines], colWidths=[96 * mm])
    co_text_tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
    ]))

    co_brand_tbl = Table([[left_visual, co_text_tbl]], colWidths=[16 * mm if logo_img is None else 25 * mm, 96 * mm if logo_img is None else 87 * mm])
    co_brand_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    is_draft = bool(verification.get("is_draft"))
    doc_status = "DRAFT STATEMENT" if is_draft else f"OFFICIAL PAYSLIP"
    if not is_draft and verification.get("version_number", 1) > 1:
        doc_status += f" (v{verification['version_number']})"

    right_lines = [
        Paragraph("SALARY SLIP", s_slip_title),
        Paragraph(f"<b>{escape(period_label.upper())}</b>", ParagraphStyle("PPeriod", parent=s_slip_sub, fontName=font_bold, fontSize=8.5, textColor=c_accent_net)),
        Paragraph(f"Payslip No: <b>{escape(payslip_num)}</b>", s_slip_sub),
        Paragraph(escape(doc_status), ParagraphStyle("PStat", parent=s_slip_sub, fontSize=6.8, textColor=c_text_secondary)),
    ]
    right_tbl = Table([[line] for line in right_lines], colWidths=[66 * mm])
    right_tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
    ]))

    hdr_table = Table([[co_brand_tbl, right_tbl]], colWidths=[114 * mm, 66 * mm])
    hdr_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 1.6, c_primary),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(hdr_table)
    story.append(Spacer(1, 3.2 * mm))

    # ── 2. EMPLOYEE & PAY PERIOD TWO-COLUMN SECTION ──
    emp_rows = [
        [
            Paragraph("Employee Name", s_lbl), Paragraph(escape(str(employee.get("full_name") or "—")), s_val),
            Paragraph("Payroll Month", s_lbl), Paragraph(escape(period_label or "—"), s_val),
        ],
        [
            Paragraph("Employee Code", s_lbl), Paragraph(escape(str(employee.get("employee_code") or "—")), s_val),
            Paragraph("Pay Period", s_lbl), Paragraph(escape(str(employee.get("pay_period_range") or "—")), s_val),
        ],
        [
            Paragraph("Department", s_lbl), Paragraph(escape(str(employee.get("department") or "—")), s_val),
            Paragraph("Payment Date", s_lbl), Paragraph(escape(str(employee.get("payment_date_display") or "Pending Disbursement")), s_val),
        ],
        [
            Paragraph("Designation", s_lbl), Paragraph(escape(str(employee.get("designation") or "—")), s_val),
            Paragraph("Payment Mode", s_lbl), Paragraph(escape(str(employee.get("payment_mode") or "—")), s_val),
        ],
        [
            Paragraph("Employment Type", s_lbl), Paragraph(escape(str(employee.get("employment_type") or "—")), s_val),
            Paragraph("Work Location", s_lbl), Paragraph(escape(str(employee.get("work_location") or "—")), s_val),
        ],
        [
            Paragraph("Date of Joining", s_lbl), Paragraph(escape(str(employee.get("joining_date_display") or "—")), s_val),
            Paragraph("Payslip Ref", s_lbl), Paragraph(escape(payslip_num), s_val),
        ],
    ]
    emp_tbl = Table(emp_rows, colWidths=[28 * mm, 62 * mm, 28 * mm, 62 * mm])
    emp_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_secondary_bg),
        ("BOX", (0, 0), (-1, -1), 0.6, c_border),
        ("LINEBEFORE", (2, 0), (2, -1), 0.5, c_border),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.0),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(emp_tbl)
    story.append(Spacer(1, 2.5 * mm))

    # ── 3. BANK & STATUTORY DETAILS ──
    stat_pairs: list[tuple[str, str]] = []
    if bank_stat.get("bank_name"):
        stat_pairs.append(("Bank Name", str(bank_stat["bank_name"])))
    if bank_stat.get("masked_account_number"):
        stat_pairs.append(("Bank A/C No.", str(bank_stat["masked_account_number"])))
    if bank_stat.get("masked_pan"):
        stat_pairs.append(("PAN", str(bank_stat["masked_pan"])))
    if bank_stat.get("masked_uan"):
        stat_pairs.append(("UAN", str(bank_stat["masked_uan"])))
    if bank_stat.get("pf_member_number"):
        stat_pairs.append(("PF Member ID", str(bank_stat["pf_member_number"])))
    if bank_stat.get("esic_number"):
        stat_pairs.append(("ESIC Number", str(bank_stat["esic_number"])))
    if bank_stat.get("tax_regime"):
        stat_pairs.append(("Tax Regime", str(bank_stat["tax_regime"]).upper()))

    if stat_pairs:
        bank_rows: list[list[Any]] = []
        for idx in range(0, len(stat_pairs), 3):
            chunk = stat_pairs[idx: idx + 3]
            row: list[Any] = []
            for k, v in chunk:
                row.extend([Paragraph(escape(k), s_lbl), Paragraph(escape(v), s_val)])
            while len(row) < 6:
                row.extend([Paragraph("", s_lbl), Paragraph("", s_val)])
            bank_rows.append(row)

        bank_tbl = Table(bank_rows, colWidths=[23 * mm, 37 * mm, 23 * mm, 37 * mm, 23 * mm, 37 * mm])
        bank_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
            ("BOX", (0, 0), (-1, -1), 0.6, c_border),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#F1F5F9")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(bank_tbl)
        story.append(Spacer(1, 2.5 * mm))

    # ── 4. COMPACT ATTENDANCE & WORK SUMMARY ──
    att_cells_row1 = [
        ("Calendar Days", str(attendance.get("calendar_days", "—"))),
        ("Scheduled Working", str(attendance.get("scheduled_working_days", "—"))),
        ("Present Days", str(attendance.get("present_days", "—"))),
        ("Paid Leave", str(attendance.get("paid_leave_days", "0.0"))),
        ("Holidays / Weekly Offs", f"{attendance.get('holidays', 0)} / {attendance.get('weekly_offs', 0)}"),
    ]
    att_cells_row2 = [
        ("Loss of Pay (LOP)", str(attendance.get("lop_days", "0.0"))),
        ("Unpaid Leave", str(attendance.get("unpaid_leave_days", "0.0"))),
        ("Total Paid Days", str(attendance.get("paid_days", "—"))),
        ("Overtime Hours", f"{attendance.get('overtime_hours', '0.0')} hrs" if Decimal(str(attendance.get("overtime_hours") or 0)) > 0 else "0.0 hrs"),
        ("Payment Status", str(employee.get("payment_status_display") or "PENDING")),
    ]

    def _att_pair_cell(lbl: str, val: str) -> Any:
        return Paragraph(f"<font color='#64748B' size='6.7'>{escape(lbl)}</font><br/><b>{escape(val)}</b>",
                         ParagraphStyle("AttCell", parent=base_styles["Normal"], fontName=font_bold, fontSize=7.4, leading=9.5, textColor=c_text_primary, alignment=TA_CENTER))

    att_data = [
        [_att_pair_cell(l, v) for l, v in att_cells_row1],
        [_att_pair_cell(l, v) for l, v in att_cells_row2],
    ]
    att_tbl = Table(att_data, colWidths=[36 * mm] * 5)
    att_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_secondary_bg),
        ("BOX", (0, 0), (-1, -1), 0.6, c_border),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, c_border),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.8),
    ]))
    story.append(att_tbl)
    story.append(Spacer(1, 2.8 * mm))

    # ── 5. HIGHLIGHTED SALARY SUMMARY CARDS ──
    gross_str = format_currency(totals.get("gross_earnings"), currency)
    ded_str = format_currency(totals.get("total_deductions"), currency)
    net_str = format_currency(totals.get("net_pay"), currency)

    def _kpi_card(label: str, val: str, value_color: colors.Color, is_net: bool = False) -> Any:
        lbl_st = ParagraphStyle("KPIL", parent=base_styles["Normal"], fontName=font_bold, fontSize=6.8, leading=8.5,
                                textColor=c_accent_net if is_net else c_text_secondary, alignment=TA_CENTER)
        val_st = ParagraphStyle("KPIV", parent=base_styles["Normal"], fontName=font_bold, fontSize=12.5 if is_net else 10.5,
                                leading=14.5, textColor=value_color, alignment=TA_CENTER)
        return [Paragraph(escape(label.upper()), lbl_st), Paragraph(escape(val), val_st)]

    kpi_tbl = Table(
        [
            [
                _kpi_card("Gross Earnings", gross_str, c_primary),
                _kpi_card("Total Deductions", ded_str, colors.HexColor("#B91C1C")),
                _kpi_card("Net Salary Payable", net_str, c_accent_net, is_net=True),
            ]
        ],
        colWidths=[58 * mm, 58 * mm, 64 * mm],
    )
    kpi_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (1, 0), colors.white),
        ("BACKGROUND", (2, 0), (2, 0), colors.HexColor("#ECFDF5")),
        ("BOX", (0, 0), (-1, -1), 0.7, c_border),
        ("LINEBEFORE", (1, 0), (2, 0), 0.6, c_border),
        ("LINEABOVE", (2, 0), (2, 0), 2.0, c_accent_net),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
    ]))
    story.append(kpi_tbl)
    story.append(Spacer(1, 2.8 * mm))

    # ── 6. TWO-COLUMN EARNINGS & DEDUCTIONS LEDGER TABLE (repeatRows=1 for auto pagination) ──
    show_zero = bool(options.get("show_zero_components", False))
    vis_earnings = [e for e in earnings if show_zero or quantize_money(e.get("amount")) != Decimal("0.00") or e.get("required")]
    vis_deductions = [d for d in deductions if show_zero or quantize_money(d.get("amount")) != Decimal("0.00") or d.get("required")]
    if not vis_earnings:
        vis_earnings = [{"label": "Earnings", "amount": totals.get("gross_earnings", "0.00")}]
    if not vis_deductions:
        vis_deductions = [{"label": "No Applicable Deductions", "amount": Decimal("0.00")}]

    max_rows = max(len(vis_earnings), len(vis_deductions))
    amt_col_hdr = f"Amount ({currency})" if currency != "INR" else "Amount (₹)"
    ledger_rows: list[list[Any]] = [
        [
            Paragraph("EARNINGS", s_tbl_hdr_l),
            Paragraph(escape(amt_col_hdr), s_tbl_hdr_r),
            Paragraph("DEDUCTIONS", s_tbl_hdr_l),
            Paragraph(escape(amt_col_hdr), s_tbl_hdr_r),
        ]
    ]
    for i in range(max_rows):
        if i < len(vis_earnings):
            e = vis_earnings[i]
            e_lbl = Paragraph(escape(str(e.get("label") or "")), s_row_l)
            e_amt = Paragraph(escape(format_currency(e.get("amount"), currency, with_symbol=False)), s_row_r)
        else:
            e_lbl, e_amt = Paragraph("", s_row_l), Paragraph("", s_row_r)

        if i < len(vis_deductions):
            d = vis_deductions[i]
            d_lbl = Paragraph(escape(str(d.get("label") or "")), s_row_l)
            d_amt = Paragraph(escape(format_currency(d.get("amount"), currency, with_symbol=False)), s_row_r)
        else:
            d_lbl, d_amt = Paragraph("", s_row_l), Paragraph("", s_row_r)

        ledger_rows.append([e_lbl, e_amt, d_lbl, d_amt])

    ledger_rows.append([
        Paragraph("Gross Earnings", s_row_bold_l),
        Paragraph(escape(gross_str), s_row_bold_r),
        Paragraph("Total Deductions", s_row_bold_l),
        Paragraph(escape(ded_str), s_row_bold_r),
    ])

    ledger_tbl = Table(ledger_rows, colWidths=[58 * mm, 32 * mm, 58 * mm, 32 * mm], repeatRows=1)
    ledger_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), c_primary),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, c_secondary_bg]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8EEF5")),
        ("BOX", (0, 0), (-1, -1), 0.7, c_border),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, c_border),
        ("LINEBEFORE", (2, 0), (2, -1), 0.8, c_border),
        ("LINEABOVE", (0, -1), (-1, -1), 0.9, c_primary),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(ledger_tbl)
    story.append(Spacer(1, 2.8 * mm))

    # ── 7. PROMINENT NET SALARY PAYABLE & AMOUNT IN WORDS ──
    words_str = str(totals.get("net_pay_words") or amount_in_words(totals.get("net_pay"), currency))
    net_box_rows = [
        [
            Paragraph(
                f"<font color='#0B665C' size='7.8'><b>NET SALARY PAYABLE</b></font><br/>"
                f"<font color='#64748B' size='7.1'>Amount in Words: </font>"
                f"<font color='#17212F' size='7.4'><b>{escape(words_str)}</b></font>",
                ParagraphStyle("NetWords", parent=base_styles["Normal"], fontName=font_reg, leading=10.5),
            ),
            Paragraph(
                escape(net_str),
                ParagraphStyle("NetBig", parent=base_styles["Normal"], fontName=font_bold, fontSize=13.5, leading=16, textColor=c_accent_net, alignment=TA_RIGHT),
            ),
        ]
    ]
    net_box = Table(net_box_rows, colWidths=[126 * mm, 54 * mm])
    net_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF9")),
        ("BOX", (0, 0), (-1, -1), 0.9, c_accent_net),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(net_box)
    story.append(Spacer(1, 2.8 * mm))

    # ── 8. OPTIONAL EMPLOYER CONTRIBUTIONS & FINANCIAL-YEAR YTD SUMMARY ──
    show_empr = bool(options.get("show_employer_contributions", True)) and bool(employer_contribs)
    show_ytd = bool(options.get("show_ytd_summary", True)) and isinstance(ytd, dict) and bool(ytd.get("has_data"))

    if show_empr or show_ytd:
        side_panels: list[Any] = []
        col_widths_opt: list[float] = []

        if show_empr:
            empr_tbl_rows = [[Paragraph("EMPLOYER CONTRIBUTIONS (CTC — NON-DEDUCTIBLE)", s_sec_hdr), Paragraph("", s_sec_hdr)]]
            for item in employer_contribs:
                empr_tbl_rows.append([
                    Paragraph(escape(str(item["label"])), s_row_l),
                    Paragraph(escape(format_currency(item["amount"], currency)), s_row_r),
                ])
            empr_panel = Table(empr_tbl_rows, colWidths=[56 * mm, 32 * mm] if show_ytd else [125 * mm, 55 * mm])
            empr_panel.setStyle(TableStyle([
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#E8EEF5")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, c_border),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#F1F5F9")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            side_panels.append(empr_panel)
            col_widths_opt.append(88 * mm if show_ytd else 180 * mm)

        if show_ytd and ytd:
            fy_txt = escape(str(ytd.get("financial_year") or ""))
            ytd_rows = [[Paragraph(f"YEAR-TO-DATE SUMMARY (FY {fy_txt})", s_sec_hdr), Paragraph("", s_sec_hdr)]]
            for lbl, key in [
                ("YTD Gross Earnings", "gross_earnings"),
                ("YTD Employee PF", "employee_pf"),
                ("YTD Professional Tax", "professional_tax"),
                ("YTD Income Tax (TDS)", "tds"),
                ("YTD Total Deductions", "total_deductions"),
                ("YTD Net Salary", "net_pay"),
            ]:
                ytd_rows.append([
                    Paragraph(escape(lbl), s_row_bold_l if key == "net_pay" else s_row_l),
                    Paragraph(escape(format_currency(ytd.get(key, 0), currency)), s_row_bold_r if key == "net_pay" else s_row_r),
                ])
            ytd_panel = Table(ytd_rows, colWidths=[54 * mm, 34 * mm] if show_empr else [125 * mm, 55 * mm])
            ytd_panel.setStyle(TableStyle([
                ("SPAN", (0, 0), (1, 0)),
                ("BACKGROUND", (0, 0), (1, 0), colors.HexColor("#E8EEF5")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.6, c_border),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#F1F5F9")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            if show_empr:
                side_panels.append(Spacer(4 * mm, 1))
                col_widths_opt.append(4 * mm)
            side_panels.append(ytd_panel)
            col_widths_opt.append(88 * mm if show_empr else 180 * mm)

        if side_panels:
            opt_wrap = Table([side_panels], colWidths=col_widths_opt)
            opt_wrap.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(opt_wrap)
            story.append(Spacer(1, 2.8 * mm))

    # ── 9. BOTTOM GOVERNANCE BLOCK: HR & PAYROLL SUPPORT + QR VERIFICATION + AUTHORIZED SIGNATORY ──
    # Left zone: HR & Payroll Support (never uses personal HR user contact info)
    hr_lines = [Paragraph("HR & PAYROLL SUPPORT", s_sec_hdr)]
    if hr_info.get("hr_contact_name"):
        hr_lines.append(Paragraph(f"Contact: <b>{escape(str(hr_info['hr_contact_name']))}</b>", s_small_muted))
    if hr_info.get("hr_designation") or hr_info.get("hr_department"):
        desig_dept = " — ".join(x for x in [hr_info.get("hr_designation"), hr_info.get("hr_department")] if x)
        hr_lines.append(Paragraph(escape(desig_dept), s_small_muted))
    if hr_info.get("hr_email"):
        hr_lines.append(Paragraph(f"Email: {escape(str(hr_info['hr_email']))}", s_small_muted))
    if hr_info.get("payroll_support_email") and hr_info.get("payroll_support_email") != hr_info.get("hr_email"):
        hr_lines.append(Paragraph(f"Payroll Helpdesk: {escape(str(hr_info['payroll_support_email']))}", s_small_muted))
    if hr_info.get("hr_phone"):
        ext = f" (Ext. {hr_info['office_extension']})" if hr_info.get("office_extension") else ""
        hr_lines.append(Paragraph(f"Phone: {escape(str(hr_info['hr_phone']) + ext)}", s_small_muted))
    hr_lines.append(Paragraph("For salary-related queries, please contact the HR & Payroll Department.", s_small_italic))

    hr_tbl = Table([[line] for line in hr_lines], colWidths=[58 * mm])
    hr_tbl.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
    ]))

    # Center zone: Real QR Verification + Document Checksum (no sensitive data inside QR)
    show_qr = bool(options.get("enable_qr_verification", True)) and bool(verification.get("verification_url"))
    if show_qr:
        qr_widget = _qr_drawing(str(verification["verification_url"]), size_pt=16 * mm, accent_hex=primary_hex)
        sha_short = str(verification.get("sha256_hash") or verification.get("checksum_short") or "")[:12]
        s_doc_id = ParagraphStyle("DocIdCompact", parent=s_small_muted, fontSize=6.2, leading=8.5)
        ver_lines = [
            Paragraph("DOCUMENT VERIFICATION", s_sec_hdr),
            Paragraph(f"Doc ID: <b>{escape(str(verification.get('document_id') or ''))}</b>", s_doc_id),
            Paragraph(f"Ver: v{verification.get('version_number', 1)} | Ref: {escape(sha_short)}", s_small_muted),
            Paragraph("Scan QR to verify authenticity.", s_small_italic),
        ]
        ver_text_tbl = Table([[l] for l in ver_lines], colWidths=[42 * mm])
        ver_text_tbl.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0.6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
        ]))
        qr_zone = Table([[qr_widget, ver_text_tbl]], colWidths=[17 * mm, 42 * mm])
        qr_zone.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
    else:
        qr_zone = Table([[Paragraph("", s_small_muted)]], colWidths=[59 * mm])

    # Right zone: Authorized Signatory (never generates fake signatures)
    sig_img = _load_image_flowable(signatory.get("signature_image_url"), max_width=26 * mm, max_height=10 * mm)
    seal_img = _load_image_flowable(signatory.get("company_seal_url"), max_width=14 * mm, max_height=10 * mm)

    sig_right_style = ParagraphStyle("SigR", parent=s_small_muted, alignment=TA_RIGHT)
    sig_hdr_style = ParagraphStyle("SigH", parent=s_sec_hdr, alignment=TA_RIGHT)
    sig_lines: list[Any] = [Paragraph("AUTHORIZED SIGNATORY", sig_hdr_style)]
    if sig_img is not None or seal_img is not None:
        img_row = [seal_img or "", sig_img or ""]
        img_tbl = Table([img_row], colWidths=[16 * mm, 28 * mm])
        img_tbl.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ]))
        sig_lines.append(img_tbl)
    else:
        unsigned_note = str(
            signatory.get("unsigned_declaration")
            or "Computer-generated salary slip; no physical signature required."
        )
        sig_lines.append(Paragraph(escape(unsigned_note), ParagraphStyle("SigU", parent=s_small_italic, alignment=TA_RIGHT)))

    if signatory.get("signatory_name"):
        sig_lines.append(Paragraph(f"<b>{escape(str(signatory['signatory_name']))}</b>", sig_right_style))
    sig_role = " | ".join(x for x in [signatory.get("signatory_designation"), signatory.get("signatory_department")] if x)
    if sig_role:
        sig_lines.append(Paragraph(escape(sig_role), sig_right_style))
    if signatory.get("issue_date_display"):
        sig_lines.append(Paragraph(f"Issued: {escape(str(signatory['issue_date_display']))}", sig_right_style))

    sig_tbl = Table([[line] for line in sig_lines], colWidths=[50 * mm])
    sig_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0.8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.8),
    ]))

    bottom_box = Table([[hr_tbl, qr_zone, sig_tbl]], colWidths=[62 * mm, 64 * mm, 54 * mm])
    bottom_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), c_secondary_bg),
        ("BOX", (0, 0), (-1, -1), 0.6, c_border),
        ("LINEBEFORE", (1, 0), (2, 0), 0.5, c_border),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(bottom_box)

    canvas_meta = {
        "company_name": company_display,
        "document_id": verification.get("document_id") or payslip_num,
        "payslip_number": payslip_num,
        "generated_display": verification.get("generated_display") or datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "footer_declaration": company.get("footer_declaration"),
        "show_ofc360_footer": bool(options.get("show_ofc360_footer", True)),
        "is_draft": is_draft,
    }
    doc.build(story, canvasmaker=lambda *a, **kw: _PayslipNumberedCanvas(*a, payslip_meta=canvas_meta, **kw))
    buffer.seek(0)
    return buffer.getvalue()


def render_compat_summary_pdf(
    title: str,
    lines: list[tuple[str, str]],
    total_lines: list[tuple[str, str]],
    branding: dict[str, Any] | None = None,
    currency: str = "INR",
) -> bytes:
    """Backward-compatible PDF helper honoring bundled Unicode fonts & tenant branding."""
    from reportlab.platypus import SimpleDocTemplate

    font_reg, font_bold, _, _ = _ensure_fonts_registered()
    branding = branding or {}
    header = branding.get("pdf_header", {})
    primary = str(header.get("primary_color") or "#182C43")
    secondary = str(header.get("secondary_color") or "#F5F7FA")
    c_primary = _safe_hex_color(primary, "#182C43")
    c_secondary = _safe_hex_color(secondary, "#F5F7FA")
    display_name = str(branding.get("display_name") or "OFC360")

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=16 * mm, leftMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm, title=title, author=f"{display_name} Payroll",
    )
    styles = getSampleStyleSheet()
    st_title = ParagraphStyle("CompatT", parent=styles["Normal"], fontName=font_bold, fontSize=14, leading=18, textColor=c_primary)
    st_sub = ParagraphStyle("CompatS", parent=styles["Normal"], fontName=font_reg, fontSize=8.5, leading=12, textColor=colors.HexColor("#64748B"))
    st_cell = ParagraphStyle("CompatC", parent=styles["Normal"], fontName=font_reg, fontSize=8.5, leading=11, textColor=colors.HexColor("#17212F"))
    st_cell_r = ParagraphStyle("CompatCR", parent=st_cell, alignment=TA_RIGHT)
    st_cell_b = ParagraphStyle("CompatCB", parent=st_cell, fontName=font_bold, textColor=c_primary)
    st_cell_br = ParagraphStyle("CompatCBR", parent=st_cell_b, alignment=TA_RIGHT)

    story: list[Any] = [Paragraph(f"{escape(display_name)} — {escape(title)}", st_title)]
    if header.get("text"):
        story.append(Paragraph(escape(str(header["text"])), st_sub))
    story.append(Spacer(1, 5 * mm))

    table_data: list[list[Any]] = [
        [Paragraph("<b>Description</b>", ParagraphStyle("CH", parent=st_cell, fontName=font_bold, textColor=colors.white)),
         Paragraph("<b>Amount / Value</b>", ParagraphStyle("CHR", parent=st_cell_r, fontName=font_bold, textColor=colors.white))]
    ]
    for k, v in lines:
        table_data.append([Paragraph(escape(str(k)), st_cell), Paragraph(escape(str(v)), st_cell_r)])
    for k, v in total_lines:
        table_data.append([Paragraph(escape(str(k)), st_cell_b), Paragraph(escape(str(v)), st_cell_br)])

    table = Table(table_data, colWidths=[112 * mm, 66 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), c_primary),
        ("ROWBACKGROUNDS", (0, 1), (-1, len(lines)), [colors.white, c_secondary]),
        ("BACKGROUND", (0, len(lines) + 1), (-1, -1), colors.HexColor("#E8EEF5")),
        ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#E2E8F0")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.35, colors.HexColor("#E2E8F0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(table)
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph(f"Generated by {escape(display_name)} Payroll • Currency: {escape(currency)}", st_sub))
    document.build(story)
    return output.getvalue()
