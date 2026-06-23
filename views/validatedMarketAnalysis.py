
# -- Validated Market Analysis Page -- #

'''

Streamlit page for career-page-only compensation analysis. Provides
geographic normalization, semantic role mapping to the engineering
levels, company-weighted averaging, band recalculation, timestamped
deduplication, and trend analytics.

Addresses all 8 feature requests from objectives.md.

Author: Sean Bowman
Date:   03/01/2026

'''

# Standard library imports
import io
import os
import sys
import logging

# Third-party imports
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

# Ensure tools directory is importable
_viewsDir = os.path.dirname(os.path.abspath(__file__))
_appDir = os.path.dirname(_viewsDir)
_toolsDir = os.path.join(_appDir, 'tools')
if _toolsDir not in sys.path:
    sys.path.insert(0, _toolsDir)

# Local imports
from auditUtils import (
    colors, plotlyDarkLayout, salaryBands, geographicAdjustments,
    surveyColumns, loadMarketSurveyData, levelForExperience,
)
from compensationScraper import CompensationScraper, ScraperConfig
from careerPageScraper import CareerPageScraper
from referenceParser import loadReferenceData
from validatedAnalysis import (
    extractYearsOfExperience, assignBuckets,
    computeGeoFactors, applyGeoNormalization,
    companyWeightedAverage, recalculateSalaryBands,
    addCollectionTimestamps, deduplicateWithTimestamps,
    saveValidatedSnapshot, loadValidatedHistory, loadSnapshotData,
    computeTrendAnalytics, compareReferenceToScraped,
    validatedCacheDir, filterEngineeringRoles,
    _checkBucketMonotonicity, applyMarketPositionAdjustment,
)


# ---------------------------------------------------------------------- #
# -- Helpers -- #
# ---------------------------------------------------------------------- #

def _bestAvailableData(*candidates):
    '''Return the first non-None, non-empty DataFrame from candidates.'''
    for df in candidates:
        if df is not None and not df.empty:
            return df
    return None


# ---------------------------------------------------------------------- #
# -- Page Renderer -- #
# ---------------------------------------------------------------------- #

def renderValidatedMarketAnalysis():

    '''

    Render the Validated Market Analysis page with 6 tabs covering
    all features from objective.md.

    '''

    st.title('Validated Market Analysis')
    st.markdown(
        'Career-page-only compensation data pipeline with geographic normalization, '
        'semantic role mapping, and trend analytics. All data comes directly from '
        'company career websites for 100% confirmed validity.'
    )

    # -- About Expander -- #
    with st.expander('About This Tool', expanded=False):
        st.markdown(
            '**Features:**\n\n'
            '1. **Career Page Only** -- data sourced exclusively from company career sites (26 companies)\n'
            '2. **Geographic Normalization** -- salary conversion to the HQ-location baseline, validated by multi-location postings\n'
            '3. **Company-Weighted Averaging** -- equal weight per company regardless of listing count\n'
            '4. **Semantic Role Mapping** -- auto-classify listings into Level I-V buckets with management detection\n'
            '5. **YoE as Primary Metric** -- years of experience drives level assignment (50% weight)\n'
            '6. **Band Recalculation** -- propose updated salary bands from market data (overlap allowed, $1k rounding)\n'
            '7. **Timestamps & Dedup** -- collection timestamps prevent duplicates across scrapes\n'
            '8. **Trend Analytics** -- moving averages and reference vs scraped comparison'
        )

    st.markdown('---')

    # -- Initialize Session State -- #
    _initSessionState()

    # -- Tabs -- #
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        'Data Collection',
        'Geographic Normalization',
        'Role Mapping',
        'Market Analysis',
        'Band Recalculation',
        'Trends & Analytics',
    ])

    with tab1:
        _renderDataCollection()

    with tab2:
        _renderGeoNormalization()

    with tab3:
        _renderRoleMapping()

    with tab4:
        _renderMarketAnalysis()

    with tab5:
        _renderBandRecalculation()

    with tab6:
        _renderTrendAnalytics()


# ---------------------------------------------------------------------- #
# -- Session State Initialization -- #
# ---------------------------------------------------------------------- #

def _initSessionState():

    '''

    Initialize all session state keys used by this page.

    '''

    defaults = {
        'vma_careerData': None,
        'vma_validatedData': None,
        'vma_reviewedData': None,
        'vma_geoFactors': None,
        'vma_geoValidation': None,
        'vma_companyAverages': None,
        'vma_proposedBands': None,
        'vma_bandComparison': None,
        'vma_lastScrapeTimestamp': None,
        'vma_monoWarnings': [],
    }

    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default


# ---------------------------------------------------------------------- #
# -- Tab 1: Data Collection (Features 1, 7) -- #
# ---------------------------------------------------------------------- #

