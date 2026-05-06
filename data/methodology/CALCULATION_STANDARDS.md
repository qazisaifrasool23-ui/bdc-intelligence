# BDC Calculation Standards

This document captures the formulas, units conventions, and source-priority
rules used to populate `data/timeseries/<TICKER>.json` for the 47-fund traded
BDC universe. Every field below is computed identically across all funds and
all quarters.

---

## Source priority (used for every extracted field)

1. **XBRL structured data** — `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json`
2. **Filing document text** — primary 10-Q or 10-K HTML pulled from EDGAR
3. **8-K earnings press releases (EX-99.1)** filed within 45 days of period end
4. **Mathematical derivation** — only when Layers 1–3 fail
5. **Null** — never fabricate, never estimate, never interpolate

---

## Rounding conventions

| Type | Decimals | Example |
|---|---|---|
| Dollar amounts ($millions) | 3 | `12.345` |
| Per-share amounts | 4 | `0.4823` |
| Percentages | 2 | `8.45` |
| Ratios | 4 | `1.1234` |
| Counts (shares, companies, etc.) | 0 (integer) | `425000000` |

## Units

All monetary values stored in **$millions** unless explicitly per-share.

- Filing reports in thousands → divide by 1,000
- Filing reports in full dollars → divide by 1,000,000

## Quarter assignment

- Match to filing's `period_end` (not `filingDate`).
- Calendar mapping: Q1=Jan–Mar, Q2=Apr–Jun, Q3=Jul–Sep, Q4=Oct–Dec.
- For non-calendar fiscal years (e.g. SAR fiscal-Feb), the period covered
  is the source of truth; the calendar quarter label is approximate.

## Amendments

If both `10-Q` and `10-Q/A` (or `10-K` / `10-K/A`) exist for the same
period, the amendment is authoritative.

## Sign conventions

| Field | Positive means |
|---|---|
| `net_unrealized_gains_mn` | gain |
| `realized_gain_loss_3mo_mn` | gain |
| `na_new_additions_mn` | always positive |
| `na_resolutions_mn` | always positive |
| `nav_per_share_yoy_pct` | NAV grew YoY |

---

## Field definitions and formulas

### Group A — Balance sheet

#### A1 `shares_outstanding`
- XBRL: `CommonStockSharesOutstanding`, `EntityCommonStockSharesOutstanding`
- Fallback: `shares_outstanding = net_assets_mn × 1_000_000 / nav_per_share`
- Stored as integer.

#### A2 `debt_to_equity_ratio`
- Equals `leverage` (an alias for the same metric per BDC convention).
- Copy directly; do not recompute.

#### A3 `equity_ratio`
- `equity_ratio = net_assets_mn / total_assets_mn`
- Decimal (not %). Per GAAP ASC 946 (Investment Companies) balance-sheet
  presentation.

#### A4 `nav_per_share_yoy_pct`
- `((nav_per_share[Q] − nav_per_share[Q-4]) / nav_per_share[Q-4]) × 100`
- Q-4 is the same quarter one year prior; null for the first 4 quarters.
- Standard BDC performance metric per Dechow et al. (2010) earnings-quality
  framework adapted for investment companies.

### Group B — Income statement

#### B1 `admin_fee_mn`
- XBRL: `AdministrationFeeExpense`, `AdministrativeServicesExpense`,
  `GeneralAndAdministrativeExpense`.
- Filing text: line items "administration fee", "administrative services
  fee", "administrative expenses".
- Many BDCs do not separately disclose admin fees (bundled into management
  or other expenses) — null when not separately disclosed.

### Group C — Earnings quality

#### C1 `pik_income_mn`
- XBRL: `PaymentInKindInterestIncome`, `PIKInterestIncome`,
  `AccretionOfDiscountAndPaymentInKindInterest`.
- Filing-text fallback: "payment-in-kind", "PIK interest", "paid-in-kind".
- Final fallback (only when both above null and `pik_pct` is non-null):
  `pik_income_mn = total_investment_income_mn × pik_pct / 100`.

#### C2 `mgmt_fee_as_pct_of_assets`
- `(management_fee_mn × 4) / total_investments_fv_mn × 100`
- Annualised quarterly fee divided by **portfolio fair value** (matches
  SEC Form N-2 fee-table denominator per AICPA Investment Companies
  guide §7.3).

### Group D — Dividends and tax

#### D1 `spillover_per_share`
- Primary source: 10-K (annual). Sometimes disclosed quarterly in 10-Q.
- XBRL: `UndistributedOrdinaryIncomeLoss`, `UndistributedTaxableIncome`,
  `InvestmentCompanyUndistributedOrdinaryIncome`.
- Filing text: "spillover", "undistributed taxable income", "undistributed
  ordinary income", "estimated spillover".
- If only total disclosed: `spillover_per_share = total_spillover_mn × 1_000_000 / shares_outstanding`.
- For quarters between disclosures: **carry forward** the prior 10-K value;
  do not interpolate.

#### D2 `spillover_months_coverage`
- `spillover_per_share / (dividend_per_share / 3)`
- Standard practitioner metric: months of monthly-equivalent distribution
  covered by the spillover balance.

