# Changelog

All notable changes to `l10n_se_skv_vat_report` will be documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project adheres to Odoo's `<odoo-version>.<major>.<minor>.<patch>`
versioning scheme.

## [Unreleased]

## [19.0.2.0.1] — 2026-05-11

### Fixed (review feedback from PR #2)

- **Filing creation no longer fails for invoice users** — ACL grants
  `account.group_account_invoice` create+write on filing (delete still
  manager-only).
- **Replaced `EXCLUDE` constraint with partial UNIQUE INDEX** — works on
  vanilla PostgreSQL without the `btree_gist` extension.
- **Drafts can be unfiled cleanly** — null `journal_entry_id` before
  unlinking the draft move so the `ondelete='restrict'` FK doesn't
  block the cancellation.
- **Booking always uses posted moves** — wizard auto-enables
  `only_posted` before creating the journal entry, so the filing
  snapshot can never include drafts that aren't on 2650.
- **Decimal-quantized box amounts** — `box_amounts_json` now stores
  Decimal-quantized strings instead of floats, eliminating
  representation noise in stale-detection.
- **Multi-company drift checks** — `_current_box_amounts` runs in
  `with_company(filing.company_id)` so balances are never mixed across
  companies.
- **HTML escaping in wizard banners** — `period_label`, `filed_by.name`,
  and other interpolated values are escaped via `markupsafe`. Prevents
  potential XSS via maliciously-named users.
- **Sanitized exception path** — full traceback logged server-side via
  `_logger.exception`, banner shows a generic message instead of the
  raw exception text.

## [19.0.2.0.0] — 2026-05-11

### Added

- **Filing model** (`l10n_se_skv_vat_report.filing`) — persistent record
  of submitted VAT returns. Each filing freezes the box-amounts, links
  to the period-end journal entry, and stores the exported eSKD XML.
  Per-company unique constraint on (period_start, period_end) for active
  (`state=filed`) filings prevents double-filing the same period.
- **Spiris-style period locking** — `action_create_vat_journal_entry`
  now creates a filing in `state=filed` alongside the journal entry.
  The wizard recognizes the period as "submitted" and gates further
  modifications behind an explicit unfile step.
- **Stale-filing detection** — when opening the wizard for any period,
  earlier filings are scanned for drift (= new/changed VAT moves after
  filing). Drifted prior periods block new eSKD export and bookkeeping
  with a red banner listing the periods and per-box deltas, so the user
  must either unfile and re-submit, or move the offending entries to an
  open period.
- **Unfile flow** — cancels a filing. If the journal entry is `posted`,
  Odoo's standard `account.move._reverse_moves` creates a counter-entry
  in the same period and posts it (preserves the audit trail). Draft
  entries are unlinked outright. The filing transitions to
  `state=cancelled` with reason, timestamp, and reverser captured.
- **Filings list/form views** + menu entry under
  *Accounting → Reporting → Skatteverket → Momsinlämningar*.

### Changed

- **eSKD export now requires a filing** — exporting before bookkeeping
  is no longer possible; the XML always reflects the frozen filing
  values, guaranteeing the uploaded file matches what's on 2650.
  Re-exporting an existing filing is allowed and updates the stored
  XML attachment on the filing record.
- **Wizard idempotency check** moved from `account.move.ref` lookup to
  the filing's SQL exclusion constraint — stronger guarantee, no
  reliance on ref strings.

### Compliance rationale

- Mirrors how Spiris and similar SE accounting tools handle period
  closure: one filing per period, corrections require unfile + re-submit
  rather than incremental amendment files. Aligns with SFL 49 kap §11
  (period-error skattetillägg) — small drift caught before re-filing
  avoids the 2 % surcharge.

[19.0.2.0.0]: https://github.com/molnkontakt/odoo-l10n-se-skv/releases/tag/v19.0.2.0.0
[19.0.2.0.1]: https://github.com/molnkontakt/odoo-l10n-se-skv/releases/tag/v19.0.2.0.1

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
[Unreleased]: https://github.com/molnkontakt/odoo-l10n-se-skv/compare/v19.0.2.0.0...HEAD