def _renderDataCollection():

    '''

    Career-page-only scraping with timestamps, dedup, and cache control.
    Supports both live scrape and loading an existing dataset.

    '''

    st.subheader('Career Page Data Collection')

    # -- Data Source Selector -- #
    # Allows loading a previously collected dataset instead of triggering a live scrape.
    # This is useful for re-running the analysis pipeline on cached or previously exported data.
    dataSource = st.radio(
        'Data source',
        options=['Run live scrape', 'Load saved dataset'],
        horizontal=True,
        key='vma_dataSource',
        help=(
            '**Run live scrape** -- Fetch fresh job listings from company career pages.\n\n'
            '**Load saved dataset** -- Load a previously exported CSV/Excel file or use the '
            'dataset already collected in the Scraper tab. No network requests are made.'
        ),
    )

    st.markdown('---')

    if dataSource == 'Load saved dataset':
        _renderLoadExistingDataset()
        # Fall through to display results if data was loaded
        _renderDataCollectionResults()
        return

    st.markdown(
        'Scrape job listings directly from aerospace company career websites. '
        'Only data from verified career pages is used -- no aggregator or '
        'crowd-sourced estimates.'
    )

    # Load career page configs
    refData = loadReferenceData()
    careerPages = refData.get('careerPages', [])
    allCompanies = [p['company'] for p in careerPages]

    # -- Controls -- #
    controlCol1, controlCol2, controlCol3 = st.columns([2, 1, 1])

    with controlCol1:
        selectedCompanies = st.multiselect(
            'Target Companies',
            allCompanies,
            default=allCompanies,
            key='vma_companies',
        )

    with controlCol2:
        cachePolicy = st.selectbox(
            'Cache Policy',
            ['Use existing cache', 'Refresh older than 24h', 'Refresh older than 7d', 'Force refresh all'],
            key='vma_cachePolicy',
            help=(
                'Controls when cached career page data is refreshed. '
                'Older cache data is reused to avoid redundant requests.'
            ),
        )

    with controlCol3:
        engineeringOnly = st.checkbox(
            'Engineering roles only',
            value=True,
            key='vma_engineeringOnly',
            help=(
                'Filter results to engineering-related roles only. '
                'Removes accounting, HR, finance, legal, and other '
                'non-technical listings from the results.'
            ),
        )

    st.markdown('')

    # Map cache policy to TTL hours
    cacheTtlMap = {
        'Use existing cache': 168,
        'Refresh older than 24h': 24,
        'Refresh older than 7d': 168,
        'Force refresh all': 0,
    }
    cacheTtl = cacheTtlMap.get(cachePolicy, 168)

    # -- Scrape Button -- #
    runScrape = st.button('Scrape Career Pages', width='stretch', type='primary')

    if runScrape:
        if not selectedCompanies:
            st.warning('Please select at least one company.')
            return

        progressBar = st.progress(0)
        statusText = st.empty()
        totalCompanies = len(selectedCompanies)

        def progressCallback(step, total, message):
            pct = min(step / max(total, 1), 1.0)
            progressBar.progress(pct)
            statusText.text(f'Company {int(step) + 1} of {totalCompanies} -- {message}')

        try:
            config = ScraperConfig(cacheTtlHours=cacheTtl)
            scraper = CompensationScraper(config)
            careerScraper = CareerPageScraper(scraper)

            # Run career-page-only scrape
            mergedDf = careerScraper.scrapeAllMerged(
                companies=selectedCompanies,
                progressCallback=progressCallback,
            )

            # Add timestamps and dedup against existing data
            mergedDf = addCollectionTimestamps(mergedDf)

            existingData = st.session_state.vma_careerData
            if existingData is not None and not existingData.empty:
                mergedDf = deduplicateWithTimestamps(mergedDf, existingData)

            # Apply engineering role filter if enabled
            totalBeforeFilter = len(mergedDf)
            if engineeringOnly:
                mergedDf = filterEngineeringRoles(mergedDf)
                filteredCount = totalBeforeFilter - len(mergedDf)
                if filteredCount > 0:
                    statusText.text(
                        f'Filtered {filteredCount:,} non-engineering listings '
                        f'({len(mergedDf):,} remaining).'
                    )

            st.session_state.vma_careerData = mergedDf
            st.session_state.vma_lastScrapeTimestamp = pd.Timestamp.now().isoformat()

            # Reset downstream state so user re-runs normalization/bucketing
            st.session_state.vma_validatedData = None
            st.session_state.vma_reviewedData = None
            st.session_state.vma_geoFactors = None
            st.session_state.vma_geoValidation = None
            st.session_state.vma_companyAverages = None
            st.session_state.vma_proposedBands = None

            progressBar.progress(1.0)
            statusText.text(f'Complete -- {totalCompanies} companies scraped.')

        except Exception as e:
            st.error(f'Scrape failed: {e}')

    _renderDataCollectionResults()


# ---------------------------------------------------------------------- #
# -- Data Collection Helpers -- #
# ---------------------------------------------------------------------- #

def _renderDataCollectionResults():
    '''Display collected career page data with metrics, table, and export controls.'''
    careerData = st.session_state.vma_careerData

    if careerData is not None and not careerData.empty:
        st.markdown('---')

        # Summary metrics
        withSalary = careerData[
            pd.to_numeric(careerData.get('Min'), errors='coerce').notna() |
            pd.to_numeric(careerData.get('Max'), errors='coerce').notna()
        ]

        metricCols = st.columns(4)
        with metricCols[0]:
            st.metric('Total Listings', f'{len(careerData):,}')
        with metricCols[1]:
            st.metric('With Salary Data', f'{len(withSalary):,}')
        with metricCols[2]:
            companiesFound = careerData['Company'].nunique() if 'Company' in careerData.columns else 0
            st.metric('Companies', f'{companiesFound}')
        with metricCols[3]:
            lastScrape = st.session_state.vma_lastScrapeTimestamp
            if lastScrape:
                st.metric('Last Collected', pd.Timestamp(lastScrape).strftime('%m/%d %H:%M'))

        # Data table
        displayCols = ['Company', 'Listing', 'Seniority', 'Min', 'Max', 'Location', 'State', 'CollectedAt']
        availableCols = [c for c in displayCols if c in careerData.columns]
        st.dataframe(
            careerData[availableCols].reset_index(drop=True),
            width='stretch',
            height=400,
        )

        # -- Snapshot Management -- #
        with st.expander('Snapshot Management', expanded=False):
            snapCol1, snapCol2 = st.columns(2)

            with snapCol1:
                if st.button('Save Current Data as Snapshot'):
                    filename = saveValidatedSnapshot(careerData)
                    st.success(f'Snapshot saved: {filename}')

            with snapCol2:
                history = loadValidatedHistory()
                if history:
                    st.caption(f'{len(history)} saved snapshot(s)')
                    for snap in history[:5]:
                        st.text(f'{snap["timestamp"][:16]} -- {snap["recordCount"]} records')
                else:
                    st.caption('No saved snapshots yet.')

        # Download
        csvData = careerData[availableCols].to_csv(index=False)
        st.download_button(
            'Download Career Page Data (CSV)',
            data=csvData,
            file_name='career_page_data.csv',
            mime='text/csv',
        )

    elif careerData is not None:
        st.info('No data collected. Try adjusting companies or check career page availability.')


