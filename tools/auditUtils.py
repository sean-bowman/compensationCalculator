
# -- Compensation Audit Utilities -- #

'''

Data loading, constants, and calculation functions for the
Compensation Structure Audit Tool.

Author: Sean Bowman
Date:   02/23/2026

'''

# Standard library imports
import copy
import json
import os
from typing import Optional, Dict, List

# Third-party imports
import pandas as pd

# ---------------------------------------------------------------------- #
# -- Constants & Reference Data -- #
# ---------------------------------------------------------------------- #

# Base directory for tools and documentation
_toolsDir = os.path.dirname(os.path.abspath(__file__))
_appDir = os.path.dirname(_toolsDir)
_docDir = os.path.join(_appDir, 'documentation')

# Data file paths (data files live in documentation/). The market survey is a
# synthetic, version-controlled CSV -- there is no binary spreadsheet
# dependency for startup data.
_surveyFile = os.path.join(_docDir, 'marketSurveySynthetic.csv')
referenceFile = os.path.join(_docDir, 'compensationReference.md')
levelsFile = os.path.join(_docDir, 'engineeringLevels.md')

# ---------------------------------------------------------------------- #
# -- Data Loading Functions -- #
# ---------------------------------------------------------------------- #

def loadMarketSurveyData(filePath: str = _surveyFile, schemaStyle: str = 'auto') -> pd.DataFrame:

    '''

    Load and parse market survey data from a CSV or Excel file.
    Defaults to the synthetic market survey CSV in documentation/.

    Supports three schema styles:
    - 'reference': a legacy Excel layout (rows 30-592, cols B-U)
    - 'flat': a file whose first row already contains headers matching surveyColumns
    - 'auto': detect format automatically based on file content

    Auto-detection reads the first row of the file. If it contains recognised
    surveyColumns headers (Company, Listing, Min, Max), it uses flat mode.
    Otherwise it falls back to the reference layout. The default synthetic
    CSV is a flat-header file, so it always parses in flat mode.

    Parameters:
    -----------
    filePath : str
        Path to a CSV (.csv) or Excel (.xlsx) file
    schemaStyle : str
        One of 'auto', 'reference', or 'flat'

    Returns:
    --------
    pd.DataFrame : Cleaned survey data with standardized column names

    '''

    isCsv = filePath.lower().endswith('.csv')

    # -- Determine schema style -- #
    if schemaStyle == 'auto':
        schemaStyle = _detectSchemaStyle(filePath, isCsv)

    # -- Load the raw DataFrame -- #
    try:
        if schemaStyle == 'flat':
            df = _loadFlat(filePath, isCsv)
        else:
            df = _loadReference(filePath)
    except PermissionError:
        raise PermissionError(
            f'Cannot read "{os.path.basename(filePath)}" -- the file is currently open '
            f'in another application (e.g., Excel). Please close the spreadsheet and restart '
            f'the application.'
        )

    # -- Clean and standardise -- #
    return _cleanSurveyDataFrame(df)


def _detectSchemaStyle(filePath: str, isCsv: bool) -> str:

    '''

    Peek at the first row of a file to decide whether it already has
    surveyColumns headers (flat) or needs the reference-sheet layout.

    '''

    # CSV files are always treated as flat (they come from exports or scrapes)
    if isCsv:
        return 'flat'

    try:
        peek = pd.read_excel(filePath, sheet_name=0, header=None, nrows=1)
        firstRow = [str(v).strip() for v in peek.iloc[0]]
        # If the first row contains at least Company, Listing, Min, Max -> flat
        requiredHeaders = {'Company', 'Listing', 'Min', 'Max'}
        if requiredHeaders.issubset(set(firstRow)):
            return 'flat'
    except Exception:
        pass

    return 'reference'


def _loadReference(filePath: str) -> pd.DataFrame:

    '''

    Load a legacy survey-spreadsheet layout (rows 30-592, columns B-U
    from Sheet1). Retained as a fallback for the 'reference' schema
    style; the default synthetic dataset uses the flat schema instead.

    '''

    df = pd.read_excel(
        filePath,
        sheet_name='Sheet1',
        header=None,
        skiprows=29,
        usecols='B:U',
        names=surveyColumns,
    )

    # Drop the header row if it was included in the data range
    if df.iloc[0]['Company'] == 'Company':
        df = df.iloc[1:].reset_index(drop=True)

    return df


