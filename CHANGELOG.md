# Changelog

All notable changes to `l10n_se_skv_vat_report` will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to Odoo's `<odoo-version>.<major>.<minor>.<patch>`
versioning scheme.

## [Unreleased]

(Nothing yet — first public release is v19.0.1.0.0.)

## [19.0.1.0.0] — 2026-05-10

### Added

- **Period picker wizard** with quarter, month, and custom-range modes.
  Defaults to the previous quarter (the period typically declared).
- **All Skatteverket boxes** 05–08, 10–12, 20–24, 30–32, 35–42, 48,
  50, 60–62 read directly from `tax_tag_ids` on `account.move.line`,
  bypassing the `tax_line_id` filter that makes the OCA generic VAT
  report blind to SIE-imported entries.
- **Inline HTML preview** in the wizard.
- **Printable PDF** via QWeb report.
- **eSKD XML export** matching Skatteverket's `eSKDUpload` DTD 6.0
  (ISO-8859-1, CRLF, only non-zero fields).
- **Compliance checks**:
    - Dormant VAT accounts (2618/2628/2638/2648) with a balance
    - One-sided reverse charge (2614/2624/2634 without matching
      2645/2647) — flags violations of ML 16 kap.
    - Unclosed prior period balance on 2650
- **Draft warning** with clickable links to unposted moves in the
  selected period.
- **Drill-down** action: list all journal lines that contributed to the
  report, grouped by account.
- **Period-end VAT bookkeeping** helper: closes 261x/262x/263x/264x to
  2650 with rounding diff to 3740. Idempotent via `ref="MOMS YYYY Qx"`
  so accidental double-clicks fail loudly instead of double-booking.

### Compliance

- Implements ML 2023:200 kap. 16 (reverse charge) validation
- Honors BFL 5 kap. 5 § (corrections via new entries, never overwrite)
- Output format matches Skatteverket's published eSKD spec exactly

[19.0.1.0.0]: https://github.com/molnkontakt/odoo-l10n-se-skv/releases/tag/v19.0.1.0.0
[Unreleased]: https://github.com/molnkontakt/odoo-l10n-se-skv/compare/v19.0.1.0.0...HEAD