def _renderLoadExistingDataset():
    '''
    Render controls for loading an existing dataset into the validated analysis pipeline
    instead of triggering a live career page scrape.

    Three load options are presented in priority order:
      1. Files in documentation/ matching training_scrape_*.xlsx
      2. Dataset already collected in the Scraper tab (st.session_state.scrapedDataset)
      3. Manual file upload (CSV or Excel)
    '''
    import glob

    st.markdown(
        'Load a previously collected dataset to skip the live scrape. '
        'The loaded data is fed directly into the analysis pipeline (Geographic Normalization, '
        'Role Mapping, Band Recalculation) in subsequent tabs.'
    )

    # -- Option 1: Saved training scrape files in documentation/ -- #
    _docDir = os.path.join(_appDir, 'documentation')
    savedFiles = sorted(
        glob.glob(os.path.join(_docDir, 'training_scrape_*.xlsx')),
        reverse=True,  # Most recent first
    )
    savedFileNames = [os.path.basename(f) for f in savedFiles]

    loadSource = st.radio(
        'Load from',
        options=[
            'Saved scrape file (documentation/)',
            'Current scraper session data',
            'Upload file',
        ],
        key='vma_loadSource',
        horizontal=False,
    )

    loadedDf = None

    if loadSource == 'Saved scrape file (documentation/)':
        if savedFileNames:
            selectedFile = st.selectbox(
                'Select file',
                savedFileNames,
                key='vma_savedFileSelect',
            )
            selectedPath = os.path.join(_docDir, selectedFile)
            st.caption(f'Path: `{selectedPath}`')

            if st.button('Load Selected File', type='primary', width='stretch'):
                try:
                    loadedDf = pd.read_excel(selectedPath)
                    st.success(f'Loaded {len(loadedDf):,} rows from `{selectedFile}`.')
                except Exception as e:
                    st.error(f'Failed to read file: {e}')
        else:
            st.info(
                'No saved scrape files found in `documentation/`. '
                'Run a scrape in Market Data Collection or NN Training Data mode first, '
                'then export the results to `documentation/`.'
            )

    elif loadSource == 'Current scraper session data':
        sessionDf = st.session_state.get('scrapedDataset')
        if sessionDf is not None and not sessionDf.empty:
            st.success(f'Session dataset available: {len(sessionDf):,} rows from the Scraper tab.')
            if st.button('Use Session Dataset', type='primary', width='stretch'):
                loadedDf = sessionDf.copy()
        else:
            st.info(
                'No dataset in current session. '
                'Go to **Market Tools → Scraper** and run a Market Data Collection scrape first.'
            )

    else:  # Upload file
        uploadedFile = st.file_uploader(
            'Upload CSV or Excel file',
            type=['csv', 'xlsx'],
            key='vma_datasetUpload',
            help='Must contain at minimum a Listing column and ideally Company, Min, Max, Seniority, Discipline.',
        )
        if uploadedFile is not None:
            try:
                if uploadedFile.name.endswith('.csv'):
                    loadedDf = pd.read_csv(uploadedFile)
                else:
                    loadedDf = pd.read_excel(uploadedFile)
                st.success(f'Loaded {len(loadedDf):,} rows from `{uploadedFile.name}`.')
            except Exception as e:
                st.error(f'Failed to read file: {e}')

    # -- Validate and store loaded data -- #
    if loadedDf is not None and not loadedDf.empty:
        # Check for key columns
        expectedCols = {'Company', 'Listing', 'Min', 'Max', 'Seniority', 'Discipline'}
        presentCols = expectedCols & set(loadedDf.columns)
        missingCols = expectedCols - set(loadedDf.columns)

        if missingCols:
            st.warning(
                f'Missing expected columns: {", ".join(sorted(missingCols))}. '
                'Analysis may be incomplete, but the data will still be loaded.'
            )

        # Add timestamps if not present (needed by downstream dedup logic)
        if 'CollectedAt' not in loadedDf.columns:
            loadedDf = addCollectionTimestamps(loadedDf)

        st.session_state.vma_careerData = loadedDf
        st.session_state.vma_lastScrapeTimestamp = pd.Timestamp.now().isoformat()

        # Reset downstream pipeline state so user re-runs normalization on the new data
        for key in ('vma_validatedData', 'vma_reviewedData', 'vma_geoFactors',
                    'vma_geoValidation', 'vma_companyAverages', 'vma_proposedBands'):
            st.session_state[key] = None

        st.info(
            f'Dataset loaded ({len(loadedDf):,} rows, {len(presentCols)}/{len(expectedCols)} expected columns). '
            'Proceed to the **Geographic Normalization** tab to continue the analysis pipeline.'
        )


# ---------------------------------------------------------------------- #
# -- Tab 2: Geographic Normalization (Feature 2) -- #
# ---------------------------------------------------------------------- #

