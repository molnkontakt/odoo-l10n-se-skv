{
    "name": "Sweden — Skatteverket VAT Report",
    "version": "19.0.1.0.0",
    "category": "Accounting/Localizations/Reporting",
    "summary": "Swedish VAT return (momsdeklaration) per Skatteverket boxes 05, 10, 20-24, 30-32, 35-42, 48, 50, 60-62 — with eSKD export",
    "description": """
Sweden — Skatteverket VAT Report
================================

A complete VAT return generator for Swedish Odoo Community Edition.
Reads ``tax_tag_ids`` directly from ``account.move.line`` and aggregates
per Skatteverket box, so it works for both:

* Odoo-native invoices (where the tags come from ``account.tax``
  repartition lines)
* SIE-imported journal entries (where the tags are set directly on the
  move lines without an associated ``account.tax``)

The latter is the common gap that makes other VAT reports show empty
boxes for companies migrating from Visma/Fortnox/SpeedLedger/Bokio/Spiris.

Features
--------

* Wizard with quarter / month / custom-range period picker
* Default to the *previous* quarter (the one you typically declare)
* All Skatteverket boxes 05-62 supported
* Inline HTML preview, printable PDF report
* **eSKD XML export** matching the Skatteverket DTD 6.0 spec — upload
  directly via skatteverket.se / "Lämna momsdeklaration → Deklarera via fil"
* Compliance checks: dormant VAT accounts with balance, one-sided
  reverse charge (BAS 2614/2624/2634 without matching 2645/2647),
  unclosed prior period balance on 2650
* Drill-down: list all journal lines that contributed to a box, grouped
  by account
* Draft warning: lists unposted moves in the period as clickable links
* "Create VAT bookkeeping entry" — generates the period-end clearing
  draft (closes 261x/262x/263x/264x to 2650, with rounding to 3740)

Installation
------------

1. Install the module via the Apps menu (or ``odoo -i l10n_se_skv_vat_report``).
2. Make sure your chart of accounts is the Swedish BAS (the ``l10n_se``
   module is a hard dependency).
3. Open *Accounting → Reporting → Skatteverket → VAT Report*.

License: LGPL-3.
""",
    "author": "Molnkontakt AB",
    "website": "https://github.com/molnkontakt/odoo-l10n-se-skv",
    "license": "LGPL-3",
    "depends": ["account", "l10n_se"],
    "data": [
        "security/ir.model.access.csv",
        "views/skv_moms_views.xml",
        "reports/skv_moms_report.xml",
    ],
    "installable": True,
    "application": False,
}
