
# -- Data Scraper Page -- #

'''

Streamlit UI for running aerospace compensation data scrapes from
public sources. Provides source selection, real-time progress tracking,
result visualization, and merge/export capabilities.

Author: Sean Bowman
Date:   02/25/2026

'''

# Standard library imports
import io
import os
import re
import sys
import logging

# Third-party imports
import streamlit as st
import pandas as pd
import plotly.express as px

# Ensure tools directory is importable
_viewsDir = os.path.dirname(os.path.abspath(__file__))
_appDir = os.path.dirname(_viewsDir)
_toolsDir = os.path.join(_appDir, 'tools')
if _toolsDir not in sys.path:
    sys.path.insert(0, _toolsDir)

# Local imports
from auditUtils import (
    colors, plotlyDarkLayout, loadMarketSurveyData,
    mergeScrapedData, surveyColumns,
)
from compensationScraper import (
    CompensationScraper, ScraperConfig, defaultTargetCompanies,
    loadApiKeys, validateApiKeys,
)
from validatedAnalysis import filterEngineeringRoles


# ---------------------------------------------------------------------- #
# -- Log Capture Handler -- #
# ---------------------------------------------------------------------- #

class _StreamlitLogHandler(logging.Handler):

    '''

    Lightweight logging handler that collects WARNING+ messages
    emitted during a scrape so they can be displayed in the UI.

    '''

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))

    def summarize(self) -> str:

        '''

        Parse collected log messages into a quantitative markdown summary
        grouped by category (HTTP errors, empty results, parse failures, etc.).

        '''

        from collections import Counter

        if not self.records:
            return ''

        httpErrors = Counter()       # status code -> count
        noData = []                  # source names that returned nothing
        parseFailures = []           # source names with parse errors
        accessIssues = []            # sources blocked or requiring auth
        configIssues = []            # missing keys, unknown sources, etc.
        other = []                   # anything uncategorized

        for msg in self.records:
            # HTTP status errors: "HTTP 404 from https://..."
            httpMatch = re.search(r'HTTP (\d{3}) from', msg)
            if httpMatch:
                httpErrors[httpMatch.group(1)] += 1
                continue

            # No data collected: "No BLS data collected"
            noDataMatch = re.search(r'No (\S+.*?) data collected', msg)
            if noDataMatch:
                noData.append(noDataMatch.group(1))
                continue

            # Parse failures: "... parsing error for ..."
            parseMatch = re.search(r'(\S+) parsing error', msg, re.IGNORECASE)
            if parseMatch:
                parseFailures.append(parseMatch.group(1))
                continue

            # Access issues: "blocked", "authentication", "JS-rendered"
            if any(kw in msg.lower() for kw in ['blocked', 'authentication', 'js-rendered']):
                # Extract source name from the message
                sourceMatch = re.search(r'No (\S+)', msg)
                sourceName = sourceMatch.group(1) if sourceMatch else 'Unknown'
                accessIssues.append(sourceName)
                continue

            # Config issues: missing keys, unknown sources
            if 'api key' in msg.lower() or 'unknown source' in msg.lower():
                configIssues.append(msg)
                continue

            other.append(msg)

        # Build markdown summary
        lines = []

        if httpErrors:
            total = sum(httpErrors.values())
            breakdown = ', '.join(f'{code}: {count}' for code, count in sorted(httpErrors.items()))
            lines.append(f'**HTTP Errors** -- {total} failed request(s) ({breakdown})')

        if noData:
            lines.append(f'**No Results** -- {len(noData)} source(s) returned empty data: {", ".join(noData)}')

        if accessIssues:
            lines.append(f'**Access Blocked** -- {len(accessIssues)} source(s) may require authentication or are JS-rendered: {", ".join(accessIssues)}')

        if parseFailures:
            counted = Counter(parseFailures)
            parts = [f'{src} ({n})' if n > 1 else src for src, n in counted.items()]
            lines.append(f'**Parse Failures** -- {len(parseFailures)} error(s) across: {", ".join(parts)}')

        if configIssues:
            lines.append(f'**Configuration** -- {len(configIssues)} issue(s): {"; ".join(configIssues)}')

        if other:
            lines.append(f'**Other** -- {len(other)} additional warning(s)')

        return '\n\n'.join(lines)


# ---------------------------------------------------------------------- #
# -- Row Flagging -- #
# ---------------------------------------------------------------------- #

# US state abbreviations for multi-state detection
_stateAbbreviations = {
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC',
}


def _flagSuspectRows(df: pd.DataFrame) -> pd.DataFrame:

    '''

    Analyze a scraped DataFrame and add a _reviewFlag column identifying
    rows that may require human review. A row can have multiple flags
    separated by commas.

    Flag categories:
        Missing Salary   -- Both Min and Max are NaN or 0
        Wide Range       -- Max - Min > $80,000
        Ambiguous Location -- Location contains 'Remote', 'Various',
                             'Multiple', or is missing
        Multi-State      -- Location contains 2+ US state abbreviations

    '''

    if df.empty:
        return df.assign(_reviewFlag='')

    flags = [[] for _ in range(len(df))]

    # Coerce salary columns to numeric
    minVals = pd.to_numeric(df.get('Min'), errors='coerce').fillna(0)
    maxVals = pd.to_numeric(df.get('Max'), errors='coerce').fillna(0)

    for i in range(len(df)):
        rowFlags = []

        # Missing Salary
        if minVals.iloc[i] == 0 and maxVals.iloc[i] == 0:
            rowFlags.append('Missing Salary')

        # Wide Range
        salaryRange = maxVals.iloc[i] - minVals.iloc[i]
        if minVals.iloc[i] > 0 and maxVals.iloc[i] > 0 and salaryRange > 80000:
            rowFlags.append('Wide Range')

        # Location checks
        loc = str(df['Location'].iloc[i]) if 'Location' in df.columns else ''
        locLower = loc.lower()

        if not loc or loc == 'nan' or any(kw in locLower for kw in ['remote', 'various', 'multiple']):
            rowFlags.append('Ambiguous Location')

        # Multi-State: find 2+ state abbreviations in location string
        stateMatches = re.findall(r'\b([A-Z]{2})\b', loc)
        matchedStates = [s for s in stateMatches if s in _stateAbbreviations]
        if len(set(matchedStates)) >= 2:
            rowFlags.append('Multi-State')

        flags[i] = ', '.join(rowFlags)

    result = df.copy()
    result['_reviewFlag'] = flags
    return result