def _renderGeoNormalization():

    '''

    Geographic factor validation and salary normalization to the HQ baseline.

    '''

    st.subheader('Geographic Salary Normalization')
    st.markdown(
        'Compute location-based salary adjustment factors from multi-location job '
        'postings (e.g., a company listing the same role in two different cities). '
        'All salaries are normalized to the HQ-location equivalent for apples-to-apples comparison.'
    )

    careerData = st.session_state.vma_careerData

    if careerData is None or careerData.empty:
        st.info('Run a career page scrape in the Data Collection tab first.')
        return

    # -- Compute Geo Factors -- #
    if st.button('Compute Geographic Factors', width='stretch', type='primary'):
        geoFactors, evidenceDf = computeGeoFactors(careerData, geographicAdjustments)

        # Apply normalization
        normalizedDf = applyGeoNormalization(careerData, geoFactors)

        st.session_state.vma_geoFactors = geoFactors
        st.session_state.vma_geoValidation = evidenceDf
        st.session_state.vma_careerData = normalizedDf

        # Reset downstream
        st.session_state.vma_validatedData = None
        st.session_state.vma_reviewedData = None

        st.success('Geographic normalization applied.')
        st.rerun()

    geoFactors = st.session_state.vma_geoFactors
    evidenceDf = st.session_state.vma_geoValidation

    if geoFactors is not None:
        st.markdown('---')

        # -- Factor Comparison Table -- #
        factorCol, chartCol = st.columns(2)

        with factorCol:
            st.markdown('**Geographic Adjustment Factors**')
            st.caption('1.0 = HQ baseline. Values >1.0 indicate higher cost locations.')

            factorRows = []
            for loc, factor in sorted(geoFactors.items()):
                refFactor = geographicAdjustments.get(loc, None)
                delta = f'{(factor - refFactor):.3f}' if refFactor is not None else 'N/A'
                factorRows.append({
                    'Location': loc,
                    'Validated Factor': round(factor, 4),
                    'Reference Factor': round(refFactor, 4) if refFactor is not None else 'N/A',
                    'Delta': delta,
                })

            factorDf = pd.DataFrame(factorRows)
            st.dataframe(factorDf, width='stretch', height=300)

        with chartCol:
            st.markdown('**Factor Distribution**')
            if factorRows:
                chartDf = pd.DataFrame(factorRows)
                chartDf['Validated Factor'] = pd.to_numeric(chartDf['Validated Factor'], errors='coerce')
                chartDf = chartDf.sort_values('Validated Factor', ascending=True)
                figGeo = px.bar(
                    chartDf,
                    x='Validated Factor',
                    y='Location',
                    orientation='h',
                    title='Geographic Factors (HQ baseline = 1.0)',
                    color='Validated Factor',
                    color_continuous_scale='RdYlGn_r',
                )
                figGeo.update_layout(height=400, **plotlyDarkLayout)
                st.plotly_chart(figGeo, width='stretch')

        # -- Evidence Table -- #
        if evidenceDf is not None and not evidenceDf.empty:
            with st.expander(f'Validation Evidence ({len(evidenceDf)} pairs)', expanded=False):
                st.markdown(
                    'Multi-location postings used to derive geographic factors. '
                    'Each row shows the same job posted in two different states.'
                )
                st.dataframe(evidenceDf, width='stretch', height=300)
        else:
            st.caption(
                'No multi-location postings found for direct validation. '
                'Using reference factors from the compensation survey spreadsheet.'
            )

        # -- Before/After Scatter -- #
        if 'AdjustedMidpoint' in careerData.columns and 'Midpoint' not in careerData.columns:
            careerData['Midpoint'] = (
                pd.to_numeric(careerData.get('Min'), errors='coerce') +
                pd.to_numeric(careerData.get('Max'), errors='coerce')
            ) / 2

        if 'AdjustedMidpoint' in careerData.columns:
            validPlot = careerData[
                (pd.to_numeric(careerData.get('Midpoint'), errors='coerce') > 0) &
                (pd.to_numeric(careerData.get('AdjustedMidpoint'), errors='coerce') > 0)
            ]

            if not validPlot.empty:
                st.markdown('**Original vs Normalized Salary Distribution**')
                figCompare = go.Figure()
                figCompare.add_trace(go.Histogram(
                    x=pd.to_numeric(validPlot['Midpoint'], errors='coerce'),
                    name='Original',
                    opacity=0.6,
                    marker_color=colors['info'],
                ))
                figCompare.add_trace(go.Histogram(
                    x=pd.to_numeric(validPlot['AdjustedMidpoint'], errors='coerce'),
                    name='HQ-Baseline Normalized',
                    opacity=0.6,
                    marker_color=colors['accent'],
                ))
                figCompare.update_layout(
                    barmode='overlay',
                    xaxis_title='Salary ($)',
                    yaxis_title='Count',
                    height=350,
                    **plotlyDarkLayout,
                )
                st.plotly_chart(figCompare, width='stretch')


# ---------------------------------------------------------------------- #
# -- Tab 3: Role Mapping (Features 4, 5) -- #
# ---------------------------------------------------------------------- #

