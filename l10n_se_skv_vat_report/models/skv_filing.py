"""SKV momsdeklaration filing — frozen record of a submitted VAT return.

Spiris-modell: en period kan ha en filing åt gången. Filing skapas när
användaren bokar momsverifikatet (action_create_vat_journal_entry) och
fryser då de rapporterade box-värdena. För att rätta något i en redan
inlämnad period måste användaren först ångra filingen (vilket reverse:ar
bokningen via account.move._reverse_moves).

Stale-detektering: när wizarden öppnas för en NY period kontrolleras alla
tidigare filings — om saldot på SE-tax-tags i den frusna perioden har
ändrats (= nya/ändrade verifikat med moms efter inlämningsdatum) blockeras
ny export/bokning tills användaren antingen ångrar gamla filingen eller
flyttar de nya verifikaten till en öppen period.
"""

import json
from decimal import ROUND_HALF_UP, Decimal

from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Tolerance for drift detection: 0.50 kr per box. eSKD rounds to whole
# kronor anyway, so sub-krona deltas (öres) are not material.
DRIFT_TOLERANCE = Decimal("0.50")
TWO = Decimal("0.01")


class SkvFiling(models.Model):
    _name = "l10n_se_skv_vat_report.filing"
    _description = "SKV Momsdeklaration — inlämnad rapport"
    _order = "period_end desc, id desc"
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name", store=True)

    period_start = fields.Date(string="Period från", required=True, index=True)
    period_end = fields.Date(string="Period till", required=True, index=True)
    period_label = fields.Char(string="Period", required=True,
                               help="T.ex. '2026 Q1' eller '2026-03'")

    state = fields.Selection([
        ("filed", "Inlämnad"),
        ("cancelled", "Ångrad"),
    ], string="Status", default="filed", required=True, index=True)

    filed_at = fields.Datetime(string="Inlämnad", default=fields.Datetime.now,
                               required=True, readonly=True)
    filed_by = fields.Many2one("res.users", string="Inlämnad av",
                               default=lambda self: self.env.user,
                               required=True, readonly=True)

    cancelled_at = fields.Datetime(string="Ångrad", readonly=True)
    cancelled_by = fields.Many2one("res.users", string="Ångrad av", readonly=True)
    cancel_reason = fields.Text(string="Anledning till ångrande")

    # Frusna box-värden — JSON-objekt med Decimal-quantized strängar
    # för att undvika float-precision drift, t.ex.:
    #   {"se_05": "12345.67", "se_10": "3086.25", ...}
    # get_box_amounts() läser tillbaka som Decimal.
    box_amounts_json = fields.Text(string="Frusna box-värden (JSON)",
                                   readonly=True, required=True)

    # Sammanfattning för listvyn
    total_out_vat = fields.Monetary(string="Utgående moms", readonly=True,
                                    currency_field="currency_id")
    total_in_vat = fields.Monetary(string="Ingående moms", readonly=True,
                                   currency_field="currency_id")
    to_pay = fields.Monetary(string="Att betala SKV", readonly=True,
                             currency_field="currency_id")

    currency_id = fields.Many2one("res.currency",
                                  default=lambda s: s.env.company.currency_id,
                                  required=True)
    company_id = fields.Many2one("res.company", required=True, index=True,
                                 default=lambda s: s.env.company)

    # eSKD-fil som faktiskt exporterades
    eskd_data = fields.Binary(string="eSKD-fil", readonly=True, attachment=True)
    eskd_filename = fields.Char(string="eSKD-filnamn", readonly=True)

    # Det skapade momsverifikatet (kan ha blivit reverserat — se reversal_move_id)
    journal_entry_id = fields.Many2one("account.move",
                                       string="Momsverifikat", readonly=True,
                                       ondelete="restrict")
    reversal_move_id = fields.Many2one("account.move",
                                       string="Reverseringsverifikat", readonly=True,
                                       ondelete="set null",
                                       help="Skapas vid ångrande av posted "
                                            "verifikat (account.move._reverse_moves).")

    # Note: no _sql_constraints — we use a partial unique INDEX created in
    # init() instead. Constraints with WHERE-clauses require either
    # EXCLUDE (which needs btree_gist extension) or a partial UNIQUE INDEX
    # (vanilla PostgreSQL). Partial index is simpler and portable.

    def init(self):
        # One ACTIVE filing per (company, period). Cancelled filings are
        # excluded so a period can be unfiled and re-filed any number of
        # times, but only one filing can be active at a time.
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
                l10n_se_skv_filing_uniq_filed_period
            ON l10n_se_skv_vat_report_filing (company_id, period_start, period_end)
            WHERE state = 'filed'
        """)

    @api.depends("period_label", "state", "filed_at")
    def _compute_display_name(self):
        for r in self:
            r.display_name = f"MOMS {r.period_label or '?'} ({r.state})"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_box_amounts(self) -> dict:
        """Return the frozen box-amounts as a {code: Decimal} dict.

        Snapshots are stored as JSON strings for bit-exact round-trip
        (avoids float-precision drift). Callers that need a float (PDF
        rendering, eSKD int-rounding) can cast at the use site.
        """
        self.ensure_one()
        if not self.box_amounts_json:
            return {}
        return {
            k: Decimal(str(v)).quantize(TWO, rounding=ROUND_HALF_UP)
            for k, v in json.loads(self.box_amounts_json).items()
        }

    @api.model
    def find_filed_for_period(self, date_from, date_to, company_id=None):
        """Return the active (state=filed) filing for the given period, or empty."""
        company_id = company_id or self.env.company.id
        return self.search([
            ("company_id", "=", company_id),
            ("period_start", "=", date_from),
            ("period_end", "=", date_to),
            ("state", "=", "filed"),
        ], limit=1)

    @api.model
    def find_overlapping_filings(self, date_from, date_to, company_id=None,
                                 exclude_exact=True):
        """Return active filings whose period overlaps the given range.

        Used to catch cases like: Q1 is filed, user opens the wizard with
        period_type=month and picks February — the wizard would otherwise
        miss that February is already covered by the Q1 filing.

        exclude_exact=True (default) skips a filing whose period matches
        exactly — that case is handled by find_filed_for_period and shown
        as the "Period redan inlämnad" banner instead.
        """
        company_id = company_id or self.env.company.id
        domain = [
            ("company_id", "=", company_id),
            ("state", "=", "filed"),
            ("period_start", "<=", date_to),
            ("period_end", ">=", date_from),
        ]
        filings = self.search(domain)
        if exclude_exact:
            filings = filings.filtered(
                lambda f: not (f.period_start == date_from
                               and f.period_end == date_to)
            )
        return filings

    @api.model
    def find_stale_prior_filings(self, before_date, company_id=None):
        """Return filings with period_end < before_date that have drifted from
        their frozen box-amounts (= new/changed VAT moves since filing).

        TODO(perf): runs full _compute_box_amounts() per candidate, so cost
        is O(n_filings) on every wizard open. For typical SE companies
        (~4 quarters/year × a few years) n is small. If this becomes hot:
        cache an aml.write_date watermark per filing and only recompute
        when something newer than the watermark touched the period.
        """
        company_id = company_id or self.env.company.id
        candidates = self.search([
            ("company_id", "=", company_id),
            ("state", "=", "filed"),
            ("period_end", "<", before_date),
        ])
        stale = self.env[self._name]
        for filing in candidates:
            if filing._has_drifted():
                stale |= filing
        return stale

    def _current_box_amounts(self) -> dict:
        """Recompute the box-amounts NOW for this filing's period (posted only).

        Used by stale-detection — compares the current saldo against the
        frozen snapshot. Runs in the filing's company context so multi-company
        setups don't mix balances from sibling companies.
        """
        self.ensure_one()
        # Reuse the wizard's computation by instantiating a transient one.
        # with_company swaps env.company so _compute_box_amounts() uses the
        # filing's company even if env.company differs (multi-company users).
        wizard = self.env["l10n_se_skv_vat_report.wizard"].with_company(
            self.company_id
        ).new({
            "date_from": self.period_start,
            "date_to": self.period_end,
            "only_posted": True,
        })
        rows, _out, _in, _pay = wizard._compute_box_amounts()
        return {
            r["code"]: Decimal(str(r["amount"])).quantize(TWO, rounding=ROUND_HALF_UP)
            for r in rows
        }

    def _has_drifted(self) -> bool:
        """True if current saldo differs from the frozen snapshot beyond
        DRIFT_TOLERANCE per box. Decimal-only comparison — no float noise.
        """
        self.ensure_one()
        frozen = self.get_box_amounts()
        current = self._current_box_amounts()
        zero = Decimal("0")
        for code in set(frozen) | set(current):
            if abs(frozen.get(code, zero) - current.get(code, zero)) >= DRIFT_TOLERANCE:
                return True
        return False

    def get_drift_details(self) -> list:
        """Return list of {code, frozen, current, diff} for boxes that drifted."""
        self.ensure_one()
        frozen = self.get_box_amounts()
        current = self._current_box_amounts()
        zero = Decimal("0")
        details = []
        for code in sorted(set(frozen) | set(current)):
            f = frozen.get(code, zero)
            c = current.get(code, zero)
            diff = c - f
            if abs(diff) >= DRIFT_TOLERANCE:
                details.append({
                    "code": code,
                    "frozen": f,
                    "current": c,
                    "diff": diff,
                })
        return details

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_view_journal_entry(self):
        self.ensure_one()
        if not self.journal_entry_id:
            raise UserError(_("Inget momsverifikat kopplat till denna inlämning."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.journal_entry_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_download_eskd(self):
        """Trigger eSKD file download via the standard /web/content URL."""
        self.ensure_one()
        if not self.eskd_data:
            raise UserError(_(
                "Ingen eSKD-fil finns på denna inlämning. Ångra och boka "
                "om perioden för att generera filen på nytt."
            ))
        return {
            "type": "ir.actions.act_url",
            "url": (f"/web/content/l10n_se_skv_vat_report.filing/{self.id}"
                    f"/eskd_data?filename_field=eskd_filename&download=true"),
            "target": "self",
        }

    def action_view_drift_details(self):
        """Open the move-lines that drove the drift, scoped to this filing's period."""
        self.ensure_one()
        SE_country = self.env["res.country"].search([("code", "=", "SE")], limit=1)
        SE_tag_ids = self.env["account.account.tag"].search([
            ("country_id", "=", SE_country.id),
            ("applicability", "=", "taxes"),
        ]).ids
        return {
            "type": "ir.actions.act_window",
            "name": _("Verifikat i %s (efter inlämning)") % self.period_label,
            "res_model": "account.move.line",
            "view_mode": "list,form",
            "domain": [
                ("date", ">=", self.period_start),
                ("date", "<=", self.period_end),
                ("parent_state", "=", "posted"),
                ("tax_tag_ids", "in", SE_tag_ids),
                ("company_id", "=", self.company_id.id),
                # Skapade efter filing — visar troliga drift-orsaker först
                ("create_date", ">=", self.filed_at),
            ],
            "context": {
                "search_default_group_by_move_id": 1,
                "create": False,
            },
        }

    def action_unfile(self):
        """Cancel the filing. If the journal entry is posted, reverse it via
        Odoo's standard _reverse_moves (creates a counter-entry, leaves the
        original in place for the audit trail). If draft, just unlink it.
        """
        self.ensure_one()
        if self.state != "filed":
            raise UserError(_("Endast inlämnade filings kan ångras."))

        # Reason is optional but recommended — captured via the wizard view
        reason = self.env.context.get("default_cancel_reason") or self.cancel_reason

        move = self.journal_entry_id
        reversal = self.env["account.move"]
        if move:
            if move.state == "posted":
                # Reverse via Odoo's standard mechanism. Posted reversal lands
                # in the same period (date=move.date), keeping the audit trail
                # in place rather than backdating to today.
                reversal = move._reverse_moves(default_values_list=[{
                    "date": move.date,
                    "ref": _("Ångrad MOMS %s") % self.period_label,
                }], cancel=False)
                # Post the reversal so it actually offsets the original
                reversal.action_post()
            elif move.state == "draft":
                # Draft entries can be unlinked outright. Must null
                # journal_entry_id first because the FK is ondelete=restrict
                # (we never want a posted move silently disappearing).
                self.journal_entry_id = False
                move.unlink()
            # else: cancelled/already gone — leave as-is

        self.write({
            "state": "cancelled",
            "cancelled_at": fields.Datetime.now(),
            "cancelled_by": self.env.user.id,
            "cancel_reason": reason,
            "reversal_move_id": reversal.id if reversal else False,
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Inlämning ångrad"),
                "message": _("MOMS %s är nu ångrad. Du kan generera en ny "
                             "rapport och boka om den.") % self.period_label,
                "type": "success",
                "sticky": False,
            },
        }
