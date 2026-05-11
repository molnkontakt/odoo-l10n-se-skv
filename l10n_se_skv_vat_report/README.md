# Sweden — Skatteverket VAT Report

> Swedish VAT return (*momsdeklaration*) generator for Odoo Community
> Edition. All Skatteverket boxes 05-62, eSKD XML export, period-end
> bookkeeping helper, drill-down to source verifications.

> [!WARNING]
> **Under active development — use at your own risk.** This module is
> provided as-is. No functionality has been verified against every
> possible scenario, chart of accounts variation, or fiscal setup.
> You are solely responsible for verifying that the report output,
> eSKD file, and period-end bookkeeping match your actual tax
> obligations before submitting anything to Skatteverket. Molnkontakt
> AB disclaims all liability for errors, omissions, incorrect filings,
> missed deadlines, penalties, or any other consequences arising from
> use of this module. Always reconcile against your bookkeeping and
> consult a qualified accountant if uncertain.
>
> *På svenska:* Modulen är under utveckling och tillhandahålls i
> befintligt skick. Ingen funktionalitet är verifierad för alla
> scenarier. All användning sker på eget ansvar. Molnkontakt AB
> friskriver sig från allt ansvar för felaktigheter, missade
> deadlines, skattetillägg eller andra konsekvenser som kan uppstå
> vid användning. Stäm alltid av mot din bokföring och rådgör med
> en kvalificerad redovisningskonsult vid osäkerhet.

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

### Reporting

- **Period picker** — year / quarter / month / custom range. Defaults
  to the previous quarter (the one you typically declare). Yearly
  mode is for businesses with beskattningsunderlag ≤ 1M SEK that
  report annually per SFL 26 kap. 11 §.
- **All Skatteverket boxes** — 05, 06, 07, 08, 10, 11, 12, 20-24,
  30-32, 35-42, 48, 50, 60-62.
- **Inline preview** — HTML table in the wizard.
- **Printable PDF** — QWeb report.
- **eSKD XML export** — matches Skatteverket's `eSKDUpload` DTD 6.0
  (ISO-8859-1, CRLF, only non-zero fields). Upload directly via
  *skatteverket.se → Lämna momsdeklaration → Deklarera via fil*.
- **Drill-down** — list all journal lines that contributed to the
  report, grouped by account.

### Filing & period locking (Spiris-style)

- **Filings model** (`l10n_se_skv_vat_report.filing`) — each
  submitted return is persisted as a frozen record holding the box
  amounts (Decimal-quantized JSON), the period-end journal entry,
  and the generated eSKD XML. One active filing per `(company,
  period)` is enforced by a partial `UNIQUE INDEX` (no `btree_gist`
  required).
- **One-click submit** — *Skapa momsbokföring + lämna in* creates
  the closing journal entry **and** the filing **and** the eSKD
  file in a single action. Re-opening the wizard for a filed period
  shows a status banner instead of letting you book again.
- **Unfile flow** — to correct a submitted period you explicitly
  unfile, which `account.move._reverse_moves` posts a counter-entry
  in the same period (audit trail preserved) or unlinks a draft
  outright. Then you can generate a new report and re-submit.
- **Overlap detection** — selecting a period that fully or partially
  overlaps an existing filed period (e.g. picking month February
  when Q1 is already filed) shows a red banner and blocks
  export/booking until the prior filing is unfiled or the wizard
  range is adjusted.
- **Stale-prior detection** — each time the wizard is opened, it
  re-computes the box totals for every earlier filed period and
  flags any that have drifted (= new or changed VAT-tagged moves
  after submission). Booking and export are blocked until the user
  either unfiles the drifted period(s) or moves the offending
  entries to an open period.

### Compliance checks

- **Dormant VAT accounts** (2618/2628/2638/2648) with a balance
- **One-sided reverse charge** (2614/2624/2634 without matching
  2645/2647 — forbidden under ML 16 kap)
- **Unclosed prior period balance on 2650**
- **Draft warning** — lists unposted moves in the period as clickable
  links so you can post or review them before declaring.

### Period-end bookkeeping

The submit action closes 261x/262x/263x/264x against 2650 with the
öres rounding diff going to 3740. The closing entry is opened as a
draft for review before posting; the filing references the move so
unfiling can reverse it cleanly.

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

1. Pick the period (default = previous quarter; year, month and custom
   range also available).
2. Review the compliance warnings, draft warning, and any
   overlap/drift banners. Use *Visa i webbläsare* / *Skriv ut PDF*
   to preview the result.
3. Click **Skapa momsbokföring + lämna in** — this creates the
   closing journal entry, freezes the filing, and generates the
   eSKD file in one step.
4. From the filing form (or from *Accounting → Reporting →
   Skatteverket → Momsinlämningar*), click **Hämta eSKD-fil** and
   upload it on skatteverket.se.
5. If something needs to change after submission, open the filing
   and click **Ångra inlämning** — the journal entry is reversed
   and you can re-run the wizard.

The wizard's *Regenerera eSKD-fil* button is a fallback if the file
ever needs to be re-emitted from the same frozen values; eSKD is
generated automatically at filing time and rarely needs manual
regeneration.

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

## Disclaimer

This module is under active development. No part of it has been
verified for every possible scenario, chart of accounts variation,
or fiscal setup. **You bear sole responsibility for the correctness
of every number, journal entry, and eSKD file produced.** Always
reconcile against your bookkeeping and consult a qualified accountant
before submitting anything to Skatteverket.

Molnkontakt AB disclaims all liability for any errors, omissions,
incorrect filings, missed deadlines, penalties (including but not
limited to *skattetillägg*, *förseningsavgift*, or interest), data
loss, or any other direct, indirect, incidental, or consequential
damages arising from the use of this module, regardless of theory of
liability and even if advised of the possibility of such damages.

This disclaimer is in addition to, and not in lieu of, the warranty
and liability terms in the LGPL-3 license below.

## License

LGPL-3.

## Contributing

Issues and PRs welcome at
<https://github.com/molnkontakt/odoo-l10n-se-skv>.
