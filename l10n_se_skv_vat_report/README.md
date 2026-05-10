# Sweden — Skatteverket VAT Report

> Swedish VAT return (*momsdeklaration*) generator for Odoo Community
> Edition. All Skatteverket boxes 05-62, eSKD XML export, period-end
> bookkeeping helper, drill-down to source verifications.

## Why

Odoo CE doesn't ship a Swedish VAT report. The OCA `account_financial_report`
module includes a generic VAT report, but it only sees journal lines that
have a non-null `tax_line_id` — i.e. lines created by an `account.tax`
record. **SIE-imported journal entries** (the typical migration path
from Visma, Fortnox, SpeedLedger, Bokio, Spiris, etc.) carry their tax
tags directly on the move line without an associated `account.tax`, so
they're invisible to the OCA report.

This module reads `tax_tag_ids` straight off `account.move.line` (via
the `account_account_tag_account_move_line_rel` join table), so it works
for both Odoo-native invoices **and** legacy SIE imports.

## Features

- **Period picker** — quarter / month / custom range. Defaults to the
  previous quarter (the one you typically declare).
- **All Skatteverket boxes** — 05, 06, 07, 08, 10, 11, 12, 20-24,
  30-32, 35-42, 48, 50, 60-62.
- **Inline preview** — HTML table in the wizard.
- **Printable PDF** — QWeb report.
- **eSKD XML export** — matches Skatteverket's `eSKDUpload` DTD 6.0
  (ISO-8859-1, CRLF, only non-zero fields). Upload directly via
  *skatteverket.se → Lämna momsdeklaration → Deklarera via fil*.
- **Compliance checks** in the wizard:
    - Dormant VAT accounts (2618/2628/2638/2648) with a balance
    - One-sided reverse charge (2614/2624/2634 without matching
      2645/2647 — *forbidden under ML 16 kap*)
    - Unclosed prior period balance on 2650
- **Draft warning** — lists unposted moves in the period as clickable
  links so you can post or review them before declaring.
- **Drill-down** — list all journal lines that contributed to the
  report, grouped by account.
- **Period-end bookkeeping** — single-click "Create VAT bookkeeping
  entry" that closes 261x/262x/263x/264x against 2650 (rounding diff
  to 3740). Idempotent via `ref="MOMS YYYY Qx"`, opens the draft for
  review before posting.

## Installation

```bash
# Clone into your Odoo addons path
cd /path/to/odoo/addons   # or /opt/oca/custom
git clone https://github.com/molnkontakt/odoo-l10n-se-skv.git
mv odoo-l10n-se-skv/l10n_se_skv_vat_report .

# Add the module's parent dir to your odoo.conf addons_path if not already
# Then install via UI (Apps menu) or CLI:
sudo -u odoo /usr/bin/odoo -c /etc/odoo/odoo.conf -d <dbname> \
    -i l10n_se_skv_vat_report --stop-after-init
sudo systemctl restart odoo
```

Hard dependencies: `account`, `l10n_se`. (The Swedish BAS chart of
accounts must be loaded — that's what `l10n_se` provides.)

## Usage

*Accounting → Reporting → Skatteverket → Momsrapport*

1. Pick the period (default = previous quarter).
2. Review the compliance warnings, if any.
3. Click **Visa i webbläsare** (preview), **Skriv ut PDF**, or
   **Exportera eSKD-fil**.
4. Optionally click **Skapa momsbokföring** to generate the period-end
   clearing entry (closes VAT accounts to 2650).

## eSKD format

The exported file matches Skatteverket's spec exactly:

```xml
<?xml version="1.0" encoding="ISO-8859-1"?>
<eSKDUpload Version="6.0">
<OrgNr>556000-0175</OrgNr>
<Moms>
<Period>202603</Period>
<ForsMomsEjAnnan>449054</ForsMomsEjAnnan>
<MomsUtgHog>112264</MomsUtgHog>
...
<MomsBetala>103330</MomsBetala>
</Moms>
</eSKDUpload>
```

Tag mapping per box is documented in
`wizard/skv_moms_wizard.py::ESKD_FIELDS`. Source: Skatteverket's
[Lämna momsdeklaration via fil](https://www.skatteverket.se/foretag/skatterochavdrag/momsdeklaration/lamnamomsdeklaration/lamnamomsdeklarationviafil.4.7eada0316b0b39cf9c11ea8.html)
documentation.

## Compliance grounding

Rules implemented are based on:

- **Skatteverket's blankett SKV 4700** (momsdeklaration) — field
  layout, box semantics
- **Skatteverket's eSKDUpload spec 6.0** — XML format
- **ML 2023:200** (Mervärdesskattelagen), in particular:
    - 16 kap. — reverse-charge rules; the validator that flags
      2614/2624/2634 without 2645/2647 enforces ML 16 kap.'s
      "silent netting prohibited" rule
    - 13 kap. — input VAT deductibility
- **BFL 5 kap. 5 §** — corrections must be visible alongside
  originals, never overwrite. The "Skapa momsbokföring" helper creates
  a *new* draft entry rather than mutating posted moves.

## Tested with

- Odoo 19 CE
- Swedish BAS chart of accounts (BAS 2026)
- Both freshly Odoo-bookkept companies and migrations from external
  systems via SIE4 import

## Limitations

- Sweden-only. The validator framework is pluggable but the built-in
  rules assume `country_id.code='SE'`.
- Single-company only at the moment. Multi-company support is on the
  roadmap — see issues.
- For foreign-currency invoices the report uses `debit - credit`
  directly (always company currency) rather than the cached
  `aml.balance` field, since the cache has been seen to drift on
  Odoo 19 for some EUR/USD invoices.

## License

LGPL-3.

## Contributing

Issues and PRs welcome at
<https://github.com/molnkontakt/odoo-l10n-se-skv>.