def _renderRoleMapping():

    '''

    Semantic role bucketing with management detection and manual review.

    '''

    st.subheader('Role Mapping to Engineering Levels')
    st.markdown(
        'Auto-classify listings into engineering levels using years of experience '
        '(50% weight), title keywords (30%), and salary range (20%). Management roles '
        'are flagged for manual review.'
    )

    careerData = st.session_state.vma_careerData

    if careerData is None or careerData.empty:
        st.info('Run a career page scrape in the Data Collection tab first.')
        return

    # -- Run Bucketing -- #
    if st.button('Assign Buckets', width='stretch', type='primary'):
        # Ensure Description column exists (may be empty for some scrapers)
        if 'Description' not in careerData.columns:
            careerData['Description'] = ''

        bucketedDf = assignBuckets(careerData)
        st.session_state.vma_validatedData = bucketedDf
        st.session_state.vma_reviewedData = None

        # Check for monotonicity issues and store warnings
        monoWarnings = _checkBucketMonotonicity(bucketedDf)
        st.session_state.vma_monoWarnings = monoWarnings

        st.success('Bucket assignment complete.')
        st.rerun()

    validatedData = st.session_state.vma_validatedData

    if validatedData is None or validatedData.empty:
        if st.session_state.vma_careerData is not None:
            st.caption('Click "Assign Buckets" to classify listings into levels.')
        return

    st.markdown('---')

    # -- Monotonicity Warnings -- #
    monoWarnings = st.session_state.get('vma_monoWarnings', [])
    if monoWarnings:
        for warn in monoWarnings:
            st.warning(warn)

    # -- Summary Metrics -- #
    totalListings = len(validatedData)
    mgmtCount = validatedData['ManagementFlag'].sum() if 'ManagementFlag' in validatedData.columns else 0
    reviewCount = validatedData['ManualReviewNeeded'].sum() if 'ManualReviewNeeded' in validatedData.columns else 0
    classifiedCount = (validatedData['LevelBucket'] != 'Unclassified').sum() if 'LevelBucket' in validatedData.columns else 0

    metricCols = st.columns(4)
    with metricCols[0]:
        st.metric('Total Listings', f'{totalListings:,}')
    with metricCols[1]:
        st.metric('Classified', f'{classifiedCount:,}')
    with metricCols[2]:
        st.metric('Management Flagged', f'{int(mgmtCount):,}')
    with metricCols[3]:
        st.metric('Needs Review', f'{int(reviewCount):,}')

    # -- Filters -- #
    filterCol1, filterCol2, filterCol3 = st.columns(3)

    with filterCol1:
        bucketOptions = sorted(validatedData['LevelBucket'].dropna().unique().tolist())
        selectedBuckets = st.multiselect(
            'Filter by Bucket',
            bucketOptions,
            default=bucketOptions,
            key='vma_bucketFilter',
        )

    with filterCol2:
        confidenceThreshold = st.slider(
            'Min Confidence',
            0.0, 1.0, 0.0, 0.1,
            key='vma_confidenceFilter',
        )

    with filterCol3:
        mgmtOnly = st.checkbox('Management flagged only', key='vma_mgmtFilter')

    # Apply filters
    displayDf = validatedData.copy()
    if selectedBuckets:
        displayDf = displayDf[displayDf['LevelBucket'].isin(selectedBuckets)]
    if confidenceThreshold > 0:
        displayDf = displayDf[displayDf['BucketConfidence'] >= confidenceThreshold]
    if mgmtOnly:
        displayDf = displayDf[displayDf['ManagementFlag'] == True]

    # -- Editable Table -- #
    editCols = [
        'Company', 'Listing', 'LevelBucket', 'BucketConfidence',
        'ManagementFlag', 'ManualReviewNeeded', 'YoeEstimate',
        'AdjustedMidpoint', 'Location', 'State',
    ]
    availableEditCols = [c for c in editCols if c in displayDf.columns]
    editableDf = displayDf[availableEditCols].reset_index(drop=True)

    bucketChoices = ['Level 1', 'Level 2', 'Level 3', 'Level 4', 'Level 5', 'Unclassified']

    columnConfig = {
        'Company': st.column_config.TextColumn('Company', disabled=True),
        'Listing': st.column_config.TextColumn('Listing', disabled=True),
        'LevelBucket': st.column_config.SelectboxColumn(
            'Level Bucket', options=bucketChoices, required=True,
        ),
        'BucketConfidence': st.column_config.ProgressColumn(
            'Confidence', min_value=0.0, max_value=1.0, format='%.1f',
        ),
        'ManagementFlag': st.column_config.CheckboxColumn('Mgmt'),
        'ManualReviewNeeded': st.column_config.CheckboxColumn('Review'),
        'YoeEstimate': st.column_config.NumberColumn('YoE Est', format='%.1f'),
        'AdjustedMidpoint': st.column_config.NumberColumn('Adj Midpoint', format='$%d'),
        'Location': st.column_config.TextColumn('Location', disabled=True),
        'State': st.column_config.TextColumn('State', disabled=True),
    }

    editedDf = st.data_editor(
        editableDf,
        column_config=columnConfig,
        width='stretch',
        height=500,
        num_rows='fixed',
        key='vma_roleEditor',
    )

    st.markdown('')

    # -- Apply Button -- #
    applyCol, downloadCol = st.columns(2)

    with applyCol:
        if st.button('Apply Reviewed Mappings', width='stretch', type='primary'):
            # Merge edits back into the full validated dataset
            fullDf = validatedData.copy()
            filteredIndices = displayDf.index.tolist()

            for col in availableEditCols:
                if col in ('Company', 'Listing', 'Location', 'State'):
                    continue
                for localIdx, globalIdx in enumerate(filteredIndices):
                    if localIdx < len(editedDf):
                        fullDf.at[globalIdx, col] = editedDf.iloc[localIdx][col]

            st.session_state.vma_validatedData = fullDf
            st.session_state.vma_reviewedData = fullDf
            st.session_state.vma_companyAverages = None
            st.session_state.vma_proposedBands = None
            st.success('Reviewed mappings applied.')
            st.rerun()

    with downloadCol:
        csvData = editedDf.to_csv(index=False)
        st.download_button(
            'Download Mapped Data (CSV)',
            data=csvData,
            file_name='role_mapped_data.csv',
            mime='text/csv',
        )

    # -- Charts -- #
    st.markdown('---')
    chartCol1, chartCol2 = st.columns(2)

    with chartCol1:
        st.markdown('**Listings per Level Bucket**')
        if 'LevelBucket' in validatedData.columns:
            bucketCounts = validatedData['LevelBucket'].value_counts().reset_index()
            bucketCounts.columns = ['Bucket', 'Count']
            bucketCounts = bucketCounts.sort_values('Bucket')

            figBuckets = px.bar(
                bucketCounts,
                x='Count',
                y='Bucket',
                orientation='h',
                color='Bucket',
                color_discrete_map={
                    'Level 1': colors['levels']['Level 1'],
                    'Level 2': colors['levels']['Level 2'],
                    'Level 3': colors['levels']['Level 3'],
                    'Level 4': colors['levels']['Level 4'],
                    'Level 5': colors['levels']['Level 5'],
                    'Unclassified': colors['textMuted'],
                },
            )
            figBuckets.update_layout(
                height=300, showlegend=False, **plotlyDarkLayout,
            )
            st.plotly_chart(figBuckets, width='stretch')

    with chartCol2:
        st.markdown('**YoE vs Salary by Bucket**')
        scatterSalCol = 'AdjustedMidpoint' if 'AdjustedMidpoint' in validatedData.columns else 'Midpoint'
        if scatterSalCol not in validatedData.columns:
            # Compute Midpoint from Min/Max if missing
            validatedData['Min'] = pd.to_numeric(validatedData.get('Min'), errors='coerce')
            validatedData['Max'] = pd.to_numeric(validatedData.get('Max'), errors='coerce')
            validatedData['Midpoint'] = (validatedData['Min'].fillna(0) + validatedData['Max'].fillna(0)) / 2
            scatterSalCol = 'Midpoint'

        plotData = validatedData[
            (validatedData['YoeEstimate'].notna()) &
            (pd.to_numeric(validatedData.get(scatterSalCol, 0), errors='coerce') > 0)
        ].copy()

        if not plotData.empty:
            plotData[scatterSalCol] = pd.to_numeric(plotData[scatterSalCol], errors='coerce')

            figScatter = px.scatter(
                plotData,
                x='YoeEstimate',
                y=scatterSalCol,
                color='LevelBucket',
                color_discrete_map={
                    'Level 1': colors['levels']['Level 1'],
                    'Level 2': colors['levels']['Level 2'],
                    'Level 3': colors['levels']['Level 3'],
                    'Level 4': colors['levels']['Level 4'],
                    'Level 5': colors['levels']['Level 5'],
                    'Unclassified': colors['textMuted'],
                },
                labels={'YoeEstimate': 'Years of Experience', scatterSalCol: 'Salary ($)'},
                hover_data=['Company', 'Listing'],
            )

            # Overlay proposed band regions
            for bandName, band in salaryBands.items():
                bandColor = colors['levels'].get(bandName, colors['textMuted'])
                minYrs = band['minYrs']
                maxYrs = band['maxYrs'] or 15

                figScatter.add_shape(
                    type='rect',
                    x0=minYrs, x1=maxYrs,
                    y0=band['min'], y1=band['max'],
                    fillcolor=bandColor,
                    opacity=0.1,
                    line=dict(color=bandColor, width=1),
                )

            figScatter.update_layout(
                height=300, **plotlyDarkLayout,
            )
            st.plotly_chart(figScatter, width='stretch')
        else:
            st.caption('Insufficient data for scatter plot (need YoE and salary).')


