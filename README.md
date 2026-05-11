# odoo-l10n-se-skv

Odoo modules implementing Skatteverket integration for Swedish accounting.

## Modules

| Module | Description |
|--------|-------------|
| [`l10n_se_skv_vat_report`](l10n_se_skv_vat_report/) | VAT return (*momsdeklaration*) report — all SKV boxes 05-62, eSKD XML export, period-end bookkeeping, drill-down |

More modules will land here as we work through other Skatteverket-facing
features (eSKD-import for filed returns, SIE5-export, AGI-filing helpers,
etc.). Each module installs independently.

## Disclaimer

Modules in this repository are under active development. **Use at
your own risk.** No functionality has been verified for every
possible scenario, chart of accounts variation, or fiscal setup.
You are solely responsible for the correctness of every output
before submitting anything to Skatteverket or otherwise relying on
the result.

Molnkontakt AB disclaims all liability for errors, omissions,
incorrect filings, missed deadlines, penalties (*skattetillägg*,
*förseningsavgift*, interest, etc.), or any other consequences —
direct, indirect, incidental, or consequential — arising from use
of these modules. Always reconcile against your bookkeeping and
consult a qualified accountant if uncertain. This disclaimer
supplements the warranty and liability terms in LGPL-3.

## License

LGPL-3 — same as the surrounding Odoo CE ecosystem.
