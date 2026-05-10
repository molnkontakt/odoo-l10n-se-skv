# Security Policy

## Reporting a Vulnerability

If you discover a security issue, please report it **privately** via
[GitHub's private vulnerability reporting](https://github.com/molnkontakt/odoo-l10n-se-skv/security/advisories/new).

We aim to acknowledge reports within 5 business days and provide a status
update within 14 days.

## Scope

In scope:

- Code in this repository
- Python imports declared in module manifests

Out of scope:

- Vulnerabilities in upstream Odoo (report to Odoo SA directly)
- Vulnerabilities in Skatteverket's eSKD upload service (report to Skatteverket)

## Security-relevant design notes

- The module reads from Odoo's ORM and produces XML/PDF output. It does
  not call out to any third-party service. The `eSKD`-export file is
  produced locally; the user uploads it manually via skatteverket.se.
- No credentials or PII are stored by the module.
