
# Compensation Audit Tool

A Streamlit-based tool for engineering compensation analysis, benchmarking, and employee auditing. Built around a synthetic salary framework and a synthetic market survey, and optionally supplemented by live and cached market data scraped from public sources.

> **Demonstration data:** This is a public, personal build. The salary bands, the market survey, and every dollar figure are **fictional** — they are invented round numbers for demonstration and do not represent any real company's compensation. See [Data Backend](#data-backend).

---

## Table of Contents

- [Overview](#overview)
- [Project Structure](#project-structure)
- [Data Backend](#data-backend)
  - [Synthetic Data Sources](#synthetic-data-sources)
  - [Compensation Formula](#compensation-formula)
  - [Reference Document](#reference-document)
- [Modules](#modules)
  - [tools/](#tools)
  - [views/](#views)
- [Data Scraper](#data-scraper)
  - [Scraper Sources](#scraper-sources)
  - [CLI Interface](#cli-interface)
  - [Caching](#caching)
- [Neural Classifier](#neural-classifier)
- [Running the App](#running-the-app)
- [Developer Notes](#developer-notes)

---

## Overview

The tool provides a multi-page Streamlit interface for:

- Computing individual salaries against the proposed 5-level compensation framework
- Auditing all employees against their current compensation bands
- Benchmarking the salary bands against aerospace industry market data
- Exploring raw job listing data scraped from public sources
- Classifying scraped job listings into engineering levels via a trained MLP

---

## Project Structure

```txt
compensationcalculator/
│
├── GUI.py                          # Streamlit entry point, navigation
├── cli.py                          # CLI runner for the data scraper
├── scraperInterface.py             # Thin wrapper: run scraper from terminal
├── scrapeForTraining.py            # One-off script: build labeled training dataset
│
├── tools/                          # Backend logic
│   ├── auditUtils.py               # Data loading, constants, salary calculation
│   ├── referenceParser.py          # Parses compensationReference.md for company/SOC lists
│   ├── compensationScraper.py      # Multi-source market data scraper
│   ├── careerPageScraper.py        # Scraper for company career page job listings
│   ├── featureEngineering.py       # Feature matrix construction for the classifier
│   ├── neuralClassifier.py         # MLP classifier: job listing → engineering level (1–5)
│   ├── nnVisualizations.py         # Plotly charts for classifier diagnostics
│   ├── validatedAnalysis.py        # Statistical analysis of validated market data
│   └── README.md                   # tools/ sub-module documentation
│
├── views/                          # Streamlit page modules
│   ├── compensationCalculator.py   # Interactive salary calculator
│   ├── levelsOverview.py           # Engineering levels framework display
│   ├── individualAudit.py          # Per-employee audit with band positioning
│   ├── marketComparison.py         # Proposed bands vs. survey aggregate
│   ├── marketDataExplorer.py       # Raw scraped listings table
│   ├── validatedMarketAnalysis.py  # Validated listing analysis with classifier overlay
│   ├── marketTools.py              # Scraper controls and training data management
│   ├── dataScraper.py              # Streamlit UI for live scraping sessions
│   ├── nnShowcase.py               # Neural classifier diagnostics and training UI
│   └── references.py              # Rendered source documentation page
│
├── documentation/
│   ├── marketSurveySynthetic.csv                       # Synthetic, fictional market survey
│   ├── compensationReference.md                        # Canonical source reference doc
│   ├── engineeringLevels.md                            # Levels detail for UI rendering
│   ├── auditUtilsREADME.md                             # auditUtils detailed reference
│   ├── neuralClassifierREADME.md                       # Classifier architecture notes
│   └── scraperREADME.md                                # Scraper source documentation
│
└── .streamlit/                     # Streamlit theme configuration
```

The synthetic salary framework (bands, modifiers, premiums, geographic factors) lives in
[tools/syntheticData.py](tools/syntheticData.py) as readable Python constants.

---

## Data Backend

### Synthetic Data Sources

All compensation data in this build is **synthetic and fictional** — invented round numbers for
demonstration. There is no binary-spreadsheet dependency for startup data.

#### Synthetic salary framework — `tools/syntheticData.py`

The salary framework is a set of readable, version-controlled Python constants: `SALARY_BANDS`,
`EXPERIENCE_MODIFIERS`, `MANAGEMENT_PREMIUMS`, `EXTENDED_BANDS`, `GEOGRAPHIC_ADJUSTMENTS`, and
`WAGE_BENCHMARKS`. `auditUtils.py` imports these directly at module load.

The five-level individual-contributor band structure (fictional figures):

| Level | Name | Min | Median | Max | Min Yrs |
|---|---|---|---|---|---|
| I | Associate Engineer | $70,000 | $80,000 | $90,000 | 0 |
| II | Engineer | $90,000 | $100,000 | $110,000 | 2 |
| III | Senior Engineer | $110,000 | $125,000 | $140,000 | 4 |
| IV | Staff Engineer | $140,000 | $160,000 | $180,000 | 7 |
| V | Principal Engineer | $180,000 | $205,000 | $230,000 | 12 |

`auditUtils.py` exposes these as the `salaryBands`, `experienceModifiers`, and
`managementPremiums` constants (deep-copied so the runtime band/premium editors can mutate them).

#### Synthetic market survey — `documentation/marketSurveySynthetic.csv`

A flat-header CSV of fictional job listings across fictional aerospace companies, used by the
market comparison pages and the classifier. Schema-auto-detected on load (flat-header mode).
Loaded by `loadMarketSurveyData()` in [tools/auditUtils.py](tools/auditUtils.py).

### Compensation Formula

```txt
finalSalary = (baseSalary * relevanceMultiplier * complexityMultiplier + managementPremium) * startupMultiple
```

Where:

- `baseSalary` — interpolated from the level's min/median/max based on band position
- `relevanceMultiplier` — 1.0 / 1.025 / 1.05 (Low/Med/High relevance)
- `complexityMultiplier` — 1.0 / 1.025 / 1.05 (Low/Med/High complexity)
- `managementPremium` — $0 / $5,000 / $15,000 / $40,000 (IC / RE / Lead / Director), fictional
- `startupMultiple` — configurable startup compensation factor

The 5-level framework and the formula are real; only the dollar figures are fictional.

### Reference Document

`documentation/compensationReference.md` is the **single source of truth** for external sources. It is not just documentation — it is parsed at runtime by `referenceParser.py` to extract:

- Company names (used as scraper targets)
- SOC codes (used to query BLS OEWS API)
- States (used for geographic filters)

Do not remove or reformat sections of `compensationReference.md` without checking `referenceParser.py`. The parser uses `###` heading patterns and expects the "Salary Aggregator Data" section to list companies in `### N. Source: Company Name` format.

---

## Modules

### tools/

| File | Purpose |
|---|---|
| [auditUtils.py](tools/auditUtils.py) | Data loading, column schema, salary calculation, module-level constants. All views import from here. |
| [referenceParser.py](tools/referenceParser.py) | Parses `compensationReference.md` to extract companies, SOC codes, and states. Returns empty lists on parse failure rather than raising. |
| [compensationScraper.py](tools/compensationScraper.py) | Multi-source scraper. Each source is an independent method returning a normalized DataFrame. Source failures do not block other sources. |
| [careerPageScraper.py](tools/careerPageScraper.py) | Scrapes company career pages for job listings. Used to build the training dataset for the classifier. |
| [featureEngineering.py](tools/featureEngineering.py) | Constructs the feature matrix for the MLP from scraped listing data. |
| [neuralClassifier.py](tools/neuralClassifier.py) | Trains and persists a scikit-learn `MLPClassifier` to assign engineering levels (1–5) to job listings. |
| [nnVisualizations.py](tools/nnVisualizations.py) | Plotly diagnostics for the classifier (confusion matrix, permutation importance, CV metrics). |
| [validatedAnalysis.py](tools/validatedAnalysis.py) | Statistical analysis pipeline for validated market listings with classifier-assigned levels. |

### views/

Each file in `views/` is a Streamlit page module registered in `GUI.py`. All pages call a single top-level `render*()` function.

| File | Page Title | Description |
|---|---|---|
| [compensationCalculator.py](views/compensationCalculator.py) | Salary Calculator | Interactive inputs for level, band position, modifiers. Real-time salary output and band visualization. |
| [levelsOverview.py](views/levelsOverview.py) | Engineering Levels | Displays the 5-level framework, descriptions, and experience ranges from `engineeringLevels.md`. |
| [individualAudit.py](views/individualAudit.py) | Employee Audit | Per-employee band positioning, modifier audit, deviation from formula. |
| [marketComparison.py](views/marketComparison.py) | Market Comparison | Proposed bands overlaid on survey aggregate ranges by level. |
| [marketDataExplorer.py](views/marketDataExplorer.py) | Job Listings Explorer | Filterable table of raw scraped listings from the survey or scraper cache. |
| [validatedMarketAnalysis.py](views/validatedMarketAnalysis.py) | Validated Market Analysis | Classifier-annotated listings with statistical analysis by level. |
| [marketTools.py](views/marketTools.py) | Market Tools | Trigger live scraping runs, manage cache, export datasets. |
| [dataScraper.py](views/dataScraper.py) | (sub-page) | Streamlit UI wrapper around `CompensationScraper` with real-time `st.status()` progress. |
| [nnShowcase.py](views/nnShowcase.py) | (sub-page) | Train, evaluate, and inspect the neural classifier from the browser. |
| [references.py](views/references.py) | References & Sources | Renders `compensationReference.md` directly in the sidebar navigation. |

---

## Data Scraper

### Scraper Sources

`compensationScraper.py` implements an independent method per data source. All sources return DataFrames normalized to the same schema as the survey file (`surveyColumns` from `auditUtils.py`). Sources:

| Source | Type | Notes |
|---|---|---|
| BLS OEWS | REST API | Queries by SOC code and state; SOC codes pulled from `compensationReference.md` |
| FRED | REST API | Federal Reserve earnings time series |
| H1B | Web | Public visa salary disclosure data |
| Levels.fyi | Web | Company/level salary data |
| Data USA | Web | Census/ACS salary aggregates |
| Glassdoor | Web | Salary estimates from employee reports |
| PayScale | Web | Employee-reported salary research |
| ZipRecruiter | Web | Salary estimates from job postings |
| Comparably | Web | Company salary comparisons |
| Indeed | Web | Job posting salary estimates |
| Salary.com | Web | Benchmark percentiles by job level |

Career page job listings are handled separately by `careerPageScraper.py`, which targets specific company career portals.

### CLI Interface

The scraper can be run directly from the terminal without starting the Streamlit app:

```bash
# Run all sources
python cli.py

# Run specific sources
python cli.py --sources bls h1b careerPages --output results.xlsx

# List available sources
python cli.py --list-sources

# Merge cached results
python cli.py --merge --output merged.xlsx
```

### Caching

Scraped results are cached under `tools/.scraperCache/` as JSON. Cache hits are logged at INFO level. Cache is keyed by source + query parameters. The validated analysis pipeline uses a separate cache at `tools/.validatedCache/`. Trained classifier models are persisted to `tools/.modelCache/`.

---

## Neural Classifier

The MLP classifier in `neuralClassifier.py` maps scraped job listings to engineering levels I–V. Design choices:

- **scikit-learn `MLPClassifier`** — appropriate for small tabular training sets; avoids TensorFlow overhead
- **`StandardScaler`** — required for MLP convergence on mixed-scale features
- **Stratified K-Fold CV** — handles class imbalance across levels
- **Oversampling** — minority classes are upsampled before training
- **L2 regularization + early stopping** — overfitting prevention on small dataset

Feature engineering is in `featureEngineering.py`. The feature matrix is built from salary range, title keywords, company embedding, and experience signals. See `documentation/neuralClassifierREADME.md` for full architecture notes.

By default the classifier trains on the synthetic market survey (`documentation/marketSurveySynthetic.csv`). That dataset is small, so the bundled classifier is a demonstration of the pipeline; `scrapeForTraining.py` can build a larger labeled dataset from live scraping.

---

## Running the App

```bash
# Install dependencies (Python 3.x)
pip install streamlit pandas plotly scikit-learn requests beautifulsoup4 joblib

# Launch the app
streamlit run GUI.py
```

The app runs on `localhost:8501` by default. Streamlit configuration (theme, layout) is in `.streamlit/`.

---

## Developer Notes

- All views import constants and data from `auditUtils.py`. That module is loaded once at import time — modifying `tools/syntheticData.py` or the synthetic survey CSV requires restarting the app.
- `tools/` is inserted into `sys.path` by both `GUI.py` and `cli.py` so modules in `tools/` can import each other without package-relative paths.
- `referenceParser.py` is the bridge between the human-readable reference doc and the scraper. Parse functions return empty lists on failure so a malformed reference file does not crash the scraper.
- The `use_container_width` Streamlit parameter is deprecated. Use `width='stretch'` instead throughout the codebase.
- Temporary files matching `*.tmp`, `*.tmp.*`, `tmpclaude-*` should be deleted after any editing session. Cached scraper data in `tools/.scraperCache/` older than 12 hours can be cleared safely.