# ---------------------------------------------------------------------- #
# -- NN Training Data Mode -- #
# ---------------------------------------------------------------------- #

# Career page source keys (the only sources that produce individual job listings
# suitable for manual Vlvl labeling; aggregate sources like BLS/FRED/H1B are not
# appropriate for per-listing NN training data).
_trainingSourceKeys = ['careerPages']

# Columns written to the labeling template Excel
_labelingColumns = [
    'Company', 'Listing', 'Discipline', 'Seniority',
    'Location', 'State', 'Min', 'Max', 'Link',
]

# Instructions text embedded in Sheet 2 of the labeling template
_labelingInstructions = '''Labeling Instructions

Purpose
-------
Fill in the Vlvl column (1-5) for each job listing based on the engineering
level framework. This data will be used to retrain the neural network classifier
that assigns levels to scraped job postings.

Level Definitions
-----------------
  Vlvl 1  --  Associate / Entry-level engineer (0-1 years experience)
  Vlvl 2  --  Engineer (2-3 years experience)
  Vlvl 3  --  Senior Engineer (4-6 years experience)
  Vlvl 4  --  Staff / Lead Engineer (7-11 years experience)
  Vlvl 5  --  Principal / Distinguished Engineer (12+ years experience)

Labeling Guidance
-----------------
  - Use the job title and seniority column as primary signals
  - If Min/Max salary is present, use it to corroborate your level assignment
  - "Senior" in title -> typically Vlvl 3; "Staff" -> Vlvl 4; "Principal" -> Vlvl 5
  - When in doubt between two adjacent levels, leave a note in the Notes column
  - Leave Vlvl blank if the listing is clearly not an engineering role (management,
    HR, finance, etc.) -- these rows will be filtered before training

Import
------
After completing labels, save the file and use the "Import Labeled Data" tab
in the NN Training Data mode to load it back into the app. Then retrain the
neural network from the NN Classifier tab.
'''