def _loadFlat(filePath: str, isCsv: bool) -> pd.DataFrame:

    '''

    Load a file whose first row contains column headers.
    Aligns columns to the surveyColumns schema, filling any
    missing columns with None.

    '''

    if isCsv:
        df = pd.read_csv(filePath)
    else:
        df = pd.read_excel(filePath, sheet_name=0)

    # Align to surveyColumns -- keep extra columns (e.g., DataSource) intact
    for col in surveyColumns:
        if col not in df.columns:
            df[col] = None

    return df


def _cleanSurveyDataFrame(df: pd.DataFrame) -> pd.DataFrame:

    '''

    Apply shared cleaning to any survey DataFrame regardless of how
    it was loaded: coerce numerics, strip strings, compute midpoints.

    '''

    # Clean numeric columns
    for col in ['Min', 'Max', 'Vmin', 'Vmax', 'ExpReq', 'Estimated', 'Vexp', 'Vlvl', 'Level']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Drop rows where Company is null (empty rows)
    df = df.dropna(subset=['Company']).reset_index(drop=True)

    # Clean string columns
    for col in ['Company', 'Listing', 'Seniority', 'Location', 'TeamDepartment',
                'Discipline', 'PositionType', 'State']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Calculate midpoint salary
    if 'Min' in df.columns and 'Max' in df.columns:
        df['Midpoint'] = (df['Min'] + df['Max']) / 2
    if 'Vmin' in df.columns and 'Vmax' in df.columns:
        df['LevelMidpoint'] = (df['Vmin'] + df['Vmax']) / 2

    return df

