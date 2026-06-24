# BDC Intelligence — Verification Log

**Started:** 2026-05-31  
**Purpose:** Flag values that appear wrong vs. source filing. DO NOT overwrite flagged values without explicit approval.
---
## Flag Format
```
### {TICKER} — {FIELD} — {QUARTER}
- **Current value:** {value}
- **Expected value:** {value}
- **Source filing:** {accession}
- **Evidence:** {description}
- **Screenshot:** {path}
- **Status:** PENDING REVIEW
## Flagged Values
### TBKCF / TBCI — net_assets_mn — Q1 2023 through Q4 2025
- **Issue:** `net_assets_mn` values are identical to 3 decimal places across both funds for all quarters Q1 2023–Q4 2025.
- **Status:** APPROVED AND FIXED — 2026-06-02
- **Finding:** TBCI values were correct throughout. TBKCF had TBCI's `net_assets_mn` and `total_debt_mn` copy-pasted across Q1 2023–Q4 2025 (confirmed by exact decimal matches to TBCI XBRL). `management_fee_mn` at Q4 2023 (2522.0) and Q4 2024 (11793.0) had the same ÷1000 unit error seen in CGBD. See TBKCF section below for full detail and fill_log entries dated 2026-06-02.
## ADS — Systemic Corruption in Core Financial Metrics (CRITICAL)
**Date discovered:** 2026-05-31  
**Source compared:** EDGAR XBRL companyfacts for CIK0001837532 vs existing timeseries  
**Status:** APPROVED AND FIXED — 2026-06-02
### Resolution Summary
Full timeseries rebuild completed from EDGAR CIK 1837532 (Apollo Debt Solutions BDC) consolidated filings.
**Changes applied (fill_log.md entries: ADS, 2026-06-02):**
- Q1 2020–Q3 2021 (7 quarters): all non-metadata financial fields nulled — data was from wrong fund CIK 1634452 (ABPCIC). ADS did not have operations in this period.
- Q4 2021: all non-metadata fields nulled except `net_assets_mn` = 0.05 ($50K seed capital per XBRL AssetsNet, accn 0000950170-22-005054). `total_assets_mn` previously 977.517 → null (wrong-CIK artifact).
- Q1 2022–Q3 2025 (14 quarters): BS fields (total_assets_mn, net_assets_mn, total_debt_mn, shares_outstanding) and IS fields (management_fee_mn, incentive_fee_mn, net_investment_income_mn, interest_expense_mn) corrected from XBRL consolidated facts.
- Q4 2022–Q4 2025 (4 Q4 quarters): IS fields derived as FY annual − YTD Q3 where XBRL quarterly entries were absent.
- interest_expense_mn 2022–2023: sourced from `us-gaap:InterestExpense`. 2024–2025: sourced from `us-gaap:InterestExpenseOperating` (ADS changed XBRL concept tag starting 2024).
- Q1 2026 row added with full BS + IS data from 10-Q filed 2026-05-11 (accn 0001193125-26-215667).
- Total field changes: ~220 (109 nulls + ~111 XBRL fills). See fill_log.md entries dated 2026-06-02 tagged "ADS".
### Summary
ADS (Apollo Debt Solutions BDC) timeseries has captured data from a **sub-entity or single share class** rather than the consolidated fund. Virtually every balance sheet and income statement metric is materially wrong across all quarters Q4 2022–Q4 2025.
### Key Discrepancies by Field
| Field | Example Period | DB Value | XBRL Value | Ratio | Implication |
|-------|---------------|----------|------------|-------|-------------|
| `total_assets_mn` | 2024-12-31 | 1,694 | 15,235 | 9.0x | DB captures ~1/9 of real assets |
| `shares_outstanding` | 2024-12-31 | 63,702,963 | 384,043,002 | 6.0x | Only ~1 share class captured |
| `net_assets_mn` | 2024-12-31 | 7,503 | 9,546 | 1.27x | Class I only vs. all classes |
| `management_fee_mn` | 2025-09-30 | 6.1 | 44.4 | 7.3x | Severely understated |
| `incentive_fee_mn` | 2025-09-30 | 3.6 | 40.4 | 11.1x | Severely understated |
| `total_debt_mn` | 2022-12-31 | 3,835 | 2,193 | 0.57x | Inconsistent direction |
| `unused_capacity_mn` | 2024-03-31 | 102 | 2,565 | 25.1x | Completely wrong |
### Root Cause Hypothesis
ADS is a multi-share-class nontraded BDC (Class S, I, D, F, G). The database appears to have captured:
- `shares_outstanding` from Class I only (largest class but not all classes)
- `total_assets_mn` possibly from a sub-entity (Cardinal Funding financing sub) or one filing column
- `net_assets_mn` from Class I only
- Fees computed against incorrect AUM base
Additionally, for Q4 2021 (inaugural period), DB shows `net_assets_mn` = 50.0M but XBRL = 0.05M ($50K) — the fund had barely launched.
### Q1–Q3 2022 Source URL Error
The existing timeseries entries for Q1–Q3 2021 have `source_url` values pointing to **CIK 1634452** (which is ABPCIC, a different fund). ADS's actual CIK is 1837532. These entries may be entirely from the wrong fund.
### Recommended Action
Full rebuild of ADS timeseries from EDGAR CIK 1837532 consolidated 10-K/10-Q filings. Proposed corrections (pending approval):
| Quarter | Field | Current DB | Correct Value | Source |
|---------|-------|-----------|---------------|--------|
| 2022-12-31 | total_assets_mn | 1191.734 | 4506.220 | XBRL 0000950170-23-008434 |
| 2022-12-31 | net_assets_mn | 1901.230 | 2154.933 | XBRL 0000950170-23-008434 |
| 2022-12-31 | shares_outstanding | 50228088 | 92877753 | XBRL 0000950170-23-008434 |
| 2022-12-31 | total_debt_mn | 3835.000 | 2193.128 | XBRL 0000950170-23-008434 |
| 2023-12-31 | total_assets_mn | 1394.764 | 7153.867 | XBRL 0000950170-24-031479 |
| 2023-12-31 | net_assets_mn | 3265.050 | 4123.696 | XBRL 0000950170-24-031479 |
| 2024-12-31 | total_assets_mn | 1693.995 | 15235.388 | XBRL 0000950170-25-038785 |
| 2024-12-31 | net_assets_mn | 7502.610 | 9546.496 | XBRL 0000950170-25-038785 |
| 2025-12-31 | total_assets_mn | 1980.943 | 25897.540 | XBRL 0001193125-26-102386 |
| 2025-12-31 | net_assets_mn | 11836.700 | 14770.208 | XBRL 0001193125-26-102386 |
*Full discrepancy table: 88 periods/fields flagged. Complete list in fill_log_ads_xbrl_comparison.json*
## CGBD — Fee and Interest Expense Unit Errors (CRITICAL)
**Date discovered:** 2026-06-01
**Source compared:** 10-K filings (accessions below) vs existing timeseries values
Multiple CGBD quarters have `management_fee_mn`, `incentive_fee_mn`, and `interest_expense_mn` stored as raw dollar-thousands (e.g. 28343.0) instead of dollar-millions (28.343). The annual 10-K filings report these as "$28,343 thousand"; somewhere in the original load the /1000 conversion was skipped.
### Affected Quarters and Fields
| Quarter | Field | Current (wrong) | Correct | Filing |
|---------|-------|-----------------|---------|--------|
| Q4 2021 | management_fee_mn | 28343.0 | 28.343 | 0001544206-22-000009 (10-K FY2021 IS) |
| Q4 2021 | incentive_fee_mn | 17680.0 | 17.680 | 0001544206-22-000009 |
| Q4 2021 | interest_expense_mn | 28829.0 | 28.829 | 0001544206-22-000009 |
| Q4 2021 | fee_as_pct_of_nii | 201811.006 | ~201.8 | derived from wrong fees |
| Q4 2021 | mgmt_fee_as_pct_of_assets | 5895.68 | ~0.59 | derived from wrong fees |
| Q4 2021 | interest_coverage_ratio | 0.001 | ~3.0 | derived from wrong interest_expense_mn |
| Q4 2022 | management_fee_mn | 28803.0 | ~28.803 | 0001544206-23-000009 (10-K FY2022, unverified) |
| Q4 2022 | incentive_fee_mn | 21414.0 | ~21.414 | same (unverified) |
157 field changes applied via `cgbd_comprehensive_fix.py` (2026-06-02). All 25 quarters corrected:
- Q4 2021 and Q4 2022 unit errors fixed (÷1000 applied).
- Q1 2020–Q3 2025 placeholder fee/interest values replaced with filing-sourced figures.
- interest_expense_mn uses combined "Interest expense and credit facility fees" line throughout for consistency with 2023+ IS presentation.
- Derived ratios (interest_coverage_ratio, fee_as_pct_of_nii, expense_ratio_pct, net_expense_ratio_pct) recomputed for all affected quarters.
- 67 fill_log.md entries appended, each with specific accession number and IS section reference.
### Root Cause
Annual 10-K IS reports amounts in thousands. For Q4 quarters (derived as FY − YTD Q3), the raw FY value was written without ÷1000 conversion. Quarters Q1 2020–Q3 2021 used hardcoded placeholder values (4.0, 0.004, 6.0, 7.0) instead of filing-sourced figures.
## CGBD — Q1 2020 Fee Values Appear Wrong
Scope expanded to cover all 25 quarters Q1 2020–Q1 2026. All corrected — see CGBD unit errors resolution above and fill_log.md entries dated 2026-06-02.
## TBKCF — Systemic Data Contamination (CRITICAL)
**Date discovered:** 2026-06-02  
**Source compared:** EDGAR XBRL CIK 0001901164 (TBKCF) vs CIK 0001913724 (TBCI) vs DB  
TBKCF (T. Rowe Price OHA Select Private Credit Fund) timeseries has been contaminated with TBCI (TPG Twin Brook Capital Income Fund) data across multiple fields from Q1 2023 onward. The contamination is confirmed by exact value matches to TBCI's XBRL-reported figures.
Q4 2022 is correct for TBKCF. From Q1 2023, `net_assets_mn` and `total_debt_mn` are TBCI's figures exactly (to 3 decimal places). `management_fee_mn` has unit errors (raw $thousands stored as $millions) at Q4 2023 and Q4 2024.
### Fields Affected
| Field | Quarters | Error Type | Correct Source |
|-------|----------|------------|----------------|
| `net_assets_mn` | Q1 2023 – Q4 2025 | TBCI values used | XBRL StockholdersEquity (CIK 0001901164) |
| `total_debt_mn` | Q1 2023 – Q4 2025 | TBCI values used | XBRL LongTermDebt (CIK 0001901164) |
| `management_fee_mn` | Q4 2023, Q4 2024 | ÷1000 unit error (2522.0→2.522, 11793.0→11.793) | XBRL ManagementFeeExpense derived |
| `net_investment_income_mn` | Q1 2023 – Q4 2025 | Likely TBCI or wrong-source values; XBRL has no quarterly tagging | 10-Q IS derivation needed |
| `interest_expense_mn` | Q1 2023 – Q4 2025 | Suspected wrong source; XBRL not tagged quarterly | 10-Q IS derivation needed |
### Proposed Corrections (XBRL-sourced)
| Quarter | Field | Current (wrong) | Correct | Source Accn |
|---------|-------|-----------------|---------|-------------|
| Q1 2023 | net_assets_mn | 545.52 | 50.802 | 0001628280-23-028587 |
| Q2 2023 | net_assets_mn | 596.87 | 301.491 | 0001628280-23-028587 |
| Q3 2023 | net_assets_mn | 705.92 | 494.211 | 0001628280-23-037892 |
| Q4 2023 | net_assets_mn | 798.85 | 704.431 | 0001901164-24-000006 |
| Q1 2024 | net_assets_mn | 1048.78 | 834.609 | 0001901164-24-000009 |
| Q2 2024 | net_assets_mn | 1281.17 | 1002.126 | 0001901164-24-000011 |
| Q3 2024 | net_assets_mn | 1418.66 | 1079.558 | 0001901164-24-000012 |
| Q4 2024 | net_assets_mn | 1541.23 | 1200.629 | 0001901164-25-000002 |
| Q1 2025 | net_assets_mn | 1728.52 | 1252.813 | 0001901164-25-000004 |
| Q2 2025 | net_assets_mn | 1914.65 | 1391.99 | 0001901164-25-000008 |
| Q3 2025 | net_assets_mn | 2129.74 | 1501.124 | 0001901164-25-000016 |
| Q4 2025 | net_assets_mn | 2384.89 | 1588.246 | 0001901164-26-000008 |
| Q4 2023 | management_fee_mn | 2522.0 | 2.522 | XBRL derived |
| Q4 2024 | management_fee_mn | 11793.0 | 11.793 | XBRL derived |
| CIK0001792509 | Q4 2025 | SOI parser error: >80% of debt holdings have lien_group/investment_type='Equity'. All lien %s nulled. Accession: 0001792509-26-000003. Cannot fix without modifying data/soi/. | OPEN | 2026-06-04 |
| CIK0001792509 | Q1 2026 | SOI parser error: >80% of debt holdings have lien_group/investment_type='Equity'. All lien %s nulled. Accession: 0001792509-26-000017. Cannot fix without modifying data/soi/. | OPEN | 2026-06-04 |
| NSI | Q4 2025 | SOI parser error: >80% of debt holdings have lien_group/investment_type='Equity'. All lien %s nulled. Accession: 0001766037-26-000004. Cannot fix without modifying data/soi/. | OPEN | 2026-06-04 |
| OCIC | Q4 2025 | SOI parser error: >80% of debt holdings have lien_group/investment_type='Equity'. All lien %s nulled. Accession: 0001812554-26-000011. Cannot fix without modifying data/soi/. | OPEN | 2026-06-04 |
| WTCAP | Q4 2025 | SOI parser error: >80% of debt holdings have lien_group/investment_type='Equity'. All lien %s nulled. Accession: 0001944831-26-000004. Cannot fix without modifying data/soi/. | OPEN | 2026-06-04 |
| SAR | ALL | net_investment_income_mn: stored values appear to be in USD thousands not millions (e.g. Q3 2022 stored=9877.437; XBRL shows 9.877M for that period). All 13 non-null NII values need dividing by 1000. Q4 gaps (2022-12-31, 2023-12-31, 2024-12-31) reflect SAR's March fiscal year — no Dec 31 filing period exists; these should remain null. Awaiting approval to apply /1000 correction. | OPEN | 2026-06-04 |
| PFLT | PRE-2022 | net_investment_income_mn: 7 pre-2022 quarters appear stored in $thousands (values 11119–12722; expected ~$10-15M quarterly). Awaiting approval to apply ÷1000. | FIXED | 2026-06-05 |
| PNNT | PRE-2022 | net_investment_income_mn: 7 pre-2022 quarters appear stored in $thousands (values 10185–12524; expected ~$10-15M quarterly). Awaiting approval to apply ÷1000. | FIXED | 2026-06-05 |