def _renderNnTrainingMode() -> None:
    '''
    Render the NN Training Data mode UI.

    Workflow:
        1. Run a career pages scrape to collect individual job listings
        2. Export a dated Excel template with an empty Vlvl column
        3. Manually label Vlvl (1-5) for each listing in Excel
        4. Import the labeled file back via the Import tab
        5. Retrain the NN from the NN Classifier tab

    '''
    st.markdown('---')
    st.markdown(
        '**Purpose:** Collect individual job listings from company career pages and export them '
        'as a labeled template for manual engineering level annotation. The completed labels are used to '
        'generate additional training data for the neural network classifier.\n\n'
        'This mode scrapes **career pages only** (Greenhouse, Lever, Workday, etc.) because '
        'those sources produce individual listings suitable for per-row labeling. Aggregate '
        'sources (BLS, FRED, H1B) are excluded — they report salary bands, not individual postings.'
    )

    st.markdown('')

    trainingTab1, trainingTab2 = st.tabs(['Export Labeling Template', 'Import Labeled Data'])

    # ---- Tab 1: Export Labeling Template ---- #
    with trainingTab1:
        st.subheader('Export Labeling Template')
        st.markdown(
            'Scrape career pages and export a dated Excel file with an empty **Vlvl** column '
            'for manual annotation. The file includes an Instructions sheet with labeling guidance.'
        )

        # Company selection
        trainingCompanies = st.multiselect(
            'Target Companies',
            defaultTargetCompanies,
            default=defaultTargetCompanies,
            key='trainingCompanies',
        )

        trainingCachePolicy = st.selectbox(
            'Cache Policy',
            ['Force refresh (recommended for training data)', 'Use cache (1 week)'],
            key='trainingCachePolicy',
            help='Force refresh is recommended for training data to capture the current live job board state.',
        )

        runTrainingScrape = st.button(
            'Scrape Career Pages',
            width='stretch',
            type='primary',
        )

        if runTrainingScrape:
            if not trainingCompanies:
                st.warning('Please select at least one company.')
            else:
                # Force TTL=0 for training scrapes to always get fresh data
                cacheTtl = 0 if 'Force refresh' in trainingCachePolicy else 168
                config = ScraperConfig(
                    cacheTtlHours=cacheTtl,
                    requestDelaySeconds=1.5,
                    targetCompanies=trainingCompanies,
                )

                trainingProgressBar = st.progress(0)
                trainingStatus = st.empty()

                def trainingProgressCallback(step, total, message):
                    '''Update progress for training scrape.'''
                    pct = min(step / max(total, 1), 1.0)
                    trainingProgressBar.progress(pct)
                    trainingStatus.text(f'{message}')

                logHandler = _StreamlitLogHandler()
                scraperLogger = logging.getLogger('compensationScraper')
                scraperLogger.addHandler(logHandler)

                try:
                    scraper = CompensationScraper(config)
                    resultsBySource = scraper.scrapeAll(
                        sources=_trainingSourceKeys,
                        progressCallback=trainingProgressCallback,
                    )
                    trainingProgressBar.progress(1.0)
                    trainingStatus.text('Career page scrape complete.')

                    # Filter to engineering roles only before exporting
                    if resultsBySource.get('careerPages') is not None:
                        resultsBySource['careerPages'] = filterEngineeringRoles(
                            resultsBySource['careerPages']
                        )

                    mergedDf = scraper.mergeResults(resultsBySource)
                    st.session_state.trainingResults = mergedDf

                    rowCount = len(mergedDf) if not mergedDf.empty else 0
                    if rowCount > 0:
                        st.success(f'Collected {rowCount:,} listings from career pages.')
                    else:
                        st.warning('No listings found. Check company selections. Workday sites may return limited data without JS rendering.')
                finally:
                    scraperLogger.removeHandler(logHandler)

        # Export controls (enabled after a training scrape has been run)
        if st.session_state.trainingResults is not None and not st.session_state.trainingResults.empty:
            trainingDf = st.session_state.trainingResults.copy()

            # Build the labeling template: select relevant columns + add empty Vlvl and Notes
            availableTemplateCols = [c for c in _labelingColumns if c in trainingDf.columns]
            templateDf = trainingDf[availableTemplateCols].copy()
            templateDf['Vlvl'] = ''
            templateDf['Notes'] = ''

            st.markdown(f'**Preview -- {len(templateDf):,} listings ready for labeling:**')
            st.dataframe(
                templateDf[['Company', 'Listing', 'Seniority', 'Discipline', 'Min', 'Max', 'Vlvl']],
                width='stretch',
                height=300,
            )

            # Build Excel with two sheets: Listings + Instructions
            from datetime import date as _date
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                templateDf.to_excel(writer, index=False, sheet_name='Listings')
                instructionsDf = pd.DataFrame({'Instructions': _labelingInstructions.strip().split('\n')})
                instructionsDf.to_excel(writer, index=False, sheet_name='Instructions')
            buffer.seek(0)

            fileName = f'training_scrape_{_date.today().strftime("%Y%m%d")}.xlsx'
            st.download_button(
                f'Download Labeling Template ({fileName})',
                data=buffer,
                file_name=fileName,
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                type='primary',
                width='stretch',
            )
        elif st.session_state.trainingResults is not None:
            st.info('No listings collected. Try running the scrape again with different companies.')

    # ---- Tab 2: Import Labeled Data ---- #
    with trainingTab2:
        st.subheader('Import Labeled Data')
        st.markdown(
            'Upload a completed labeling template (Excel) with **Vlvl** values filled in. '
            'The labeled data will be stored in session state and made available to the '
            '**NN Classifier** tab for retraining.'
        )

        uploadedFile = st.file_uploader(
            'Upload labeled Excel file',
            type=['xlsx'],
            key='labeledDataUpload',
            help='Must be a training_scrape_*.xlsx file with a Vlvl column filled in (1-5).',
        )

        if uploadedFile is not None:
            try:
                importedDf = pd.read_excel(uploadedFile, sheet_name='Listings')

                # Validate required columns
                requiredCols = {'Listing', 'Vlvl'}
                missingCols = requiredCols - set(importedDf.columns)
                if missingCols:
                    st.error(f'Missing required columns: {", ".join(sorted(missingCols))}')
                else:
                    # Drop rows with no Vlvl
                    importedDf['Vlvl'] = pd.to_numeric(importedDf['Vlvl'], errors='coerce')
                    labeledRows = importedDf.dropna(subset=['Vlvl'])
                    unlabeledCount = len(importedDf) - len(labeledRows)

                    st.markdown(f'**File preview -- {len(labeledRows):,} labeled rows ({unlabeledCount} unlabeled, excluded):**')
                    st.dataframe(
                        labeledRows[['Company', 'Listing', 'Seniority', 'Discipline', 'Min', 'Max', 'Vlvl']].head(50),
                        width='stretch',
                        height=300,
                    )

                    # Level distribution
                    vlvlCounts = labeledRows['Vlvl'].value_counts().sort_index()
                    levelMetrics = st.columns(5)
                    for i, lvl in enumerate([1, 2, 3, 4, 5]):
                        with levelMetrics[i]:
                            count = int(vlvlCounts.get(lvl, 0))
                            st.metric(f'Level {lvl}', count)

                    if st.button('Import as Training Data', type='primary', width='stretch'):
                        st.session_state.labeledTrainingData = labeledRows
                        st.success(
                            f'Imported {len(labeledRows):,} labeled listings into session state as `labeledTrainingData`. '
                            'Go to the **NN Classifier** tab to retrain the model with this data.'
                        )
            except Exception as e:
                st.error(f'Failed to read file: {e}')

        # Show current state if labeled data is already loaded
        if st.session_state.labeledTrainingData is not None:
            existing = st.session_state.labeledTrainingData
            st.info(
                f'**Currently loaded:** {len(existing):,} labeled listings in session state. '
                'Go to the NN Classifier tab to use this data for retraining.'
            )


# ---------------------------------------------------------------------- #
# -- Key Status Banner -- #
# ---------------------------------------------------------------------- #

