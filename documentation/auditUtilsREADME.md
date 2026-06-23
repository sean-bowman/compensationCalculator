# Audit Utilities Reference

## Overview

`auditUtils.py` is the core data layer for the Compensation Structure Audit Tool. It provides all constants, salary band definitions, calculation functions, data loading, and theme configuration used across every page of the Streamlit application. Every view imports from this single module to ensure consistency.

**Location:** `tools/auditUtils.py`

---

## Table of Contents

- [Directory and File Resolution](#directory-and-file-resolution)
- [Constants and Reference Data](#constants-and-reference-data)
- [Theme and Colors](#theme-and-colors)
- [Data Loading Functions](#data-loading-functions)
- [Calculation Functions](#calculation-functions)
- [Survey Data Helpers](#survey-data-helpers)
- [Scraper Integration Helpers](#scraper-integration-helpers)
- [Consumers](#consumers)
- [Data Source Files](#data-source-files)

---

## Directory and File Resolution

The module resolves all file paths relative to its own location, making the app work regardless of the working directory:

```python
toolsDir = os.path.dirname(os.path.abspath(__file__))   # tools/
appDir = os.path.dirname(toolsDir)                       # compensationcalculator/
docDir = os.path.join(appDir, 'documentation')           # compensationcalculator/documentation/
```

Data files (Excel spreadsheets, markdown references) live in `documentation/`. Code utilities and the scraper cache live in `tools/`. The module is made importable by `GUI.py` inserting `tools/` into `sys.path` at startup.

---

## Constants and Reference Data

### Engineering Levels (`levelsData`)

A dictionary keyed by Roman numeral (`'I'` through `'V'`) containing the full engineering career ladder framework. Each level includes:

| Field | Type | Description |
|-------|------|-------------|
| `title` | str | Level title (e.g. 'Associate Engineer', 'Senior Engineer') |
| `subtitle` | str | Additional label (e.g. 'Entry-Level') |
| `minExperience` | int | Minimum years of experience for this level |
| `maxExperience` | int or None | Maximum years (None = uncapped) |
| `experienceLabel` | str | Human-readable experience range (e.g. '4+ years') |
| `supervision` | str | Level of supervision required: High, Moderate, Low, Minimal, None |
| `primaryFocus` | str | One-line description of primary responsibilities |
| `keyDuties` | list[str] | 4-5 specific duties |
| `learningGoals` | list[str] | 2-3 development goals |
| `leadershipRole` | str | Leadership archetype: Learner, Peer Support, Mentor, Coach, Technical Guru |
| `leadershipDescription` | str | Description of leadership expectations |
| `generalGoals` | list[str] | Career milestone goals |
| `managementEligibility` | dict | Maps management roles (RE, Lead, Director, Chief) to boolean eligibility |

**Level Summary:**

| Key | Title | Experience | Management Eligibility |
|-----|-------|-----------|----------------------|
| `'I'` | Associate Engineer | 0-2 years | None |
| `'II'` | Engineer | 2-4 years | RE |
| `'III'` | Senior Engineer | 4+ years | RE, Lead |
| `'IV'` | Staff Engineer | 7+ years | RE, Lead, Director |
| `'V'` | Principal Engineer | 12+ years | RE, Lead, Director, Chief |

**Source:** `documentation/engineeringLevels.md`

### Salary Bands (`salaryBands`)

Dictionary keyed by `'Level 1'` through `'Level 5'` with the synthetic salary ranges. All
figures are **fictional**, invented for this public demonstration build:

| Band | Min | Median | Max | Experience Range |
|------|-----|--------|-----|-----------------|
| Level 1 | $70,000 | $80,000 | $90,000 | 0-6 years |
| Level 2 | $90,000 | $100,000 | $110,000 | 2-12 years |
| Level 3 | $110,000 | $125,000 | $140,000 | 4+ years |
| Level 4 | $140,000 | $160,000 | $180,000 | 7+ years |
| Level 5 | $180,000 | $205,000 | $230,000 | 12+ years |

Each entry also includes a `levelKey` mapping back to the Roman numeral key in `levelsData`.

**Source:** `tools/syntheticData.py` (`SALARY_BANDS` constant)

### Extended Bands (`extendedBands`)

Extended salary ranges that account for experience modifiers pushing salaries above the standard band max. Includes manager track ranges for Levels 4-5. Figures are **fictional**:

| Band | Extended Max | Manager Min | Manager Max | Manager Extended |
|------|-------------|-------------|-------------|-----------------|
| Level 1 | $99,000 | -- | -- | -- |
| Level 2 | $121,000 | -- | -- | -- |
| Level 3 | $154,000 | -- | -- | -- |
| Level 4 | $198,000 | $175,000 | $205,000 | $225,000 |
| Level 5 | $253,000 | $215,000 | $250,000 | $275,000 |

**Source:** `tools/syntheticData.py` (`EXTENDED_BANDS` constant)

### Experience Modifiers (`experienceModifiers`)

Multipliers applied to base salary based on relevance and complexity of prior experience:

```python
{
    'relevance': {'Low': 1.0, 'Medium': 1.025, 'High': 1.05},
    'complexity': {'Low': 1.0, 'Medium': 1.025, 'High': 1.05},
}
```

Maximum combined modifier: 1.05 * 1.05 = 1.1025 (10.25% above base).

### Management Premiums (`managementPremiums`)

Flat annual additions for management roles. Figures are **fictional**:

| Role | Premium |
|------|---------|
| Engineer (IC) | $0 |
| RE (Responsible Engineer) | $5,000 |
| Lead | $15,000 |
| Director | $40,000 |

**Source:** `tools/syntheticData.py` (`MANAGEMENT_PREMIUMS` constant)

### Management Minimum Levels (`managementMinLevel`)

Maps each management role to its minimum required engineering level:

| Role | Minimum Level |
|------|--------------|
| Engineer | I |
| RE | II |
| Lead | III |
| Director | IV |
| Chief | V |

### Geographic Adjustments (`geographicAdjustments`)

Cost-of-living adjustments relative to a generic HQ baseline (0.0). All city names and factors
are **fictional**:

| Location | Adjustment |
|----------|-----------|
| Metro City | -17.5% |
| Coastal City | -16.5% |
| Harbor Town | -25.2% |
| Bay District | -15.0% |
| Highland Park | -12.7% |
| Mountain View | -10.4% |
| River Bend | -11.4% |
| HQ City | 0.0% |

Negative values indicate that the location pays more than HQ (i.e. a baseline salary would need to be adjusted upward to match).

**Source:** `tools/syntheticData.py` (`GEOGRAPHIC_ADJUSTMENTS` constant)

### Wage Benchmarks (`blsBenchmarks`)

Fictional national wage percentiles used as chart reference lines. The dict key
`regionalAverage` is the geographic baseline used for cost-of-living normalization;
the UI renders it as a generic regional average:

| Metric | Value |
|--------|-------|
| Median | $130,000 |
| 10th percentile | $78,000 |
| 25th percentile | $105,000 |
| 75th percentile | $165,000 |
| 90th percentile | $200,000 |
| Regional Average | $110,000 |

**Source:** `tools/syntheticData.py` (`WAGE_BENCHMARKS` constant). For a production deployment,
replace with current public data such as the [BLS OEWS](https://www.bls.gov/oes/).

### Survey Columns (`surveyColumns`)

The 20-column schema used by the market survey data:

```
Company, Listing, Level, Seniority, ExpReq, Estimated,
Location, TeamDepartment, Discipline, PositionType,
Min, Max, Vexp, Vlvl, Filter, Vmin, Vmax,
Link, FilterCol, State
```

**Source:** `documentation/marketSurveySynthetic.csv` (flat-header CSV)

### Level Ordering (`levelOrder`)

List for comparison operations: `['I', 'II', 'III', 'IV', 'V']`

---

## Theme and Colors

### Accent Color (`accentColor`)

Accent color: `#E0975A` (copper-amber), matching `.streamlit/config.toml` primaryColor.

### Color Palette (`colors`)

Complete dark theme palette used by all Streamlit views:

**Surface Colors:**

| Key | Hex | Usage |
|-----|-----|-------|
| `bg` | `#333333` | Page background |
| `surfacePrimary` | `#4d4d4d` | Card/container backgrounds |
| `surfaceSecondary` | `#5a5a5a` | Nested surfaces |
| `surfaceBorder` | `#666666` | Borders and grid lines |

**Text Colors:**

| Key | Hex | Usage |
|-----|-----|-------|
| `textPrimary` | `#ffffff` | Main text |
| `textSecondary` | `#cccccc` | Secondary text |
| `textMuted` | `#999999` | Muted/disabled text |

**Accent Variants:**

| Key | Hex | Usage |
|-----|-----|-------|
| `accent` | `#E0975A` | Primary highlights, salary displays |
| `accentDim` | `#C97E45` | Dimmed accent |
| `accentMuted` | `#5C4636` | Subtle accent backgrounds |

**Status Colors:**

| Key | Hex | Usage |
|-----|-----|-------|
| `success` | `#22c55e` | In-band, compliant |
| `warning` | `#f59e0b` | Extended range, needs review |
| `danger` | `#ef4444` | Above/below band, non-compliant |
| `info` | `#3b82f6` | Informational highlights |

**Company Colors** (`colors['companies']`): 9 unique colors mapped to survey companies (Astra, Astroforge, Blue Origin, Impulse Space, Relativity, Rocket Lab, SpaceX, Stoke, Ursa Major). Used in scatter plots, box plots, and histograms.

**Level Colors** (`colors['levels']`): 5 colors mapped to `'Level 1'` through `'Level 5'` (blue, green, amber, red, purple). Used in salary band visualizations.

### Plotly Dark Layout (`plotlyDarkLayout`)

Pre-configured Plotly layout dictionary applied to all charts via `fig.update_layout(**plotlyDarkLayout)`:

- Transparent paper and plot backgrounds
- White font color
- Grid/zeroline colors matching surface borders
- Transparent legend background

---

## Data Loading Functions

### `loadMarketSurveyData(filePath, schemaStyle) -> pd.DataFrame`

Loads and parses a compensation survey CSV or Excel file. Defaults to the synthetic survey
(`documentation/marketSurveySynthetic.csv`).

**Parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `filePath` | `_surveyFile` (synthetic CSV) | Path to a CSV or Excel file |
| `schemaStyle` | `'auto'` | `'reference'` (legacy Excel layout, rows 30-592, cols B-U), `'flat'` (headers in first row), or `'auto'` (detect automatically) |

Returns a cleaned DataFrame with:

- Numeric columns coerced (`Min`, `Max`, `Vmin`, `Vmax`, `ExpReq`, `Estimated`, `Vexp`, `Vlvl`, `Level`)
- String columns stripped of whitespace
- Null-company rows dropped
- Calculated columns added: `Midpoint` = (Min + Max) / 2, `LevelMidpoint` = (Vmin + Vmax) / 2

The synthetic survey is a small, fictional dataset (a few dozen rows) for demonstration.

```python
from auditUtils import loadMarketSurveyData

df = loadMarketSurveyData()
print(f'{len(df)} listings from {df["Company"].nunique()} companies')
```

### `loadReferenceMarkdown(filePath) -> str`

Loads `compensationReference.md` (consolidated reference document). Returns raw markdown string for rendering with `st.markdown()`. Defaults to the standard reference file in `documentation/`.

---

## Calculation Functions

### `calculateSalary(level, bandPosition, relevance, complexity, managementRole, startupMultiple) -> dict`

Core compensation formula:

```
Final Salary = (Base * Relevance * Complexity + Management Premium) * Startup Multiple
```

**Parameters:**

| Parameter | Type | Values |
|-----------|------|--------|
| `level` | str | `'Level 1'` through `'Level 5'` |
| `bandPosition` | str or float | `'Min'`, `'Median'`, `'Max'`, or 0.0-1.0 float |
| `relevance` | str or float | `'Low'`, `'Medium'`, `'High'`, or 1.0-1.05 float |
| `complexity` | str or float | `'Low'`, `'Medium'`, `'High'`, or 1.0-1.05 float |
| `managementRole` | str | `'Engineer'`, `'RE'`, `'Lead'`, `'Director'` |
| `startupMultiple` | float | Default 1.0 |

**Returns dict with:**

```python
{
    'baseSalary': 84000.0,          # Base from band position
    'bandPercent': 0.5,             # Position within band (0.0-1.0)
    'relevanceMultiplier': 1.025,   # Resolved relevance multiplier
    'complexityMultiplier': 1.025,  # Resolved complexity multiplier
    'adjustedBase': 88221.0,        # Base * relevance * complexity
    'managementPremium': 0,         # Flat premium for role
    'totalBeforeMultiple': 88221.0, # Adjusted base + premium
    'startupMultiple': 1.0,         # Applied multiple
    'finalSalary': 88221.0,         # Final calculated salary
    'bandMin': 78000,               # Band minimum
    'bandMax': 90000,               # Band maximum
    'bandMedian': 84000,            # Band median
}
```

**Example:**

```python
from auditUtils import calculateSalary

result = calculateSalary('Level 3', 'Median', 'High', 'Medium', 'Lead')
print(f'Final salary: ${result["finalSalary"]:,.0f}')
# Base ($110,500) * 1.05 * 1.025 + $12,000 = $130,896
```

### `auditEmployee(level, managementRole, yearsExperience, currentSalary, relevance, complexity) -> dict`

Audits an individual employee's compensation against the salary bands and returns compliance findings.

**Parameters:**

| Parameter | Type | Values |
|-----------|------|--------|
| `level` | str | `'I'` through `'V'` (Roman numeral keys) |
| `managementRole` | str | `'None'`, `'Engineer'`, `'RE'`, `'Lead'`, `'Director'`, `'Chief'` |
| `yearsExperience` | float | Years of relevant experience |
| `currentSalary` | float | Current annual salary |
| `relevance` | str | `'Low'`, `'Medium'`, `'High'` (default `'Medium'`) |
| `complexity` | str | `'Low'`, `'Medium'`, `'High'` (default `'Medium'`) |

**Compliance checks performed:**

1. **Salary vs. band** -- Below Band, In Band, Extended Range, or Above Band
2. **Management role eligibility** -- Is the role valid for this engineering level?
3. **Experience alignment** -- Does years of experience match the level's expected range?

**Returns dict with:**

| Key | Type | Description |
|-----|------|-------------|
| `bandName` | str | E.g. `'Level 3'` |
| `bandMin` | int | Band minimum salary |
| `bandMax` | int | Band maximum salary |
| `bandMedian` | int | Band median salary |
| `extendedMax` | int | Extended band maximum |
| `complianceStatus` | str | `'In Band'`, `'Below Band'`, `'Above Band'`, or `'Extended Range'` |
| `issues` | list[str] | List of flagged issues |
| `recommendations` | list[str] | List of recommended actions |
| `expectedMedian` | float | Calculated median salary for comparison |
| `salaryVsMedian` | float | Difference from expected median |
| `salaryPercentInBand` | float | Percentage position within band (0-100) |

**Example:**

```python
from auditUtils import auditEmployee

results = auditEmployee(
    level='III',
    managementRole='Lead',
    yearsExperience=6,
    currentSalary=125000,
)

print(f'Status: {results["complianceStatus"]}')
for issue in results['issues']:
    print(f'  Issue: {issue}')
for rec in results['recommendations']:
    print(f'  Rec: {rec}')
```

### `_calculateBandPercentile(salary, bandMin, bandMax) -> float`

Internal helper. Returns where a salary falls within a band as a percentage (0-100). Values below 0 or above 100 indicate out-of-band salaries.

---

## Survey Data Helpers

### `getMarketBenchmarks(surveyDf, experience, discipline, companies) -> pd.DataFrame`

Filters survey data for market comparison. Applies experience window (+/- 2 years), discipline substring match, and company list filter. All parameters are optional.

```python
from auditUtils import loadMarketSurveyData, getMarketBenchmarks

df = loadMarketSurveyData()
filtered = getMarketBenchmarks(df, experience=5, discipline='Propulsion')
print(f'{len(filtered)} matching listings')
```

### `getSurveyCompanies(surveyDf) -> list`

Returns sorted list of unique company names from the survey.

### `getSurveyDisciplines(surveyDf) -> list`

Returns sorted list of unique discipline names from the survey, with whitespace cleaned and `'nan'` values excluded.

### `getSurveyStates(surveyDf) -> list`

Returns sorted list of unique state abbreviations from the survey.

### `getLevelForExperience(yearsExperience) -> str`

Maps years of experience to a recommended level key:

| Experience | Recommended Level |
|-----------|------------------|
| 0-1 years | `'I'` |
| 2-3 years | `'II'` |
| 4-6 years | `'III'` |
| 7-11 years | `'IV'` |
| 12+ years | `'V'` |

---

## Scraper Integration Helpers

### `scraperCacheDir() -> str`

Returns the absolute path to the scraper cache directory (`tools/.scraperCache/`). Creates the directory if it does not exist. Used by `compensationScraper.py` for HTTP response caching.

### `mergeScrapedData(existingDf, scrapedDf, deduplicateBy) -> pd.DataFrame`

Merges scraped compensation data with the existing survey DataFrame. Tags each source with a `DataSource` column (`'Survey'` or `'Scraped'`), aligns columns to `surveyColumns`, concatenates, deduplicates (keeping existing data when duplicates are found), and recalculates `Midpoint`.

Default deduplication columns: `['Company', 'Listing', 'Location']`.

```python
from auditUtils import loadMarketSurveyData, mergeScrapedData

existing = loadMarketSurveyData()
merged = mergeScrapedData(existing, scrapedDf)
print(f'{len(merged)} total records')
```

---

## Consumers

Every Streamlit view and the scraper infrastructure imports from `auditUtils.py`:

| File | Imports Used |
|------|-------------|
| `views/levelsOverview.py` | `levelsData`, `salaryBands`, `extendedBands`, `blsBenchmarks`, `colors`, `plotlyDarkLayout` |
| `views/compensationCalculator.py` | `levelsData`, `salaryBands`, `extendedBands`, `experienceModifiers`, `managementPremiums`, `managementMinLevel`, `calculateSalary`, `colors`, `plotlyDarkLayout` |
| `views/marketComparison.py` | `salaryBands`, `blsBenchmarks`, `colors`, `plotlyDarkLayout`, `loadMarketSurveyData`, `getSurveyCompanies`, `getSurveyDisciplines`, `getMarketBenchmarks` |
| `views/marketDataExplorer.py` | `colors`, `plotlyDarkLayout`, `getSurveyCompanies`, `getSurveyDisciplines`, `getSurveyStates`, `loadMarketSurveyData` |
| `views/individualAudit.py` | `levelsData`, `salaryBands`, `extendedBands`, `managementMinLevel`, `managementPremiums`, `blsBenchmarks`, `auditEmployee`, `calculateSalary`, `getMarketBenchmarks`, `loadMarketSurveyData`, `getSurveyCompanies`, `getSurveyDisciplines`, `colors`, `plotlyDarkLayout`, `accentColor` |
| `views/references.py` | `blsBenchmarks`, `loadReferenceMarkdown` |
| `views/dataScraper.py` | `colors`, `plotlyDarkLayout`, `loadMarketSurveyData`, `mergeScrapedData`, `surveyColumns` |
| `tools/compensationScraper.py` | `surveyColumns`, `scraperCacheDir` |
| `cli.py` | `loadMarketSurveyData`, `mergeScrapedData` |

---

## Data Source Files

The salary framework is loaded from synthetic Python constants; the remaining inputs live in
`documentation/`:

| File | Description |
|------|-------------|
| `tools/syntheticData.py` | Synthetic, fictional salary framework: `salaryBands`, `experienceModifiers`, `managementPremiums`, `extendedBands`, `geographicAdjustments`, `blsBenchmarks`. Imported by `auditUtils.py`. |
| `documentation/marketSurveySynthetic.csv` | Synthetic, fictional market survey of job listings. Read by `loadMarketSurveyData()`. |
| `documentation/compensationReference.md` | Consolidated reference document. Read by `loadReferenceMarkdown()`. |
| `documentation/engineeringLevels.md` | Engineering levels document. Parsed into the `levelsData` constant by `referenceParser.py`. |

All compensation figures in these files are fictional and provided for demonstration only.

---

*Author: Sean Bowman — 02/27/2026*