# ---------------------------------------------------------------------- #
# -- Tab 4: Market Analysis (Feature 3) -- #
# ---------------------------------------------------------------------- #

def _renderMarketAnalysis():

    '''

    Company-weighted averaging with box plots and band overlays.

    '''

    st.subheader('Market Analysis')
    st.markdown(
        'Company-weighted salary averages ensure each company contributes equally '
        'regardless of how many listings it has. Toggle between raw and weighted '
        'averages to see the impact.'
    )

    # Use reviewed data if available, otherwise validated, otherwise career
    dataDf = _bestAvailableData(
        st.session_state.vma_reviewedData,
        st.session_state.vma_validatedData,
        st.session_state.vma_careerData,
    )

    if dataDf is None or dataDf.empty:
        st.info('Complete the Data Collection and Role Mapping steps first.')
        return

    if 'LevelBucket' not in dataDf.columns:
        st.info('Run "Assign Buckets" in the Role Mapping tab first.')
        return

    salaryCol = 'AdjustedMidpoint' if 'AdjustedMidpoint' in dataDf.columns else 'Midpoint'

    # Ensure numeric -- compute Midpoint from Min/Max if it doesn't exist
    dataDf = dataDf.copy()
    if salaryCol not in dataDf.columns:
        dataDf['Min'] = pd.to_numeric(dataDf.get('Min'), errors='coerce')
        dataDf['Max'] = pd.to_numeric(dataDf.get('Max'), errors='coerce')
        dataDf['Midpoint'] = (dataDf['Min'].fillna(0) + dataDf['Max'].fillna(0)) / 2
        salaryCol = 'Midpoint'
    else:
        dataDf[salaryCol] = pd.to_numeric(dataDf.get(salaryCol), errors='coerce')
    validData = dataDf[dataDf[salaryCol] > 0]

    if validData.empty:
        st.warning('No valid salary data available for analysis.')
        return

    # -- Company-Weighted Averages Table -- #
    weighted = companyWeightedAverage(validData, groupBy='LevelBucket')

    if not weighted.empty:
        st.markdown('**Company-Weighted Averages by Level**')
        st.caption('Each company is averaged first, then companies are averaged equally.')

        displayWeighted = weighted.copy()
        for col in ['WeightedAvgMin', 'WeightedAvgMax', 'WeightedAvgMidpoint', 'StdDev']:
            if col in displayWeighted.columns:
                displayWeighted[col] = displayWeighted[col].apply(lambda x: f'${x:,.0f}' if pd.notna(x) else 'N/A')

        st.dataframe(displayWeighted, width='stretch', hide_index=True)

    # -- Toggle: Raw vs Weighted -- #
    showRaw = st.checkbox('Show raw (unweighted) averages for comparison', key='vma_showRaw')

    if showRaw:
        rawAvgs = validData.groupby('LevelBucket').agg(
            ListingCount=(salaryCol, 'count'),
            RawAvgMidpoint=(salaryCol, 'mean'),
            RawStdDev=(salaryCol, 'std'),
        ).reset_index()
        rawAvgs['RawAvgMidpoint'] = rawAvgs['RawAvgMidpoint'].round(0)
        rawAvgs['RawStdDev'] = rawAvgs['RawStdDev'].round(0)

        st.markdown('**Raw (Unweighted) Averages**')
        st.caption('Companies with more listings have more influence on the average.')
        st.dataframe(rawAvgs, width='stretch', hide_index=True)

    st.markdown('---')

    # -- Box Plots -- #
    chartCol1, chartCol2 = st.columns(2)

    with chartCol1:
        st.markdown('**Salary Distribution by Level**')
        figBox = px.box(
            validData,
            x='LevelBucket',
            y=salaryCol,
            color='LevelBucket',
            color_discrete_map={
                'Level 1': colors['levels']['Level 1'],
                'Level 2': colors['levels']['Level 2'],
                'Level 3': colors['levels']['Level 3'],
                'Level 4': colors['levels']['Level 4'],
                'Level 5': colors['levels']['Level 5'],
                'Unclassified': colors['textMuted'],
            },
            labels={salaryCol: 'Salary ($)'},
        )

        # Add proposed band lines
        for bandName, band in salaryBands.items():
            figBox.add_hline(
                y=band['median'],
                line_dash='dash',
                line_color=colors['levels'].get(bandName, '#ffffff'),
                annotation_text=f'{bandName} median',
                annotation_position='top left',
                opacity=0.5,
            )

        figBox.update_layout(height=400, showlegend=False, **plotlyDarkLayout)
        st.plotly_chart(figBox, width='stretch')

    with chartCol2:
        st.markdown('**Salary Distribution by Company**')
        companyData = validData[
            validData['Company'].notna() &
            (validData['Company'] != 'Unknown')
        ]
        if not companyData.empty:
            figCompany = px.box(
                companyData,
                x='Company',
                y=salaryCol,
                title='Salary by Company',
                labels={salaryCol: 'Salary ($)'},
            )
            figCompany.update_layout(
                height=400, xaxis_tickangle=-45, **plotlyDarkLayout,
            )
            st.plotly_chart(figCompany, width='stretch')


# ---------------------------------------------------------------------- #
# -- Tab 5: Band Recalculation (Feature 6) -- #
# ---------------------------------------------------------------------- #

