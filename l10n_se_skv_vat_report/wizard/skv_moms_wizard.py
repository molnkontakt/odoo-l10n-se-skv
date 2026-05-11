"""SKV Momsrapport-wizard — välj period, generera rapport."""

import base64
import json
import logging
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# eSKD XML-taggnamn per SKV-ruta. Källa: Skatteverkets officiella spec
# (https://www.skatteverket.se/foretag/skatterochavdrag/momsdeklaration/...)
# Ordningen nedan följer SKV-spec radordning 6–32 (sektion-grupperad enligt
# blanketten: A. Försäljning, C. Inköp omv. skattskyldighet, E. Försäljning
# undantagen, H. Import, F. Ingående moms).
# OBS: ordningen i den genererade filen följer dict-ordningen.
ESKD_FIELDS = {
    # A. Momspliktig försäljning eller uttag (rader 6–9)
    "se_05": "ForsMomsEjAnnan",
    "se_06": "UttagMoms",
    "se_07": "UlagMargbesk",
    "se_08": "HyrinkomstFriv",
    # C. Momspliktiga inköp vid omvänd betalningsskyldighet (rader 13–17)
    "se_20": "InkopVaruAnnatEg",
    "se_21": "InkopTjanstAnnatEg",
    "se_22": "InkopTjanstUtomEg",
    "se_23": "InkopVaruSverige",
    "se_24": "InkopTjanstSverige",
    # H. Import — beskattningsunderlag (rad 29)
    "se_50": "MomsUlagImport",
    # E. Försäljning undantagen från moms (rader 21–28)
    "se_35": "ForsVaruAnnatEg",
    "se_36": "ForsVaruUtomEg",
    "se_37": "InkopVaruMellan3p",
    "se_38": "ForsVaruMellan3p",
    "se_39": "ForsTjSkskAnnatEg",
    "se_40": "ForsTjOvrUtomEg",
    "se_41": "ForsKopareSkskSverige",
    "se_42": "ForsOvrigt",
    # B. Utgående moms på försäljning eller uttag (rader 10–12)
    "se_10": "MomsUtgHog",
    "se_11": "MomsUtgMedel",
    "se_12": "MomsUtgLag",
    # D. Utgående moms på inköp vid omvänd betalningsskyldighet (rader 18–20)
    "se_30": "MomsInkopUtgHog",
    "se_31": "MomsInkopUtgMedel",
    "se_32": "MomsInkopUtgLag",
    # I. Utgående moms vid import (rader 30–32)
    "se_60": "MomsImportUtgHog",
    "se_61": "MomsImportUtgMedel",
    "se_62": "MomsImportUtgLag",
    # F. Ingående moms (rad 33)
    "se_48": "MomsIngAvdr",
}


# Mappning av SKV-rutor → label på deklarationen.
# Källa: Skatteverkets blankett SKV 4700 (momsdeklaration).
SKV_ROWS = [
    ("se_05", "Momspliktig försäljning som inte ingår i fält 06, 07 eller 08"),
    ("se_06", "Momspliktig uttag"),
    ("se_07", "Beskattningsunderlag vid vinstmarginalbeskattning"),
    ("se_08", "Hyresinkomster vid frivillig skattskyldighet"),
    ("se_10", "Utgående moms 25 %"),
    ("se_11", "Utgående moms 12 %"),
    ("se_12", "Utgående moms 6 %"),
    ("se_20", "Inköp av varor från annat EU-land"),
    ("se_21", "Inköp av tjänster från annat EU-land enligt huvudregeln"),
    ("se_22", "Inköp av tjänster från land utanför EU"),
    ("se_23", "Inköp av varor i Sverige (omvänd skattskyldighet)"),
    ("se_24", "Övriga inköp av tjänster (omvänd skattskyldighet)"),
    ("se_30", "Utgående moms 25 % (omvänd skattskyldighet)"),
    ("se_31", "Utgående moms 12 % (omvänd skattskyldighet)"),
    ("se_32", "Utgående moms 6 % (omvänd skattskyldighet)"),
    ("se_35", "Försäljning av varor till annat EU-land"),
    ("se_36", "Försäljning av varor utanför EU"),
    ("se_37", "Mellanmans inköp av varor vid trepartshandel"),
    ("se_38", "Mellanmans försäljning av varor vid trepartshandel"),
    ("se_39", "Försäljning av tjänster till näringsidkare i annat EU-land"),
    ("se_40", "Övrig försäljning av tjänster omsatta utomlands"),
    ("se_41", "Försäljning där köparen är skattskyldig"),
    ("se_42", "Övrig försäljning"),
    ("se_48", "Ingående moms att dra av"),
    ("se_50", "Import av varor — beskattningsunderlag"),
    ("se_60", "Utgående moms 25 % (import av varor)"),
    ("se_61", "Utgående moms 12 % (import av varor)"),
    ("se_62", "Utgående moms 6 % (import av varor)"),
]

# Vilka rutor är "utgående moms" (debiterad) resp "ingående moms" (avdrag).
OUT_VAT_BOXES = {"se_10", "se_11", "se_12", "se_30", "se_31", "se_32",
                 "se_60", "se_61", "se_62"}
IN_VAT_BOXES = {"se_48"}


# BAS-konton → ruta-mappning för referens och valideringar.
# Källa: BAS-kontoplan 2026 + Skatteverkets blankett SKV 4700, sektion 7
# och 8 ("Momsdeklaration field-to-BAS account mapping").
BOX_TO_BAS_ACCOUNTS = {
    # B: Utgående moms (kredit-saldo förväntas)
    "se_10": ["2611", "2612", "2613", "2616"],
    "se_11": ["2621", "2622", "2623", "2626"],
    "se_12": ["2631", "2632", "2633", "2636"],
    # D: Reverse charge utg. moms
    "se_30": ["2614"],
    "se_31": ["2624"],
    "se_32": ["2634"],
    # I: Import utg. moms
    "se_60": ["2615"],
    "se_61": ["2625"],
    "se_62": ["2635"],
    # F: Ingående moms
    "se_48": ["2641", "2642", "2645", "2646", "2647", "2649"],
}

