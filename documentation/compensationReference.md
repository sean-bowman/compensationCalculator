# Compensation Analysis - Reference Documentation

This document consolidates the data sources, data file descriptions, and market context used by the Technical Levels and Compensation framework.

> **Note on data:** This is a public, personal demonstration build of the tool. All salary
> figures, company names in the synthetic dataset, and compensation bands are **fictional** and
> invented for demonstration. The numbered company entries under *Salary Aggregator Data* and the
> *Company Career Pages* table list real public career pages — they exist only to configure the
> optional live web scraper, and contain no proprietary compensation data.

---

## Table of Contents

- [Source Data Files](#source-data-files)
 - [Synthetic Salary Framework](#synthetic-salary-framework)
 - [Synthetic Market Survey](#synthetic-market-survey)
 - [Engineering Levels Document](#engineering-levels-document)
 - [Industry Compensation Scraper](#industry-compensation-scraper)
- [Market Benchmarks](#market-benchmarks)
- [Salary Aggregator Data](#salary-aggregator-data)
- [Government and BLS Data](#government-and-bls-data)
- [Additional Market Context](#additional-market-context)
- [Company Career Pages](#company-career-pages)
- [Additional Resources](#additional-resources)

---

## Source Data Files

### Synthetic Salary Framework

#### Overview

The salary framework is the primary input for the salary calculator app. In this public
demonstration build it is defined as readable Python constants in `tools/syntheticData.py` —
there is no binary-spreadsheet dependency. All dollar figures are **fictional**. The framework
has three parts:

1. **Salary Band Table**: Five technical IC (individual contributor) levels with min/median/max
 base salary, minimum years of experience required, and maximum years before promotion review.
 Each level maps to a roman numeral (I-V) used throughout the application:

 | Level | Min | Median | Max | Min Years | Max Years |
 |-------|-----|--------|-----|---------|---------|
 | Level 1: Associate Engineer (I) | \$70,000 | \$80,000 | \$90,000 | 0 | 6 |
 | Level 2: Engineer (II) | \$90,000 | \$100,000 | \$110,000 | 2 | 12 |
 | Level 3: Senior Engineer (III) | \$110,000 | \$125,000 | \$140,000 | 4 | - |
 | Level 4: Staff Engineer (IV) | \$140,000 | \$160,000 | \$180,000 | 7 | - |
 | Level 5: Principal Engineer (V) | \$180,000 | \$205,000 | \$230,000 | 12 | - |

2. **Experience Modifiers**: Two modifier categories (Relevance and Complexity), each with
 Low (1.0), Medium (1.025), and High (1.05) multipliers. Applied multiplicatively to the base
 salary before management premiums.

3. **Management Premiums**: Flat dollar amounts added after base salary modification. Engineer
 (\$0), Responsible Engineer (\$5,000), Lead (\$15,000), Director (\$40,000).

#### Implementation

Imported by `auditUtils.py` from `tools/syntheticData.py` at import time, producing the
`salaryBands`, `experienceModifiers`, and `managementPremiums` constants. The salary formula is:

$$
S_{final} = (S_{base}\cdot\epsilon_{relevance}\cdot\epsilon_{complexity} + S_{mgmt}) * \sigma_{startup}
$$

```txt
finalSalary = (baseSalary * relevanceMultiplier * complexityMultiplier + managementPremium) * startupMultiple
```

Where `baseSalary` is interpolated within the level's min-max range based on band position. The
modifiers are intentionally modest (max +5% each) so that band position does the heavy lifting.
Management premiums are additive rather than multiplicative to prevent compounding.

Used by: `calculateSalary()`, `auditEmployee()`, salary band overlays in `marketComparison.py`,
`individualAudit.py`, `levelsOverview.py`, `compensationCalculator.py`.

#### Design Notes

The 5-level framework is a generic structure; the dollar figures are invented round numbers.
Design conventions retained from the original framework:

- Experience modifiers are capped at 5% to keep the system simple and predictable
- Management premiums are flat dollar amounts (not percentages) to prevent disproportionate
 scaling at higher levels
- Extended-band maxima provide headroom above the standard max so experience modifiers can push
 a salary above the band without an automatic out-of-band flag

---

### Synthetic Market Survey

#### Overview

The market survey is a synthetic dataset of **fictional** job listings used for the market
comparison and classifier features. In this demonstration build it is a flat-header CSV,
`documentation/marketSurveySynthetic.csv`. Each row is a job listing with the following columns:

 | Column | Description |
 |--------|-------------|
 | Company | Fictional employer name |
 | Listing | Job title |
 | Level / Seniority | Company-assigned level and seniority tier |
 | ExpReq / Estimated | Required and estimated years of experience |
 | Location / State | Job location |
 | Discipline | Engineering discipline (Propulsion, Avionics, etc.) |
 | PositionType | Full-time, contract, etc. |
 | Min / Max | Salary range from listing |
 | Vexp / Vlvl | Normalized experience and level (Vlvl = classifier label) |
 | Vmin / Vmax | Normalized salary range |
 | Link | Placeholder URL |

The extended bands and geographic adjustment factors used by the audit logic are also
**fictional** and defined as constants in `tools/syntheticData.py`:

 | Level | Base Min | Base Max | Extended Max | Mgr Min | Mgr Max | Mgr Extended |
 |--------|----------|----------|--------------|---------|---------|--------------|
 | 1 | \$70,000 | \$90,000 | \$99,000 | - | - | - |
 | 2 | \$90,000 | \$110,000 | \$121,000 | - | - | - |
 | 3 | \$110,000 | \$140,000 | \$154,000 | - | - | - |
 | 4 | \$140,000 | \$180,000 | \$198,000 | \$175,000 | \$205,000 | \$225,000 |
 | 5 | \$180,000 | \$230,000 | \$253,000 | \$215,000 | \$250,000 | \$275,000 |

Geographic adjustment factors are expressed relative to a generic HQ baseline (0.0%). Negative
values mean the source location is more expensive — an employee relocating from that city to HQ
would accept a lower base salary. All city names and factors are fictional:

 | City | Adjustment |
 |------|------------|
 | HQ City | 0.0% (baseline) |
 | Metro City | -17.5% |
 | Coastal City | -16.5% |
 | Bay District | -15.0% |
 | Harbor Town | -25.2% |
 | Mountain View | -10.4% |
 | Highland Park | -12.7% |
 | River Bend | -11.4% |

#### Implementation

- `loadMarketSurveyData()` reads `marketSurveySynthetic.csv` (flat header) into a pandas
 DataFrame with standardized column names. Calculates midpoint salary and normalized midpoint.
- Extended bands and geographic adjustments are imported directly from `tools/syntheticData.py`
 at import time.

Used by: All visualization pages, `auditEmployee()`, `mergeScrapedData()`, geographic adjustment
logic in `individualAudit.py`.

#### Design Notes

The synthetic survey is small (a few dozen rows) and exists only to exercise the visualization,
filtering, and classifier code paths. It is not a real market study. The optional live web
scraper can append genuine market data alongside it.

---

### Engineering Levels Document

#### Overview

The engineering levels definition document (`engineeringLevels.md`) defines five progressive IC levels. Each level specifies:

- Title, experience range, and supervision level
- Primary focus and key duties
- Learning and growth expectations
- Leadership role and description
- General goals for the level
- Management eligibility matrix (RE, Lead, Director, Chief)

The document explicitly excludes management role descriptions, emphasizing a distinction between technical skill progression and management roles as separate axes.

#### Implementation

Parsed by `parseLevelsData()` in `referenceParser.py` at import time. The parser splits the markdown on `## Level X` headers, then extracts metadata bullets and subsections using regex. Helper functions `deriveLevelOrder()` and `deriveManagementMinLevel()` compute the level ordering and management role minimums from the parsed eligibility matrices.

Used by: `auditEmployee()` for level validation, `levelsOverview.py` for level display, `individualAudit.py` for management role checks, `compensationCalculator.py` for level descriptions.

---

### Industry Compensation Scraper

#### Overview

The compensation scraper (`compensationScraper.py`) is a modular web scraping tool that collects real-time aerospace compensation data from ten public sources. While the synthetic salary framework and survey serve as the initial baseline for the compensation framework, the scraper provides a mechanism to append genuine market data alongside the synthetic survey or to supplement it entirely with up-to-date industry figures. As market conditions evolve, the scraper ensures that compensation decisions are informed by current data rather than a static snapshot.

The ten data sources, organized into priority tiers, are:

| Tier | Source | Description | API Key Required |
|------|--------|-------------|:----------------:|
| 1 | **Data USA** | Census/ACS occupation aggregates by metro area and SOC code | No |
| 1 | **BLS OEWS** | Bureau of Labor Statistics occupational employment and wage percentiles | Optional (v1 works without) |
| 2 | **FRED** | Federal Reserve Economic Data -- earnings time series and economic indicators | Yes |
| 2 | **H1B Salary Data** | Public H-1B visa salary disclosures from the DOL | No |
| 2 | **Glassdoor** | Salary estimates and company-specific compensation data from employee reports | No |
| 2 | **PayScale** | Industry salary surveys and compensation benchmarks by role and experience | No |
| 3 | **Levels.fyi** | Company-specific salary and level data scraped from public profiles | No |
| 3 | **ZipRecruiter** | Job posting salary ranges and aggregated compensation data | No |
| 3 | **Comparably** | Compensation benchmarks with company culture and demographic context | No |
| 3 | **Indeed** | Aggregated salary data from job postings and employee submissions | No |

Sources that fail (network errors, missing API keys, rate limits) do not block other sources from completing -- each source operates independently and returns whatever data it can collect.

#### Data Storage and Caching

Scraped data is stored in two layers:

1. **HTTP cache** (`.scraperCache/` in the tools directory): Individual API responses are cached as JSON files keyed by MD5 hash of the request URL. The cache TTL defaults to 168 hours (1 week) and can be set to 0 to force a fresh scrape. This prevents redundant HTTP requests during iterative analysis sessions.

2. **Session state** (in-memory, Streamlit `st.session_state`): After a scrape completes, the merged DataFrame is stored in `st.session_state.scrapedDataset` so that all visualization pages (Market Comparison, Job Listings Explorer, Employee Audit) can access the scraped data without re-running the scrape. A merged dataset (survey + scraped) is similarly stored as `st.session_state.mergedDataset`.

All scraped data is normalized into the same 20-column schema defined by `surveyColumns` in `auditUtils.py`, which matches the column layout of the synthetic survey CSV. This schema normalization means that scraped data and the synthetic survey data can be concatenated into a single DataFrame without column mismatches.

#### Backend Integration

The scraper integrates with the existing backend through several entry points:

- **`CompensationScraper` class** (`compensationScraper.py`): Core scraper with a `ScraperConfig` dataclass for API keys, cache TTL, target companies, and request delay. Each data source is an independent method that returns a normalized DataFrame. The `scrapeAll()` method runs all (or selected) sources and returns a dict keyed by source name; `mergeResults()` combines them into a single DataFrame.

- **`mergeScrapedData()`** (`auditUtils.py`): Combines scraped data with the synthetic survey DataFrame. Tags each row with a `DataSource` column ('Survey' or 'Scraped'), deduplicates on (Company, Listing, Location), and preserves synthetic survey entries over scraped duplicates.

- **`renderDatasetSelector()`** (`auditUtils.py`): A shared Streamlit widget used across visualization pages that lets the user choose which dataset to visualize. Options include the default synthetic survey, last scraped data, merged (survey + scraped), or an imported CSV/Excel file. The selected DataFrame is returned directly to the calling page.

- **`scraperInterface.py`**: A lightweight 4-line script demonstrating the scraper API. Instantiates `CompensationScraper`, runs a full scrape, and exports to Excel.

- **`cli.py`**: A command-line interface for running scrapes outside of the Streamlit UI. Provides `--sources`, `--merge`, and `--output` arguments for scripted or batch usage.

#### User Options

Users can control the scraper's behavior through the following options:

- **Source selection**: Choose which data sources to run (any combination of the ten available sources). In the Streamlit UI, sources are presented as a multiselect widget with tier labels. In the CLI, pass `--sources dataUsa bls fred h1b levelsFyi glassdoor payscale ziprecruiter comparably indeed`.

- **Target companies**: Override the default company list (parsed from the Salary Aggregator Data section of this document via `referenceParser.py`). The default list includes all companies with entries in the aggregator section. Custom companies can be specified in the UI multiselect or CLI `--companies` flag.

- **Cache policy**: Choose between using the 1-week cache (default) or forcing a fresh scrape. In the CLI, use `--no-cache`.

- **API keys**: BLS and FRED API keys can be entered in the UI's API Key Configuration expander or passed via CLI flags. Keys are stored in session state only and are not persisted to disk.

- **Dataset switching**: After a scrape, all visualization pages automatically gain access to the scraped and merged datasets through the dataset selector widget. Users can freely switch between viewing the synthetic survey baseline, the latest scraped data, or the merged combination.

- **Export**: Scraped or merged data can be downloaded as CSV or Excel from the Data Scraper page's Merge & Export tab, or exported programmatically via `scraper.exportToExcel(df, 'output.xlsx')`.

---

## Market Benchmarks

The chart reference lines in this demonstration build use a set of **fictional** national wage
percentiles, defined as the `WAGE_BENCHMARKS` constant in `tools/syntheticData.py`. They are
illustrative placeholders, not real survey data:

- **Median Annual Wage:** \$130,000
- **10th Percentile:** \$78,000
- **25th Percentile:** \$105,000
- **75th Percentile:** \$165,000
- **90th Percentile:** \$200,000
- **Regional Average:** \$110,000

For a production deployment, replace these with current figures from a public source such as the
[BLS Occupational Employment and Wage Statistics (OEWS)](https://www.bls.gov/oes/) for the
relevant SOC code.

---

## Salary Aggregator Data

### 1. Levels.fyi: SpaceX Engineering Levels and Compensation

- **URL:** https://www.levels.fyi/companies/spacex/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Primary benchmark for new-space company compensation at all levels, including director-equivalent positioning.

### 2. Levels.fyi: Blue Origin Engineering Levels and Compensation

- **URL:** https://www.levels.fyi/companies/blue-origin/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Second major new-space company benchmark; useful for level-system comparison with SpaceX's flatter hierarchy.

### 3. Levels.fyi: Northrop Grumman Engineering Levels and Compensation

- **URL:** https://www.levels.fyi/companies/northrop-grumman/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Traditional defense contractor benchmark showing the compensation gap between defense primes and new-space companies.

### 4. Levels.fyi: Lockheed Martin Engineering Levels and Compensation

- **URL:** https://www.levels.fyi/companies/lockheed-martin/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Largest defense contractor by revenue; useful for understanding traditional aerospace compensation floor.

### 5. Levels.fyi: Rocket Lab Engineering Compensation

- **URL:** https://www.levels.fyi/companies/rocket-lab/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Mid-size launch company benchmark; demonstrates that small-vehicle launch companies can offer competitive compensation.

### 6. Levels.fyi: Aerojet Rocketdyne (now L3Harris) Engineering Compensation

- **URL:** https://www.levels.fyi/companies/aerojet-rocketdyne/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Direct propulsion-industry comparator; Aerojet Rocketdyne is the most analogous traditional company to a propulsion-focused organization.

### 7. Levels.fyi: NASA Engineering Compensation

- **URL:** https://www.levels.fyi/companies/nasa/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Federal government benchmark; establishes the floor for aerospace engineering compensation and context for GS-14/15 director-equivalent roles.

### 8. Levels.fyi: Boeing Engineering Compensation

- **URL:** https://www.levels.fyi/companies/boeing/salaries
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Largest aerospace manufacturer by headcount; represents the traditional OEM compensation baseline.

### 9. Glassdoor: Raytheon (RTX) Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/Raytheon-Technologies-Salaries-E4968.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Major defense prime with significant missile and space systems work; propulsion-adjacent compensation benchmark.

### 10. Glassdoor: GE Aerospace Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/GE-Aerospace-Salaries-E277297.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Propulsion-focused aerospace company (jet engines, turbomachinery); directly comparable engineering disciplines.

### 11. Glassdoor: The Aerospace Corporation Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/Aerospace-Corporation-Salaries-E375.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** FFRDC focused exclusively on space systems; compensation reflects mission-focused non-profit structure.

### 12. Glassdoor: Relativity Space Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/Relativity-Space-Salaries-E2171417.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Direct new-space launch competitor with similar stage and scale.

### 13. Glassdoor: Impulse Space Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/Impulse-Space-Salaries-E7600891.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Early-stage propulsion-focused startup; closely comparable in size, stage, and mission.

### 14. Glassdoor: Stoke Space Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/Stoke-Space-Salaries-E7267027.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Early-stage propulsion-focused launch startup competing for the same talent pool.

### 15. Glassdoor: Ursa Major Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/Ursa-Major-Technologies-Salaries-E3226498.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Propulsion-focused company building rocket engines; direct competitor for propulsion engineering talent.

### 16. Glassdoor: Astra Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/Astra-Space-Salaries-E3204658.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Small launch vehicle company; illustrates compensation challenges at pre-revenue aerospace startups.

### 17. Glassdoor: Astroforge Engineering Compensation

- **URL:** https://www.glassdoor.com/Salary/AstroForge-Salaries-E8534117.htm
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Early-stage space resources company; represents the frontier of new-space compensation at seed/Series A stage.

---

## Government and BLS Data

### 18. Bureau of Labor Statistics: Occupational Employment and Wages: Aerospace Engineers (SOC 17-2011)

- **URL:** https://www.bls.gov/oes/current/oes172011.htm
- **Source:** Occupational Employment and Wage Statistics (OEWS), May 2024
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** The definitive national baseline for aerospace engineering compensation. Provides percentile breakpoints for positioning any individual salary against the industry distribution.

### 19. Bureau of Labor Statistics: Mechanical Engineers (SOC 17-2141)

- **URL:** https://www.bls.gov/oes/current/oes172141.htm
- **Source:** Occupational Employment and Wage Statistics (OEWS), May 2024
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Cross-referenced SOC code for aerospace compensation analysis; captures roles that straddle mechanical and aerospace engineering disciplines.

### 20. Bureau of Labor Statistics: Electrical Engineers (SOC 17-2071)

- **URL:** https://www.bls.gov/oes/current/oes172071.htm
- **Source:** Occupational Employment and Wage Statistics (OEWS), May 2024
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Cross-referenced SOC code for aerospace compensation analysis; relevant for avionics and electrical engineering roles at aerospace companies.

### 21. Bureau of Labor Statistics: Aerospace Engineers Occupational Outlook

- **URL:** https://www.bls.gov/ooh/architecture-and-engineering/aerospace-engineers.htm
- **Source:** Occupational Outlook Handbook, 2024-2034 projections
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Industry growth context; validates that aerospace engineering is a growing field with increasing demand for talent.

### 22. Office of Personnel Management: General Schedule Pay Tables

- **URL:** https://www.opm.gov/policy-data-oversight/pay-leave/salaries-wages/
- **Key Finding:** Specific compensation figures from this public source have been omitted from this demonstration build. The entry is retained as a scraper target and reference link only.
- **Relevance:** Detailed breakdown of NASA and other federal aerospace agency pay structure; essential for GS-to-industry level mapping.

---

## Additional Market Context

The original reference document continued with narrative market-research sections
(industry salary surveys, director/VP benchmarks, aerospace industry context, and a
market-context summary). Those sections cited specific compensation figures from public
third-party sources and have been omitted from this public demonstration build.

For a production deployment, compile current market context from public sources such as
the BLS OEWS, levels.fyi, Glassdoor, and similar aggregators. The optional live web
scraper bundled with this tool automates collection from several of those sources.

## Company Career Pages

Direct career page URLs and ATS platform identifiers for each target company. Parsed by `parseCareerPagesFromReferences()` in `referenceParser.py` to configure the career page scraper. The ATS platform determines which scraping strategy is used (structured API, HTML rendering, or screenshot+OCR fallback).

| Company | ATS Platform | Career URL | Board Slug |
| ------- | ------------ | ---------- | ---------- |
| SpaceX | Greenhouse | https://www.spacex.com/careers | spacex |
| Blue Origin | Workday | https://blueorigin.wd5.myworkdayjobs.com/ | - |
| Rocket Lab | Greenhouse | https://rocketlabcorp.com/careers/ | rocketlab |
| Relativity Space | Workday | https://www.relativityspace.com/careers | - |
| Impulse Space | Pinpoint | https://impulsespace.pinpointhq.com/ | - |
| Stoke Space | Unknown | https://www.stokespace.com/careers/ | - |
| Ursa Major | Unknown | https://ursamajor.com/careers/ | - |
| Astra | Rippling | https://ats.rippling.com/astra | - |
| Astroforge | Unknown | https://www.astroforge.com/careers | - |
| L3Harris | Unknown | https://careers.l3harris.com/ | - |
| Northrop Grumman | Workday | https://ngc.wd1.myworkdayjobs.com/ | - |
| Lockheed Martin | Taleo | https://www.lockheedmartinjobs.com/ | - |
| Raytheon (RTX) | Unknown | https://careers.rtx.com/ | - |
| GE Aerospace | Workday | https://geaerospace.wd5.myworkdayjobs.com/ | - |
| The Aerospace Corporation | Workday | https://aero.wd5.myworkdayjobs.com/ | - |
| Firefly Aerospace | Unknown | https://firefly.hrmdirect.com/employment/job-openings.php | - |
| Sierra Space | Workday | https://sierraspace.wd1.myworkdayjobs.com/Sierra_Space_External_Career_Site | - |
| Vast | Greenhouse | https://www.vastspace.com/careers | vast |
| Axiom Space | Workday | https://axiomspace.wd5.myworkdayjobs.com/External_Career_Site | - |
| Intuitive Machines | Unknown | https://www.intuitivemachines.com/careers | - |
| ABL Space Systems | Lever | https://jobs.lever.co/ablspacesystems | ablspacesystems |
| Terran Orbital | Greenhouse | https://job-boards.greenhouse.io/terranorbitalcorporation | terranorbitalcorporation |
| Phantom Space | Unknown | https://phantomspace.bamboohr.com/careers | - |
| Virgin Galactic | Unknown | https://vgcareers.virgingalactic.com/global/en | - |
| Redwire Space | Greenhouse | https://careers.redwirespace.com/jobs/search | redwirespace |

**Platform Notes:**

- **Greenhouse**: Free public JSON API at `boards-api.greenhouse.io/v1/boards/{slug}/jobs`. Returns structured job data with titles, locations, and full descriptions. No authentication required.
- **Workday**: JavaScript-rendered SPA. Requires ZenRows cloud rendering or screenshot fallback. Job data is loaded dynamically via internal API calls.
- **Pinpoint/Rippling/Taleo**: Varying levels of JS rendering required. Generic HTML scraping with ZenRows rendering is attempted first.
- **Unknown**: Career page structure not yet classified. The scraper attempts generic HTML extraction, then falls back to screenshot+Tesseract OCR.

---

## Additional Resources

### Salary Comparison Tools

- **Levels.fyi Cross-Company Comparison:** https://www.levels.fyi/
- **Glassdoor Salary Explorer:** https://www.glassdoor.com/Salaries/
- **PayScale Salary Research:** https://www.payscale.com/research/US/
- **Comparably Salary Data:** https://www.comparably.com/salaries

### Federal Pay Resources

- **OPM GS Pay Calculator:** https://www.opm.gov/policy-data-oversight/pay-leave/salaries-wages/
- **FederalPay.org GS Lookup:** https://www.federalpay.org/gs

### Career Development

- **AIAA Career Resources:** https://www.aiaa.org/get-involved/students-educators/career-resources
- **Engineering Management Institute:** https://engineeringmanagementinstitute.org/
- **LeadDev Career Ladders:** https://leaddev.com/career-ladders

---

*Compiled February 2026*