def _renderKeyStatusBanner(blsKey: str, fredKey: str) -> None:
    '''
    Display a compact API key status banner.

    Validation runs once per Streamlit session and is cached in session state
    so it does not block the page on every rerender. The banner shows a colored
    tag per key (FRED, BLS). If any required key is missing or invalid,
    a warning is shown with instructions to contact the site admin.

    Parameters:
    -----------
    blsKey : str
        BLS API key (may be empty)
    fredKey : str
        FRED API key (may be empty)
    '''
    import traceback as _tb

    # Run validation once per session. Re-validate if keys have changed since last check.
    _keyHash = hash((blsKey, fredKey))
    if (
        'scraperKeyValidation' not in st.session_state
        or st.session_state.get('scraperKeyHash') != _keyHash
    ):
        try:
            valResults = validateApiKeys(
                blsApiKey=blsKey,
                fredApiKey=fredKey,
            )
            st.session_state.scraperKeyValidation = valResults
            st.session_state.scraperKeyValidationError = None
        except Exception as e:
            st.session_state.scraperKeyValidation = {}
            st.session_state.scraperKeyValidationError = _tb.format_exc()
        st.session_state.scraperKeyHash = _keyHash

    valResults = st.session_state.get('scraperKeyValidation', {})
    validationError = st.session_state.get('scraperKeyValidationError')

    # -- Build status tag HTML -- #
    def _tag(label: str, ok) -> str:
        '''Return an inline HTML badge for a key status.'''
        if ok is True:
            bg, fg, icon = '#1a3a1a', '#86C06C', '&#10003;'
        elif ok is False:
            bg, fg, icon = '#3a1a1a', '#ff6b6b', '&#10007;'
        else:
            bg, fg, icon = '#2a2a1a', '#cccc66', '&#8212;'
        return (
            f'<span style="background:{bg}; color:{fg}; border-radius:4px; '
            f'padding:2px 8px; margin-right:6px; font-size:0.85em; '
            f'font-family:monospace; white-space:nowrap;">'
            f'{icon} {label}</span>'
        )

    fredResult = valResults.get('fred', {})
    blsResult  = valResults.get('bls', {})

    tagsHtml = (
        _tag('FRED', fredResult.get('ok'))
        + _tag('BLS', blsResult.get('ok'))
    )

    st.markdown(
        f'<div style="margin-bottom:4px;">API Keys: {tagsHtml}</div>',
        unsafe_allow_html=True,
    )

    # -- Errors and warnings -- #
    # Collect any failed keys (ok=False) and surface them as a collapsible warning.
    failedKeys = [
        (label, result)
        for label, result in [('FRED', fredResult), ('BLS', blsResult)]
        if result.get('ok') is False
    ]

    if validationError:
        # Unexpected exception during validation itself
        with st.expander('API key validation failed -- contact your site admin', expanded=True):
            st.warning(
                'An error occurred while validating API keys. '
                'The scraper may not function correctly. '
                'Please contact your site administrator and share the details below.'
            )
            st.code(validationError, language='text')

    elif failedKeys:
        with st.expander(f'{len(failedKeys)} API key issue(s) -- contact your site admin', expanded=False):
            st.warning(
                'One or more API keys could not be validated. Some data sources may be unavailable. '
                'Contact your site administrator if this is unexpected.'
            )
            for label, result in failedKeys:
                st.error(f'**{label}:** {result.get("message", "Unknown error")}')


# ---------------------------------------------------------------------- #
# -- Data Scraper Page -- #
# ---------------------------------------------------------------------- #