def loadReferenceMarkdown(filePath: str = referenceFile) -> str:

    '''

    Load the consolidated compensation reference markdown file.
    Contains all research sources, data file overviews, BLS benchmarks,
    and market context in a single document.

    Returns:
    --------
    str : Raw markdown content

    '''

    if os.path.exists(filePath):
        with open(filePath, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return '# No reference file found'

def loadLevelsMarkdown(filePath: str = levelsFile) -> str:

    '''

    Load the engineering levels markdown file.

    Returns:
    --------
    str : Raw markdown content

    '''

    if os.path.exists(filePath):
        with open(filePath, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        return '# No levels file found'

# ---------------------------------------------------------------------- #
# -- Module-Level Data Initialization -- #
# ---------------------------------------------------------------------- #
# Engineering levels are parsed from documentation/engineeringLevels.md at
# import time. The salary framework (bands, modifiers, premiums, extended
# bands, geographic factors, wage benchmarks) is loaded from synthetic,
# version-controlled Python constants in tools/syntheticData.py -- there is
# no binary-spreadsheet dependency for startup data. All figures are
# fictional and provided for demonstration only.

# Engineering levels parsed from documentation/engineeringLevels.md
from referenceParser import parseLevelsData, deriveLevelOrder, deriveManagementMinLevel

# Synthetic salary framework constants
from syntheticData import (
    SALARY_BANDS, EXPERIENCE_MODIFIERS, MANAGEMENT_PREMIUMS,
    EXTENDED_BANDS, GEOGRAPHIC_ADJUSTMENTS, WAGE_BENCHMARKS,
)

levelsData = parseLevelsData(loadLevelsMarkdown())
levelOrder = deriveLevelOrder(levelsData)
managementMinLevel = deriveManagementMinLevel(levelsData)

# Deep-copy the synthetic constants so runtime overrides (band/premium
# editors) mutate module-level state without altering the source module.
salaryBands = copy.deepcopy(SALARY_BANDS)
experienceModifiers = copy.deepcopy(EXPERIENCE_MODIFIERS)
managementPremiums = copy.deepcopy(MANAGEMENT_PREMIUMS)
extendedBands = copy.deepcopy(EXTENDED_BANDS)
geographicAdjustments = copy.deepcopy(GEOGRAPHIC_ADJUSTMENTS)

# National wage benchmarks used as reference lines on charts
blsBenchmarks = copy.deepcopy(WAGE_BENCHMARKS)

# Apply any manual band overrides saved by the Level Bands Editor.
# Override file: tools/bandOverrides.json — only min/median/max fields are applied.
_bandOverridesPath = os.path.join(_toolsDir, 'bandOverrides.json')
if os.path.exists(_bandOverridesPath):
    with open(_bandOverridesPath, 'r', encoding='utf-8') as _f:
        _bandOverrides = json.load(_f)
    for _lvlKey, _lvlVals in _bandOverrides.items():
        if _lvlKey in salaryBands:
            for _field in ('min', 'median', 'max'):
                if _field in _lvlVals:
                    salaryBands[_lvlKey][_field] = int(_lvlVals[_field])
    del _f, _bandOverrides, _lvlKey, _lvlVals, _field

# Apply any manual management premium overrides saved by the Level Bands Editor.
# Override file: tools/premiumOverrides.json — maps role name to flat dollar premium.
_premiumOverridesPath = os.path.join(_toolsDir, 'premiumOverrides.json')
if os.path.exists(_premiumOverridesPath):
    with open(_premiumOverridesPath, 'r', encoding='utf-8') as _f:
        _premiumOverrides = json.load(_f)
    for _role, _amount in _premiumOverrides.items():
        if _role in managementPremiums:
            managementPremiums[_role] = int(_amount)
    del _f, _premiumOverrides, _role, _amount

# Column schema for the market survey spreadsheet (columns B through U).
# This schema is shared across all data sources -- the scraper normalizes
# external data into these same columns so survey and scraped data can
# be merged into a single DataFrame.
surveyColumns = [
    'Company', 'Listing', 'Level', 'Seniority', 'ExpReq', 'Estimated',
    'Location', 'TeamDepartment', 'Discipline', 'PositionType',
    'Min', 'Max', 'Vexp', 'Vlvl', 'Filter', 'Vmin', 'Vmax',
    'Link', 'FilterCol', 'State',
]

# -- Theme Colors -- #
# Dark theme palette designed to match the .streamlit/config.toml settings.
# The accent color (#E0975A) is the copper-amber accent used across
# all plots and UI highlights. Company-specific colors are assigned for
# distinguishing data points in multi-company comparison charts.

# Accent color (config.toml primaryColor)
_accentColor = '#E0975A'
# Full color palette for dark theme UI elements and chart styling
colors = {
    'bg': '#333333',
    'surfacePrimary': '#4d4d4d',
    'surfaceSecondary': '#5a5a5a',
    'surfaceBorder': '#666666',
    'textPrimary': '#ffffff',
    'textSecondary': '#cccccc',
    'textMuted': '#999999',
    'accent': _accentColor,
    'accentDim': '#C97E45',
    'accentMuted': '#5C4636',
    'success': '#22c55e',
    'warning': '#f59e0b',
    'danger': '#ef4444',
    'info': '#3b82f6',
    'companies': {
        'Apex Dynamics': '#FF6B6B',
        'Comet Industries': '#4ECDC4',
        'Helios Launch': '#45B7D1',
        'Nova Propulsion': '#96CEB4',
        'Orbital Forge': '#FFEAA7',
        'Pinnacle Aero': '#DDA0DD',
        'Stratos Systems': '#74B9FF',
        'Vertex Aerospace': '#FD79A8',
        'Zenith Spacecraft': '#A29BFE',
    },
    'levels': {
        'Level 1': '#3b82f6',
        'Level 2': '#22c55e',
        'Level 3': '#f59e0b',
        'Level 4': '#ef4444',
        'Level 5': '#a855f7',
    },
}

# Plotly dark theme layout defaults
plotlyDarkLayout = {
    'paper_bgcolor': 'rgba(0,0,0,0)',
    'plot_bgcolor': 'rgba(0,0,0,0)',
    'font': {'color': colors['textPrimary']},
    'xaxis': {
        'gridcolor': colors['surfaceBorder'],
        'zerolinecolor': colors['surfaceBorder'],
    },
    'yaxis': {
        'gridcolor': colors['surfaceBorder'],
        'zerolinecolor': colors['surfaceBorder'],
    },
    'legend': {'bgcolor': 'rgba(0,0,0,0)'},
}

# ---------------------------------------------------------------------- #
# -- Calculation Functions -- #
# ---------------------------------------------------------------------- #

def calculateSalary(
    level: str,
    bandPosition: str | float,
    relevance: str | float,
    complexity: str | float,
    managementRole: str,
    startupMultiple: float = 1.0,
) -> dict:
    
    '''

    Calculate salary using the compensation formula.
    Formula: (Base * Relevance * Complexity + Management Premium) * Startup Multiple

    Parameters:
    -----------
    level : str
        Technical level ('Level 1', 'Level 2', 'Level 3', 'Level 4', 'Level 5')
    bandPosition : str or float
        Position within band. Accepts 'Min', 'Median', 'Max' strings or a
        float 0.0-1.0 that interpolates linearly between min and max.
    relevance : str or float
        Experience relevance. Accepts 'Low', 'Medium', 'High' strings or a
        float multiplier (e.g. 1.0 to 1.05).
    complexity : str or float
        Experience complexity. Accepts 'Low', 'Medium', 'High' strings or a
        float multiplier (e.g. 1.0 to 1.05).
    managementRole : str
        Management role ('Engineer', 'RE', 'Lead', 'Director')
    startupMultiple : float
        Startup equity multiple (default 1.0)

    Returns:
    --------
    dict : Breakdown of salary calculation

    '''

    band = salaryBands[level]

    # Resolve band position to a base salary
    if isinstance(bandPosition, str):
        positionMap = {'Min': 'min', 'Median': 'median', 'Max': 'max'}
        baseSalary = band[positionMap[bandPosition]]
        bandPercent = (baseSalary - band['min']) / max(band['max'] - band['min'], 1)
    else:
        # Float 0.0-1.0 interpolation between min and max
        bandPercent = float(bandPosition)
        baseSalary = band['min'] + bandPercent * (band['max'] - band['min'])

    # Resolve relevance multiplier
    if isinstance(relevance, str):
        relevanceMultiplier = experienceModifiers['relevance'][relevance]
    else:
        relevanceMultiplier = float(relevance)

    # Resolve complexity multiplier
    if isinstance(complexity, str):
        complexityMultiplier = experienceModifiers['complexity'][complexity]
    else:
        complexityMultiplier = float(complexity)

    managementPremium = managementPremiums[managementRole]

    # Apply modifiers to base salary first, then add the flat management premium.
    # This ordering prevents management premiums from being amplified by experience
    # modifiers, which would disproportionately benefit senior managers.
    adjustedBase = baseSalary * relevanceMultiplier * complexityMultiplier
    totalBeforeMultiple = adjustedBase + managementPremium
    finalSalary = totalBeforeMultiple * startupMultiple

    return {
        'baseSalary': baseSalary,
        'bandPercent': bandPercent,
        'relevanceMultiplier': relevanceMultiplier,
        'complexityMultiplier': complexityMultiplier,
        'adjustedBase': adjustedBase,
        'managementPremium': managementPremium,
        'totalBeforeMultiple': totalBeforeMultiple,
        'startupMultiple': startupMultiple,
        'finalSalary': finalSalary,
        'bandMin': band['min'],
        'bandMax': band['max'],
        'bandMedian': band['median'],
    }

def auditEmployee(
    level: str,
    managementRole: str,
    yearsExperience: float,
    currentSalary: float,
    relevance: str = 'Medium',
    complexity: str = 'Medium',
) -> dict:
    
    '''

    Audit an individual employee's compensation against the salary bands.

    Parameters:
    -----------
    level : str
        Technical level key ('I', 'II', 'III', 'IV', 'V')
    managementRole : str
        Management role ('None', 'Engineer', 'RE', 'Lead', 'Director', 'Chief')
    yearsExperience : float
        Years of relevant experience
    currentSalary : float
        Current annual salary
    relevance : str
        Experience relevance level
    complexity : str
        Experience complexity level

    Returns:
    --------
    dict : Audit results with compliance status and recommendations

    '''

    # Map level key to salary band name
    levelToBand = {'I': 'Level 1', 'II': 'Level 2', 'III': 'Level 3', 'IV': 'Level 4', 'V': 'Level 5'}
    bandName = levelToBand[level]
    band = salaryBands[bandName]
    extended = extendedBands[bandName]
    levelInfo = levelsData[level]

    results = {
        'bandName': bandName,
        'bandMin': band['min'],
        'bandMax': band['max'],
        'bandMedian': band['median'],
        'extendedMax': extended['extendedMax'],
        'issues': [],
        'recommendations': [],
        'complianceStatus': 'In Band',
    }

    # Check salary vs band
    if currentSalary < band['min']:
        results['complianceStatus'] = 'Below Band'
        deficit = band['min'] - currentSalary
        results['issues'].append(f'Salary is ${deficit:,.0f} below band minimum (${band["min"]:,.0f})')
        results['recommendations'].append(f'Consider adjustment to at least ${band["min"]:,.0f}')
    elif currentSalary > extended['extendedMax']:
        results['complianceStatus'] = 'Above Band'
        excess = currentSalary - extended['extendedMax']
        results['issues'].append(f'Salary is ${excess:,.0f} above extended maximum (${extended["extendedMax"]:,.0f})')
        results['recommendations'].append('Consider promotion to next level or review compensation justification')
    elif currentSalary > band['max']:
        results['complianceStatus'] = 'Extended Range'
        results['issues'].append(
            f'Salary (${currentSalary:,.0f}) is above standard max (${band["max"]:,.0f}) '
            f'but within extended range (${extended["extendedMax"]:,.0f})'
        )
        results['recommendations'].append('Verify experience modifiers and management premium justify extended range')

    # Check management role validity
    if managementRole not in ('None', 'Engineer'):
        eligibility = levelInfo['managementEligibility']
        if managementRole in eligibility and not eligibility[managementRole]:
            minLevel = managementMinLevel[managementRole]
            results['issues'].append(
                f'{managementRole} role is not eligible at Level {level} '
                f'(minimum Level {minLevel} required)'
            )
            results['recommendations'].append(
                f'Either promote to Level {minLevel} or reassign management role'
            )

    # Check experience vs level alignment
    minExp = levelInfo['minExperience']
    maxExp = levelInfo['maxExperience']

    if yearsExperience < minExp:
        results['issues'].append(
            f'{yearsExperience:.0f} years experience is below the minimum '
            f'({minExp} years) for Level {level}'
        )
        results['recommendations'].append('Verify experience assessment or consider lower level assignment')

    # Allow a 2-year buffer above the level's max experience before flagging.
    # This accounts for engineers who are performing well at their current level
    # but haven't yet been promoted -- promotion timing is discretionary.
    if maxExp is not None and yearsExperience > maxExp + 2:
        results['issues'].append(
            f'{yearsExperience:.0f} years experience exceeds typical range '
            f'for Level {level} ({levelInfo["experienceLabel"]})'
        )
        results['recommendations'].append('Consider promotion review to next level')

    # Calculate expected salary for comparison
    calcResult = calculateSalary(bandName, 'Median', relevance, complexity, 'Engineer')
    results['expectedMedian'] = calcResult['finalSalary']
    results['salaryVsMedian'] = currentSalary - calcResult['finalSalary']
    results['salaryPercentInBand'] = _calculateBandPercentile(
        currentSalary, band['min'], extended['extendedMax']
    )

    return results

def _calculateBandPercentile(salary: float, bandMin: float, bandMax: float) -> float:

    '''

    Calculate where a salary falls within a band as a percentage (0-100).

    Parameters:
    -----------
    salary : float
        The salary to evaluate
    bandMin : float
        Bottom of the band
    bandMax : float
        Top of the band (extended max)

    Returns:
    --------
    float : Percentage position within band (can be <0 or >100)

    '''

    if bandMax == bandMin:
        return 50.0
    else:
        return ((salary - bandMin) / (bandMax - bandMin)) * 100

# ---------------------------------------------------------------------- #
# -- Survey Data Helper Functions -- #
# ---------------------------------------------------------------------- #

def filterMarketBenchmarks(
    surveyDf: pd.DataFrame,
    experience: Optional[float] = None,
    discipline: Optional[str] = None,
    companies: Optional[List[str]] = None,
) -> pd.DataFrame:
    
    '''

    Filter survey data to get market benchmarks for comparison.

    Parameters:
    -----------
    surveyDf : pd.DataFrame
        The full survey dataset
    experience : float, optional
        Years of experience to filter around (+/- 2 years)
    discipline : str, optional
        Engineering discipline to filter
    companies : list, optional
        List of company names to include

    Returns:
    --------
    pd.DataFrame : Filtered survey data

    '''

    filtered = surveyDf.copy()

    if experience is not None:
        filtered = filtered[
            (filtered['Estimated'] >= experience - 2) &
            (filtered['Estimated'] <= experience + 2)
        ]

    if discipline is not None and discipline != 'All':
        filtered = filtered[filtered['Discipline'].str.contains(discipline, case = False, na = False)]

    if companies is not None and len(companies) > 0:
        filtered = filtered[filtered['Company'].isin(companies)]

    return filtered

def surveyCompanies(surveyDf: pd.DataFrame) -> list:

    '''

    Get sorted list of unique companies in the survey data.

    Parameters:
    -----------
    surveyDf : pd.DataFrame
        The survey dataset

    Returns:
    --------
    list : Sorted company names
    
    '''
    
    return sorted(surveyDf['Company'].dropna().unique().tolist())

def surveyDisciplines(surveyDf: pd.DataFrame) -> list:

    '''

    Get sorted list of unique disciplines in the survey data.

    Parameters:
    -----------
    surveyDf : pd.DataFrame
        The survey dataset

    Returns:
    --------
    list : Sorted discipline names

    '''

    disciplines = surveyDf['Discipline'].dropna().unique().tolist()
    cleaned = sorted(set(d.strip() for d in disciplines if d.strip() and d.strip() != 'nan'))

    return cleaned

def surveyStates(surveyDf: pd.DataFrame) -> list:

    '''

    Get sorted list of unique states in the survey data.

    Parameters:
    -----------
    surveyDf : pd.DataFrame
        The survey dataset

    Returns:
    --------
    list : Sorted state abbreviations

    '''

    states = surveyDf['State'].dropna().unique().tolist()
    cleaned = sorted(set(s.strip() for s in states if s.strip() and s.strip() != 'nan'))

    return cleaned

def levelForExperience(yearsExperience: float) -> str:

    '''

    Determine the appropriate level for a given years of experience.

    Parameters:
    -----------
    yearsExperience : float
        Years of experience

    Returns:
    --------
    str : Recommended level key ('I' through 'V')

    '''

    if yearsExperience >= 12:
        return 'V'
    elif yearsExperience >= 7:
        return 'IV'
    elif yearsExperience >= 4:
        return 'III'
    elif yearsExperience >= 2:
        return 'II'
    else:
        return 'I'

# ---------------------------------------------------------------------- #
# -- Scraper Integration Helpers -- #
# ---------------------------------------------------------------------- #

def scraperCacheDir() -> str:

    '''

    Return the path to the scraper cache directory.
    Creates it if it does not exist.

    Returns:
    --------
    str : Absolute path to cache directory

    '''

    cacheDir = os.path.join(_toolsDir, '.scraperCache')
    os.makedirs(cacheDir, exist_ok = True)

    return cacheDir

def validatedCacheDir() -> str:

    '''

    Return the path to the validated analysis cache directory.
    Creates it if it does not exist. Parallel to scraperCacheDir(),
    used by the Validated Market Analysis page for snapshots.

    Returns:
    --------
    str : Absolute path to validated cache directory

    '''

    cacheDir = os.path.join(_toolsDir, '.validatedCache')
    os.makedirs(cacheDir, exist_ok = True)

    return cacheDir

def mergeScrapedData(
    existingDf: pd.DataFrame,
    scrapedDf: pd.DataFrame,
    deduplicateBy: Optional[List[str]] = None,
) -> pd.DataFrame:
    
    '''

    Merge scraped compensation data with the existing survey DataFrame.
    Deduplicates on (Company, Listing, Location) by default, preserving
    existing data when duplicates are found.

    Parameters:
    -----------
    existingDf : pd.DataFrame
        The loaded survey data from loadMarketSurveyData()
    scrapedDf : pd.DataFrame
        Newly scraped data in the same schema
    deduplicateBy : list, optional
        Columns to use for deduplication

    Returns:
    --------
    pd.DataFrame : Combined and deduplicated DataFrame

    '''

    if deduplicateBy is None:
        deduplicateBy = ['Company', 'Listing', 'Location']

    # Tag source if not already tagged
    if 'DataSource' not in existingDf.columns:
        existingDf = existingDf.copy()
        existingDf['DataSource'] = 'Survey'
    if 'DataSource' not in scrapedDf.columns:
        scrapedDf = scrapedDf.copy()
        scrapedDf['DataSource'] = 'Scraped'

    # Align columns - add any missing columns from survey schema
    for col in surveyColumns:
        if col not in scrapedDf.columns:
            scrapedDf[col] = None

    # Combine with existing data first so that survey entries (manually curated)
    # take precedence over scraped entries when duplicates are found.
    combined = pd.concat([existingDf, scrapedDf], ignore_index=True)

    # Only deduplicate on columns that exist in both DataFrames
    validDedupCols = [c for c in deduplicateBy if c in combined.columns]
    if validDedupCols:
        combined = combined.drop_duplicates(subset=validDedupCols, keep='first')

    combined = combined.reset_index(drop=True)

    # Recalculate midpoints if Min and Max are present
    if 'Min' in combined.columns and 'Max' in combined.columns:
        combined['Midpoint'] = (
            pd.to_numeric(combined['Min'], errors='coerce') +
            pd.to_numeric(combined['Max'], errors='coerce')
        ) / 2

    return combined

# ---------------------------------------------------------------------- #
# -- Dataset Selector Utilities -- #
# ---------------------------------------------------------------------- #

# Available dataset sources for visualization pages. Keys are session state
# identifiers; values are display labels shown in the selector widget.
datasetSources = {
    'survey': 'Synthetic Survey Data (Default)',
    'scraped': 'Last Scraped Data',
    'merged': 'Merged (Survey + Scraped)',
    'imported': 'Imported Dataset',
}

def activeDataset(sessionState: dict) -> pd.DataFrame:

    '''

    Return the currently selected dataset from session state.
    Falls back to the default survey data if no selection or
    no scraped data is available.

    Parameters:
    -----------
    sessionState : dict
        Streamlit session state (or dict-like object)

    Returns:
    --------
    pd.DataFrame : The active dataset for visualizations

    '''

    source = sessionState['datasetSource']
    if source == 'scraped' and 'scrapedDataset' in sessionState:
        return sessionState['scrapedDataset']
    elif source == 'merged' and 'mergedDataset' in sessionState:
        return sessionState['mergedDataset']
    elif source == 'imported' and 'importedDataset' in sessionState:
        return sessionState['importedDataset']
    else:
    # Default: load the curated survey data
        return loadMarketSurveyData()
    
def renderDatasetSelector() -> pd.DataFrame:

    '''

    Render a dataset source selector widget and return the selected
    DataFrame. Stores the selection in st.session_state so it persists
    across reruns.

    Options:
    - Synthetic Survey (default) -- loads from the synthetic survey CSV
    - Last Scraped Data -- from session state (if a scrape has been run)
    - Merged (Survey + Scraped) -- combines both
    - Import CSV/Excel -- file uploader for external datasets

    Returns:
    --------
    pd.DataFrame : The selected dataset ready for visualization

    '''
    
    import streamlit as st

    # Initialize session state defaults
    if 'datasetSource' not in st.session_state:
        st.session_state.datasetSource = 'survey'

    # Build available options based on what data exists in session state
    options = {'survey': datasetSources['survey']}
    if 'scrapedDataset' in st.session_state:
        options['scraped'] = datasetSources['scraped']
    if 'mergedDataset' in st.session_state:
        options['merged'] = datasetSources['merged']
    options['imported'] = datasetSources['imported']

    # Render selector
    selectorCol, statusCol = st.columns([3, 1])
    with selectorCol:
        selectedKey = st.selectbox(
            'Dataset',
            list(options.keys()),
            format_func=lambda k: options[k],
            key='datasetSource',
            label_visibility='collapsed',
        )
    with statusCol:
        # Show record count for the active dataset
        activeDf = activeDataset(st.session_state)
        st.caption(f'{len(activeDf):,} records')

    # Handle file import when "imported" is selected
    if selectedKey == 'imported':
        uploaded = st.file_uploader(
            'Upload CSV or Excel',
            type=['csv', 'xlsx', 'xls'],
            key='datasetUploader',
        )
        if uploaded is not None:
            if uploaded.name.endswith('.csv'):
                importedDf = pd.read_csv(uploaded)
            else:
                importedDf = pd.read_excel(uploaded)
            st.session_state.importedDataset = importedDf
            return importedDf
        elif 'importedDataset' in st.session_state:
            return st.session_state.importedDataset
        else:
            # No file uploaded yet -- fall back to survey
            st.info('Upload a file to use an imported dataset.')
            return loadMarketSurveyData()

    return activeDataset(st.session_state)
