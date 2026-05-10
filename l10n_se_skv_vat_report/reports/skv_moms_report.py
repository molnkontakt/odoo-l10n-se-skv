"""Report controller for SKV Momsrapport PDF."""

from odoo import api, models


class SkvMomsReport(models.AbstractModel):
    _name = "report.l10n_se_skv_vat_report.skv_moms_report_template"
    _description = "SKV Momsrapport — PDF-rapport"

    @api.model
    def _get_report_values(self, docids, data=None):
        return {
            "doc_ids": docids,
            "doc_model": "l10n_se_skv_vat_report.wizard",
            "data": data or {},
        }