def renderDataScraper():
    
    '''

    Render the data scraper page with source selection,
    progress tracking, and result visualization.

    '''

    st.title('Data Scraper')

    # -- Tool Overview -- #
    with st.expander('About This Tool', expanded=False):
        st.markdown(
            'The **Aerospace Compensation Scraper** collects salary and job listing data '
            'from up to 12 public sources to support market compensation analysis. Sources '
            'are organized into three tiers:\n\n'
            '- **Tier 1 -- Government & Direct:** BLS OEWS, FRED CPI, H-1B disclosures, '
            'and direct career page scraping from 16 target company websites (Greenhouse, '
            'Workday, and other ATS platforms)\n'
            '- **Tier 2 -- Job Boards:** Indeed, Glassdoor, ZipRecruiter, LinkedIn (where '
            'accessible)\n'
            '- **Tier 3 -- Aggregators:** Levels.fyi, Payscale, Salary.com, Comparably\n\n'
            '**Using collected data:**\n\n'
            '- Export raw results as CSV or Excel from the Results Table tab\n'
            '- Merge scraped data with the synthetic compensation survey in '
            'the Merge & Export tab\n'
            '- Review and correct flagged records (missing salary, ambiguous locations) '
            'in the Review & Correct tab before exporting\n'
            '- Scraped and merged datasets are available to the Market Comparison and '
            'Explorer pages via the dataset selector'
        )

    # -- Warnings & Limitations -- #
    st.warning(
        '**Known Limitations:**  \n'
        'Glassdoor and ZipRecruiter are scraped via JobSpy; results depend on their availability.  \n'
        'Career page salary data varies by company -- many do not post salary bands.  \n'
        'Salary figures from aggregator sites are crowd-sourced estimates, not verified '
        'offers.  \n'
        'Location data may be imprecise for remote or multi-state postings.  \n'
        'Data freshness depends on the cache policy setting below.'
    )

    st.markdown('---')

    # -- Initialize session state -- #
    if 'scraperResults' not in st.session_state:
        st.session_state.scraperResults = None
    if 'scraperMerged' not in st.session_state:
        st.session_state.scraperMerged = None
    if 'scraperErrors' not in st.session_state:
        st.session_state.scraperErrors = {}
    if 'scraperWarnings' not in st.session_state:
        st.session_state.scraperWarnings = []
    if 'scraperWarningSummary' not in st.session_state:
        st.session_state.scraperWarningSummary = ''
    if 'trainingResults' not in st.session_state:
        st.session_state.trainingResults = None
    if 'labeledTrainingData' not in st.session_state:
        st.session_state.labeledTrainingData = None

    # -- Mode Toggle -- #
    # Two distinct workflows share the same underlying scraper backend but differ
    # in data sources used, output format, and how the data is consumed downstream.
    st.markdown('#### Scraper Mode')
    scraperMode = st.radio(
        'Mode',
        options=['Market Data Collection', 'NN Training Data'],
        horizontal=True,
        key='scraperMode',
        label_visibility='collapsed',
        help=(
            '**Market Data Collection** -- Scrape all 12 sources and export results for human '
            'market analysis and comparison. Feed into the Market Comparison and Job Listings '
            'Explorer pages.\n\n'
            '**NN Training Data** -- Scrape career pages only (individual job listings, not salary '
            'aggregates) and export a labeled template for manual Vlvl annotation. Import labeled '
            'data back to retrain the neural network classifier.'
        ),
    )

    # Route to appropriate workflow
    if scraperMode == 'NN Training Data':
        _renderNnTrainingMode()
        return

    # -- Below this line: Market Data Collection mode (original behavior) -- #
    st.markdown('---')

    # -- Load API Keys & Show Status Banner -- #
    # Keys are loaded automatically from documentation/APIKeys.md or tools/apiKeys.json.
    # Validation runs once per session and is cached in session state.
    _apiKeys = loadApiKeys()
    blsKey   = _apiKeys.get('blsApiKey', '')
    fredKey  = _apiKeys.get('fredApiKey', '')

    _renderKeyStatusBanner(blsKey, fredKey)

    st.markdown('')

    # -- Source & Company Selection -- #
    sourceMeta = CompensationScraper.availableSources

    sourceCol, companyCol, cacheCol = st.columns(3)

    with sourceCol:
        sourceOptions = list(sourceMeta.keys())
        sourceLabels = [
            f'{sourceMeta[k]["name"]} (Tier {sourceMeta[k]["tier"]})'
            for k in sourceOptions
        ]
        # Build display -> key mapping
        labelToKey = dict(zip(sourceLabels, sourceOptions))

        # Sources excluded from default selection due to consistent failures.
        # All remain available for manual selection.
        #   h1b          — redirect-loop errors on most requests
        #   comparably   — consistent HTTP 403 (bot detection)
        #   salaryCom    — consistent HTTP 403/500 (bot detection)
        #   glassdoor    — JobSpy import/runtime issues; returns 0 rows
        #   ziprecruiter — same as glassdoor
        _excludedByDefault = {'h1b', 'comparably', 'salaryCom', 'glassdoor', 'ziprecruiter'}
        defaultLabels = [
            lbl for lbl in sourceLabels
            if labelToKey[lbl] not in _excludedByDefault
        ]

        selectedLabels = st.multiselect(
            'Data Sources',
            sourceLabels,
            default=defaultLabels,
            key='scraperSources',
        )
        selectedSources = [labelToKey[label] for label in selectedLabels]

    with companyCol:
        # Company list is parsed from compensationReferences.md via referenceParser
        selectedCompanies = st.multiselect(
            'Target Companies',
            defaultTargetCompanies,
            default=defaultTargetCompanies,
            key='scraperCompanies',
        )

    with cacheCol:
        cachePolicy = st.selectbox(
            'Cache Policy',
            ['Use cache (1 week)', 'Force refresh'],
            key='scraperCachePolicy',
            help=(
                'Controls whether previously fetched data is reused. '
                '**Use cache** returns stored responses for up to 1 week, '
                'which speeds up repeated scrapes and avoids hitting API '
                'rate limits. **Force refresh** ignores cached data and '
                'fetches live results from every source, which takes longer '
                'and may be throttled by external APIs.'
            ),
        )

    st.markdown('')

    # -- Run Scrape Button -- #
    runScrape = st.button('Run Scrape', width='stretch', type='primary')

    if runScrape:
        if not selectedSources:
            st.warning('Please select at least one data source.')
            return

        progressBar = st.progress(0)
        statusText = st.empty()
        totalSources = len(selectedSources)

        def progressCallback(step, total, message):
            '''Update Streamlit progress elements with step counts.'''
            pct = min(step / max(total, 1), 1.0)
            progressBar.progress(pct)
            # Show "Source 3 of 10 - Running BLS OEWS..." style text
            currentSource = int(step) + 1
            statusText.text(f'Source {currentSource} of {totalSources} -- {message}')

        # Attach a log handler to capture warnings during the scrape
        logHandler = _StreamlitLogHandler()
        scraperLogger = logging.getLogger('compensationScraper')
        scraperLogger.addHandler(logHandler)

        try:
            # Build config
            cacheTtl = 168 if 'Use cache' in cachePolicy else 0
            config = ScraperConfig(
                blsApiKey=blsKey,
                fredApiKey=fredKey,
                cacheTtlHours=cacheTtl,
                targetCompanies=selectedCompanies,
            )

            scraper = CompensationScraper(config)

            # Run scrape
            resultsBySource = scraper.scrapeAll(
                sources=selectedSources,
                progressCallback=progressCallback,
            )

            # Apply engineering role filter to career page results.
            # Career page boards (Greenhouse, Lever, etc.) return every open
            # position at a company — including non-engineering roles such as
            # baristas, HR coordinators, etc. Filter those out so they don't
            # pollute salary analysis. JobSpy sources (Glassdoor, ZipRecruiter,
            # Indeed) use role-specific search terms and don't need this pass.
            if resultsBySource.get('careerPages') is not None:
                resultsBySource['careerPages'] = filterEngineeringRoles(
                    resultsBySource['careerPages']
                )

            # Store results in session state
            st.session_state.scraperResults = resultsBySource
            st.session_state.scraperErrors = scraper.lastErrors()
            st.session_state.scraperWarnings = logHandler.records
            st.session_state.scraperWarningSummary = logHandler.summarize()
            st.session_state.scraperMerged = None  # Reset merge

            # Store combined scraped data in session state so other pages
            # (Market Comparison, Explorer, etc.) can access it via the
            # dataset selector without re-running the scrape
            allScrapedForState = scraper.mergeResults(resultsBySource)
            if not allScrapedForState.empty:
                st.session_state.scrapedDataset = allScrapedForState

            progressBar.progress(1.0)
            statusText.text(f'Scrape complete -- {totalSources} of {totalSources} sources finished.')
        finally:
            # Always detach the handler to avoid duplicates on re-run
            scraperLogger.removeHandler(logHandler)

    # -- Display Results -- #
    if st.session_state.scraperResults is not None:
        resultsBySource = st.session_state.scraperResults
        errors = st.session_state.scraperErrors

        st.markdown('---')

        # -- Summary Metrics -- #
        totalRows = sum(
            len(df) for df in resultsBySource.values()
            if df is not None and not df.empty
        )
        sourcesCompleted = sum(
            1 for df in resultsBySource.values()
            if df is not None and not df.empty
        )
        sourcesExcepted = len(errors)
        warnings = st.session_state.get('scraperWarnings', [])
        warningCount = len(warnings)

        # Empty sources: returned a DataFrame but with 0 rows (no exception thrown)
        emptySources = []
        for sourceKey, df in resultsBySource.items():
            if df is None or df.empty:
                meta = CompensationScraper.availableSources.get(sourceKey, {})
                emptySources.append(meta.get('name', sourceKey))

        # "Sources Failed" = exceptions + empty returns, so the metric reflects
        # all sources that produced no usable data, regardless of failure mode.
        sourcesWithIssues = sourcesExcepted + len(emptySources)

        metricCols = st.columns(4)
        with metricCols[0]:
            st.metric('Total Records', f'{totalRows:,}')
        with metricCols[1]:
            st.metric('Sources Completed', f'{sourcesCompleted}')
        with metricCols[2]:
            st.metric('Sources Failed', f'{sourcesWithIssues}')
        with metricCols[3]:
            st.metric('Log Messages', f'{warningCount}')

        # Show exception-level errors first (source threw an exception)
        if errors:
            with st.expander('Errors', expanded=True):
                for sourceKey, errorMsg in errors.items():
                    sourceName = CompensationScraper.availableSources[sourceKey]['name']
                    st.error(f'**{sourceName}:** {errorMsg}')

        # Show sources that returned no rows as st.error (visible failure, not just a note)
        if emptySources:
            st.error(
                f'**{len(emptySources)} source(s) returned no data:** '
                + ', '.join(emptySources)
                + '. These sources may be blocking automated requests '
                'or have changed their URL structure.'
            )

        # Scrape log: quantitative summary of WARNING+ log messages captured during the scrape
        if warnings:
            warningSummary = st.session_state.get('scraperWarningSummary', '')
            with st.expander(f'Scrape Log ({warningCount} messages)', expanded=False):
                if warningSummary:
                    st.markdown(warningSummary)
                # Raw log messages available in a collapsed sub-section
                with st.expander('Raw log messages', expanded=False):
                    st.code('\n'.join(warnings), language='text')

        st.markdown('---')

        # -- Tabs for Results -- #
        tab1, tab2, tab3, tab4 = st.tabs([
            'Results Table', 'By Source', 'Merge & Export', 'Review & Correct',
        ])

        # ---- Tab 1: Results Table ---- #
        with tab1:
            if totalRows > 0:
                # Merge all source results for display
                scraper = CompensationScraper()
                allScraped = scraper.mergeResults(resultsBySource)

                displayCols = [
                    'DataSource', 'Company', 'Listing', 'Seniority',
                    'Discipline', 'Min', 'Max', 'Midpoint', 'Location', 'State',
                    'Link',
                ]
                availableCols = [c for c in displayCols if c in allScraped.columns]

                linkColConfig = {
                    'Link': st.column_config.LinkColumn(
                        'Source URL', display_text='View Source',
                    ),
                }

                st.dataframe(
                    allScraped[availableCols].reset_index(drop=True),
                    column_config=linkColConfig,
                    width='stretch',
                    height=400,
                )

                # Download button
                csvData = allScraped[availableCols].to_csv(index=False)
                st.download_button(
                    'Download CSV',
                    data=csvData,
                    file_name='scraped_compensation_data.csv',
                    mime='text/csv',
                )

                # -- Charts -- #
                if 'Midpoint' in allScraped.columns:
                    validData = allScraped[
                        pd.to_numeric(allScraped['Midpoint'], errors='coerce') > 0
                    ].copy()

                    if not validData.empty:
                        chartCol1, chartCol2 = st.columns(2)

                        with chartCol1:
                            st.subheader('Salary Distribution by Source')
                            figHist = px.histogram(
                                validData,
                                x='Midpoint',
                                nbins=25,
                                color='DataSource',
                                title='Salary Distribution by Data Source',
                                labels={'Midpoint': 'Salary ($)'},
                            )
                            figHist.update_layout(
                                height=400, barmode='stack', **plotlyDarkLayout
                            )
                            st.plotly_chart(figHist, width='stretch')

                        with chartCol2:
                            st.subheader('Salary by Company')
                            # Only show companies with data
                            companyData = validData[
                                validData['Company'].notna() &
                                (validData['Company'] != 'Unknown')
                            ]
                            if not companyData.empty:
                                figBox = px.box(
                                    companyData,
                                    x='Company',
                                    y='Midpoint',
                                    title='Salary Distribution by Company',
                                    labels={'Midpoint': 'Salary ($)'},
                                )
                                figBox.update_layout(
                                    height=400,
                                    xaxis_tickangle=-45,
                                    **plotlyDarkLayout,
                                )
                                st.plotly_chart(figBox, width='stretch')
            else:
                st.info('No data collected. Try adjusting sources or check error messages.')

        # ---- Tab 2: By Source ---- #
        with tab2:
            for sourceKey, df in resultsBySource.items():
                sourceName = CompensationScraper.availableSources[sourceKey]['name']
                rowCount = len(df) if df is not None and not df.empty else 0

                with st.expander(f'{sourceName} ({rowCount} records)', expanded=False):
                    if df is not None and not df.empty:
                        displayCols = [
                            'Company', 'Listing', 'Seniority', 'Min', 'Max',
                            'Location', 'State', 'Discipline',
                        ]
                        availableCols = [c for c in displayCols if c in df.columns]
                        st.dataframe(
                            df[availableCols].reset_index(drop=True),
                            width='stretch',
                            height=300,
                        )
                    elif sourceKey in errors:
                        st.error(f'Failed: {errors[sourceKey]}')
                    else:
                        st.info('No data returned from this source.')

        # ---- Tab 3: Merge & Export ---- #
        with tab3:
            st.subheader('Merge with Existing Survey Data')
            st.markdown(
                'Combine scraped data with the synthetic compensation survey '
                'dataset. Duplicates are removed '
                'based on Company, Listing, and Location.'
            )

            if st.button('Merge Data', width='stretch'):
                scraper = CompensationScraper()
                allScraped = scraper.mergeResults(resultsBySource)

                existingDf = _loadExistingSurvey()
                merged = mergeScrapedData(existingDf, allScraped)
                st.session_state.scraperMerged = merged
                # Store merged dataset for cross-page access via dataset selector
                st.session_state.mergedDataset = merged

            if st.session_state.scraperMerged is not None:
                merged = st.session_state.scraperMerged

                # Show merge summary
                existingCount = len(_loadExistingSurvey())
                scrapedCount = totalRows
                mergedCount = len(merged)
                deduped = existingCount + scrapedCount - mergedCount

                mergeCols = st.columns(4)
                with mergeCols[0]:
                    st.metric('Existing Records', f'{existingCount:,}')
                with mergeCols[1]:
                    st.metric('Scraped Records', f'{scrapedCount:,}')
                with mergeCols[2]:
                    st.metric('Merged Total', f'{mergedCount:,}')
                with mergeCols[3]:
                    st.metric('Duplicates Removed', f'{deduped:,}')

                # Preview table
                displayCols = [
                    'DataSource', 'Company', 'Listing', 'Seniority',
                    'Min', 'Max', 'Midpoint', 'Location', 'State',
                ]
                availableCols = [c for c in displayCols if c in merged.columns]
                st.dataframe(
                    merged[availableCols].reset_index(drop=True),
                    width='stretch',
                    height=400,
                )

                # Export buttons
                exportCol1, exportCol2 = st.columns(2)
                with exportCol1:
                    csvData = merged[availableCols].to_csv(index=False)
                    st.download_button(
                        'Download Merged CSV',
                        data=csvData,
                        file_name='merged_compensation_data.csv',
                        mime='text/csv',
                    )
                with exportCol2:
                    # Excel export via in-memory buffer
                    buffer = io.BytesIO()
                    merged[availableCols].to_excel(buffer, index=False, sheet_name='Merged Data')
                    buffer.seek(0)
                    st.download_button(
                        'Download Merged Excel',
                        data=buffer,
                        file_name='merged_compensation_data.xlsx',
                        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    )

        # ---- Tab 4: Review & Correct ---- #
        with tab4:
            st.subheader('Review & Correct')
            st.markdown(
                'Rows that may require manual review are flagged below. '
                'Edit values inline, then click **Apply Changes** to update '
                'the dataset used by other pages. Flags are assigned automatically '
                'based on missing salary data, wide salary ranges, ambiguous '
                'locations, and multi-state postings.'
            )

            if totalRows > 0:
                # Build the flagged dataset
                scraper = CompensationScraper()
                reviewDf = scraper.mergeResults(resultsBySource)
                reviewDf = _flagSuspectRows(reviewDf)

                # -- Filter Controls -- #
                filterCol1, filterCol2, filterCol3 = st.columns(3)

                # Collect all unique flags
                allFlagValues = set()
                for flagStr in reviewDf['_reviewFlag']:
                    if flagStr:
                        for f in flagStr.split(', '):
                            allFlagValues.add(f)
                allFlagValues = sorted(allFlagValues) if allFlagValues else []

                with filterCol1:
                    selectedFlags = st.multiselect(
                        'Filter by Flag',
                        options=allFlagValues,
                        default=allFlagValues,
                        key='reviewFlagFilter',
                        help='Show only rows with these flags. Clear to show all rows.',
                    )

                with filterCol2:
                    availableSources = sorted(
                        reviewDf['DataSource'].dropna().unique().tolist()
                    ) if 'DataSource' in reviewDf.columns else []
                    selectedReviewSources = st.multiselect(
                        'Filter by Source',
                        options=availableSources,
                        default=availableSources,
                        key='reviewSourceFilter',
                    )

                with filterCol3:
                    availableCompanies = sorted(
                        reviewDf['Company'].dropna().unique().tolist()
                    ) if 'Company' in reviewDf.columns else []
                    selectedReviewCompanies = st.multiselect(
                        'Filter by Company',
                        options=availableCompanies,
                        default=availableCompanies,
                        key='reviewCompanyFilter',
                    )

                # Apply filters
                filteredDf = reviewDf.copy()

                # Flag filter: show rows matching ANY selected flag, or all rows if no flags selected
                if selectedFlags:
                    flagMask = filteredDf['_reviewFlag'].apply(
                        lambda x: any(f in str(x) for f in selectedFlags) if x else False
                    )
                    filteredDf = filteredDf[flagMask]

                if selectedReviewSources and 'DataSource' in filteredDf.columns:
                    filteredDf = filteredDf[filteredDf['DataSource'].isin(selectedReviewSources)]

                if selectedReviewCompanies and 'Company' in filteredDf.columns:
                    filteredDf = filteredDf[filteredDf['Company'].isin(selectedReviewCompanies)]

                # -- Flag Metrics -- #
                totalFlagged = (reviewDf['_reviewFlag'] != '').sum()
                missingSalary = reviewDf['_reviewFlag'].str.contains('Missing Salary', na=False).sum()
                wideRange = reviewDf['_reviewFlag'].str.contains('Wide Range', na=False).sum()
                ambiguousLoc = reviewDf['_reviewFlag'].str.contains('Ambiguous Location', na=False).sum()
                multiState = reviewDf['_reviewFlag'].str.contains('Multi-State', na=False).sum()

                flagCols = st.columns(5)
                with flagCols[0]:
                    st.metric('Total Flagged', f'{totalFlagged:,}')
                with flagCols[1]:
                    st.metric('Missing Salary', f'{missingSalary:,}')
                with flagCols[2]:
                    st.metric('Wide Range', f'{wideRange:,}')
                with flagCols[3]:
                    st.metric('Ambiguous Location', f'{ambiguousLoc:,}')
                with flagCols[4]:
                    st.metric('Multi-State', f'{multiState:,}')

                # -- Editable Table -- #
                editCols = [
                    '_reviewFlag', 'DataSource', 'Company', 'Listing',
                    'Seniority', 'Discipline', 'Min', 'Max',
                    'Location', 'State', 'Link',
                ]
                availableEditCols = [c for c in editCols if c in filteredDf.columns]
                editableDf = filteredDf[availableEditCols].reset_index(drop=True)

                # Column configuration for st.data_editor
                columnConfig = {
                    '_reviewFlag': st.column_config.TextColumn(
                        'Flag', disabled=True, help='Auto-assigned review flags',
                    ),
                    'DataSource': st.column_config.TextColumn(
                        'Source', disabled=True,
                    ),
                    'Company': st.column_config.TextColumn(
                        'Company', disabled=True,
                    ),
                    'Listing': st.column_config.TextColumn('Listing'),
                    'Seniority': st.column_config.TextColumn('Seniority'),
                    'Discipline': st.column_config.TextColumn('Discipline'),
                    'Min': st.column_config.NumberColumn(
                        'Min', format='$%d', min_value=0,
                    ),
                    'Max': st.column_config.NumberColumn(
                        'Max', format='$%d', min_value=0,
                    ),
                    'Location': st.column_config.TextColumn('Location'),
                    'State': st.column_config.TextColumn('State'),
                    'Link': st.column_config.LinkColumn(
                        'Source URL', display_text='View Source', disabled=True,
                    ),
                }

                editedDf = st.data_editor(
                    editableDf,
                    column_config=columnConfig,
                    width='stretch',
                    height=500,
                    num_rows='fixed',
                    key='reviewEditor',
                )

                st.markdown('')

                # -- Action Buttons -- #
                actionCol1, actionCol2, actionCol3 = st.columns(3)

                with actionCol1:
                    if st.button('Apply Changes', width='stretch', type='primary'):
                        # Rebuild full dataset with edits applied
                        fullReview = scraper.mergeResults(resultsBySource)
                        fullReview = _flagSuspectRows(fullReview)

                        # Apply edits from the editor back to the full dataset
                        # The editor only shows filtered rows, so map edits back
                        # by matching the filtered index positions
                        filteredIndices = filteredDf.index.tolist()
                        for editCol in availableEditCols:
                            if editCol in ('_reviewFlag', 'DataSource', 'Company'):
                                continue  # Read-only columns
                            for localIdx, globalIdx in enumerate(filteredIndices):
                                if localIdx < len(editedDf):
                                    fullReview.at[globalIdx, editCol] = editedDf.iloc[localIdx][editCol]

                        # Recalculate Midpoint after edits
                        minCol = pd.to_numeric(fullReview.get('Min'), errors='coerce')
                        maxCol = pd.to_numeric(fullReview.get('Max'), errors='coerce')
                        fullReview['Midpoint'] = ((minCol + maxCol) / 2).round(0)

                        # Re-flag after edits
                        fullReview = _flagSuspectRows(fullReview)

                        # Update session state so other pages see corrected data
                        st.session_state.reviewedData = fullReview
                        st.session_state.scrapedDataset = fullReview.drop(
                            columns=['_reviewFlag'], errors='ignore',
                        )
                        st.success('Changes applied. Updated dataset is now available across pages.')
                        st.rerun()

                with actionCol2:
                    # Use reviewed data if available, otherwise use current editor state
                    exportDf = st.session_state.get('reviewedData', editedDf)
                    exportCols = [c for c in availableEditCols if c != '_reviewFlag']
                    csvReview = exportDf[exportCols].to_csv(index=False) if not exportDf.empty else ''
                    st.download_button(
                        'Download Reviewed CSV',
                        data=csvReview,
                        file_name='reviewed_compensation_data.csv',
                        mime='text/csv',
                        disabled=exportDf.empty,
                    )

                with actionCol3:
                    exportDf = st.session_state.get('reviewedData', editedDf)
                    exportCols = [c for c in availableEditCols if c != '_reviewFlag']
                    if not exportDf.empty:
                        xlBuffer = io.BytesIO()
                        exportDf[exportCols].to_excel(
                            xlBuffer, index=False, sheet_name='Reviewed Data',
                        )
                        xlBuffer.seek(0)
                        st.download_button(
                            'Download Reviewed Excel',
                            data=xlBuffer,
                            file_name='reviewed_compensation_data.xlsx',
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        )
                    else:
                        st.download_button(
                            'Download Reviewed Excel',
                            data=b'',
                            file_name='reviewed_compensation_data.xlsx',
                            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            disabled=True,
                        )

            else:
                st.info('No data to review. Run a scrape first.')

# ---------------------------------------------------------------------- #
# -- Module-Level Execution -- #
# ---------------------------------------------------------------------- #

@st.cache_data
def _loadExistingSurvey():

    '''
    
    Load and cache the existing market survey data.
    
    '''

    return loadMarketSurveyData()

# Run as standalone page; skipped when imported as a module by marketTools.py
if __name__ != 'dataScraper':
    renderDataScraper()
