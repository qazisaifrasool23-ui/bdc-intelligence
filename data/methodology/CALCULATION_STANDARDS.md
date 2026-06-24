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

#### E3 `net_na_change_mn` *(derived)*
- Formula: `na_dollar_amount_mn[Q] − na_dollar_amount_mn[Q-1]`.
- Represents **net** change in non-accrual balance (at cost) during the
  quarter. Positive = deterioration (more dollars on non-accrual);
  negative = improvement (resolutions exceed additions); zero = no change.
- Cannot be decomposed into gross additions and gross resolutions —
  those components are not separately disclosed in public BDC filings
  for this universe (see `PHASE3_NONACCRUAL_NOTE.md` for the
  three-pass investigation).
- Null when either the current or prior quarter `na_dollar_amount_mn`
  is null.
- Source tag: `derived`.

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

---

## SOI-Derived Portfolio Analytics

**Added:** 2026-06-02  
**Approved methodology choices (user-confirmed):**
- Denominator for all lien/composition %s: **gross fair value of all investments** (not net of unfunded commitments)
- Structured Finance categorization: **tranche-dependent** — if tranche is identifiable as senior/junior map accordingly, otherwise → Subordinated
- Weighted average yield: **all-in rate on debt at fair value** (income yield basis)
- Source data: `data/soi/<TICKER>.json` holdings snapshots

---

### Lien Group Categorization

**Primary:** Use `lien_group` field on each holding directly when populated.

**Inference from `investment_type` (applied only when `lien_group` is None):**

| investment_type pattern (case-insensitive) | → Assigned group |
|--------------------------------------------|------------------|
| contains "first lien" | First Lien |
| contains "first-lien" | First Lien |
| "senior secured" without digit suffix | First Lien |
| "senior secured 1" / "senior secured loans 1" / "senior secure 1" | First Lien |
| "senior secured loans" (no suffix) | First Lien |
| "one stop" / "unitranche" | First Lien |
| "secured debt" | First Lien |
| "secured loan" | First Lien |
| "delayed draw term loan" / "revolver" / "revolving" | First Lien (senior revolvers are typically first-lien) |
| "senior secured 2" / "senior secured loans 2" / "senior secure 2" | Second Lien |
| "second lien" / "second-lien" | Second Lien |
| "junior secured" | Second Lien |
| contains "subordinat" | Subordinated |
| contains "mezzanine" | Subordinated |
| contains "unsecured" | Subordinated |
| contains "structured" / "structured finance" / "structured credit" | Subordinated (tranche unknown) |
| contains "equity" / "common stock" / "preferred stock" / "warrant" | Equity |
| contains "lp interest" / "limited partnership" | Equity |
| `is_equity = True` (regardless of investment_type) | Equity |
| `is_debt = True` with no classifiable investment_type | **Unclassified** — not assigned to any bucket |

**Numbers-only or sector-name investment_type values** (e.g. "One", "Two", "Healthcare") → Unclassified.

**Confidence threshold:** Lien %s are only written when classified FV ≥ 50% of total portfolio FV. Below 50%, all four lien fields are left null for that quarter.

---

### Metric Formulas (SOI-derived)

All computed per snapshot quarter from the holdings array in `data/soi/<TICKER>.json`.

#### `first_lien_pct`
```
numerator   = Σ fair_value_mn for holdings where effective_lien_group = "First Lien"
denominator = Σ fair_value_mn for ALL holdings (gross; unfunded commitments excluded)
result      = numerator / denominator × 100
units       = % (2 decimals)
```

#### `second_lien_pct`
```
numerator   = Σ fair_value_mn where effective_lien_group = "Second Lien"
denominator = Σ fair_value_mn ALL holdings
result      = numerator / denominator × 100
```

#### `subordinated_pct`
```
numerator   = Σ fair_value_mn where effective_lien_group in {"Subordinated", "Structured Finance"}
denominator = Σ fair_value_mn ALL holdings
result      = numerator / denominator × 100
```

#### `equity_pct`
```
numerator   = Σ fair_value_mn where effective_lien_group = "Equity" OR is_equity = True
denominator = Σ fair_value_mn ALL holdings
result      = numerator / denominator × 100
```

#### `weighted_avg_yield`
```
debt positions = holdings where is_debt = True AND all_in_rate_pct IS NOT NULL AND all_in_rate_pct > 0
numerator      = Σ (fair_value_mn × all_in_rate_pct) across debt positions
denominator    = Σ fair_value_mn across debt positions (same set)
result         = numerator / denominator
units          = % (2 decimals)
notes          = Excludes non-accrual positions (is_non_accrual = True)
              = Null if fewer than 5 debt positions have both FV and rate data
```

#### `pik_pct`
```
debt positions = holdings where is_debt = True AND fair_value_mn IS NOT NULL
numerator      = Σ fair_value_mn where is_pik = True (across debt positions)
denominator    = Σ fair_value_mn across all debt positions
result         = numerator / denominator × 100
units          = % (2 decimals)
notes          = Measures % of debt portfolio FV that has PIK component
```

#### `floating_rate_pct`
```
debt positions = holdings where is_debt = True AND fair_value_mn IS NOT NULL
floating       = positions where reference_rate IS NOT NULL
                 AND reference_rate NOT IN {"Fixed", "fixed", "FIXED", "None"}
                 AND reference_rate not blank
numerator      = Σ fair_value_mn of floating positions
denominator    = Σ fair_value_mn of ALL debt positions
result         = numerator / denominator × 100
units          = % (2 decimals)
```

#### `fixed_rate_pct`
```
= 100.0 - floating_rate_pct
(only computed when floating_rate_pct is not null)
```

#### `num_portfolio_companies`
```
= count of distinct company_name values across all holdings in the snapshot
  where company_name IS NOT NULL AND is_debt OR is_equity (exclude fund-level entries)
units = integer
```

#### `nav_per_share` (derived — not SOI-sourced)
```
When nav_per_share is null but net_assets_mn and shares_outstanding are both populated:
  nav_per_share = (net_assets_mn × 1,000,000) / shares_outstanding
  units = $ per share (4 decimals)
  source_tag = "derived"
```

---

### Override Rules

1. If a field is already populated in the timeseries from a filing-sourced value, **do not overwrite** with SOI-derived value unless the filing-sourced value is confirmed wrong.
2. SOI-derived values are tagged `source = "SOI holdings computation"` in fill_log.md.
3. Snapshots that have `total_fair_value_mn = null` or zero holdings are skipped.

