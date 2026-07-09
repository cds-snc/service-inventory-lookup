# Composing a unique program-code identifier

## Purpose

Give every Government of Canada program a single, stable, unique string that a
partner can look up in a picker widget, the way the service-inventory tool does
for service IDs. Composed from department + program code.

## Assumptions

Verified against the 2026-27 and 2025-26 lists:

- **Codes are unique per department.** A program code alone is not unique -
  internal-services codes (`ISS01`-`ISS15`) repeat for every department - but
  `(department, program code)` is unique across the dataset, so `{gcorg_ID}-{PROG}`
  is guaranteed unique.
- **Codes are stable across years.** TBS does not renumber program codes
  (confirmed with TBS). Codes are added or sunset, and a code's *name* can change
  (38 did between 2025-26 and 2026-27), but the code itself keeps its identity -
  so the identifier needs no year component.
- **Every department resolves.** [gcorg-resolver](https://gcorgs.cdssandbox.xyz) returns
  a numeric `gc_orgID` for every TBS-listed department; organizations in the Program
  Inventory but not on the TBS list of departments resolve to `0`.
- **EN and FR lists carry identical codes** and join on `(gcorg_ID, PROG)`.

## Identifier format

```
{gcorg_ID}-{PROG}
```

- `gcorg_ID` - the numeric GC organization ID for the department, as returned by
  [gcorg-resolver](https://gcorgs.cdssandbox.xyz). Used verbatim, no zero-padding;
  `0` for organizations not on the TBS list of departments.
- `PROG` - the `ProgramInventory-Répertoiredesprogrammes_code_PROG` value,
  uppercase (e.g. `BWN01`). Always 3 letters + 2 digits.
- Single hyphen delimiter. Neither part contains a hyphen, so the string splits
  back apart unambiguously.

Example: `2222-BWN01` (Agriculture and Agri-Food, "Trade and Market Expansion").

## What counts as a program

Only **Program Inventory entries**: rows with a non-blank
`ProgramInventory-Répertoiredesprogrammes_code_PROG` value. Exclude:

- Core-responsibility rows (the `...CoreResponsibility_code_PROG` level, codes
  ending in `00`) - these are groupings, not programs.
- Rows with a blank program-inventory code (entities that report no program
  inventory, e.g. some crown corporations).

Filtering to Program Inventory entries also means only departments that have
programs get resolved. Central accounting entities with no programs (Receiver
General, Regional Pay Office, Superannuation) drop out automatically.

## Authoritative data source

Open data, dataset **`3c371e57-d487-49fa-bb0d-352ae8dd6e4e`** ("Program codes
list as per the Government-wide Chart of Accounts", published by PSPC) on
open.canada.ca.

The data source is pinned to a specific fiscal year through a hardcoded URL
constant. Rolling to a new year's list is a manual, deliberate change to that
constant, so the update is intentional and can be announced. It does not roll
automatically when a new list appears, because program names can drift year over
year even though codes do not.

## Accepted risks

- **Name drift.** Since the identifier carries no year, the widget always shows
  the latest list's name for a code. A program renamed but not renumbered
  displays its newest label and silently loses its old name.
