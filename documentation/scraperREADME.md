# Aerospace Compensation Scraper

## Overview

The Aerospace Compensation Scraper is a modular Python tool that collects live compensation data from public sources across the aerospace industry. It normalizes data from multiple sources into a unified schema compatible with the existing Compensation Band Survey, and can be accessed through three interfaces: a Streamlit web page, a Python API, or a command-line interface.

---

## Table of Contents

- [Architecture](#architecture)
- [Data Sources](#data-sources)
- [Output Schema](#output-schema)
- [Web Interface (Streamlit)](#web-interface-streamlit)
- [Python API](#python-api)
- [Command-Line Interface](#command-line-interface)
- [Configuration](#configuration)
- [Caching](#caching)
- [API Key Registration](#api-key-registration)
- [Dependencies](#dependencies)
- [File Reference](#file-reference)
- [Data Source References](#data-source-references)
- [Existing Research References](#existing-research-references)

---

## Architecture

The scraper is structured as three layers:

```txt
scraperInterface.py          <-- Lightweight 4-line API (same level as GUI.py)
cli.py                       <-- Command-line interface (same level as GUI.py)
    |
    v
tools/
    compensationScraper.py   <-- Backend scraper class (all scraping logic)
    auditUtils.py            <-- Shared utilities (mergeScrapedData, getScraperCacheDir)
    .scraperCache/           <-- Cached HTTP responses (auto-created, gitignored)
views/
    dataScraper.py           <-- Streamlit page (web interface)
documentation/
    *.xlsx, *.md, *.docx     <-- Data files, references, and documentation
```

**Data flow:**

1. `CompensationScraper` class fetches data from public APIs and web pages
2. Each source method returns a DataFrame normalized to the `surveyColumns` schema
3. Results are merged, deduplicated, and optionally combined with the existing 500+ row survey
4. Output can be displayed in Streamlit, exported to CSV/Excel, or used in Python code

---

## Data Sources

### Tier 1 -- High Reliability

| Source             | Key         | Auth Required  | Records     | Description                                                                                                                                                             |
| ------------------ | ----------- | -------------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **BLS OEWS** | `bls`     | Optional       | ~3 per run  | Bureau of Labor Statistics wage percentiles for SOC 17-2011 (Aerospace), 17-2141 (Mechanical), 17-2071 (Electrical). Returns P10, P25, median, P75, P90 national wages. |
| **Data USA** | `dataUsa` | None           | ~20 per run | Census Bureau American Community Survey data via the Data USA Tesseract API. Returns 10 years of average wage data for aerospace and mechanical engineers.              |
| **FRED**     | `fred`    | API key (free) | ~5 per run  | Federal Reserve Economic Data. Median weekly earnings for engineers (converted to annual) and aerospace manufacturing employment counts.                                |
| **Career Pages** | `careerPages` | None (ZenRows optional) | Varies | Direct job listings from company career websites. Uses Greenhouse/Lever JSON APIs for supported companies, ZenRows rendering for Workday portals, and screenshot+Tesseract OCR as a universal fallback. |

### Tier 2 -- Moderate Reliability

| Source               | Key           | Auth Required | Records      | Description                                                                                                                                                                                                |
| -------------------- | ------------- | ------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **H1B Data**   | `h1b`       | None          | ~100 per run | Public Department of Labor H1B visa salary disclosures from h1bdata.info. Individual employer salary records for certified visa applications. Queries generic aerospace roles + company-specific searches. |
| **Glassdoor**  | `glassdoor` | None          | Varies       | Salary estimates from employee reports and job postings. Extracts JSON-LD structured data and meta description salary patterns from public pages.                                                          |
| **PayScale**   | `payscale`  | None          | Varies       | Industry salary surveys and compensation benchmarks by role and experience level. Parses JSON-LD and structured HTML elements.                                                                             |
| **Indeed**     | `indeed`    | None          | Varies       | Aggregated salary data from job postings and employee submissions. Filters to plausible annual salary range (30K-500K).                                                                                    |
| **Salary.com** | `salaryCom` | None          | ~10 per run  | Benchmark salary data with 10th-90th percentile ranges for leveled job titles (I-V). Light anti-bot protections, reliable for static scraping.                                                             |

### Tier 3 -- Community / Aggregator

| Source               | Key             | Auth Required | Records      | Description                                                                                                                                                                                                |
| -------------------- | --------------- | ------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Levels.fyi**    | `levelsFyi`    | None          | Varies       | Employee-reported compensation data by company and role. Attempts to parse salary tables and JSON-LD structured data. May return limited data due to client-side rendering.                                |
| **ZipRecruiter**  | `ziprecruiter` | None          | Varies       | Job posting salary ranges and aggregated compensation data. Filters to plausible annual salary range (30K-500K).                                                                                           |
| **Comparably**    | `comparably`   | None          | Varies       | Compensation benchmarks with company culture and demographic context. Extracts JSON-LD with percentile data and text fallback.                                                                             |

### Source Details

**BLS OEWS (Bureau of Labor Statistics)**

Uses the BLS Public Data API v2 at `https://api.bls.gov/publicAPI/v2/timeseries/data/`. Queries OEWS series IDs for national-level wage data across three SOC codes. If the API fails, falls back to scraping the HTML summary page at `https://www.bls.gov/oes/current/oes172011.htm`.

- SOC 17-2011: Aerospace Engineers (median $134,830 as of May 2024)
- SOC 17-2141: Mechanical Engineers
- SOC 17-2071: Electrical Engineers

**Data USA (Census/ACS)**

Uses the Tesseract API at `https://api-ts-uranium.datausa.io/tesseract/data.jsonrecords`. Queries PUMS (Public Use Microdata Sample) data for detailed occupation codes 172011 and 172141. Returns average wage and total employment population by year.

**FRED (Federal Reserve)**

Uses the FRED API at `https://api.stlouisfed.org/fred/series/observations`. Queries time series:

- `LEU0254531900A`: Median usual weekly earnings for engineers (converted to annual by multiplying by 52)
- `CES3133600001`: Aerospace products and parts manufacturing employment

**H1B Data**

Scrapes HTML tables from `https://h1bdata.info/index.php`. Queries by job title (aerospace engineer, propulsion engineer, systems engineer, mechanical engineer) and by employer name for each target company. Parses the results table for employer, job title, base salary, and location.

**Levels.fyi**

Fetches company salary pages at `https://www.levels.fyi/companies/{slug}/salaries/{role}`. Attempts two parsing strategies: JSON-LD structured data in script tags, and HTML table parsing. This source is the most fragile because Levels.fyi renders most content client-side with JavaScript.

**Glassdoor**

Fetches public salary estimate pages for aerospace engineering roles. Extracts `estimatedSalary` JSON-LD structured data (using P10/P90 percentiles when available) with a fallback to parsing salary ranges from meta description tags. **Limitation:** Glassdoor uses JavaScript-based bot detection (PerimeterX/HUMAN) that blocks automated HTTP requests with HTTP 403. When a ZenRows API key is configured, requests are routed through ZenRows cloud rendering which executes the anti-bot JavaScript challenge and returns the fully rendered page.

**PayScale**

Fetches PayScale research pages for aerospace and related engineering roles. Extracts `estimatedSalary` JSON-LD with P25/P75 percentiles, with a fallback to parsing elements with `data-testid='salary'` attributes. Returns salary benchmarks by role and experience level.

**ZipRecruiter**

Fetches ZipRecruiter salary estimate pages. Extracts JSON-LD structured data with P10/P90 percentiles, with a fallback to regex-based salary parsing from page text. All extracted values are filtered to a plausible annual salary range (30K-500K) to discard hourly rates or parsing artifacts. **Limitation:** ZipRecruiter uses Cloudflare bot detection that blocks automated HTTP requests with HTTP 403. When a ZenRows API key is configured, requests are routed through ZenRows cloud rendering which bypasses the Cloudflare challenge.

**Comparably**

Fetches Comparably public salary research pages. Extracts JSON-LD with P25/P75 percentiles, with a fallback to regex-based text parsing. Values are filtered to the same plausible annual range (30K-500K). Also provides company culture and demographic context when available.

**Indeed**

Fetches Indeed career salary pages for aerospace engineering roles. Extracts JSON-LD with P25/P75 percentiles, with a fallback to regex salary parsing from page text. Values are filtered to the plausible annual range (30K-500K).

**Salary.com**

Fetches Salary.com benchmark salary pages for leveled engineering roles (I-V). URL pattern: `https://www.salary.com/research/salary/benchmark/{slug}-salary`. Extracts `estimatedSalary` JSON-LD structured data with P10/P90 percentiles, with a fallback to parsing salary values from meta description tags. Salary.com uses light anti-bot protections that do not require JS rendering, making it a reliable alternative to Glassdoor and ZipRecruiter. Queries 13 role/level combinations across Aerospace, Mechanical, Systems, and Avionics disciplines at Entry through Principal seniority levels.

**Career Pages (Company Websites)**

Scrapes job listings directly from the career pages of 16 target aerospace companies. Uses platform-specific parsers based on each company's ATS (Applicant Tracking System):

- **Greenhouse** (SpaceX, Rocket Lab): Free public JSON API at `boards-api.greenhouse.io/v1/boards/{slug}/jobs`. Returns structured job data with titles, locations, and full HTML descriptions. No authentication or JS rendering required.
- **Lever**: Free public JSON API at `api.lever.co/v0/postings/{slug}`. Similar structured data to Greenhouse.
- **Workday** (Blue Origin, Northrop Grumman, GE Aerospace, Aerospace Corporation, Relativity Space): JavaScript-rendered SPA. Requires ZenRows cloud rendering. Falls back to screenshot+OCR if ZenRows is unavailable.
- **Other platforms** (Pinpoint, Rippling, Taleo, Unknown): Generic HTML scraping with engineering keyword filtering. Falls back to screenshot+Tesseract OCR if HTML extraction yields no results.

Salary data is extracted from job description text via regex pattern matching. Many aerospace job listings do not include salary ranges, so listings without salary data are still captured with title, location, discipline, and seniority information. Company-to-platform mappings are configured in the "Company Career Pages" section of `compensationReference.md`.

### Known Limitations

Several data sources have access restrictions that prevent or limit automated scraping:

| Source | Issue | Status |
|--------|-------|--------|
| **Glassdoor** | PerimeterX/HUMAN bot detection. Direct HTTP requests return HTTP 403. | Bypassed with ZenRows API key; blocked without key |
| **ZipRecruiter** | Cloudflare bot detection. Direct HTTP requests return HTTP 403. | Bypassed with ZenRows API key; blocked without key |
| **FRED** | Requires a free API key. Without a key the source is skipped entirely. | Skipped unless key provided |
| **Levels.fyi** | Most salary data is rendered client-side via React/JavaScript. Static HTML scraping captures only JSON-LD and `<table>` elements, missing JS-rendered content. Small or niche companies often return 404. | Partial -- large companies return data, small companies may not |
| **H1B Data** | Some company-specific queries trigger redirect loops on h1bdata.info. Generic job-title queries work reliably. | Partial -- generic queries succeed, some company queries fail |
| **Indeed** | Occasional HTTP 403 on specific role pages. Most queries succeed. | Mostly functional |
| **Career Pages (Workday)** | Workday portals require JS rendering via ZenRows. Without a ZenRows key, these companies fall back to screenshot+OCR. | ZenRows key recommended for best results |
| **Career Pages (OCR)** | Screenshot+OCR fallback requires Tesseract installed locally and ZenRows key for screenshots. OCR accuracy varies with page layout. | Functional but lower accuracy than structured APIs |

These limitations are inherent to static HTTP scraping without a headless browser. The Streamlit UI displays a warning callout listing any sources that returned no data after a scrape completes.

---

## Output Schema

All scraped data is normalized to match the existing `surveyColumns` schema from `auditUtils.py`, plus a `DataSource` provenance column:

| Column             | Type  | Description                                                             |
| ------------------ | ----- | ----------------------------------------------------------------------- |
| `Company`        | str   | Company name or data source label (e.g. 'BLS National', 'Data USA/ACS') |
| `Listing`        | str   | Job title or data description                                           |
| `Level`          | int   | Inferred engineering level 1-5 (from title keywords and experience)     |
| `Seniority`      | str   | Inferred seniority: Entry, Mid, Senior, Staff, or Principal             |
| `ExpReq`         | float | Required experience (if available from source)                          |
| `Estimated`      | float | Estimated years of experience                                           |
| `Location`       | str   | City or geographic label                                                |
| `TeamDepartment` | str   | Team/department (typically null for scraped data)                       |
| `Discipline`     | str   | Inferred discipline: Aerospace, Propulsion, Mechanical, etc.            |
| `PositionType`   | str   | IC or Manager                                                           |
| `Min`            | float | Salary range minimum (or single salary figure)                          |
| `Max`            | float | Salary range maximum (or single salary figure)                          |
| `Vexp`           | float | Normalized experience mapping (null for scraped data)                   |
| `Vlvl`           | float | Normalized level mapping (null for scraped data)                        |
| `Filter`         | str   | Filter flag (null for scraped data)                                     |
| `Vmin`           | float | Normalized min band (null for scraped data)                             |
| `Vmax`           | float | Normalized max band (null for scraped data)                             |
| `Link`           | str   | Source URL for the data point                                           |
| `FilterCol`      | str   | Filter column (null for scraped data)                                   |
| `State`          | str   | State abbreviation (e.g. 'CA', 'FL', 'US' for national)                 |
| `DataSource`     | str   | Provenance: 'BLS', 'Data USA', 'FRED', 'H1B', 'Levels.fyi', 'Glassdoor', 'PayScale', 'ZipRecruiter', 'Comparably', 'Indeed', 'Salary.com', or 'Survey' |
| `Midpoint`       | float | Calculated (Min + Max) / 2                                              |

When merged with the existing survey, the `DataSource` column distinguishes original survey records ('Survey') from scraped records.

---

## Web Interface (Streamlit)

The Data Scraper page is accessible from the Streamlit app sidebar under **Data Collection > Data Scraper**.

### Launching the App

```bash
cd compensationcalculator
streamlit run GUI.py
```

### Page Layout

**1. API Key Configuration** (collapsed expander)

Enter optional API keys for BLS, FRED, and ZenRows. Keys are stored in Streamlit session state only and are never persisted to disk. The ZenRows key enables Glassdoor and ZipRecruiter scraping by bypassing JavaScript anti-bot protections.

**2. Source & Company Selection**

- **Data Sources**: Multi-select to choose which sources to scrape. Each source shows its tier and name.
- **Target Companies**: Multi-select of 16 default aerospace companies. Used by H1B and Levels.fyi for company-specific queries.
- **Cache Policy**: Choose 'Use cache (1 week)' to reuse previous responses, or 'Force refresh' to re-fetch everything.

**3. Run Scrape**

Click the 'Run Scrape' button to start. A progress bar and status text update in real time as each source is processed. Sources that fail are caught individually and do not stop other sources.

**4. Results**

After the scrape completes, results are displayed in three tabs:

- **Results Table**: Combined DataFrame from all sources with histogram and box plot visualizations. Includes a 'Download CSV' button.
- **By Source**: Expandable sections showing each source's individual results and row counts.
- **Merge & Export**: Merge scraped data with the existing 500+ row compensation band survey. Shows before/after metrics (existing records, scraped records, merged total, duplicates removed). Includes CSV and Excel download buttons.

---

## Python API

The primary API is the `CompensationScraper` class in `tools/compensationScraper.py`. The `scraperInterface.py` file at the repo root demonstrates the lightweight 4-line usage pattern.

### Quick Start

```python
from tools.compensationScraper import CompensationScraper, ScraperConfig

scraper = CompensationScraper(ScraperConfig())
df = scraper.runFullScrape()
scraper.exportToExcel(df, 'compensationData.xlsx')
```

### CompensationScraper Methods

**`scraper.runFullScrape(sources, progressCallback) -> pd.DataFrame`**

Scrape all (or selected) sources and return a single merged DataFrame. Combines `scrapeAll()` and `mergeResults()` into one call.

```python
# All sources
df = scraper.runFullScrape()

# Specific sources only
df = scraper.runFullScrape(sources=['bls', 'h1b', 'dataUsa'])

# With progress tracking
def onProgress(step, total, message):
    print(f'[{step}/{total}] {message}')

df = scraper.runFullScrape(progressCallback=onProgress)
```

**`scraper.runSingleSource(source, progressCallback) -> pd.DataFrame`**

Scrape one data source and return its normalized DataFrame.

```python
blsDf = scraper.runSingleSource('bls')
h1bDf = scraper.runSingleSource('h1b')
```

**`scraper.exportToExcel(df, outputPath) -> str`**

Export a DataFrame to Excel in survey-compatible format. Returns the absolute output path.

```python
path = scraper.exportToExcel(df, 'output.xlsx')
```

**`scraper.lastErrors() -> dict`**

Return errors from the last `scrapeAll()` or `runFullScrape()` call.

```python
for source, error in scraper.lastErrors().items():
    print(f'{source} failed: {error}')
```

**`scraper.clearCache()`**

Delete all cached HTTP responses.

### Advanced Usage -- Direct Orchestration

For finer control, use `scrapeAll()` and `mergeResults()` separately:

```python
from tools.compensationScraper import CompensationScraper, ScraperConfig

config = ScraperConfig(
    blsApiKey='your_key',
    fredApiKey='your_key',
    cacheTtlHours=24,
    requestDelaySeconds=3.0,
    targetCompanies=['SpaceX', 'Blue Origin'],
)

scraper = CompensationScraper(config)

# Run individual source methods directly
blsDf = scraper.scrapeBls()
h1bDf = scraper.scrapeH1b()

# Run selected sources with fault isolation
resultsBySource = scraper.scrapeAll(sources=['bls', 'h1b', 'dataUsa'])

# Check for errors
for source, error in scraper.lastErrors().items():
    print(f'{source} failed: {error}')

# Merge all results into one DataFrame
merged = scraper.mergeResults(resultsBySource)
```

---

## Command-Line Interface

The CLI is in `cli.py` (same level as `GUI.py`):

### List Available Sources

```bash
python cli.py --list-sources
```

### Run a Scrape

```bash
# All no-key sources
python cli.py --sources dataUsa bls h1b

# All sources with keys
python cli.py --bls-key YOUR_KEY --fred-key YOUR_KEY

# Force fresh data
python cli.py --sources bls --no-cache

# Export to Excel
python cli.py --sources dataUsa bls h1b --output results.xlsx

# Merge with existing survey and export
python cli.py --sources dataUsa bls h1b --merge --output merged.xlsx
```

### CLI Arguments

| Argument           | Description                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| `--sources`      | Space-separated source keys: `dataUsa`, `bls`, `fred`, `h1b`, `levelsFyi`, `glassdoor`, `payscale`, `ziprecruiter`, `comparably`, `indeed`, `salaryCom`, `careerPages`. Default: all. |
| `--bls-key`      | BLS API registration key                                                                          |
| `--fred-key`     | FRED API key                                                                                      |
| `--zenrows-key`  | ZenRows API key for JS-rendered pages (Glassdoor, ZipRecruiter)                                   |
| `--output`       | Output Excel file path                                                                            |
| `--merge`        | Merge results with the existing compensation band survey                                          |
| `--no-cache`     | Ignore cached responses and re-fetch everything                                                   |
| `--list-sources` | Print available sources and exit                                                                  |

### Example Output

```
Aerospace Compensation Scraper
========================================
  [  0%] Running Data USA...
  [ 10%] Running BLS OEWS...
  [ 20%] Running FRED...
  [ 30%] Running H1B Data...
  [ 40%] Running Levels.fyi...
  [ 50%] Running Glassdoor...
  [ 60%] Running PayScale...
  [ 70%] Running ZipRecruiter...
  [ 80%] Running Comparably...
  [ 90%] Running Indeed...
  [100%] All sources complete.

Collected 150 records

Records by source:
  H1B: 91
  Data USA: 20
  Glassdoor: 12
  PayScale: 8
  ZipRecruiter: 6
  Indeed: 5
  FRED: 5
  BLS: 3

Salary range: $60,000 - $208,000
Average midpoint: $102,450

Done.
```

---

## Configuration

The `ScraperConfig` dataclass controls scraper behavior:

| Parameter               | Default                                          | Description                                                          |
| ----------------------- | ------------------------------------------------ | -------------------------------------------------------------------- |
| `blsApiKey`           | `''`                                           | BLS API v2 key. V1 (no key) has lower rate limits.                   |
| `fredApiKey`          | `''`                                           | FRED API key. Required for the `fred` source.                      |
| `scraperApiKey`       | `''`                                           | ZenRows API key. Enables Glassdoor and ZipRecruiter scraping.        |
| `cacheDir`            | `tools/.scraperCache/`                         | Directory for cached HTTP responses.                                 |
| `cacheTtlHours`       | `168` (1 week)                                 | How long cached responses remain valid. Set to 0 to disable caching. |
| `requestDelaySeconds` | `2.0`                                          | Minimum seconds between HTTP requests (rate limiting).               |
| `userAgent`           | `'CompensationAudit/1.0 (Research)'`           | User-Agent header sent with all requests.                            |
| `targetCompanies`     | 16 aerospace companies                           | Companies to search for in H1B and Levels.fyi queries.               |
| `targetSocCodes`      | `['17-2011', '17-2141', '17-2071']`            | SOC codes for BLS queries.                                           |
| `timeoutSeconds`      | `30`                                           | HTTP request timeout.                                                |

### Default Target Companies

SpaceX, Blue Origin, Rocket Lab, Relativity Space, Impulse Space, Stoke Space, Ursa Major, Astra, Astroforge, L3Harris, Northrop Grumman, Lockheed Martin, Boeing, Raytheon, GE Aerospace, The Aerospace Corporation.

---

## Caching

HTTP responses are cached to `tools/.scraperCache/` as JSON files. Each file contains:

```json
{
    "timestamp": "2026-02-25T18:39:12.345678",
    "url": "https://api.bls.gov/publicAPI/v2/timeseries/data/",
    "content": "..."
}
```

Cache files are keyed by an MD5 hash of the URL + query parameters. Responses older than `cacheTtlHours` (default 1 week) are automatically re-fetched.

**Cache management:**

```python
# Clear all cached responses (Python)
scraper.clearCache()
```

```bash
# Clear cache manually
rm -rf compensationcalculator/tools/.scraperCache/*.json
```

The `.scraperCache/` directory should be added to `.gitignore` to avoid committing cached data.

---

## API Key Registration

### BLS API Key (Optional)

The BLS API v1 works without a key but limits requests to 25 per day. Registering for a free v2 key raises this to 500 per day.

1. Visit https://data.bls.gov/registrationEngine/
2. Fill out the registration form
3. Receive your key by email

### FRED API Key (Required for FRED source)

1. Visit https://fred.stlouisfed.org/docs/api/api_key.html
2. Create a free FRED account
3. Request an API key from your account settings
4. Key is available immediately after registration

### ZenRows API Key (Optional -- enables Glassdoor and ZipRecruiter)

ZenRows provides cloud-based JavaScript rendering that bypasses Cloudflare and PerimeterX anti-bot protections. The free tier includes 1,000 requests per month, which is sufficient for weekly scraping runs (~50 pages per run).

1. Visit https://www.zenrows.com/
2. Create a free account
3. Copy the API key from your dashboard
4. Enter the key in the Streamlit UI or pass via `--zenrows-key` on the CLI

Without a ZenRows key, Glassdoor and ZipRecruiter sources will gracefully fail (returning 0 rows) as before. All other sources are unaffected.

---

## Dependencies

The scraper requires these Python packages (in addition to the base app dependencies):

```bash
pip install requests beautifulsoup4 lxml pytesseract Pillow
```

| Package            | Purpose                                        |
| ------------------ | ---------------------------------------------- |
| `requests`       | HTTP client for API and web requests           |
| `beautifulsoup4` | HTML parsing for H1B and BLS fallback scraping |
| `lxml`           | Fast HTML parser backend for BeautifulSoup     |
| `pytesseract`    | Python wrapper for Tesseract OCR (career page screenshot fallback) |
| `Pillow`         | Image processing for screenshot handling       |

**System dependency:** Tesseract OCR must be installed on the system for the screenshot+OCR fallback to work. Install via `apt install tesseract-ocr` (Linux), `brew install tesseract` (macOS), or the [Windows installer](https://github.com/UB-Mannheim/tesseract/wiki). The `pytesseract` and `Pillow` packages are only required if using the screenshot fallback -- all other career page scraping (Greenhouse API, Lever API) works without them.

These are in addition to the existing app dependencies: `streamlit`, `pandas`, `plotly`, `fpdf`, `kaleido`, `openpyxl`.

---

## File Reference

| File                       | Location                | Purpose                                                                                                          |
| -------------------------- | ----------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `compensationScraper.py` | `tools/`              | Backend scraper class with 12 data source methods, caching, rate limiting, and schema normalization              |
| `careerPageScraper.py`   | `tools/`              | Career page scraper with platform-specific parsers (Greenhouse, Lever, Workday) and screenshot+OCR fallback      |
| `scraperInterface.py`    | `compensationcalculator/` (root) | Lightweight 4-line script demonstrating the scraper API                                               |
| `cli.py`                 | `compensationcalculator/` (root) | Command-line interface with argument parsing, merge, and export                                       |
| `dataScraper.py`         | `views/`              | Streamlit page for the web interface                                                                             |
| `auditUtils.py`          | `tools/`              | Shared utilities -- `loadMarketSurveyData()`, `mergeScrapedData()`, `scraperCacheDir()`                         |
| `GUI.py`                 | `compensationcalculator/` (root) | Main Streamlit app -- Data Scraper page in navigation                                                 |
| `scraperREADME.md`       | `documentation/`      | This file                                                                                                        |

---

## Data Source References

These are the public data sources accessed by the scraper:

### Government / Official Data

1. **Bureau of Labor Statistics - OEWS**

   - URL: https://www.bls.gov/oes/current/oes172011.htm
   - API: https://api.bls.gov/publicAPI/v2/timeseries/data/
   - Data: National and state-level wage percentiles for aerospace engineers (SOC 17-2011)
   - Terms: Public domain, no restrictions on use
2. **FRED (Federal Reserve Economic Data)**

   - URL: https://fred.stlouisfed.org/
   - API: https://api.stlouisfed.org/fred/series/observations
   - Data: Median earnings time series, aerospace manufacturing employment
   - Terms: Free API key required, public data
3. **H1B Visa Salary Disclosures (via h1bdata.info)**

   - URL: https://h1bdata.info/
   - Original Data: U.S. Department of Labor Labor Condition Applications (LCA)
   - Data: Employer-specific salary disclosures for certified H1B visa applications
   - Terms: Public government data indexed by a community service
4. **Data USA / Census Bureau ACS**

   - URL: https://datausa.io/profile/soc/aerospace-engineers
   - API: https://api-ts-uranium.datausa.io/tesseract/data.jsonrecords
   - Data: American Community Survey average wages and employment counts by occupation
   - Terms: Public data aggregated from Census Bureau PUMS

### Community / Aggregator Data

5. **Levels.fyi**
   - URL: https://www.levels.fyi/
   - Data: Employee-reported compensation data by company, level, and role
   - Terms: Public pages accessible; site may block automated access
   - Note: This source yields limited results because most content is JavaScript-rendered

6. **Glassdoor**
   - URL: https://www.glassdoor.com/Salaries/
   - Data: Salary estimates from employee reports and job postings
   - Terms: Public salary pages accessible; detailed data requires authentication
   - Note: Scrapes public salary estimate pages and JSON-LD structured data

7. **PayScale**
   - URL: https://www.payscale.com/research/US/
   - Data: Salary research based on employee-reported compensation
   - Terms: Public salary pages accessible

8. **ZipRecruiter**
   - URL: https://www.ziprecruiter.com/Salaries/
   - Data: Salary estimates based on aggregated job posting data
   - Terms: Public salary pages accessible

9. **Comparably**
   - URL: https://www.comparably.com/salaries
   - Data: Company salary comparisons and compensation ranges
   - Terms: Public salary pages accessible

10. **Indeed**
    - URL: https://www.indeed.com/career/salaries
    - Data: Salary estimates from aggregated job posting data
    - Terms: Public career salary pages accessible

11. **Salary.com**
    - URL: https://www.salary.com/research/salary/benchmark/
    - Data: Benchmark salary data with 10th-90th percentile ranges for leveled job titles (I-V)
    - Terms: Public salary pages accessible; light anti-bot protections

### Company Career Pages (Direct)

12. **Greenhouse API**
    - API: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs
    - Companies: SpaceX, Rocket Lab
    - Data: Structured JSON job listings with titles, locations, and HTML descriptions
    - Terms: Public unauthenticated API; no rate limit documentation

13. **Lever API**
    - API: https://api.lever.co/v0/postings/{slug}
    - Data: Structured JSON job listings with titles, locations, and descriptions
    - Terms: Public unauthenticated API

14. **Workday Career Portals**
    - URL pattern: https://{tenant}.wd5.myworkdayjobs.com/
    - Companies: Blue Origin, Northrop Grumman, GE Aerospace, The Aerospace Corporation, Relativity Space
    - Data: JS-rendered job listing pages; requires cloud rendering to extract
    - Terms: Public career pages

15. **Other ATS Platforms** (Pinpoint, Rippling, Taleo)
    - Companies: Impulse Space, Astra, Boeing, Lockheed Martin, and others
    - Data: HTML job listing pages with varying structures
    - Terms: Public career pages

---

## Existing Research References

The scraper complements 40 research sources curated in the consolidated reference document:

### Reference Documentation (`compensationReference.md`)

All research sources, data file descriptions, BLS benchmarks, and market context are maintained in a single consolidated document. Sources are organized by category:

**Salary Aggregator Data (17 sources)**

- Levels.fyi data for SpaceX, Blue Origin, Northrop Grumman, Lockheed Martin, Rocket Lab, Aerojet Rocketdyne (L3Harris), NASA, and Boeing
- Glassdoor data for Raytheon, GE Aerospace, Aerospace Corporation, Relativity Space, Impulse Space, Stoke Space, Ursa Major, Astra, and Astroforge

**Government and BLS Data (5 sources)**

- BLS Occupational Employment and Wages (SOC 17-2011, 17-2141, 17-2071)
- BLS Occupational Outlook Handbook (2024-2034 projections)
- OPM General Schedule pay tables

**Industry Salary Surveys (4 sources)**

- Glassdoor aerospace engineer salary data
- PayScale aerospace engineer salary report
- ZipRecruiter aerospace engineer statistics
- Comparably aerospace director salary range

**Career Ladder Research (4 sources)**

- LeadDev IC vs. management career tracks
- Saxon Aerospace career pathways
- Fonzi engineering career levels guide
- Levels.fyi cross-company level framework

**Director and VP Benchmarks (4 sources)**

- Glassdoor engineering director salary (all industries)
- Glassdoor SpaceX director salary data
- Glassdoor VP of engineering salary
- SpaceCrew space industry salary data

**Aerospace Industry Context (6 sources)**

- AIAA workforce and compensation resources
- Comparably SpaceX vs. Lockheed Martin vs. Boeing culture comparison
- The Structures Company aerospace career progression
- State labor department aerospace industry wage data
- AIA Facts and Figures 2024 workforce report
- StartUs Insights space launch industry compensation trends

**Market Context**

- NewSpace company compensation ranges (SpaceX, Blue Origin, Rocket Lab)
- Startup compensation trends from Carta and Space Talent
- NASA compensation context
- Region-specific aerospace salary data
- Key takeaways for compensation framework positioning

### Synthetic Survey Data (`documentation/marketSurveySynthetic.csv`)

The bundled survey is a synthetic, fictional dataset of job listings across fictional aerospace companies, with salary ranges, locations, disciplines, and normalized level assignments. All figures are invented for demonstration. The scraper's output is designed to complement and extend this dataset with genuine market data.

---

*Author: Sean Bowman — 02/27/2026*
