# Archived timeseries

Files moved here on 2026-05-15 as part of the CIK resolution sweep
(commit `Sweep`). Each file is preserved verbatim so the data can be
recovered if a fund is reinstated.

| Archive path | Original ticker | Reason archived |
|---|---|---|
| `BCIC.json` | BCIC | Ghost row: the "BlackRock Capital Investment Corp" entity merged into BKCC in 2018. The SEC ticker `BCIC` now belongs to an unrelated entity (BCP Investment Corp, formerly Portman Ridge / KCAP / Kohlberg Capital). |
| `CCSI.json` | CCSI | Duplicate row. Same CIK (0001702510, "Carlyle Credit Solutions, Inc.") as `CCSO`, which is now the canonical row. |
| `CSRC.json` | CSRC | Not a BDC. SIC 6798 indicates this is "CNL Strategic Residential Credit, Inc." — a REIT, not a 1940-Act Business Development Company. |
| `GS_PCC.json` | GS_PCC | Duplicate row. Same CIK (0001920145, "Goldman Sachs Private Credit Corp.") as `GCRED`, which is now the canonical row. |
| `MSIF_pre_msc_income_fund.json` | MSIF (old) | The old `MSIF` row was wrongly labeled "Morgan Stanley Investment Inc Fund" and pointed at CIK 0001535778, which is actually "MSC Income Fund, Inc." (formerly HMS Income Fund, managed by Main Street Capital). The old row has been removed and a fresh `MSIF` row was added with the correct display name and metadata. This archived timeseries belongs to the now-correctly-identified MSC Income Fund entity but was collected under the wrong label — review before reusing. |
| `TROW_OHA.json` | TROW_OHA | Duplicate row. Same CIK (0001901164, "T. Rowe Price OHA Select Private Credit Fund") as `TBKCF`, which is now the canonical row. |