def _renderBandRecalculation():

    '''

    Propose updated salary bands from validated market data.

    '''

    st.subheader('Salary Band Recalculation')
    st.markdown(
        'Propose updated salary bands based on validated market data. '
        'Bands are computed from percentiles, rounded to nearest $1,000, '
        'and overlap between levels is allowed by default (per industry standard).'
    )

    dataDf = _bestAvailableData(
        st.session_state.vma_reviewedData,
        st.session_state.vma_validatedData,
    )

    if dataDf is None or dataDf.empty or 'LevelBucket' not in dataDf.columns:
        st.info('Complete Role Mapping first to assign listings to engineering levels.')
        return

    # -- Configuration -- #
    configCol1, configCol2, configCol3, configCol4 = st.columns(4)

    with configCol1:
        minPct = st.number_input('Min Percentile', 1, 49, 10, key='vma_minPct')
    with configCol2:
        medPct = st.number_input('Median Percentile', 25, 75, 50, key='vma_medPct')
    with configCol3:
        maxPct = st.number_input('Max Percentile', 51, 99, 90, key='vma_maxPct')
    with configCol4:
        allowOverlap = st.checkbox('Allow Band Overlap', value=True, key='vma_allowOverlap')

    st.markdown('')

    # -- Compute -- #
    if st.button('Compute Proposed Bands', width='stretch', type='primary'):
        proposedBands, comparisonDf = recalculateSalaryBands(
            dataDf,
            currentBands=salaryBands,
            roundTo=1000,
            allowOverlap=allowOverlap,
            minPercentile=minPct,
            medianPercentile=medPct,
            maxPercentile=maxPct,
        )
        st.session_state.vma_proposedBands = proposedBands
        st.session_state.vma_bandComparison = comparisonDf
        st.rerun()

    rawProposedBands = st.session_state.vma_proposedBands

    if rawProposedBands is None:
        st.caption('Click "Compute Proposed Bands" to generate a proposal.')
        return

    # -- Market Position Adjustment -- #
    st.markdown('---')
    st.markdown('**Market Position Adjustment**')
    st.caption(
        'Adjust proposed bands to account for company size, revenue stage, '
        'regional cost of living, production cadence, or other factors. '
        'Market data is sourced from larger companies -- apply a knockdown '
        'to target a competitive position for a smaller or pre-revenue employer.'
    )

    adjCol1, adjCol2 = st.columns([1, 2])

    with adjCol1:
        positionPreset = st.selectbox(
            'Company Profile',
            ['Large / Established (0%)', 'Mid-size / Growth Stage (-10%)',
             'Small / Pre-Revenue (-20%)', 'Custom'],
            key='vma_positionPreset',
        )

    # Map presets to percentages
    presetMap = {
        'Large / Established (0%)': 0,
        'Mid-size / Growth Stage (-10%)': -10,
        'Small / Pre-Revenue (-20%)': -20,
    }

    with adjCol2:
        if positionPreset == 'Custom':
            adjustmentPct = st.slider(
                'Adjustment (%)',
                min_value=-50,
                max_value=20,
                value=0,
                step=5,
                key='vma_adjustmentPct',
                help='Negative values reduce bands, positive values increase them.',
            )
        else:
            adjustmentPct = presetMap.get(positionPreset, 0)
            st.markdown(f'Adjustment: **{adjustmentPct:+d}%**')

    # Apply adjustment
    if adjustmentPct != 0:
        proposedBands = applyMarketPositionAdjustment(rawProposedBands, adjustmentPct)
    else:
        proposedBands = rawProposedBands

    comparisonDf = st.session_state.get('vma_bandComparison', pd.DataFrame())

    if not comparisonDf.empty:
        # Rebuild comparison with adjusted values if knockdown is applied
        if adjustmentPct != 0:
            adjustedComp = comparisonDf.copy()
            multiplier = 1.0 + (adjustmentPct / 100.0)
            for col in ['ProposedMin', 'ProposedMedian', 'ProposedMax']:
                if col in adjustedComp.columns:
                    adjustedComp[col] = (adjustedComp[col] * multiplier).apply(
                        lambda x: int(round(x / 1000) * 1000) if pd.notna(x) else x
                    )
            # Recompute deltas
            for base in ['Min', 'Median', 'Max']:
                proposedCol = f'Proposed{base}'
                currentCol = f'Current{base}'
                deltaCol = f'Delta{base}'
                if proposedCol in adjustedComp.columns and currentCol in adjustedComp.columns:
                    adjustedComp[deltaCol] = adjustedComp[proposedCol] - adjustedComp[currentCol]
            displaySource = adjustedComp
        else:
            displaySource = comparisonDf

        st.markdown('---')
        adjLabel = f' (adjusted {adjustmentPct:+d}%)' if adjustmentPct != 0 else ''
        st.markdown(f'**Current vs Proposed Salary Bands{adjLabel}**')

        # Format currency columns for display
        displayComp = displaySource.copy()
        currencyCols = [
            'CurrentMin', 'ProposedMin', 'DeltaMin',
            'CurrentMedian', 'ProposedMedian', 'DeltaMedian',
            'CurrentMax', 'ProposedMax', 'DeltaMax',
        ]
        for col in currencyCols:
            if col in displayComp.columns:
                displayComp[col] = displayComp[col].apply(
                    lambda x: f'${x:,.0f}' if pd.notna(x) else 'N/A'
                )

        st.dataframe(displayComp, width='stretch', hide_index=True)

        # -- Band Visualization -- #
        st.markdown('**Band Comparison Chart**')

        bandChartRows = []
        for _, row in displaySource.iterrows():
            level = row['Level']
            bandChartRows.append({'Level': level, 'Type': 'Current', 'Min': row['CurrentMin'], 'Max': row['CurrentMax']})
            bandChartRows.append({'Level': level, 'Type': 'Proposed', 'Min': row['ProposedMin'], 'Max': row['ProposedMax']})

        bandChartDf = pd.DataFrame(bandChartRows)
        bandChartDf['Range'] = bandChartDf['Max'] - bandChartDf['Min']

        figBands = go.Figure()

        for bandType, color in [('Current', colors['textMuted']), ('Proposed', colors['accent'])]:
            subset = bandChartDf[bandChartDf['Type'] == bandType]
            figBands.add_trace(go.Bar(
                name=bandType,
                y=subset['Level'],
                x=subset['Range'],
                base=subset['Min'],
                orientation='h',
                marker_color=color,
                opacity=0.7,
            ))

        figBands.update_layout(
            barmode='group',
            xaxis_title='Salary ($)',
            yaxis_title='Level',
            height=350,
            **plotlyDarkLayout,
        )
        st.plotly_chart(figBands, width='stretch')

        # -- Export -- #
        exportCol1, exportCol2 = st.columns(2)

        with exportCol1:
            csvExport = displaySource.to_csv(index=False)
            st.download_button(
                'Download Comparison (CSV)',
                data=csvExport,
                file_name='proposed_salary_bands.csv',
                mime='text/csv',
            )

        with exportCol2:
            if st.button('Save Snapshot with Proposed Bands'):
                filename = saveValidatedSnapshot(dataDf, bands=proposedBands)
                st.success(f'Snapshot saved: {filename}')


# ---------------------------------------------------------------------- #
# -- Tab 6: Trends & Analytics (Feature 8) -- #
# ---------------------------------------------------------------------- #