# Vilande momskonton — ska inte ha saldo vid periodavslut. Saldo här =
# missade transaktioner från konstruktionsfas eller liknande.
DORMANT_VAT_ACCOUNTS = ["2618", "2628", "2638", "2648"]

# Reverse-charge-par — om den ena sidan har saldo MÅSTE den andra också ha det.
# Källa: ML 2023:200 16 kap. — vid reverse charge (omvänd skattskyldighet)
# måste BÅDE utgående OCH ingående moms bokföras; "silent netting" där
# bara ena sidan bokförs är förbjudet.
RC_PAIRS = [
    # (output VAT account, [valid input VAT accounts])
    ("2614", ["2645", "2647"]),  # 25%
    ("2624", ["2645", "2647"]),  # 12%
    ("2634", ["2645", "2647"]),  # 6%
]


class SkvMomsWizard(models.TransientModel):
    _name = "l10n_se_skv_vat_report.wizard"
    _description = "SKV Momsrapport — period-väljare"

    period_type = fields.Selection([
        ("quarter", "Kvartal"),
        ("month", "Månad"),
        ("custom", "Eget intervall"),
    ], string="Periodtyp", default="quarter", required=True)

    def _year_selection(self):
        current = date.today().year
        # Allow current year + 4 back + 1 forward
        return [(str(y), str(y)) for y in range(current - 4, current + 2)]

    def _default_year(self):
        today = date.today()
        prev_q_first = (today.replace(day=1) - relativedelta(months=3))
        return str(prev_q_first.year)

    def _default_quarter(self):
        # Previous quarter (= what you typically declare)
        today = date.today()
        prev_q_month = (today.replace(day=1) - relativedelta(months=3)).month
        return str((prev_q_month - 1) // 3 + 1)

    def _default_month(self):
        # Previous month
        today = date.today()
        prev_m = (today.replace(day=1) - relativedelta(months=1)).month
        return str(prev_m)

    year = fields.Selection(_year_selection, string="År",
                            default=_default_year, required=True)
    quarter = fields.Selection([
        ("1", "Q1 (jan–mar)"),
        ("2", "Q2 (apr–jun)"),
        ("3", "Q3 (jul–sep)"),
        ("4", "Q4 (okt–dec)"),
    ], string="Kvartal", default=_default_quarter)
    month = fields.Selection([(str(i), f"{i:02d}") for i in range(1, 13)],
                             string="Månad", default=_default_month)

    date_from = fields.Date(string="Från datum")
    date_to = fields.Date(string="Till datum")

    only_posted = fields.Boolean(
        string="Endast bokförda verifikat",
        default=True,
        help="Avmarkera för att även inkludera utkast (för granskning).",
    )

    @api.onchange("period_type", "year", "quarter", "month")
    def _onchange_period(self):
        if not self.year:
            return
        year_int = int(self.year)
        if self.period_type == "quarter" and self.quarter:
            q = int(self.quarter)
            start_month = (q - 1) * 3 + 1
            self.date_from = date(year_int, start_month, 1)
            self.date_to = (self.date_from + relativedelta(months=3)) - relativedelta(days=1)
        elif self.period_type == "month" and self.month:
            self.date_from = date(year_int, int(self.month), 1)
            self.date_to = (self.date_from + relativedelta(months=1)) - relativedelta(days=1)

    def _compute_box_amounts(self):
        """Sum balance per SKV tax tag for posted moves in the period.

        Reads account_account_tag.account_move_line m2m directly so it works
        for both Odoo-native invoices (tax-driven tags) and SIE-imported
        journal entries (manually-tagged via SQL backfill).
        """
        if not self.date_from or not self.date_to:
            raise UserError(_("Period saknas."))

        SE_country = self.env["res.country"].search([("code", "=", "SE")], limit=1)
        tags = self.env["account.account.tag"].search([
            ("country_id", "=", SE_country.id),
            ("applicability", "=", "taxes"),
        ])
        # Map "se_05" → tag id
        tag_by_code = {}
        for t in tags:
            label = (t.with_context(lang="en_US").name or "").strip()
            if label.startswith("se_"):
                tag_by_code[label] = t.id

        states = ["posted"] if self.only_posted else ["posted", "draft"]

        # SKV declaration always shows positive amounts.
        # Sales / output VAT: balance is naturally negative (credit side) → flip.
        # Purchases / input VAT: balance is positive (debit side) → keep.
        SALES_OR_OUT_VAT = {
            "se_05", "se_06", "se_07", "se_08",
            "se_10", "se_11", "se_12",
            "se_30", "se_31", "se_32",
            "se_35", "se_36", "se_37", "se_38",
            "se_39", "se_40", "se_41", "se_42",
            "se_60", "se_61", "se_62",
        }

        # One grouped query for all relevant tag IDs, then map results to
        # boxes locally. Replaces a previous N-queries-per-call pattern
        # that scaled badly on large datasets.
        tag_ids = list(tag_by_code.values())
        balance_by_tag: dict[int, float] = {}
        if tag_ids:
            self.env.cr.execute("""
                SELECT rel.account_account_tag_id,
                       COALESCE(SUM(aml.debit - aml.credit), 0)
                FROM account_account_tag_account_move_line_rel rel
                JOIN account_move_line aml ON aml.id = rel.account_move_line_id
                JOIN account_move m ON m.id = aml.move_id
                WHERE rel.account_account_tag_id = ANY(%s)
                  AND m.date BETWEEN %s AND %s
                  AND m.state = ANY(%s)
                  AND m.company_id = %s
                GROUP BY rel.account_account_tag_id
            """, (tag_ids, self.date_from, self.date_to, states, self.env.company.id))
            balance_by_tag = {tid: float(bal or 0.0) for tid, bal in self.env.cr.fetchall()}

        rows = []
        for code, label in SKV_ROWS:
            tag_id = tag_by_code.get(code)
            if not tag_id:
                continue
            balance = balance_by_tag.get(tag_id, 0.0)
            amount = round(-balance, 2) if code in SALES_OR_OUT_VAT else round(balance, 2)
            rows.append({
                "code": code,
                "label": label,
                "amount": amount,
            })

        # Compute summary:
        total_out_vat = sum(r["amount"] for r in rows if r["code"] in OUT_VAT_BOXES)
        total_in_vat = sum(r["amount"] for r in rows if r["code"] in IN_VAT_BOXES)
        to_pay = total_out_vat - total_in_vat
        return rows, total_out_vat, total_in_vat, to_pay

    def _build_eskd_xml(self, rows, to_pay):
        """Build eSKD XML according to Skatteverket DTD 6.0.

        References:
          - reference eSKD file (sample Q4 export from a Swedish accounting tool)
          - https://www.skatteverket.se/download/.../agexempel_v6.txt (SKV agexempel)

        Format: ISO-8859-1 encoded (matches SKV's own example), CRLF line
        terminators, only non-zero fields. Some accounting tools (e.g. Spiris) export UTF-8+BOM but
        the DTD allows both — we follow SKV's reference encoding for
        maximum compatibility with their parser.

        Period = YYYYMM of the period's last month (Q4 = 202512).
        OrgNr = NNNNNN-NNNN (10 digits + dash).

        Returns: (bytes, mimetype) — bytes are ISO-8859-1 encoded.
        """
        company = self.env.company
        org_raw = (company.vat or "").replace("SE", "").strip()
        # Strip trailing "01" if it's a Swedish org-nr pattern (12 digits incl 01 suffix)
        if len(org_raw) == 12 and org_raw.endswith("01"):
            org_raw = org_raw[:10]
        if len(org_raw) == 10:
            org_nr = f"{org_raw[:6]}-{org_raw[6:]}"
        else:
            org_nr = company.company_registry or ""

        # Period = YYYYMM of last month in interval
        period = self.date_to.strftime("%Y%m")

        # Round to int (eSKD uses no decimals — kronor only).
        # Use ROUND_HALF_UP to stay consistent with the rest of the
        # module (VAT period-end bookkeeping uses Decimal+HALF_UP). Built-in
        # round() does bankers rounding which would diverge by ±1 kr on
        # exact .50-amounts.
        def to_int_kr(val):
            return int(Decimal(str(val)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

        # Header per SKV-spec: line 1 XML decl, line 2 root element, line 3 OrgNr,
        # line 4 <Moms>, line 5 <Period>. No DOCTYPE — SKV's official examples
        # (agexempel_v6.txt + the moms documentation) omit it.
        lines = ['<?xml version="1.0" encoding="ISO-8859-1"?>']
        lines.append('<eSKDUpload Version="6.0">')
        lines.append(f'  <OrgNr>{org_nr}</OrgNr>')
        lines.append('  <Moms>')
        lines.append(f'    <Period>{period}</Period>')

        # Emit each row in the canonical SKV-DTD order (matches ESKD_FIELDS dict order
        # since Python 3.7 preserves insertion order).
        amount_by_code = {r["code"]: r["amount"] for r in rows}
        for code, eskd_field in ESKD_FIELDS.items():
            amount = amount_by_code.get(code, 0)
            if to_int_kr(amount) != 0:
                lines.append(f'    <{eskd_field}>{to_int_kr(amount)}</{eskd_field}>')

        # MomsBetala är obligatorisk — alltid med, även 0.
        # Negativt belopp = moms att få tillbaka, anges med "-" direkt före siffran.
        pay_int = to_int_kr(to_pay)
        if pay_int < 0:
            lines.append(f'    <MomsBetala>-{abs(pay_int)}</MomsBetala>')
        else:
            lines.append(f'    <MomsBetala>{pay_int}</MomsBetala>')
        lines.append('  </Moms>')
        lines.append('</eSKDUpload>')

        body = "\r\n".join(lines) + "\r\n"
        # Encode as ISO-8859-1 (latin1). Org-nr only has digits + dash so
        # there are no characters that fail to encode.
        return body.encode("iso-8859-1")

    def _check_vat_compliance(self):
        """Run compliance checks per swedish-vat skill error patterns.

        Returns list of {level: 'warning'|'error', message: str} dicts.

        Checks (from references/vat-compliance-reference.md §9):
          1. Vilande momskonton (2618/2628/2638/2648) med saldo → varning
          2. One-sided reverse charge (2614/2624/2634 utan motsvarande 2645/2647)
          3. 2650 har saldo i början av perioden (= föregående period inte stängd)
          4. Formel-validering: SUM(utg moms) − R48 = R49
        """
        warnings = []
        company_id = self.env.company.id

        # Helper to fetch saldo on account codes for the period
        def saldo_for(codes, period_only=True):
            if not codes:
                return Decimal("0")
            self.env.cr.execute("""
                SELECT COALESCE(SUM(aml.debit - aml.credit), 0)
                FROM account_move_line aml
                JOIN account_account a ON a.id = aml.account_id
                JOIN account_move m ON m.id = aml.move_id
                WHERE a.code_store->>%s = ANY(%s)
                  AND m.state = 'posted'
                  AND m.company_id = %s
                  AND m.date BETWEEN %s AND %s
            """, (str(company_id), list(codes), company_id,
                  self.date_from if period_only else date(2000, 1, 1),
                  self.date_to))
            return Decimal(str(self.env.cr.fetchone()[0] or 0))

        # Check 1: Vilande momskonton med saldo
        dormant = saldo_for(DORMANT_VAT_ACCOUNTS)
        if abs(dormant) >= Decimal("1.00"):
            warnings.append({
                "level": "warning",
                "message": (
                    f"⚠ Vilande momskonton ({', '.join(DORMANT_VAT_ACCOUNTS)}) "
                    f"har saldo {dormant} kr i perioden. Dessa ska normalt "
                    f"vara nollställda. Kontrollera om transaktioner ska "
                    f"flyttas till aktiva momskonton."
                ),
            })

        # Check 2: One-sided reverse charge
        for out_acc, in_accs in RC_PAIRS:
            out_saldo = saldo_for([out_acc])
            in_saldo = saldo_for(in_accs)
            # out på kredit (negativ balance), in på debet (positiv)
            # Om out har saldo men in är noll → trasig RC
            if abs(out_saldo) >= Decimal("1.00") and abs(in_saldo) < Decimal("1.00"):
                warnings.append({
                    "level": "error",
                    "message": (
                        f"⛔ Konto {out_acc} (utg. moms reverse charge) har "
                        f"saldo {-out_saldo} kr men motsvarande ingående moms "
                        f"({'/'.join(in_accs)}) är 0. Reverse charge måste "
                        f"bokföras BÅDE som utg och ing moms (ML 16 kap, "
                        f"silent netting förbjudet)."
                    ),
                })

        # Check 3: 2650 — får inte ha kvarvarande saldo från tidigare period
        # vid periodens början. Räkna saldo PER START-DATE genom att summera
        # alla transaktioner upp till (men inte inklusive) date_from.
        self.env.cr.execute("""
            SELECT COALESCE(SUM(aml.debit - aml.credit), 0)
            FROM account_move_line aml
            JOIN account_account a ON a.id = aml.account_id
            JOIN account_move m ON m.id = aml.move_id
            WHERE a.code_store->>%s = '2650'
              AND m.state = 'posted'
              AND m.company_id = %s
              AND m.date < %s
        """, (str(company_id), company_id, self.date_from))
        opening_2650 = Decimal(str(self.env.cr.fetchone()[0] or 0))
        # Tolerera ören
        if abs(opening_2650) >= Decimal("1.00"):
            warnings.append({
                "level": "warning",
                "message": (
                    f"⚠ Konto 2650 (Redovisningskonto för moms) har saldo "
                    f"{opening_2650} kr vid periodens början. Föregående "
                    f"periods deklaration är troligen inte ombokad mot bank. "
                    f"När SKV betalas: bokför 2650 D / 1930 K."
                ),
            })

        return warnings

    def action_view_details(self):
        """Open list of all journal lines that contribute to the report.
        Lets the user drill down from a sum to the verifikat that built it up.

        Grupperar per `account_id` (tag-grupperning fungerar dåligt på m2m)
        och visar tag-chips i list-kolumnen så användaren ser direkt vilken
        ruta varje rad bidrar till.
        """
        self.ensure_one()
        if not self.date_from or not self.date_to:
            self._onchange_period()

        SE_country = self.env["res.country"].search([("code", "=", "SE")], limit=1)
        SE_tag_ids = self.env["account.account.tag"].search([
            ("country_id", "=", SE_country.id),
            ("applicability", "=", "taxes"),
        ]).ids

        states = ["posted"] if self.only_posted else ["posted", "draft"]

        return {
            "type": "ir.actions.act_window",
            "name": _("Detaljer SKV Momsrapport %s") % self._period_label(),
            "res_model": "account.move.line",
            "view_mode": "list,form",
            "domain": [
                ("date", ">=", self.date_from),
                ("date", "<=", self.date_to),
                ("parent_state", "in", states),
                ("tax_tag_ids", "in", SE_tag_ids),
                ("company_id", "=", self.env.company.id),
            ],
            "context": {
                "search_default_group_by_account_id": 1,
                "create": False,
                "edit": False,
            },
        }

    def _period_label(self):
        """Human label like '2026 Q1' or '2026-03' for ref-fältet."""
        if self.period_type == "quarter" and self.quarter:
            return f"{self.year} Q{self.quarter}"
        if self.period_type == "month" and self.month:
            return f"{self.year}-{int(self.month):02d}"
        return f"{self.date_from} – {self.date_to}"

    def action_create_vat_journal_entry(self):
        """Create a draft journal entry that closes all VAT accounts for the period
        against 2650 Redovisningskonto för moms.

        Mirrors SIE-import-style bookkeeping:
          2611/2614/2624 (output VAT)        kredit → debet (closing)
          2641/2645      (input VAT)         debet  → kredit (closing)
          2650 Redovisningskonto för moms    skuld till SKV
          3740 Öresavrundning                rounding diff (kr → öre)

        Idempotent via `ref = MOMS <period>`. Won't create duplicates.
        Returns action that opens the draft for review.
        """
        self.ensure_one()
        if not self.date_from or not self.date_to:
            self._onchange_period()

        # Spiris-modell: blockera om tidigare inlämnade perioder har drift,
        # eller om denna period redan har en aktiv inlämning.
        self._block_if_stale()
        if self.filing_id:
            raise UserError(_(
                "Perioden är redan inlämnad (%s). Ångra inlämningen "
                "först om du vill boka om."
            ) % self.filing_id.display_name)

        # Booking always uses POSTED moves only (we close 2611-264x balances
        # to 2650 — drafts are not on those balances yet). If the user has
        # toggled only_posted=False for preview purposes, re-enable it for
        # the actual booking so the filing snapshot matches what's on 2650.
        if not self.only_posted:
            self.only_posted = True

        Move = self.env["account.move"]
        Account = self.env["account.account"]
        Filing = self.env["l10n_se_skv_vat_report.filing"]

        period_ref = f"MOMS {self._period_label()}"

        # Find a "Diverse"/"Misc" journal — type=general, default
        misc_journal = self.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", self.env.company.id),
        ], limit=1)

        if not misc_journal:
            raise UserError(_("Hittar ingen journal av typen 'Diverse operationer'."))

        # VAT account codes to close (BAS standard).
        # Output VAT (2610-series): naturally credit balance — close by debiting.
        # Input VAT (2640-series): naturally debit balance — close by crediting.
        VAT_ACCOUNT_CODES = [
            # Output VAT
            "2610", "2611", "2612", "2613", "2614", "2615", "2616", "2617", "2618",
            "2620", "2621", "2622", "2623", "2624", "2625", "2626", "2627", "2628",
            "2630", "2631",
            # Input VAT
            "2640", "2641", "2645", "2647", "2648", "2649",
            # Other VAT helpers
            "2660",
        ]

        # Sum balance per VAT account in period
        self.env.cr.execute("""
            SELECT a.id, a.code_store->>%s, COALESCE(SUM(aml.debit - aml.credit), 0) AS bal
            FROM account_move_line aml
            JOIN account_account a ON a.id = aml.account_id
            JOIN account_move m ON m.id = aml.move_id
            WHERE a.code_store->>%s = ANY(%s)
              AND m.date BETWEEN %s AND %s
              AND m.state = 'posted'
              AND m.company_id = %s
            GROUP BY a.id, a.code_store->>%s
            HAVING COALESCE(SUM(aml.debit - aml.credit), 0) <> 0
        """, (str(self.env.company.id), str(self.env.company.id),
              VAT_ACCOUNT_CODES,
              self.date_from, self.date_to,
              self.env.company.id, str(self.env.company.id)))
        vat_balances = self.env.cr.fetchall()

        if not vat_balances:
            raise UserError(_(
                "Inga momskonton med saldo hittades för perioden %s – %s. "
                "Är fakturorna bokförda?") % (self.date_from, self.date_to))

        # Build line vals using Decimal to avoid float-precision rounding
        # that breaks Odoo's "post is balanced" check (amounts must match exactly
        # to 2 decimals).
        TWO = Decimal("0.01")

        def q(d):
            return float(Decimal(d).quantize(TWO, rounding=ROUND_HALF_UP))

        line_vals = []
        # Track sums in Decimal for exact balance check
        total_debit = Decimal("0")
        total_credit = Decimal("0")
        for acc_id, _code, balance in vat_balances:
            bal = Decimal(str(balance)).quantize(TWO, rounding=ROUND_HALF_UP)
            if bal > 0:
                line_vals.append((0, 0, {
                    "account_id": acc_id,
                    "name": _("Periodavslut moms %s") % self._period_label(),
                    "debit": 0.0,
                    "credit": float(bal),
                }))
                total_credit += bal
            else:
                amt = -bal
                line_vals.append((0, 0, {
                    "account_id": acc_id,
                    "name": _("Periodavslut moms %s") % self._period_label(),
                    "debit": float(amt),
                    "credit": 0.0,
                }))
                total_debit += amt
        # net_to_offset = D − K (positive = pay SKV, goes on 2650 K side)
        net_to_offset = total_debit - total_credit

        # net_to_offset = belopp att skuldföra på 2650 (positivt = betala SKV)
        # Hitta kontona
        acc_2650 = Account.search([
            ("code_store", "=", "2650"),
            ("company_ids", "in", [self.env.company.id]),
        ], limit=1)
        if not acc_2650:
            raise UserError(_("Hittar inget konto 2650 Redovisningskonto för moms."))
        acc_3740 = Account.search([
            ("code_store", "=", "3740"),
            ("company_ids", "in", [self.env.company.id]),
        ], limit=1)
        if not acc_3740:
            # 3740 is part of standard BAS but if missing, fall back to a similar
            # rounding account (3741, 7960, etc.)
            acc_3740 = Account.search([
                ("code_store", "in", ["3741", "7960", "7961", "7969"]),
                ("company_ids", "in", [self.env.company.id]),
            ], limit=1)

        # eSKD-export rapporterar heltal kronor → 2650 ska bli heltal så att
        # bank-betalningen 2650 D / 1930 K går rent. Diff (öres) → 3740.
        rounded_net = Decimal(int(net_to_offset.to_integral_value(rounding=ROUND_HALF_UP)))
        rounding_diff = (net_to_offset - rounded_net).quantize(TWO, rounding=ROUND_HALF_UP)

        # 2650-raden — heltal kronor
        if rounded_net > 0:
            line_vals.append((0, 0, {
                "account_id": acc_2650.id,
                "name": _("Moms att betala SKV %s") % self._period_label(),
                "debit": 0.0,
                "credit": float(rounded_net),
            }))
            total_credit += rounded_net
        elif rounded_net < 0:
            line_vals.append((0, 0, {
                "account_id": acc_2650.id,
                "name": _("Moms att få tillbaka SKV %s") % self._period_label(),
                "debit": float(-rounded_net),
                "credit": 0.0,
            }))
            total_debit += -rounded_net

        # Öresavrundning: balansera D − K så det blir exakt noll
        if abs(rounding_diff) >= TWO:
            if not acc_3740:
                raise UserError(_(
                    "Konto 3740 Öresavrundning saknas och avrundningsdiff är %s kr. "
                    "Skapa kontot eller bokför manuellt."
                ) % rounding_diff)
            if rounding_diff > 0:
                # Momskonton summerar högre än rounded_net → 3740 K för balans
                line_vals.append((0, 0, {
                    "account_id": acc_3740.id,
                    "name": _("Öresavrundning moms %s") % self._period_label(),
                    "debit": 0.0,
                    "credit": float(rounding_diff),
                }))
                total_credit += rounding_diff
            else:
                line_vals.append((0, 0, {
                    "account_id": acc_3740.id,
                    "name": _("Öresavrundning moms %s") % self._period_label(),
                    "debit": float(-rounding_diff),
                    "credit": 0.0,
                }))
                total_debit += -rounding_diff

        # Final balance check
        if total_debit != total_credit:
            raise UserError(_(
                "Internt fel: bokföringen är inte balanserad. "
                "D=%s, K=%s, diff=%s. Rapportera till utvecklaren."
            ) % (total_debit, total_credit, total_debit - total_credit))

        move = Move.create({
            "journal_id": misc_journal.id,
            "date": self.date_to,
            "ref": period_ref,
            "move_type": "entry",
            "line_ids": line_vals,
        })

        # Compute and freeze the box-amounts for this period — these are
        # the values eSKD will report (and what stale-detection compares
        # against in future periods).
        #
        # Store as Decimal-quantized strings (not floats) so the JSON
        # snapshot is bit-exact and stale-detection doesn't trigger on
        # float representation noise (e.g. 12345.67 → 12345.6700000001).
        rows, total_out, total_in, to_pay = self._compute_box_amounts()
        TWO = Decimal("0.01")
        box_amounts = {
            r["code"]: str(Decimal(str(r["amount"])).quantize(TWO, rounding=ROUND_HALF_UP))
            for r in rows
        }

        filing = Filing.create({
            "period_start": self.date_from,
            "period_end": self.date_to,
            "period_label": self._period_label(),
            "box_amounts_json": json.dumps(box_amounts),
            "total_out_vat": total_out,
            "total_in_vat": total_in,
            "to_pay": to_pay,
            "journal_entry_id": move.id,
            "company_id": self.env.company.id,
        })

        # Open the filing — from there the user can view the journal entry,
        # export eSKD, or unfile.
        return {
            "type": "ir.actions.act_window",
            "name": _("Momsinlämning %s") % self._period_label(),
            "res_model": "l10n_se_skv_vat_report.filing",
            "res_id": filing.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_export_eskd(self):
        """Generate eSKD XML and offer download.

        Kräver att perioden är BOKAD (= filing finns) — eSKD-värdena ska
        alltid matcha det som är bokfört på 2650. Tidigare flöde där eSKD
        kunde exporteras separat innan bokning ledde till divergens om
        nya verifikat tillkom mellan export och bokning.
        """
        self.ensure_one()
        if not self.date_from or not self.date_to:
            self._onchange_period()
        if not self.only_posted:
            raise UserError(_("eSKD-export kräver bara bokförda verifikat. "
                              "Kryssa i 'Endast bokförda verifikat'."))
        self._block_if_stale()
        if not self.filing_id:
            raise UserError(_(
                "Perioden är inte bokad ännu. Kör 'Skapa momsbokföring' "
                "först — bokningen skapar inlämningen och fryser värdena, "
                "varefter eSKD kan exporteras."
            ))

        # Use the FROZEN values from the filing, not a fresh recompute.
        # Stale-detection above ensures these still match reality; reading
        # from the filing guarantees the eSKD download exactly matches the
        # bokning, even if a re-export happens later.
        # get_box_amounts() returns Decimal — _build_eskd_xml's to_int_kr()
        # uses Decimal(str(val)) internally so we can pass either type.
        frozen = self.filing_id.get_box_amounts()
        zero = Decimal("0")
        rows = [{"code": code, "amount": frozen.get(code, zero),
                 "label": label} for code, label in SKV_ROWS]
        xml_bytes = self._build_eskd_xml(rows, self.filing_id.to_pay)
        filename = f"{self.date_from.strftime('%Y%m%d')}-{self.date_to.strftime('%Y%m%d')}.eskd"
        self.eskd_filename = filename
        self.eskd_data = base64.b64encode(xml_bytes)

        # Persist the exported XML on the filing too — so we can show
        # exactly what was uploaded later.
        self.filing_id.write({
            "eskd_data": self.eskd_data,
            "eskd_filename": filename,
        })

        return {
            "type": "ir.actions.act_url",
            "url": (f"/web/content/l10n_se_skv_vat_report.wizard/{self.id}/eskd_data"
                    f"?filename_field=eskd_filename&download=true"),
            "target": "self",
        }

    def action_view_report(self):
        """Open the report in PDF."""
        self.ensure_one()
        if not self.date_from or not self.date_to:
            self._onchange_period()
        rows, out_vat, in_vat, to_pay = self._compute_box_amounts()
        # Count drafts in period for the report warning
        draft_count = self.env["account.move"].search_count([
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
            ("state", "=", "draft"),
            ("move_type", "in", ["in_invoice", "out_invoice",
                                  "in_refund", "out_refund", "entry"]),
            ("company_id", "=", self.env.company.id),
        ])
        data = {
            "date_from": self.date_from,
            "date_to": self.date_to,
            "company_name": self.env.company.name,
            "company_vat": self.env.company.vat or "",
            "rows": rows,
            "total_out_vat": out_vat,
            "total_in_vat": in_vat,
            "to_pay": to_pay,
            "only_posted": self.only_posted,
            "draft_count": draft_count,
        }
        return self.env.ref(
            "l10n_se_skv_vat_report.action_report_skv_moms"
        ).report_action(self, data=data)

    # Stored result fields for in-browser preview
    result_html = fields.Html(string="Resultat", readonly=True)

    # eSKD download fields
    eskd_filename = fields.Char(string="eSKD-filnamn", readonly=True)
    eskd_data = fields.Binary(string="eSKD-fil", readonly=True)

    draft_warning = fields.Html(
        string="Varning",
        compute="_compute_draft_warning",
    )

    compliance_warnings = fields.Html(
        string="Compliance-varningar",
        compute="_compute_compliance_warnings",
    )

    # ------------------------------------------------------------------
    # Filing status (Spiris-modell: en filing per period, fryser värden)
    # ------------------------------------------------------------------
    filing_id = fields.Many2one(
        "l10n_se_skv_vat_report.filing",
        string="Aktiv inlämning för perioden",
        compute="_compute_filing_id",
    )
    filing_status_html = fields.Html(
        string="Inlämningsstatus",
        compute="_compute_filing_status_html",
    )
    stale_filings_html = fields.Html(
        string="Tidigare perioder med drift",
        compute="_compute_stale_filings_html",
    )
    has_stale_prior = fields.Boolean(
        compute="_compute_stale_filings_html",
        help="True om någon tidigare inlämnad period har drivit (= nya verifikat "
             "med moms efter inlämning). Blockerar eSKD-export och bokning.",
    )
    cancel_reason = fields.Text(string="Anledning till ångrande")

    @api.depends("date_from", "date_to")
    def _compute_filing_id(self):
        Filing = self.env["l10n_se_skv_vat_report.filing"]
        for w in self:
            if not w.date_from or not w.date_to:
                w.filing_id = False
                continue
            w.filing_id = Filing.find_filed_for_period(
                w.date_from, w.date_to, w.env.company.id)

    @api.depends("filing_id")
    def _compute_filing_status_html(self):
        for w in self:
            if not w.filing_id:
                w.filing_status_html = False
                continue
            f = w.filing_id
            filed_str = fields.Datetime.context_timestamp(
                w, f.filed_at).strftime("%Y-%m-%d %H:%M")
            # Escape user-controlled strings (period_label is ours, but
            # filed_by.name could be anything). Use Markup for the static
            # template so escape() is applied to interpolated values only.
            w.filing_status_html = Markup(
                '<div class="alert alert-info" style="margin:0;">'
                '<strong>📄 Period redan inlämnad</strong><br/>'
                'MOMS {label} bokad och eSKD-exporterad {filed_at} '
                'av {user}.<br/>'
                'Att betala SKV: <strong>{amount} kr</strong>. '
                'För att ändra: ångra inlämningen först (knapp nedan), '
                'sedan kan du generera om rapporten.'
                '</div>'
            ).format(
                label=escape(f.period_label or ""),
                filed_at=escape(filed_str),
                user=escape(f.filed_by.name or ""),
                amount=escape(f"{f.to_pay:,.2f}"),
            )

    @api.depends("date_from", "date_to")
    def _compute_stale_filings_html(self):
        Filing = self.env["l10n_se_skv_vat_report.filing"]
        for w in self:
            w.has_stale_prior = False
            w.stale_filings_html = False
            if not w.date_from:
                continue
            try:
                stale = Filing.find_stale_prior_filings(
                    w.date_from, w.env.company.id)
            except Exception:
                # Log full traceback server-side; show a generic message
                # in the UI to avoid leaking internal info via the banner.
                _logger.exception(
                    "Stale-filing check failed for wizard period %s",
                    w.date_from)
                w.stale_filings_html = Markup(
                    '<div class="alert alert-info">Kunde inte kontrollera '
                    'tidigare inlämningar — se serverloggar för detaljer.'
                    '</div>'
                )
                continue
            if not stale:
                continue
            w.has_stale_prior = True
            # Build the inner <li>-list safely: every interpolated value
            # goes through escape(), summary string is concatenated as
            # Markup for the static delimiters.
            items = []
            for f in stale:
                drift = f.get_drift_details()
                # Each diff piece is built from internal data (code, diff
                # number) — still escape defensively.
                diff_pieces = [
                    escape(f"{d['code'][3:]}: {d['diff']:+,.0f} kr")
                    for d in drift[:4]
                ]
                if len(drift) > 4:
                    diff_pieces.append(escape(f"+{len(drift) - 4} till"))
                diff_summary = Markup(", ").join(diff_pieces)
                filed_str = fields.Datetime.context_timestamp(
                    w, f.filed_at).strftime("%Y-%m-%d")
                items.append(Markup(
                    '<li><strong>MOMS {label}</strong> '
                    '(inlämnad {filed_at}): {diff}</li>'
                ).format(
                    label=escape(f.period_label or ""),
                    filed_at=escape(filed_str),
                    diff=diff_summary,
                ))
            w.stale_filings_html = Markup(
                '<div class="alert alert-danger" style="margin:0;">'
                '<strong>⛔ Det finns ändringar i tidigare inlämnade '
                'perioder</strong><br/>'
                'Nya eller ändrade momsverifikat har dykt upp i perioder '
                'som redan är bokförda och rapporterade till SKV. Du måste '
                'antingen ångra dessa inlämningar och göra om dem, eller '
                'flytta verifikaten till en öppen period innan du kan '
                'fortsätta.<ul style="margin:8px 0 0 0;">{items}</ul></div>'
            ).format(items=Markup("").join(items))

    def _block_if_stale(self):
        """Raise UserError if there are drifted prior filings."""
        self.ensure_one()
        Filing = self.env["l10n_se_skv_vat_report.filing"]
        stale = Filing.find_stale_prior_filings(
            self.date_from, self.env.company.id)
        if stale:
            labels = ", ".join(stale.mapped("period_label"))
            raise UserError(_(
                "Tidigare inlämnade perioder har ändrats: %s. "
                "Ångra dem och boka om, eller flytta de nya verifikaten till "
                "innevarande period, innan du kan fortsätta."
            ) % labels)

    def action_unfile_period(self):
        """Cancel the filing for the wizard's period (Spiris flow)."""
        self.ensure_one()
        if not self.filing_id:
            raise UserError(_("Det finns ingen aktiv inlämning att ångra."))
        return self.filing_id.with_context(
            default_cancel_reason=self.cancel_reason
        ).action_unfile()

    def action_view_filing(self):
        self.ensure_one()
        if not self.filing_id:
            raise UserError(_("Ingen inlämning för perioden."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "l10n_se_skv_vat_report.filing",
            "res_id": self.filing_id.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.depends("date_from", "date_to")
    def _compute_compliance_warnings(self):
        for w in self:
            if not w.date_from or not w.date_to:
                w.compliance_warnings = False
                continue
            try:
                checks = w._check_vat_compliance()
            except Exception as e:
                w.compliance_warnings = (
                    f'<div class="alert alert-info">Kunde inte köra '
                    f'compliance-check: {e}</div>'
                )
                continue
            if not checks:
                w.compliance_warnings = False
                continue
            html = []
            for c in checks:
                color = "danger" if c["level"] == "error" else "warning"
                html.append(
                    f'<div class="alert alert-{color}" style="margin:4px 0;">'
                    f'{c["message"]}</div>'
                )
            w.compliance_warnings = "".join(html)

    @api.depends("date_from", "date_to")
    def _compute_draft_warning(self):
        for w in self:
            if not w.date_from or not w.date_to:
                w.draft_warning = False
                continue
            domain = [
                ("date", ">=", w.date_from),
                ("date", "<=", w.date_to),
                ("state", "=", "draft"),
                ("move_type", "in", ["in_invoice", "out_invoice",
                                      "in_refund", "out_refund", "entry"]),
                ("company_id", "=", w.env.company.id),
            ]
            drafts = w.env["account.move"].search(domain)
            if not drafts:
                w.draft_warning = False
                continue
            # Group counts by move_type for the warning text
            by_type = {}
            for m in drafts:
                by_type[m.move_type] = by_type.get(m.move_type, 0) + 1
            type_labels = {
                "in_invoice": "leverantörsfakturor",
                "out_invoice": "kundfakturor",
                "in_refund": "lev. kreditfakturor",
                "out_refund": "kund kreditfakturor",
                "entry": "verifikat",
            }
            parts = [f"{n} {type_labels.get(t, t)}" for t, n in by_type.items()]
            # Clickable links: each draft → form view via web-client.
            # Use the legacy /web#-hash router which reliably resolves to the
            # account.move form (the modern /odoo/account-move/<id> route
            # doesn't always work and falls back to /odoo/discuss).
            link_items = []
            for m in drafts[:5]:
                label = m.name if m.name and m.name != "/" else _("(utkast %s)") % m.id
                url = (f"/web#id={m.id}&model=account.move&view_type=form")
                link_items.append(
                    f'<a href="{url}" target="_blank">{label}</a>'
                )
            if len(drafts) > 5:
                link_items.append(_("...m.fl."))
            link = ", ".join(link_items)
            w.draft_warning = (
                f'<div class="alert alert-warning" role="alert" style="margin:0;">'
                f'<strong>⚠ {len(drafts)} ej bokförda utkast</strong> i perioden '
                f'({", ".join(parts)}). '
                f'Granska och bokför dem innan du lämnar in deklarationen, '
                f'annars kan momsen bli fel.<br/>'
                f'<strong>Utkast:</strong> {link}'
                f'</div>'
            )

    def action_view_in_browser(self):
        """Compute and re-render wizard with HTML preview inline."""
        self.ensure_one()
        if not self.date_from or not self.date_to:
            self._onchange_period()
        rows, out_vat, in_vat, to_pay = self._compute_box_amounts()

        def fmt(n):
            # Swedish: 1 234 567,89
            return f"{n:,.2f}".replace(",", " ").replace(".", ",")

        html = ['<table class="o_list_view table table-sm" style="width:100%;border-collapse:collapse;">']
        html.append('<thead><tr style="border-bottom:2px solid #888;">'
                    '<th style="width:10%;text-align:left;">Ruta</th>'
                    '<th>Beskrivning</th>'
                    '<th style="width:20%;text-align:right;">Belopp (kr)</th>'
                    '</tr></thead><tbody>')
        for r in rows:
            if r["amount"]:
                html.append(f'<tr><td><b>{r["code"][3:]}</b></td>'
                            f'<td>{r["label"]}</td>'
                            f'<td style="text-align:right;">{fmt(r["amount"])}</td></tr>')
        html.append('</tbody></table>')
        html.append(f'<p style="margin-top:12px;">'
                    f'<b>Utgående moms:</b> {fmt(out_vat)} kr<br/>'
                    f'<b>Avdrag ingående moms:</b> –{fmt(in_vat)} kr<br/>'
                    f'<b style="font-size:1.1em;">Att betala till SKV: {fmt(to_pay)} kr</b>'
                    f'</p>')
        self.result_html = "".join(html)

        return {
            "type": "ir.actions.act_window",
            "res_model": "l10n_se_skv_vat_report.wizard",
            "res_id": self.id,
            "view_mode": "form",
            "view_id": self.env.ref("l10n_se_skv_vat_report.view_skv_moms_wizard_form").id,
            "target": "new",
            "context": self.env.context,
        }