#### D3 `roc_pct`
- Source: 10-K tax-character section, Form 8937, or 19a notices (8-K).
- Phrases: "return of capital", "tax characterization of distributions",
  "character of distributions".
- 100%-ordinary-income quarters → record `0.0`, not null.

### Group E — Credit quality

#### E1 `na_new_additions_mn`
- Source: non-accrual rollforward in 10-Q credit-quality section.
- Phrases: "placed on non-accrual", "additions to non-accrual",
  "new non-accrual investments".
- Recorded **at cost basis**.

#### E2 `na_resolutions_mn`
- Same rollforward; "removed from non-accrual", "resolved", "repaid",
  "restructured and removed".
- Recorded at cost basis.

### Group F — Portfolio composition

#### F1 `top_10_concentration_pct`
- Direct disclosure in MD&A or supplemental schedule preferred.
- Otherwise: sum top 10 positions by FV from Schedule of Investments,
  divide by `total_investments_fv_mn`, ×100.
- Standard portfolio-concentration metric per S&P Global BDC framework.

#### F2 `sponsor_pct`
- MD&A: "sponsor-backed", "sponsored transactions", "sponsor finance".
- Null if not disclosed; do not infer.

#### F3 `geographic_us_pct`
- MD&A geographic-diversification table.
- 100%-US-focused funds with explicit statement → `100.0`.

#### F4 `avg_ebitda_mn`
- MD&A portfolio-quality section: "median EBITDA", "weighted-average EBITDA".
- **Median preferred** when both median and mean disclosed.

#### F5 `avg_leverage_borrower`
- MD&A: "median net leverage", "median net debt/EBITDA" of portfolio
  companies (NOT of the BDC itself).
- Median preferred (per KBRA BDC Compendium Q3 2025 — median is the
  standard cross-BDC comparable statistic).

#### F6 `avg_interest_coverage_borrower`
- MD&A: "median interest coverage", "average interest coverage ratio"
  of portfolio companies.
- Median preferred.

### Group G — Origination intelligence

#### G1 `yield_on_new_investments_pct`
- MD&A origination section or supplemental tables.
- Phrases: "yield on new investments", "weighted average yield on new
  commitments", "new investment yield".

#### G2 `new_investment_count`
- MD&A or 8-K earnings press release.
- Integer count of **new portfolio-company relationships** added in quarter.
- Dollar amount alone (without count) → null.

#### G3 `exit_count`
- MD&A or 8-K press release. Phrases: "X portfolio companies exited",
  "fully realized", "repaid in full".
- Partial repayments do **not** count.

### Group H — Capital structure

#### H1 `debt_fixed_pct`
- Borrowings table in 10-Q notes.
- Fallback: `debt_unsecured_notes_mn / total_debt_mn × 100`
  (unsecured notes are typically fixed rate for BDCs).

#### H2 `debt_floating_pct`
- `100 − debt_fixed_pct`. Null when `debt_fixed_pct` is null.

---

## Pre-existing fields used as inputs

The following fields are assumed to already be populated in each
timeseries entry by upstream pipelines and are used as inputs to the
formulas above. Their definitions are taken from the original BDC
extraction pipeline:

`nav_per_share`, `nav_per_share_qoq_change`, `net_assets_mn`,
`total_investments_fv_mn`, `total_debt_mn`, `total_assets_mn`,
`leverage`, `nii_per_share`, `dividend_per_share`, `nii_coverage`,
`total_investment_income_mn`, `net_investment_income_mn`,
`total_expenses_mn`, `pik_pct`, `weighted_avg_yield`, `cost_of_debt_pct`,
`na_pct_cost`, `na_pct_fv`, `first_lien_pct`, `second_lien_pct`,
`subordinated_pct`, `equity_pct`, `floating_rate_pct`,
`num_portfolio_companies`, `originations_mn`, `repayments_mn`,
`net_unrealized_gains_mn`, `credit_facility_drawn_mn`,
`unused_capacity_mn`, `management_fee_mn`, `incentive_fee_mn`,
`interest_expense_mn`, `weighted_avg_interest_rate`,
`debt_revolver_mn`, `debt_unsecured_notes_mn`.

---

## Methodology references

- **`mgmt_fee_as_pct_of_assets`** — Annualised basis consistent with SEC
  Form N-2 fee-table disclosure. Denominator is portfolio fair value per
  AICPA Investment Companies guide §7.3.
- **`nii_coverage`** — Standard BDC dividend-sustainability metric per
  KBRA BDC Rating Methodology (2021) and the Wells Fargo BDC research
  framework.
- **`spillover_months_coverage`** — Standard practitioner metric.
- **`equity_ratio`** — GAAP ASC 946 (Investment Companies).
- **`nav_per_share_yoy_pct`** — Standard BDC performance metric per
  Dechow et al. (2010) earnings-quality framework adapted for investment
  companies.
- **`avg_leverage_borrower` / `avg_interest_coverage_borrower`** — Use
  median when both disclosed, per KBRA BDC Compendium Q3 2025.
- **`top_10_concentration_pct`** — S&P Global BDC credit-analysis
  framework.