def _renderTrendAnalytics():

    '''

    Moving average trends and reference vs scraped comparison.

    '''

    st.subheader('Trends & Analytics')
    st.markdown(
        'Compare validated market data against the reference survey and track '
        'salary trends over time across multiple data collection events.'
    )

    # -- Load Snapshots -- #
    history = loadValidatedHistory()

    if not history:
        st.info(
            'No saved snapshots yet. Save a snapshot from the Data Collection tab '
            'to enable trend analysis.'
        )

        # Still show reference vs current scraped comparison if data available
        _renderReferenceComparison()
        return

    # -- Snapshot Selection -- #
    st.markdown('**Saved Snapshots**')
    snapshotLabels = [
        f'{snap["timestamp"][:16]} ({snap["recordCount"]} records)'
        for snap in history
    ]
    selectedSnapshots = st.multiselect(
        'Select Snapshots for Analysis',
        snapshotLabels,
        default=snapshotLabels[:5],
        key='vma_snapshotSelect',
    )

    if not selectedSnapshots:
        st.caption('Select at least one snapshot.')
        return

    # Load selected snapshot data
    selectedIndices = [snapshotLabels.index(s) for s in selectedSnapshots]
    snapshotDfs = []
    snapshotTimestamps = []

    for idx in sorted(selectedIndices):
        snap = history[idx]
        snapDf = loadSnapshotData(snap['csvPath'])
        if not snapDf.empty:
            snapshotDfs.append(snapDf)
            snapshotTimestamps.append(snap['timestamp'])

    if not snapshotDfs:
        st.warning('Could not load selected snapshots.')
        return

    st.markdown('---')

    # -- Trend Analysis (2+ Snapshots) -- #
    if len(snapshotDfs) >= 2:
        st.markdown('**Salary Trends Over Time**')

        windowSize = st.slider(
            'Moving Average Window',
            2, min(5, len(snapshotDfs)), min(3, len(snapshotDfs)),
            key='vma_maWindow',
        )

        trendDf = computeTrendAnalytics(
            snapshotDfs, snapshotTimestamps,
            groupBy='LevelBucket',
            windowSize=windowSize,
        )

        if not trendDf.empty:
            figTrend = px.line(
                trendDf,
                x='Timestamp',
                y='MovingAvg',
                color='LevelBucket',
                color_discrete_map={
                    'Level 1': colors['levels']['Level 1'],
                    'Level 2': colors['levels']['Level 2'],
                    'Level 3': colors['levels']['Level 3'],
                    'Level 4': colors['levels']['Level 4'],
                    'Level 5': colors['levels']['Level 5'],
                },
                markers=True,
                labels={'MovingAvg': 'Avg Salary ($)', 'Timestamp': 'Collection Date'},
                title=f'Company-Weighted Average Salary (MA window={windowSize})',
            )
            figTrend.update_layout(height=400, **plotlyDarkLayout)
            st.plotly_chart(figTrend, width='stretch')
        else:
            st.caption('Insufficient data for trend chart.')

    # -- Reference vs Latest Scraped -- #
    _renderReferenceComparison()


def _renderReferenceComparison():

    '''

    Compare reference survey data against the most recently scraped data.

    '''

    dataDf = _bestAvailableData(
        st.session_state.vma_reviewedData,
        st.session_state.vma_validatedData,
    )

    if dataDf is None or dataDf.empty or 'LevelBucket' not in dataDf.columns:
        return

    st.markdown('---')
    st.markdown('**Reference Survey vs Scraped Data**')

    # Load reference survey and assign buckets for comparison
    refDf = loadMarketSurveyData()

    # The reference data may not have LevelBucket -- create one from Vlvl column
    if 'LevelBucket' not in refDf.columns:
        if 'Vlvl' in refDf.columns:
            refDf['LevelBucket'] = refDf['Vlvl'].apply(
                lambda x: f'Level {int(x)}' if pd.notna(x) and 1 <= x <= 5 else 'Unclassified'
            )
        else:
            st.caption('Reference data does not have level assignments for comparison.')
            return

    # Ensure AdjustedMidpoint exists on reference data (use raw Midpoint)
    if 'AdjustedMidpoint' not in refDf.columns:
        refMinCol = pd.to_numeric(refDf.get('Min'), errors='coerce')
        refMaxCol = pd.to_numeric(refDf.get('Max'), errors='coerce')
        refDf['AdjustedMidpoint'] = (refMinCol + refMaxCol) / 2

    # Need Company column for weighting
    if 'Company' not in refDf.columns or refDf['Company'].isna().all():
        st.caption('Reference data missing company information for weighted comparison.')
        return

    comparisonDf = compareReferenceToScraped(refDf, dataDf, groupBy='LevelBucket')

    if comparisonDf.empty:
        st.caption('Insufficient data for reference comparison.')
        return

    # Format for display
    displayComp = comparisonDf.copy()
    for col in ['RefAvgMidpoint', 'ScrapedAvgMidpoint', 'Delta']:
        if col in displayComp.columns:
            displayComp[col] = displayComp[col].apply(
                lambda x: f'${x:,.0f}' if pd.notna(x) else 'N/A'
            )
    if 'DeltaPct' in displayComp.columns:
        displayComp['DeltaPct'] = displayComp['DeltaPct'].apply(
            lambda x: f'{x:+.1f}%' if pd.notna(x) else 'N/A'
        )

    st.dataframe(displayComp, width='stretch', hide_index=True)

    # Delta bar chart
    rawComp = compareReferenceToScraped(refDf, dataDf, groupBy='LevelBucket')
    if not rawComp.empty and 'DeltaPct' in rawComp.columns:
        figDelta = px.bar(
            rawComp,
            x='LevelBucket',
            y='DeltaPct',
            color='DeltaPct',
            color_continuous_scale='RdYlGn',
            labels={'DeltaPct': 'Change (%)', 'LevelBucket': 'Level'},
            title='Scraped vs Reference (% Change)',
        )
        figDelta.update_layout(height=300, **plotlyDarkLayout)
        st.plotly_chart(figDelta, width='stretch')


# ---------------------------------------------------------------------- #
# -- Module-Level Execution -- #
# -- Called from marketTools.py via renderValidatedMarketAnalysis() -- #
# ---------------------------------------------------------------------- #
