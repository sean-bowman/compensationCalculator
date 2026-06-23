
# -- Aerospace Compensation Scraper -- #

'''

Modular web scraper for aerospace compensation data from public sources.
Each data source is an independent method that returns normalized DataFrames
compatible with the existing survey data schema. Sources that fail do not
block other sources from completing.

Supported Sources:
    - BLS OEWS (Bureau of Labor Statistics - Occupational Employment & Wages)
    - FRED (Federal Reserve Economic Data - earnings time series)
    - H1B Data (public visa salary disclosures)
    - Levels.fyi (company/level salary data)
    - Data USA (Census/ACS aggregates)
    - Glassdoor (salary estimates from employee reports)
    - PayScale (salary research from employee data)
    - ZipRecruiter (salary estimates from job postings)
    - Comparably (company salary comparisons)
    - Indeed (salary estimates from job postings)
    - Salary.com (benchmark salary data with percentiles by job level)

Author: Sean Bowman
Date:   02/26/2026

'''

# Standard library imports
import os
import re
import time
import json
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Callable

# Third-party imports
import requests
import pandas as pd
from bs4 import BeautifulSoup

# JobSpy is an open-source Python library for scraping job listings from
# Glassdoor, Indeed, ZipRecruiter, and LinkedIn without a paid proxy.
# Install with: pip install python-jobspy
# The import is deferred to call time so it is retried on each scrape run
# without requiring a process restart after package installation.
def _tryImportJobspy():
    '''
    Attempt to import scrape_jobs from python-jobspy.

    Returns:
    --------
    tuple : (callable or None, error_message or None)
    '''
    try:
        from jobspy import scrape_jobs
        return scrape_jobs, None
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'

# Local imports
from auditUtils import surveyColumns, scraperCacheDir
from referenceParser import loadReferenceData, deriveCompanyUrlSlugs

# ---------------------------------------------------------------------- #
# -- Logging Setup -- #
# ---------------------------------------------------------------------- #

# The scraper logger provides real-time progress feedback during CLI-driven
# scraping sessions (scraperInterface.py). It reports which data sources are
# being fetched, HTTP response codes, cache hits, and per-source row counts.
# In the Streamlit web UI, scraping progress is shown via st.status() widgets
# instead -- the logger is not displayed there. The logger is the primary
# feedback mechanism for API and CLI calls, where no web interface is available.
#
# Logging levels used in this module:
#   INFO    - Source start/completion, row counts, cache clears
#   DEBUG   - Cache hits, individual URL fetches
#   WARNING - HTTP errors, empty results, missing API keys
#   ERROR   - Parse failures, request exceptions
logger = logging.getLogger('compensationScraper')
logger.setLevel(logging.INFO)

# Attach a console (stderr) handler so log messages are visible in terminal
# sessions. The guard (if not logger.handlers) prevents duplicate handlers
# when the module is re-imported (e.g., during Streamlit hot-reload).
# StreamHandler() defaults to sys.stderr, which keeps log output separate
# from any stdout data the scraper may produce.
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'
    ))
    logger.addHandler(_handler)

# ---------------------------------------------------------------------- #
# -- Configuration -- #
# ---------------------------------------------------------------------- #

# Reference data is parsed from the compensation reference markdown files
# so those documents remain the single source of truth for companies,
# SOC codes, and other configurable values. See referenceParser.py.
_referenceData = loadReferenceData()

# Companies parsed from the "Salary Aggregator Data" section of
# compensationReference.md. Includes both new-space competitors
# and traditional defense primes for full market spectrum.
defaultTargetCompanies = _referenceData['companies']

# SOC codes parsed from the "Government and BLS Data" section.
# 17-2011 (Aerospace), 17-2141 (Mechanical), and 17-2071 (Electrical)
# are included because many aerospace roles are cross-classified.
defaultSocCodes = [code for code, label in _referenceData['socCodes']]

# Lookup dict for SOC code -> human-readable label, keyed by the
# hyphen-stripped format used in BLS API series IDs (e.g., '172011')
_defaultSocLabels = {
    code.replace('-', ''): label
    for code, label in _referenceData['socCodes']
}

# FIPS state codes used for state-level BLS API queries. These states represent
# major aerospace industry hubs. One state is used as the geographic baseline
# (0.0%) for cost-of-living normalization in multi-location compensation analysis;
# California (06) and Washington (53) are typically the highest-paying markets.
stateFips = {
    'FL': '12', 'CA': '06', 'TX': '48', 'WA': '53',
    'CO': '08', 'AL': '01', 'AZ': '04', 'VA': '51',
}

# ---------------------------------------------------------------------- #
# -- API Key Persistence -- #
# ---------------------------------------------------------------------- #

# Path to the local API key store. This file is gitignored and never committed.
# It is written by saveApiKeys() and auto-populated from APIKeys.md on first load.
_apiKeysPath = os.path.join(os.path.dirname(__file__), 'apiKeys.json')

# Path to the human-maintained API key markdown file. Located in documentation/
# so it can be stored alongside other project references. Also gitignored.
_apiKeysMdPath = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'documentation', 'APIKeys.md')


def _parseApiKeysMd() -> dict:
    '''
    Parse API keys from documentation/APIKeys.md.

    Expected format (section headers followed by key on the next non-blank line):
        ## FRED
        <key>

        ## BLS
        <key>

    Returns:
    --------
    dict : Keys dict with blsApiKey and fredApiKey fields.
           Any key not found in the file is returned as an empty string.
    '''
    if not os.path.exists(_apiKeysMdPath):
        return {}

    try:
        with open(_apiKeysMdPath, 'r', encoding='utf-8') as f:
            content = f.read()
    except OSError:
        return {}

    keys = {'blsApiKey': '', 'fredApiKey': ''}

    # Find each ## Section header and grab the first non-blank line after it.
    # Handles case-insensitive header names and leading/trailing whitespace.
    sectionMap = {
        'fred': 'fredApiKey',
        'bls': 'blsApiKey',
    }

    lines = content.splitlines()
    currentSection = None
    for line in lines:
        stripped = line.strip()

        # Check for a ## section header
        if stripped.startswith('##'):
            headerText = stripped.lstrip('#').strip().lower()
            currentSection = sectionMap.get(headerText)
            continue

        # If we are inside a known section, grab the first non-blank, non-header line as the key
        if currentSection and stripped and not stripped.startswith('#'):
            keys[currentSection] = stripped
            currentSection = None  # Reset so subsequent lines in the same section are ignored

    return keys


def _loadSavedApiKeys() -> dict:
    '''
    Load persisted API keys from tools/apiKeys.json.

    Returns:
    --------
    dict : Keys dict with blsApiKey and fredApiKey fields,
           or empty dict if the file does not exist.
    '''
    if os.path.exists(_apiKeysPath):
        try:
            with open(_apiKeysPath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def loadApiKeys() -> dict:
    '''
    Load API keys with the following priority order:
      1. tools/apiKeys.json  (previously saved/cached, gitignored)
      2. documentation/APIKeys.md  (human-maintained file, gitignored)

    If APIKeys.md is found but apiKeys.json does not exist, the keys from
    the markdown file are written to apiKeys.json so they persist for future loads.

    Returns:
    --------
    dict : Keys dict with blsApiKey and fredApiKey fields.
           Any unavailable key is an empty string.
    '''
    jsonKeys = _loadSavedApiKeys()
    if any(v for v in jsonKeys.values()):
        return jsonKeys

    # Fall back to APIKeys.md
    mdKeys = _parseApiKeysMd()
    if any(v for v in mdKeys.values()):
        # Cache to apiKeys.json so subsequent calls are faster
        try:
            saveApiKeys(**mdKeys)
        except OSError:
            pass  # Non-fatal: apiKeys.json will just be re-parsed next time
        return mdKeys

    return {'blsApiKey': '', 'fredApiKey': ''}


def saveApiKeys(blsApiKey: str = '', fredApiKey: str = '') -> None:
    '''
    Persist API keys to tools/apiKeys.json (gitignored).

    Parameters:
    -----------
    blsApiKey : str
        BLS v2 API key (optional)
    fredApiKey : str
        FRED API key
    '''
    data = {
        'blsApiKey': blsApiKey.strip(),
        'fredApiKey': fredApiKey.strip(),
    }
    with open(_apiKeysPath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)


def clearApiKeys() -> None:
    '''Delete the persisted API key file if it exists.'''
    if os.path.exists(_apiKeysPath):
        os.remove(_apiKeysPath)


def hasSavedApiKeys() -> bool:
    '''Return True if a saved API key file exists with at least one non-empty key.'''
    keys = _loadSavedApiKeys()
    return any(v for v in keys.values())


def validateApiKeys(blsApiKey: str = '', fredApiKey: str = '') -> dict:
    '''
    Test each provided API key with a lightweight validation request.

    Parameters:
    -----------
    blsApiKey : str
        BLS v2 API key to test (optional)
    fredApiKey : str
        FRED API key to test

    Returns:
    --------
    dict : Results keyed by 'bls' and 'fred'.
           Each value is a dict with 'ok' (bool) and 'message' (str).
    '''
    results = {}

    # -- BLS validation -- #
    # Query the /timeseries/data/ endpoint with a known series (national aerospace wages).
    # A valid key returns a 200 response; an invalid key returns a 400 with error message.
    if blsApiKey:
        try:
            resp = requests.post(
                'https://api.bls.gov/publicAPI/v2/timeseries/data/',
                json={'seriesid': ['OEU000000000000001'], 'registrationkey': blsApiKey},
                timeout=10,
            )
            if resp.status_code == 200:
                payload = resp.json()
                if payload.get('status') == 'REQUEST_SUCCEEDED':
                    results['bls'] = {'ok': True, 'message': 'BLS v2 key is valid.'}
                else:
                    msg = '; '.join(payload.get('message', ['Unknown error']))
                    results['bls'] = {'ok': False, 'message': f'BLS key rejected: {msg}'}
            else:
                results['bls'] = {'ok': False, 'message': f'BLS returned HTTP {resp.status_code}.'}
        except requests.RequestException as e:
            results['bls'] = {'ok': False, 'message': f'BLS connection error: {e}'}
    else:
        results['bls'] = {'ok': None, 'message': 'No BLS key provided (v1 rate limits apply).'}

    # -- FRED validation -- #
    # Query a known series (median weekly earnings, all workers). Returns 200 on valid key,
    # 400 with 'Bad Request' on invalid key.
    if fredApiKey:
        try:
            resp = requests.get(
                'https://api.stlouisfed.org/fred/series',
                params={'series_id': 'LES1252881600Q', 'api_key': fredApiKey, 'file_type': 'json'},
                timeout=10,
            )
            if resp.status_code == 200:
                results['fred'] = {'ok': True, 'message': 'FRED key is valid.'}
            elif resp.status_code == 400:
                results['fred'] = {'ok': False, 'message': 'FRED key rejected (bad request or invalid key).'}
            else:
                results['fred'] = {'ok': False, 'message': f'FRED returned HTTP {resp.status_code}.'}
        except requests.RequestException as e:
            results['fred'] = {'ok': False, 'message': f'FRED connection error: {e}'}
    else:
        results['fred'] = {'ok': False, 'message': 'No FRED key provided. FRED source will be skipped.'}

    return results


# Dataclasses are a type of Python class that automatically generates special methods like __init__(),
# __repr__(), and __eq__() based on class attributes. They are ideal for configuration objects because
# they provide a clear and concise way to define the expected parameters, their types, and default values.
# In this scraper, ScraperConfig is a dataclass that encapsulates all the configurable settings for the
# CompensationScraper, such as API keys, caching options, request delays, target companies and SOC codes,
# and HTTP timeouts. Using a dataclass makes it easy to create and manage scraper instances with different
# configurations, and to ensure that all necessary parameters are provided with the correct types.
@dataclass
class ScraperConfig:

    '''

    Configuration for the CompensationScraper.

    Parameters:
    -----------
    blsApiKey : str
        BLS API v2 registration key (optional, v1 works without)
    fredApiKey : str
        FRED API key from https://fred.stlouisfed.org/docs/api/api_key.html
    cacheDir : str
        Directory for cached responses (default: .scraperCache in tools/)
    cacheTtlHours : int
        How long cached responses remain valid (default 168 = 1 week)
    requestDelaySeconds : float
        Minimum delay between HTTP requests (default 2.0)
    userAgent : str
        User-Agent header for requests
    targetCompanies : list
        Companies to search for
    targetSocCodes : list
        SOC codes to query
    timeoutSeconds : int
        HTTP request timeout

    '''

    blsApiKey: str = ''
    fredApiKey: str = ''
    cacheDir: str = ''
    cacheTtlHours: int = 168  # 1 week -- BLS/FRED data updates infrequently
    requestDelaySeconds: float = 2.0  # Respectful rate limit for public APIs
    userAgent: str = 'CompensationAudit/1.0 (Research)' # Name of scraper for API identification
    # Default target companies and SOC codes are loaded from the compensation reference markdown files
    # to keep them centralized and editable without code changes.
    # The lambda function syntax with copy() ensures that the default lists are not shared across instances, allowing for safe mutation if needed.
    targetCompanies: List[str] = field(default_factory = lambda: defaultTargetCompanies.copy())
    targetSocCodes: List[str] = field(default_factory = lambda: defaultSocCodes.copy())
    timeoutSeconds: int = 30

    # The __post_init__ method is called automatically after the dataclass is initialized.
    # It sets a default cache directory if one was not provided, using the scraperCacheDir() function
    # from auditUtils.py, and loads any persisted API keys from tools/apiKeys.json if present.
    def __post_init__(self):
        '''Set default cache directory and load persisted API keys if present.'''
        if not self.cacheDir:
            self.cacheDir = scraperCacheDir()

        # Load API keys from apiKeys.json or APIKeys.md (both gitignored).
        # Only fills fields that were not explicitly set by the caller (still at default '').
        # This allows programmatic callers to override loaded keys by passing them explicitly.
        savedKeys = loadApiKeys()
        if savedKeys:
            if not self.blsApiKey and savedKeys.get('blsApiKey'):
                self.blsApiKey = savedKeys['blsApiKey']
            if not self.fredApiKey and savedKeys.get('fredApiKey'):
                self.fredApiKey = savedKeys['fredApiKey']

# ---------------------------------------------------------------------- #
# -- Main Scraper Class -- #
# ---------------------------------------------------------------------- #

class CompensationScraper:

    '''

    Modular aerospace compensation data scraper.

    Each data source is an independent method returning a DataFrame with
    columns matching the surveyColumns schema. Sources that fail do not
    block other sources.

    Parameters:
    -----------
    config : ScraperConfig, optional
        Scraper configuration. Uses defaults if not provided.

    Examples:
    ---------
    >>> scraper = CompensationScraper()
    >>> results = scraper.scrapeAll()
    >>> merged = scraper.mergeResults(results)

    '''

    # Available data sources with metadata
    availableSources = {
        'dataUsa': {
            'name': 'Data USA',
            'description': 'Census/ACS aggregate wage data by occupation',
            'requiresKey': False,
            'tier': 1,
        },
        'bls': {
            'name': 'BLS OEWS',
            'description': 'Bureau of Labor Statistics occupational wage percentiles',
            'requiresKey': False,
            'tier': 1,
        },
        'fred': {
            'name': 'FRED',
            'description': 'Federal Reserve median earnings time series',
            'requiresKey': True,
            'tier': 1,
        },
        'h1b': {
            'name': 'H1B Data',
            'description': 'Public H1B visa salary disclosures by employer',
            'requiresKey': False,
            'tier': 2,
        },
        'levelsFyi': {
            'name': 'Levels.fyi',
            'description': 'Employee-reported compensation by company and level',
            'requiresKey': False,
            'tier': 2,
        },
        'glassdoor': {
            'name': 'Glassdoor',
            'description': 'Salary estimates from employee reports and job postings',
            'requiresKey': False,
            'tier': 2,
        },
        'payscale': {
            'name': 'PayScale',
            'description': 'Salary research based on employee-reported compensation',
            'requiresKey': False,
            'tier': 2,
        },
        'ziprecruiter': {
            'name': 'ZipRecruiter',
            'description': 'Salary estimates based on job posting data',
            'requiresKey': False,
            'tier': 2,
        },
        'comparably': {
            'name': 'Comparably',
            'description': 'Company salary comparisons and compensation data',
            'requiresKey': False,
            'tier': 3,
        },
        'indeed': {
            'name': 'Indeed',
            'description': 'Salary estimates from aggregated job posting data',
            'requiresKey': False,
            'tier': 2,
        },
        'salaryCom': {
            'name': 'Salary.com',
            'description': 'Benchmark salary data with percentiles by job level (I-V)',
            'requiresKey': False,
            'tier': 2,
        },
        'careerPages': {
            'name': 'Career Pages',
            'description': 'Direct job listings from company career websites (Greenhouse, Workday, etc.)',
            'requiresKey': False,
            'tier': 1,
        },
    }

    def __init__(self, config: Optional[ScraperConfig] = None) -> None:

        '''
        
        Initialize the scraper with configuration.
        
        Parameters:
        -----------
        config : ScraperConfig, optional
            Scraper configuration. If None, defaults are used.
        
        '''
        self.config = config or ScraperConfig()
        self._lastRequestTime = 0.0
        os.makedirs(self.config.cacheDir, exist_ok=True)

    # ------------------------------------------------------------------ #
    # -- Internal Helpers -- #
    # ------------------------------------------------------------------ #

    def _rateLimitWait(self) -> None:

        '''
        
        Enforce minimum delay between HTTP requests.
        
        '''

        elapsed = time.time() - self._lastRequestTime

        if elapsed < self.config.requestDelaySeconds:
            time.sleep(self.config.requestDelaySeconds - elapsed)

    def _cacheKey(self, url: str, params: Optional[Dict] = None) -> str:

        '''
        
        Generate a cache key from URL and parameters.
        
        Parameters:
        -----------
        url : str
            Request URL
        params : dict, optional
            Query parameters
        
        Returns:
        --------
        str : Cache key

        '''

        keyStr = url + json.dumps(params or {}, sort_keys=True)

        return hashlib.md5(keyStr.encode()).hexdigest()

    def _cachePath(self, cacheKey: str) -> str:

        '''
        
        Return file path for a cache key inside cacheDir.
        
        Parameters:
        -----------
        cacheKey : str
            Cache key
        
        Returns:
        --------
        str : File path

        '''

        return os.path.join(self.config.cacheDir, f'{cacheKey}.json')

    def _loadFromCache(self, cacheKey: str) -> Optional[str]:

        '''
        Load cached response text if within TTL, else None.

        Parameters:
        -----------
        cacheKey : str
            The cache key to look up

        Returns:
        --------
        str or None : Cached content if valid, else None

        '''

        cachePath = self._cachePath(cacheKey)

        if not os.path.exists(cachePath):
            return None

        try:
            with open(cachePath, 'r', encoding='utf-8') as f:
                cached = json.load(f)

            cachedTime = datetime.fromisoformat(cached['timestamp'])
            if datetime.now() - cachedTime > timedelta(hours=self.config.cacheTtlHours):
                return None

            return cached['content']
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    def _saveToCache(self, cacheKey: str, content: str, url: str = ''):

        '''

        Write response text to cache file.

        Parameters:
        -----------
        cacheKey : str
            The cache key
        content : str
            Response content to cache
        url : str
            Original URL for reference

        '''

        cachePath = self._cachePath(cacheKey)
        cacheData = {
            'timestamp': datetime.now().isoformat(),
            'url': url,
            'content': content,
        }

        try:
            with open(cachePath, 'w', encoding='utf-8') as f:
                json.dump(cacheData, f)
        except OSError as e:
            logger.warning(f'Failed to write cache: {e}')

    @property
    def _browserHeaders(self) -> Dict[str, str]:
        '''Browser-like headers for sites with bot detection.'''
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }

    def _makeRequest(
        self,
        url: str,
        method: str = 'GET',
        headers: Optional[Dict] = None,
        params: Optional[Dict] = None,
        jsonBody: Optional[Dict] = None,
        useCache: bool = True,
        sourceName: str = '',
        suppressWarnings: bool = False,
    ) -> Optional[str]:

        '''

        Rate-limited HTTP request with caching.

        Parameters:
        -----------
        url : str
            Request URL
        method : str
            HTTP method (GET or POST)
        headers : dict, optional
            Additional headers
        params : dict, optional
            Query parameters
        jsonBody : dict, optional
            JSON body for POST requests
        useCache : bool
            Whether to use caching (default True)
        sourceName : str
            Source identifier for logging context (unused for routing)
        suppressWarnings : bool
            When True, log non-200 HTTP responses at DEBUG instead of WARNING.
            Useful for sources where 404 is expected (e.g. Levels.fyi company
            pages that simply do not exist for every company).

        Returns:
        --------
        str or None : Response text, or None if request failed

        '''

        cacheKey = self._cacheKey(url, params or jsonBody)

        # Check cache first
        if useCache:
            cached = self._loadFromCache(cacheKey)
            if cached is not None:
                logger.debug(f'Cache hit for {url}')
                return cached

        # Rate limit
        self._rateLimitWait()

        requestHeaders = {'User-Agent': self.config.userAgent}
        if headers:
            requestHeaders.update(headers)

        try:
            if method.upper() == 'POST':
                response = requests.post(
                    url, headers=requestHeaders, json=jsonBody,
                    timeout=self.config.timeoutSeconds,
                )
            else:
                response = requests.get(
                    url, headers=requestHeaders, params=params,
                    timeout=self.config.timeoutSeconds,
                )

            self._lastRequestTime = time.time()

            if response.status_code == 200:
                content = response.text
                if useCache:
                    self._saveToCache(cacheKey, content, url)
                return content
            else:
                if suppressWarnings:
                    logger.debug(f'HTTP {response.status_code} from {url}')
                else:
                    logger.warning(f'HTTP {response.status_code} from {url}')
                return None

        except requests.RequestException as e:
            logger.error(f'Request failed for {url}: {e}')
            return None

    def _normalizeToSchema(
        self,
        rawDf: pd.DataFrame,
        columnMapping: Dict[str, str],
        source: str,
        keepWithoutSalary: bool = False,
    ) -> pd.DataFrame:

        '''

        Map arbitrary DataFrame columns to surveyColumns schema.

        Parameters:
        -----------
        rawDf : pd.DataFrame
            Raw data from a scraper source
        columnMapping : dict
            Maps source column names to surveyColumns names
        source : str
            Data source identifier for provenance
        keepWithoutSalary : bool
            If True, retain rows where both Min and Max are NaN (useful for
            career page listings that provide title/location data without salary).
            Default False preserves the existing plausibility gate behavior.

        Returns:
        --------
        pd.DataFrame : Normalized DataFrame with surveyColumns + DataSource

        '''

        if rawDf.empty:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        normalized = pd.DataFrame()

        # Map provided columns
        for sourceCol, targetCol in columnMapping.items():
            if sourceCol in rawDf.columns:
                normalized[targetCol] = rawDf[sourceCol]

        # Fill missing survey columns with None
        for col in surveyColumns:
            if col not in normalized.columns:
                normalized[col] = None

        # Add provenance column
        normalized['DataSource'] = source

        # Ensure numeric columns are numeric
        for col in ['Min', 'Max', 'ExpReq', 'Estimated', 'Vexp', 'Vlvl',
                     'Level', 'Vmin', 'Vmax']:
            if col in normalized.columns:
                normalized[col] = pd.to_numeric(normalized[col], errors='coerce')

        # Salary plausibility gate for aerospace engineering roles.
        # Any Min or Max value below $25,000 is implausible (hourly rates,
        # parsing artifacts, zeros, or non-US data). Coerce to NaN so they
        # do not skew averages or visualizations. Then drop rows where
        # both Min and Max ended up as NaN (no usable salary data).
        for col in ['Min', 'Max']:
            if col in normalized.columns:
                implausible = (normalized[col] < 25000) | (normalized[col] <= 0)
                normalized.loc[implausible, col] = pd.NA

        if not keepWithoutSalary:
            if 'Min' in normalized.columns and 'Max' in normalized.columns:
                bothMissing = normalized['Min'].isna() & normalized['Max'].isna()
                normalized = normalized[~bothMissing].reset_index(drop=True)

        return normalized

    def _inferLevel(self, title: str, yearsExp: Optional[float] = None) -> Optional[int]:

        '''

        Infer engineering level (1-5) from job title keywords and experience.

        Parameters:
        -----------
        title : str
            Job title string
        yearsExp : float, optional
            Years of experience if known

        Returns:
        --------
        int or None : Inferred level 1-5, or None if unable to determine

        '''

        if not title:
            return None

        titleLower = title.lower()

        # Title keyword matching is ordered from highest to lowest seniority.
        # Mapping follows the 5-level technical framework:
        #   L5: Principal / Chief / Fellow
        #   L4: Director / Staff
        #   L3: Senior / Lead  (lead has management scope but maps to L3 technically)
        #   L2: Engineer / RE  (default for unlabeled mid-level postings)
        #   L1: Junior / Associate / Entry / Intern
        if any(kw in titleLower for kw in ['principal', 'chief', 'fellow', 'distinguished']):
            return 5
        if any(kw in titleLower for kw in ['director', 'staff']):
            return 4
        if any(kw in titleLower for kw in ['senior', 'sr.', 'sr ', 'lead']):
            return 3
        if any(kw in titleLower for kw in ['junior', 'jr.', 'jr ', 'associate', 'entry',
                                            'intern', 'i ', ' i', 'level 1', 'grade 1']):
            return 1

        # If we have experience data, use that
        if yearsExp is not None:
            if yearsExp >= 12:
                return 5
            elif yearsExp >= 7:
                return 4
            elif yearsExp >= 4:
                return 3
            elif yearsExp >= 2:
                return 2
            else:
                return 1

        # Default to mid-level if no signals
        return 2

    def _inferSeniority(self, title: str) -> str:

        '''

        Infer seniority string from job title.

        Parameters:
        -----------
        title : str
            Job title string

        Returns:
        --------
        str : Seniority label

        '''

        if not title:
            return 'Unknown'

        titleLower = title.lower()

        if any(kw in titleLower for kw in ['principal', 'fellow', 'distinguished']):
            return 'Principal'
        if 'director' in titleLower:
            return 'Director'
        if 'chief' in titleLower:
            return 'Chief'
        if any(kw in titleLower for kw in ['staff']):
            return 'Staff'
        if 'lead' in titleLower:
            return 'Lead'
        if any(kw in titleLower for kw in ['senior', 'sr.']):
            return 'Senior'
        if any(kw in titleLower for kw in ['junior', 'jr.', 'associate', 'entry', 'intern']):
            return 'Entry'
        return 'Mid'

    def _inferDiscipline(self, title: str) -> str:

        '''

        Infer engineering discipline from job title.

        Parameters:
        -----------
        title : str
            Job title string

        Returns:
        --------
        str : Discipline label

        '''

        if not title:
            return 'General'

        titleLower = title.lower()

        # Keyword-to-discipline mapping for classifying job titles into the
        # discipline taxonomy. Order matters for ambiguous titles -- e.g., a
        # 'propulsion test engineer' matches 'propulsion' before 'test' because
        # 'propulsion' appears first in the dict iteration order.
        # Order matters -- more specific multi-word phrases must appear before
        # their component keywords to prevent partial-match shadowing.
        # e.g. 'ground systems' must precede 'systems', 'quality control' before 'control'.
        disciplineMap = {
            'propulsion': 'Propulsion',
            'rocket': 'Propulsion',
            'combustion': 'Propulsion',
            'turbomachinery': 'Propulsion',
            'structures': 'Structures',
            'stress': 'Structures',
            'structural': 'Structures',
            'avionics': 'Avionics',
            'gnc': 'GNC',
            'guidance': 'GNC',
            'navigation': 'GNC',
            'flight control': 'GNC',
            'attitude control': 'GNC',
            'trajectory': 'GNC',
            'thermal': 'Thermal',
            'manufacturing': 'Manufacturing',
            'production': 'Manufacturing',
            'test': 'Test',
            'ground systems': 'Ground Systems',
            'ground support': 'Ground Systems',
            'ground software': 'Ground Systems',
            'ground se': 'Ground Systems',   # "Ground SE" abbreviation
            'systems': 'Systems',
            'software': 'Software',
            'electrical': 'Electrical',
            'harness': 'Electrical',
            'mechanical': 'Mechanical',
            'materials': 'Materials',
            'quality control': 'Quality',
            'quality': 'Quality',
            'controls': 'GNC',              # "Controls Engineer" (not "quality control")
            'fluid': 'Fluids',
            'launch operations': 'Launch',
            'launch vehicle': 'Launch',
            'aerodynamic': 'Aerodynamics',
            'aero ': 'Aerodynamics',
        }

        for keyword, discipline in disciplineMap.items():
            if keyword in titleLower:
                return discipline

        # Fallback rules for ambiguous titles that don't match the above keywords but contain discipline hints
        return 'Aerospace'

    def _mapLocation(self, locationStr: str) -> Tuple[str, str]:

        '''

        Parse location string into (city, state) tuple.

        Parameters:
        -----------
        locationStr : str
            Location string (e.g. 'Los Angeles, CA' or 'California')

        Returns:
        --------
        tuple : (city, stateAbbr) or ('Unknown', 'Unknown')

        '''

        if not locationStr or locationStr in ('nan', 'None', ''):
            return ('Unknown', 'Unknown')

        locationStr = locationStr.strip()

        # Handle 'City, ST' format
        if ',' in locationStr:
            parts = [p.strip() for p in locationStr.split(',')]
            city = parts[0]
            state = parts[-1].strip()
            # Extract just the state abbreviation if it has more info
            stateMatch = re.match(r'([A-Z]{2})', state)
            if stateMatch:
                return (city, stateMatch.group(1))
            return (city, state)

        # Fallback state name mapping for location strings that don't use
        # the standard 'City, ST' format (e.g., 'California' or 'Florida').
        # This list covers the 15 states with the highest aerospace employment.
        stateNames = {
            'california': 'CA', 'florida': 'FL', 'texas': 'TX',
            'washington': 'WA', 'colorado': 'CO', 'alabama': 'AL',
            'arizona': 'AZ', 'virginia': 'VA', 'new york': 'NY',
            'georgia': 'GA', 'maryland': 'MD', 'ohio': 'OH',
            'utah': 'UT', 'connecticut': 'CT', 'new mexico': 'NM',
        }

        # City / metro area name lookup for locations without a state code.
        # Covers major aerospace employment hubs and common "Bay Area" style
        # shorthand that doesn't match the comma-separated city/state format.
        metroCityToState = {
            # California
            'san francisco': 'CA', 'bay area': 'CA', 'silicon valley': 'CA',
            'los angeles': 'CA', 'hawthorne': 'CA', 'el segundo': 'CA',
            'long beach': 'CA', 'san jose': 'CA', 'san diego': 'CA',
            'sacramento': 'CA', 'irvine': 'CA', 'santa ana': 'CA',
            'vandenberg': 'CA', 'mojave': 'CA',
            # Texas
            'houston': 'TX', 'austin': 'TX', 'dallas': 'TX',
            'fort worth': 'TX', 'san antonio': 'TX', 'mcgregor': 'TX',
            # Florida
            'cape canaveral': 'FL', 'kennedy space center': 'FL',
            'orlando': 'FL', 'miami': 'FL', 'titusville': 'FL',
            'brevard': 'FL', 'merritt island': 'FL',
            # Washington
            'seattle': 'WA', 'kent': 'WA', 'everett': 'WA',
            'redmond': 'WA', 'bellevue': 'WA',
            # Colorado
            'denver': 'CO', 'colorado springs': 'CO', 'boulder': 'CO',
            'littleton': 'CO', 'centennial': 'CO',
            # Alabama
            'huntsville': 'AL', 'decatur': 'AL',
            # Arizona
            'phoenix': 'AZ', 'tucson': 'AZ', 'chandler': 'AZ', 'tempe': 'AZ',
            # Virginia
            'arlington': 'VA', 'reston': 'VA', 'chantilly': 'VA',
            'falls church': 'VA', 'dulles': 'VA',
            # Maryland
            'bethesda': 'MD', 'greenbelt': 'MD', 'columbia': 'MD',
            # Ohio
            'cleveland': 'OH', 'dayton': 'OH', 'columbus': 'OH',
            # Utah
            'salt lake': 'UT', 'ogden': 'UT', 'promontory': 'UT',
            # New Mexico
            'albuquerque': 'NM', 'las cruces': 'NM',
            # New York
            'new york city': 'NY', 'nyc': 'NY',
        }

        locLower = locationStr.lower()

        # Check full state names first
        for stateName, abbr in stateNames.items():
            if stateName in locLower:
                return (locationStr, abbr)

        # Check city / metro area names
        for cityName, abbr in metroCityToState.items():
            if cityName in locLower:
                return (locationStr, abbr)

        return (locationStr, 'Unknown')

    # ------------------------------------------------------------------ #
    # -- Data Source: Data USA -- #
    # ------------------------------------------------------------------ #

    def scrapeDataUsa(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape Data USA API for aerospace engineer wage data.
        Uses Census Bureau American Community Survey data aggregated by
        the datausa.io platform.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping Data USA...')
        if progressCallback:
            progressCallback(0, 2, 'Querying Data USA API...')

        rows = []

        # Data USA uses a Tesseract API backend for PUMS data
        apiUrl = 'https://api-ts-uranium.datausa.io/tesseract/data.jsonrecords'

        # Query aggregate wage data for aerospace engineers (SOC 172011)
        params = {
            'cube': 'pums_5',
            'drilldowns': 'Year,Detailed Occupation',
            'measures': 'Average Wage,Total Population',
            'Detailed Occupation': '172011',
        }

        content = self._makeRequest(apiUrl, params=params)
        if content:
            try:
                data = json.loads(content)
                for record in data['data']:
                    avgWage = record['Average Wage']
                    year = record['Year']
                    employment = record['Total Population']

                    if avgWage:
                        # Data USA returns a single average wage per year -- estimate a range
                        # by applying +/- 25% to approximate the spread seen in BLS percentile data
                        rows.append({
                            'Company': 'Data USA/ACS',
                            'Listing': f'Aerospace Engineer (SOC 17-2011) - {year}',
                            'Min': float(avgWage) * 0.75,
                            'Max': float(avgWage) * 1.25,
                            'Location': 'National',
                            'State': 'US',
                            'Discipline': 'Aerospace',
                            'Seniority': 'All Levels',
                            'Link': 'https://datausa.io/profile/soc/aerospace-engineers',
                            '_employment': employment,
                            '_year': year,
                        })
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f'Failed to parse Data USA response: {e}')

        if progressCallback:
            progressCallback(1, 2, 'Querying Data USA for mechanical engineers...')

        # Also query mechanical engineers for broader context
        params['Detailed Occupation'] = '172141'
        content = self._makeRequest(apiUrl, params=params)
        if content:
            try:
                data = json.loads(content)
                for record in data['data']:
                    avgWage = record['Average Wage']
                    year = record['Year']

                    if avgWage:
                        rows.append({
                            'Company': 'Data USA/ACS',
                            'Listing': f'Mechanical Engineer (SOC 17-2141) - {year}',
                            'Min': float(avgWage) * 0.75,
                            'Max': float(avgWage) * 1.25,
                            'Location': 'National',
                            'State': 'US',
                            'Discipline': 'Mechanical',
                            'Seniority': 'All Levels',
                            'Link': 'https://datausa.io/profile/soc/mechanical-engineers',
                            '_year': year,
                        })
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f'Failed to parse Data USA mechanical response: {e}')

        if progressCallback:
            progressCallback(2, 2, 'Data USA complete.')

        if not rows:
            logger.warning('No Data USA data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'Data USA')

    # ------------------------------------------------------------------ #
    # -- Data Source: BLS OEWS -- #
    # ------------------------------------------------------------------ #

    def scrapeBls(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape BLS Occupational Employment and Wage Statistics.
        Uses the BLS Public Data API v2 (or v1 without key) to fetch
        wage percentiles for aerospace-related SOC codes.

        Fallback: Scrapes the OES HTML summary page if the API fails.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized BLS wage data

        '''

        logger.info('Scraping BLS OEWS data...')

        rows = []
        totalSteps = len(self.config.targetSocCodes) + 1

        # -- Strategy 1: BLS Public Data API -- #
        apiUrl = 'https://api.bls.gov/publicAPI/v2/timeseries/data/'

        for idx, socCode in enumerate(self.config.targetSocCodes):
            if progressCallback:
                progressCallback(idx, totalSteps, f'Querying BLS for SOC {socCode}...')

            socClean = socCode.replace('-', '')

            # BLS OEWS series ID format: OEUN{area}{industry}{soc}{datatype}
            # - OEUN = OES national data prefix
            # - 0000000 = national area (all US)
            # - 000000 = all industries
            # - {socClean} = SOC code without hyphen (e.g., 172011)
            # - Data type suffixes: 04=mean, 07=p10, 08=p25, 12=median, 13=p75, 14=p90
            # Reference: https://www.bls.gov/help/hlpforma.htm#OE
            seriesIds = [
                f'OEUN0000000000000{socClean}04',  # Mean annual wage
                f'OEUN0000000000000{socClean}12',  # Median annual wage
                f'OEUN0000000000000{socClean}07',  # 10th percentile
                f'OEUN0000000000000{socClean}08',  # 25th percentile
                f'OEUN0000000000000{socClean}13',  # 75th percentile
                f'OEUN0000000000000{socClean}14',  # 90th percentile
            ]

            payload = {
                'seriesid': seriesIds,
                'startyear': '2023',
                'endyear': '2025',
            }
            if self.config.blsApiKey:
                payload['registrationkey'] = self.config.blsApiKey

            content = self._makeRequest(apiUrl, method='POST', jsonBody=payload)
            if content:
                try:
                    data = json.loads(content)
                    if data['status'] == 'REQUEST_SUCCEEDED':
                        seriesResults = {}
                        for series in data['Results']['series']:
                            seriesId = series['seriesID']
                            for obs in series['data']:
                                year = obs['year']
                                period = obs['period']
                                if period == 'A01':  # Annual data
                                    value = obs['value']
                                    try:
                                        seriesResults[seriesId] = float(value)
                                    except ValueError:
                                        pass

                        # Build percentile-based rows
                        socLabel = _defaultSocLabels[socClean]

                        # Find percentile values from the series results
                        percentiles = {}
                        for sid, val in seriesResults.items():
                            if sid.endswith('04'):
                                percentiles['mean'] = val
                            elif sid.endswith('12'):
                                percentiles['median'] = val
                            elif sid.endswith('07'):
                                percentiles['p10'] = val
                            elif sid.endswith('08'):
                                percentiles['p25'] = val
                            elif sid.endswith('13'):
                                percentiles['p75'] = val
                            elif sid.endswith('14'):
                                percentiles['p90'] = val

                        # BLS percentile data types can return hourly wages
                        # instead of annual. Detect by checking if values are
                        # implausibly low for annual salaries (< $500) and
                        # convert hourly -> annual (hourly * 2080 hours/year).
                        for key in list(percentiles.keys()):
                            if percentiles[key] < 500:
                                percentiles[key] = percentiles[key] * 2080

                        if percentiles:
                            rows.append({
                                'Company': 'BLS National',
                                'Listing': f'{socLabel} (SOC {socCode}) - Wage Distribution',
                                'Min': percentiles['p10'],
                                'Max': percentiles['p90'],
                                'Location': 'National',
                                'State': 'US',
                                'Discipline': 'Aerospace' if '2011' in socCode else (
                                    'Mechanical' if '2141' in socCode else 'Electrical'
                                ),
                                'Seniority': 'All Levels',
                                'Link': f'https://www.bls.gov/oes/current/oes{socClean}.htm',
                                '_mean': percentiles['mean'],
                                '_median': percentiles['median'],
                                '_p10': percentiles['p10'],
                                '_p25': percentiles['p25'],
                                '_p75': percentiles['p75'],
                                '_p90': percentiles['p90'],
                            })
                    else:
                        logger.warning(f'BLS API returned status: {data["status"]}')
                        # Messages may contain useful error info
                        for msg in data['message']:
                            logger.warning(f'BLS message: {msg}')
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f'Failed to parse BLS API response: {e}')

        # -- Strategy 2: Fallback to HTML scrape of OES summary page -- #
        if not rows:
            if progressCallback:
                progressCallback(len(self.config.targetSocCodes), totalSteps,
                                 'API failed, trying HTML fallback...')

            fallbackRows = self._scrapeBlsHtmlFallback()
            rows.extend(fallbackRows)

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'BLS scrape complete.')

        if not rows:
            logger.warning('No BLS data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'BLS')

    def _scrapeBlsHtmlFallback(self) -> List[Dict]:

        '''

        Fallback: scrape the BLS OES HTML summary page for aerospace engineers.

        Returns:
        --------
        list : List of row dictionaries

        '''

        rows = []
        url = 'https://www.bls.gov/oes/current/oes172011.htm'
        content = self._makeRequest(url)

        if not content:
            return rows

        try:
            soup = BeautifulSoup(content, 'html.parser')

            # Look for the wage estimate table
            tables = soup.find_all('table')
            for table in tables:
                headerRow = table.find('tr')
                if headerRow and 'percentile' in headerRow.get_text().lower():
                    dataRows = table.find_all('tr')[1:]
                    for row in dataRows:
                        cells = row.find_all(['td', 'th'])
                        if len(cells) >= 6:
                            try:
                                # Typical BLS table: Area | Employment | Mean | P10 | P25 | Median | P75 | P90
                                areaName = cells[0].get_text(strip=True)
                                values = []
                                for cell in cells[1:]:
                                    text = cell.get_text(strip=True).replace(',', '').replace('$', '')
                                    try:
                                        values.append(float(text))
                                    except ValueError:
                                        values.append(None)

                                if len(values) >= 5 and values[0] is not None:
                                    rows.append({
                                        'Company': f'BLS {areaName}',
                                        'Listing': 'Aerospace Engineer (SOC 17-2011)',
                                        'Min': values[2] if len(values) > 2 and values[2] else 0,
                                        'Max': values[-1] if values[-1] else 0,
                                        'Location': areaName,
                                        'State': 'US',
                                        'Discipline': 'Aerospace',
                                        'Seniority': 'All Levels',
                                        'Link': url,
                                    })
                            except (IndexError, ValueError):
                                continue
        except Exception as e:
            logger.error(f'BLS HTML fallback parsing failed: {e}')

        return rows

    # ------------------------------------------------------------------ #
    # -- Data Source: FRED -- #
    # ------------------------------------------------------------------ #

    def scrapeFred(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape FRED (Federal Reserve Economic Data) for aerospace
        engineer earnings time series data.

        Requires a FRED API key (free registration).

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized earnings trend data

        '''

        logger.info('Scraping FRED data...')

        if not self.config.fredApiKey:
            logger.warning('No FRED API key provided. Skipping FRED source.')
            if progressCallback:
                progressCallback(1, 1, 'FRED skipped (no API key).')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rows = []

        # FRED series for two complementary data points:
        # - LEU0254531900A: Median weekly earnings for engineers (CPS survey,
        #   covers all engineering, not aerospace-specific -- best available proxy)
        # - CES3133600001: Employment count in aerospace manufacturing (NAICS 3364),
        #   useful for tracking industry size trends rather than salary data
        seriesIds = {
            'LEU0254531900A': 'Median Usual Weekly Earnings - Engineers',
            'CES3133600001': 'Aerospace Products & Parts Manufacturing Employment',
        }

        totalSteps = len(seriesIds)
        apiUrl = 'https://api.stlouisfed.org/fred/series/observations'

        for idx, (seriesId, description) in enumerate(seriesIds.items()):
            if progressCallback:
                progressCallback(idx, totalSteps, f'Querying FRED series {seriesId}...')

            params = {
                'series_id': seriesId,
                'api_key': self.config.fredApiKey,
                'file_type': 'json',
                'sort_order': 'desc',
                'limit': '10',
            }

            content = self._makeRequest(apiUrl, params=params)
            if content:
                try:
                    data = json.loads(content)
                    observations = data['observations']

                    for obs in observations:
                        value = obs['value']
                        date = obs['date']

                        if value and value != '.':
                            numericValue = float(value)

                            # Weekly earnings series - convert to annual
                            if 'Weekly' in description:
                                annualSalary = numericValue * 52
                                rows.append({
                                    'Company': 'FRED/CPS',
                                    'Listing': f'{description} ({date})',
                                    'Min': annualSalary * 0.85,
                                    'Max': annualSalary * 1.15,
                                    'Location': 'National',
                                    'State': 'US',
                                    'Discipline': 'Aerospace',
                                    'Seniority': 'All Levels',
                                    'Link': f'https://fred.stlouisfed.org/series/{seriesId}',
                                    '_rawValue': numericValue,
                                    '_date': date,
                                })
                            else:
                                # Employment data - store as metadata only
                                rows.append({
                                    'Company': 'FRED/BLS',
                                    'Listing': f'{description} ({date}) - {numericValue:,.0f} employed',
                                    'Min': 0,
                                    'Max': 0,
                                    'Location': 'National',
                                    'State': 'US',
                                    'Discipline': 'Aerospace',
                                    'Seniority': 'All Levels',
                                    'Link': f'https://fred.stlouisfed.org/series/{seriesId}',
                                    '_rawValue': numericValue,
                                    '_date': date,
                                })
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    logger.error(f'Failed to parse FRED response for {seriesId}: {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'FRED complete.')

        # Filter out employment-only rows (Min/Max = 0)
        rows = [r for r in rows if r['Min'] > 0 or r['Max'] > 0]

        if not rows:
            logger.warning('No FRED wage data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'FRED')

    # ------------------------------------------------------------------ #
    # -- Data Source: H1B Data -- #
    # ------------------------------------------------------------------ #

    def scrapeH1b(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape H1B visa salary disclosure data from h1bdata.info.
        This is public government data (Department of Labor LCA filings)
        presented through a community indexing service.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized H1B salary data

        '''

        logger.info('Scraping H1B data...')

        rows = []
        baseUrl = 'https://h1bdata.info/index.php'

        # Generic job title queries capture broad aerospace salary data. We search
        # multiple title variants because employers use inconsistent titles in LCA
        # filings (e.g., 'propulsion engineer' vs 'aerospace engineer - propulsion').
        # Years 2024-2025 are targeted for recency; older data is less relevant
        # due to rapid salary inflation in the aerospace sector.
        queries = [
            {'job': 'aerospace engineer', 'em': '', 'year': '2024'},
            {'job': 'aerospace engineer', 'em': '', 'year': '2025'},
            {'job': 'propulsion engineer', 'em': '', 'year': '2024'},
            {'job': 'systems engineer', 'em': '', 'year': '2024'},
            {'job': 'mechanical engineer aerospace', 'em': '', 'year': '2024'},
        ]

        # Add company-specific queries
        for company in self.config.targetCompanies[:10]:  # Limit to avoid too many requests
            queries.append({
                'job': 'engineer',
                'em': company.lower().replace(' ', '+'),
                'year': '2024',
            })

        totalSteps = len(queries)

        for idx, query in enumerate(queries):
            if progressCallback:
                label = query['em'] if 'em' in query else query['job']
                progressCallback(idx, totalSteps, f'Querying H1B data: {label}...')

            content = self._makeRequest(baseUrl, params=query)
            if not content:
                continue

            try:
                soup = BeautifulSoup(content, 'html.parser')
                table = soup.find('table', {'id': 'myTable'})
                if not table:
                    # Try finding any data table
                    table = soup.find('table')
                if not table:
                    continue

                tableRows = table.find_all('tr')[1:]  # Skip header

                for row in tableRows[:100]:  # Limit rows per query
                    cells = row.find_all('td')
                    if len(cells) >= 4:
                        employer = cells[0].get_text(strip=True)
                        jobTitle = cells[1].get_text(strip=True)
                        baseSalaryText = cells[2].get_text(strip=True)
                        location = cells[3].get_text(strip=True)

                        # Parse salary
                        salaryClean = baseSalaryText.replace(',', '').replace('$', '').strip()
                        try:
                            salary = float(salaryClean)
                        except ValueError:
                            continue

                        # H1B filings below $40K are likely hourly rate entries that weren't
                        # annualized, or part-time positions -- filter them to avoid skewing results
                        if salary < 40000:
                            continue

                        city, state = self._mapLocation(location)
                        level = self._inferLevel(jobTitle)
                        seniority = self._inferSeniority(jobTitle)
                        discipline = self._inferDiscipline(jobTitle)

                        rows.append({
                            'Company': employer,
                            'Listing': jobTitle,
                            'Level': level,
                            'Seniority': seniority,
                            'Min': salary,
                            'Max': salary,  # H1B data is a single salary figure
                            'Location': city,
                            'State': state,
                            'Discipline': discipline,
                            'Link': baseUrl,
                        })
            except Exception as e:
                logger.error(f'H1B parsing error for query {query}: {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'H1B scrape complete.')

        if not rows:
            logger.warning('No H1B data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)

        # Deduplicate within H1B results
        rawDf = rawDf.drop_duplicates(
            subset=['Company', 'Listing', 'Min', 'Location'], keep='first'
        )

        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Level': 'Level',
            'Seniority': 'Seniority',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Link': 'Link',
        }, 'H1B')

    # ------------------------------------------------------------------ #
    # -- Data Source: Levels.fyi -- #
    # ------------------------------------------------------------------ #

    def scrapeLevelsFyi(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape Levels.fyi for company-specific compensation data.
        Attempts to access salary pages for target aerospace companies.

        Note: This source may block automated access. If blocked, it
        degrades gracefully and returns an empty DataFrame.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping Levels.fyi...')

        rows = []

        # Company slug mapping for levels.fyi URLs -- derived programmatically
        # from the target company names via referenceParser
        companySlugMap = deriveCompanyUrlSlugs(self.config.targetCompanies)

        # Roles to query
        rolesSlugs = [
            'mechanical-engineer',
            'systems-engineer',
            'software-engineer',
            'hardware-engineer',
        ]

        # Companies confirmed to have no salary pages on levels.fyi (verified by 404).
        # Skipping them avoids wasting a request + wait per role slug per scrape run.
        # Update this set if a company later gets a levels.fyi profile.
        _levelsFyiKnownAbsent = {
            'rocket-lab', 'ge-aerospace', 'the-aerospace-corporation',
            'relativity-space', 'impulse-space', 'stoke-space',
            'ursa-major', 'astra', 'astroforge',
        }

        # Build URL list from target companies, skipping known-absent ones
        targetSlugs = {}
        for company in self.config.targetCompanies:
            if company in companySlugMap:
                slug = companySlugMap[company]
                if slug not in _levelsFyiKnownAbsent:
                    targetSlugs[company] = slug
                else:
                    logger.debug(f'Levels.fyi: skipping {company} (known absent)')

        if not targetSlugs:
            logger.warning('No target companies have Levels.fyi slugs.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        totalSteps = len(targetSlugs) * len(rolesSlugs)
        step = 0

        for companyName, companySlug in targetSlugs.items():
            for roleSlug in rolesSlugs:
                if progressCallback:
                    progressCallback(step, totalSteps,
                                     f'Levels.fyi: {companyName} / {roleSlug}...')
                step += 1

                url = f'https://www.levels.fyi/companies/{companySlug}/salaries/{roleSlug}'
                # 404 is expected for many companies that simply don't have a levels.fyi page;
                # suppress to DEBUG so they don't clutter the warning log.
                content = self._makeRequest(url, suppressWarnings=True)

                if not content:
                    continue

                try:
                    soup = BeautifulSoup(content, 'html.parser')

                    # Levels.fyi renders most salary data via client-side JavaScript (React),
                    # so direct HTML scraping has limited effectiveness. We try two strategies:
                    # 1. JSON-LD structured data (sometimes embedded for SEO)
                    # 2. Any pre-rendered HTML tables (rare but sometimes present)
                    # If both fail, the method degrades gracefully to an empty DataFrame.

                    # Try JSON-LD first
                    scriptTags = soup.find_all('script', type='application/ld+json')
                    for script in scriptTags:
                        try:
                            jsonData = json.loads(script.string)
                            if isinstance(jsonData, dict):
                                # Look for salary/compensation data
                                if 'baseSalary' in jsonData:
                                    salaryData = jsonData['baseSalary']
                                    if isinstance(salaryData, dict):
                                        minVal = salaryData['minValue']
                                        maxVal = salaryData['maxValue']
                                        if minVal or maxVal:
                                            roleName = roleSlug.replace('-', ' ').title()
                                            rows.append({
                                                'Company': companyName,
                                                'Listing': f'{roleName} (Levels.fyi)',
                                                'Min': float(minVal) if minVal else 0,
                                                'Max': float(maxVal) if maxVal else 0,
                                                'Location': 'Various',
                                                'State': 'US',
                                                'Discipline': self._inferDiscipline(roleSlug),
                                                'Seniority': 'All Levels',
                                                'Link': url,
                                            })
                        except (json.JSONDecodeError, TypeError):
                            continue

                    # Try finding salary tables in the HTML
                    tables = soup.find_all('table')
                    for table in tables:
                        tableRows = table.find_all('tr')
                        for tRow in tableRows[1:]:  # Skip header
                            cells = tRow.find_all(['td', 'th'])
                            if len(cells) >= 3:
                                try:
                                    levelText = cells[0].get_text(strip=True)
                                    # Look for salary values in remaining cells
                                    salaries = []
                                    for cell in cells[1:]:
                                        text = cell.get_text(strip=True)
                                        cleanText = text.replace('$', '').replace(',', '').replace('K', '000').replace('k', '000')
                                        try:
                                            salaries.append(float(cleanText))
                                        except ValueError:
                                            continue

                                    if salaries:
                                        roleName = roleSlug.replace('-', ' ').title()
                                        rows.append({
                                            'Company': companyName,
                                            'Listing': f'{roleName} - {levelText}',
                                            'Level': self._inferLevel(levelText),
                                            'Seniority': self._inferSeniority(levelText),
                                            'Min': min(salaries),
                                            'Max': max(salaries),
                                            'Location': 'Various',
                                            'State': 'US',
                                            'Discipline': self._inferDiscipline(roleSlug),
                                            'Link': url,
                                        })
                                except (ValueError, IndexError):
                                    continue

                except Exception as e:
                    logger.error(f'Levels.fyi parsing error for {companyName}/{roleSlug}: {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'Levels.fyi scrape complete.')

        if not rows:
            logger.warning('No Levels.fyi data collected (may be blocked or JS-rendered).')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Level': 'Level',
            'Seniority': 'Seniority',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Link': 'Link',
        }, 'Levels.fyi')

    # ------------------------------------------------------------------ #
    # -- Data Source: Glassdoor -- #
    # ------------------------------------------------------------------ #

    def scrapeGlassdoor(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape Glassdoor for aerospace engineer job listings via JobSpy.

        Uses the python-jobspy library to pull individual job listings with
        salary data directly from Glassdoor. Requires python-jobspy to be
        installed (pip install python-jobspy). Returns empty if not available.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping Glassdoor via JobSpy...')

        _jobspyScrape, _importErr = _tryImportJobspy()
        if _jobspyScrape is None:
            logger.warning(
                f'python-jobspy unavailable; Glassdoor skipped ({_importErr}). '
                f'Run: python.exe -m streamlit run GUI.py'
            )
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        searchTerms = [
            ('aerospace engineer', 'Aerospace'),
            ('mechanical engineer', 'Mechanical'),
            ('propulsion engineer', 'Propulsion'),
            ('systems engineer', 'Systems'),
            ('avionics engineer', 'Avionics'),
        ]

        totalSteps = len(searchTerms)
        allRows = []

        for idx, (term, discipline) in enumerate(searchTerms):
            if progressCallback:
                progressCallback(idx, totalSteps, f'Glassdoor (JobSpy): {term}...')

            try:
                listings = _jobspyScrape(
                    site_name=['glassdoor'],
                    search_term=term,
                    location='United States',
                    results_wanted=25,
                    enforce_annual_salary=True,
                    verbose=0,
                )

                if listings is None or listings.empty:
                    continue

                # Keep only rows that have at least one salary bound
                salaryRows = listings.dropna(subset=['min_amount', 'max_amount'], how='all')
                for _, row in salaryRows.iterrows():
                    title = str(row.get('title', ''))
                    locationStr = str(row.get('location', ''))
                    _, state = self._mapLocation(locationStr)
                    minAmt = row.get('min_amount')
                    maxAmt = row.get('max_amount')
                    # If one bound is missing, mirror the other
                    minAmt = float(minAmt) if pd.notna(minAmt) else float(maxAmt)
                    maxAmt = float(maxAmt) if pd.notna(maxAmt) else float(minAmt)

                    allRows.append({
                        'Company': str(row.get('company', 'Unknown')),
                        'Listing': title,
                        'Min': minAmt,
                        'Max': maxAmt,
                        'Location': locationStr,
                        'State': state,
                        'Discipline': self._inferDiscipline(title),
                        'Seniority': self._inferSeniority(title),
                        'Link': str(row.get('job_url', '')),
                    })

            except Exception as e:
                logger.error(f'Glassdoor JobSpy error for "{term}": {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'Glassdoor scrape complete.')

        if not allRows:
            logger.warning('No Glassdoor data collected via JobSpy.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(allRows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'Glassdoor')

    # ------------------------------------------------------------------ #
    # -- Data Source: PayScale -- #
    # ------------------------------------------------------------------ #

    def scrapePayscale(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape PayScale for aerospace engineer salary data.

        PayScale provides publicly accessible salary research pages with
        range data. This scraper targets their research pages which include
        structured data for search engines.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping PayScale...')

        rows = []

        # PayScale research pages for aerospace-related roles
        searchTerms = [
            ('Aerospace_Engineer', 'Aerospace'),
            ('Mechanical_Engineer', 'Mechanical'),
            ('Propulsion_Engineer', 'Propulsion'),
            ('Systems_Engineer', 'Systems'),
            ('Avionics_Engineer', 'Avionics'),
            # 'Rocket_Engineer' removed — not a recognised PayScale job title (404)
        ]

        totalSteps = len(searchTerms)

        for idx, (searchTerm, discipline) in enumerate(searchTerms):
            if progressCallback:
                progressCallback(idx, totalSteps, f'PayScale: {searchTerm}...')

            url = f'https://www.payscale.com/research/US/Job={searchTerm}/Salary'
            content = self._makeRequest(url, headers=self._browserHeaders)

            if not content:
                continue

            try:
                soup = BeautifulSoup(content, 'html.parser')

                # PayScale embeds JSON-LD with salary estimates
                scriptTags = soup.find_all('script', type='application/ld+json')
                for script in scriptTags:
                    try:
                        jsonData = json.loads(script.string)
                        if isinstance(jsonData, dict) and 'estimatedSalary' in jsonData:
                            for estimate in jsonData['estimatedSalary']:
                                currency = estimate.get('currency', 'USD')
                                if currency != 'USD':
                                    continue
                                minVal = estimate.get('percentile25', estimate.get('minValue', 0))
                                maxVal = estimate.get('percentile75', estimate.get('maxValue', 0))
                                jobTitle = estimate.get('name', searchTerm.replace('_', ' '))

                                if minVal or maxVal:
                                    rows.append({
                                        'Company': 'PayScale',
                                        'Listing': f'{jobTitle} (PayScale)',
                                        'Min': float(minVal) if minVal else 0,
                                        'Max': float(maxVal) if maxVal else 0,
                                        'Location': 'National',
                                        'State': 'US',
                                        'Discipline': discipline,
                                        'Seniority': self._inferSeniority(jobTitle),
                                        'Link': url,
                                    })
                    except (json.JSONDecodeError, TypeError, KeyError):
                        continue

                # Fallback: look for salary data in page text
                if not rows or rows[-1].get('Link') != url:
                    # PayScale pages often have a prominent salary range in specific elements
                    salaryElements = soup.find_all(attrs={'data-testid': re.compile(r'salary', re.IGNORECASE)})
                    for elem in salaryElements:
                        text = elem.get_text(strip=True)
                        vals = re.findall(r'\$(\d{2,3}(?:,\d{3})*)', text)
                        if len(vals) >= 2:
                            try:
                                numVals = [float(v.replace(',', '')) for v in vals]
                                rows.append({
                                    'Company': 'PayScale',
                                    'Listing': f'{searchTerm.replace("_", " ")} (PayScale)',
                                    'Min': min(numVals),
                                    'Max': max(numVals),
                                    'Location': 'National',
                                    'State': 'US',
                                    'Discipline': discipline,
                                    'Seniority': 'All Levels',
                                    'Link': url,
                                })
                            except ValueError:
                                pass

            except Exception as e:
                logger.error(f'PayScale parsing error for {searchTerm}: {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'PayScale scrape complete.')

        if not rows:
            logger.warning('No PayScale data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'PayScale')

    # ------------------------------------------------------------------ #
    # -- Data Source: ZipRecruiter -- #
    # ------------------------------------------------------------------ #

    def scrapeZiprecruiter(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape ZipRecruiter for aerospace engineer job listings via JobSpy.

        Uses the python-jobspy library to pull individual job listings with
        salary data directly from ZipRecruiter. Requires python-jobspy to be
        installed (pip install python-jobspy). Returns empty if not available.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping ZipRecruiter via JobSpy...')

        _jobspyScrape, _importErr = _tryImportJobspy()
        if _jobspyScrape is None:
            logger.warning(
                f'python-jobspy unavailable; ZipRecruiter skipped ({_importErr}). '
                f'Run: python.exe -m streamlit run GUI.py'
            )
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        searchTerms = [
            ('aerospace engineer', 'Aerospace'),
            ('mechanical engineer', 'Mechanical'),
            ('propulsion engineer', 'Propulsion'),
            ('systems engineer', 'Systems'),
            ('avionics engineer', 'Avionics'),
        ]

        totalSteps = len(searchTerms)
        allRows = []

        for idx, (term, discipline) in enumerate(searchTerms):
            if progressCallback:
                progressCallback(idx, totalSteps, f'ZipRecruiter (JobSpy): {term}...')

            try:
                listings = _jobspyScrape(
                    site_name=['zip_recruiter'],
                    search_term=term,
                    location='United States',
                    results_wanted=25,
                    enforce_annual_salary=True,
                    verbose=0,
                )

                if listings is None or listings.empty:
                    continue

                # Keep only rows that have at least one salary bound
                salaryRows = listings.dropna(subset=['min_amount', 'max_amount'], how='all')
                for _, row in salaryRows.iterrows():
                    title = str(row.get('title', ''))
                    locationStr = str(row.get('location', ''))
                    _, state = self._mapLocation(locationStr)
                    minAmt = row.get('min_amount')
                    maxAmt = row.get('max_amount')
                    # If one bound is missing, mirror the other
                    minAmt = float(minAmt) if pd.notna(minAmt) else float(maxAmt)
                    maxAmt = float(maxAmt) if pd.notna(maxAmt) else float(minAmt)

                    allRows.append({
                        'Company': str(row.get('company', 'Unknown')),
                        'Listing': title,
                        'Min': minAmt,
                        'Max': maxAmt,
                        'Location': locationStr,
                        'State': state,
                        'Discipline': self._inferDiscipline(title),
                        'Seniority': self._inferSeniority(title),
                        'Link': str(row.get('job_url', '')),
                    })

            except Exception as e:
                logger.error(f'ZipRecruiter JobSpy error for "{term}": {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'ZipRecruiter scrape complete.')

        if not allRows:
            logger.warning('No ZipRecruiter data collected via JobSpy.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(allRows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'ZipRecruiter')

    # ------------------------------------------------------------------ #
    # -- Data Source: Comparably -- #
    # ------------------------------------------------------------------ #

    def scrapeComparably(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape Comparably for aerospace engineer salary data.

        Comparably provides publicly accessible salary pages with company
        comparisons and salary ranges. This scraper targets their public
        salary research pages.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping Comparably...')

        rows = []

        searchTerms = [
            ('aerospace-engineer', 'Aerospace'),
            ('mechanical-engineer', 'Mechanical'),
            ('systems-engineer', 'Systems'),
            ('software-engineer', 'Software'),
        ]

        totalSteps = len(searchTerms)

        for idx, (searchSlug, discipline) in enumerate(searchTerms):
            if progressCallback:
                progressCallback(idx, totalSteps, f'Comparably: {searchSlug}...')

            url = f'https://www.comparably.com/salaries/salaries-for-{searchSlug}'
            content = self._makeRequest(url, headers=self._browserHeaders)

            if not content:
                continue

            try:
                soup = BeautifulSoup(content, 'html.parser')

                # Try JSON-LD structured data
                scriptTags = soup.find_all('script', type='application/ld+json')
                for script in scriptTags:
                    try:
                        jsonData = json.loads(script.string)
                        if isinstance(jsonData, dict) and 'estimatedSalary' in jsonData:
                            for estimate in jsonData['estimatedSalary']:
                                minVal = estimate.get('percentile25', estimate.get('minValue', 0))
                                maxVal = estimate.get('percentile75', estimate.get('maxValue', 0))
                                jobTitle = estimate.get('name', searchSlug.replace('-', ' ').title())

                                if minVal or maxVal:
                                    rows.append({
                                        'Company': 'Comparably',
                                        'Listing': f'{jobTitle} (Comparably)',
                                        'Min': float(minVal) if minVal else 0,
                                        'Max': float(maxVal) if maxVal else 0,
                                        'Location': 'National',
                                        'State': 'US',
                                        'Discipline': discipline,
                                        'Seniority': self._inferSeniority(jobTitle),
                                        'Link': url,
                                    })
                    except (json.JSONDecodeError, TypeError, KeyError):
                        continue

                # Fallback: parse salary text from the page
                if not rows or rows[-1].get('Link') != url:
                    salaryPattern = re.findall(r'\$(\d{2,3}(?:,\d{3})*)', soup.get_text())
                    if len(salaryPattern) >= 2:
                        try:
                            vals = sorted([float(v.replace(',', '')) for v in salaryPattern])
                            plausible = [v for v in vals if 30000 <= v <= 500000]
                            if len(plausible) >= 2:
                                rows.append({
                                    'Company': 'Comparably',
                                    'Listing': f'{searchSlug.replace("-", " ").title()} (Comparably)',
                                    'Min': plausible[0],
                                    'Max': plausible[-1],
                                    'Location': 'National',
                                    'State': 'US',
                                    'Discipline': discipline,
                                    'Seniority': 'All Levels',
                                    'Link': url,
                                })
                        except ValueError:
                            pass

            except Exception as e:
                logger.error(f'Comparably parsing error for {searchSlug}: {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'Comparably scrape complete.')

        if not rows:
            logger.warning('No Comparably data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'Comparably')

    # ------------------------------------------------------------------ #
    # -- Data Source: Indeed -- #
    # ------------------------------------------------------------------ #

    def scrapeIndeed(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape Indeed for aerospace engineer salary data.

        Indeed publishes public salary estimate pages based on aggregated
        job posting data. This scraper targets those public pages and
        extracts salary ranges from structured data or page content.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping Indeed...')

        rows = []

        searchTerms = [
            ('Aerospace-Engineer', 'Aerospace'),
            ('Mechanical-Engineer', 'Mechanical'),
            ('Propulsion-Engineer', 'Propulsion'),
            ('Systems-Engineer', 'Systems'),
            ('Avionics-Engineer', 'Avionics'),
            ('Rocket-Engineer', 'Propulsion'),
        ]

        totalSteps = len(searchTerms)

        for idx, (searchSlug, discipline) in enumerate(searchTerms):
            if progressCallback:
                progressCallback(idx, totalSteps, f'Indeed: {searchSlug}...')

            url = f'https://www.indeed.com/career/{searchSlug}/salaries'
            content = self._makeRequest(url, headers=self._browserHeaders)

            if not content:
                continue

            try:
                soup = BeautifulSoup(content, 'html.parser')

                # Indeed often embeds salary data in JSON-LD
                scriptTags = soup.find_all('script', type='application/ld+json')
                for script in scriptTags:
                    try:
                        jsonData = json.loads(script.string)
                        if isinstance(jsonData, dict) and 'estimatedSalary' in jsonData:
                            for estimate in jsonData['estimatedSalary']:
                                currency = estimate.get('currency', 'USD')
                                if currency != 'USD':
                                    continue
                                minVal = estimate.get('percentile25', estimate.get('minValue', 0))
                                maxVal = estimate.get('percentile75', estimate.get('maxValue', 0))
                                jobTitle = estimate.get('name', searchSlug.replace('-', ' '))

                                if minVal or maxVal:
                                    rows.append({
                                        'Company': 'Indeed',
                                        'Listing': f'{jobTitle} (Indeed)',
                                        'Min': float(minVal) if minVal else 0,
                                        'Max': float(maxVal) if maxVal else 0,
                                        'Location': 'National',
                                        'State': 'US',
                                        'Discipline': discipline,
                                        'Seniority': self._inferSeniority(jobTitle),
                                        'Link': url,
                                    })
                    except (json.JSONDecodeError, TypeError, KeyError):
                        continue

                # Fallback: parse salary ranges from page text
                if not rows or rows[-1].get('Link') != url:
                    pageText = soup.get_text()
                    # Look for salary range patterns
                    rangePattern = re.findall(r'\$(\d{2,3}(?:,\d{3})*)', pageText)
                    if len(rangePattern) >= 2:
                        try:
                            vals = sorted([float(v.replace(',', '')) for v in rangePattern])
                            plausible = [v for v in vals if 30000 <= v <= 500000]
                            if len(plausible) >= 2:
                                rows.append({
                                    'Company': 'Indeed',
                                    'Listing': f'{searchSlug.replace("-", " ")} (Indeed)',
                                    'Min': plausible[0],
                                    'Max': plausible[-1],
                                    'Location': 'National',
                                    'State': 'US',
                                    'Discipline': discipline,
                                    'Seniority': 'All Levels',
                                    'Link': url,
                                })
                        except ValueError:
                            pass

            except Exception as e:
                logger.error(f'Indeed parsing error for {searchSlug}: {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'Indeed scrape complete.')

        if not rows:
            logger.warning('No Indeed data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'Indeed')

    # ------------------------------------------------------------------ #
    # -- Data Source: Salary.com -- #
    # ------------------------------------------------------------------ #

    def scrapeSalaryCom(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape Salary.com for aerospace engineer salary data.

        Salary.com publishes benchmark salary pages with detailed percentile
        data (10th through 90th) for standardized job titles at levels I-V.
        Pages use JSON-LD structured data and have light anti-bot protections,
        making them reliable for static HTTP scraping.

        URL pattern: https://www.salary.com/research/salary/benchmark/{slug}-salary

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data

        '''

        logger.info('Scraping Salary.com...')

        rows = []

        # Salary.com uses leveled job titles (I-V) which map to seniority.
        # Each level has its own page with distinct salary ranges.
        searchTerms = [
            ('aerospace-engineer-i', 'Aerospace', 'Entry'),
            ('aerospace-engineer-ii', 'Aerospace', 'Mid'),
            ('aerospace-engineer-iii', 'Aerospace', 'Senior'),
            ('aerospace-engineer-iv', 'Aerospace', 'Staff'),
            ('aerospace-engineer-v', 'Aerospace', 'Principal'),
            ('mechanical-engineer-i', 'Mechanical', 'Entry'),
            ('mechanical-engineer-iii', 'Mechanical', 'Senior'),
            ('mechanical-engineer-v', 'Mechanical', 'Principal'),
            ('systems-engineer-i', 'Systems', 'Entry'),
            ('systems-engineer-iii', 'Systems', 'Senior'),
            ('systems-engineer-v', 'Systems', 'Principal'),
            ('avionics-engineer-i', 'Avionics', 'Entry'),
            ('avionics-engineer-iii', 'Avionics', 'Senior'),
        ]

        totalSteps = len(searchTerms)

        for idx, (searchSlug, discipline, seniority) in enumerate(searchTerms):
            if progressCallback:
                progressCallback(idx, totalSteps, f'Salary.com: {searchSlug}...')

            url = f'https://www.salary.com/research/salary/benchmark/{searchSlug}-salary'
            content = self._makeRequest(url, headers=self._browserHeaders)

            if not content:
                continue

            try:
                soup = BeautifulSoup(content, 'html.parser')

                # Salary.com embeds JSON-LD with OccupationAggregationByEmployer schema
                scriptTags = soup.find_all('script', type='application/ld+json')
                for script in scriptTags:
                    try:
                        jsonData = json.loads(script.string)
                        # Handle both single objects and arrays
                        if isinstance(jsonData, list):
                            jsonData = jsonData[0] if jsonData else {}

                        # Look for estimatedSalary or occupationalCategory data
                        if isinstance(jsonData, dict) and 'estimatedSalary' in jsonData:
                            for estimate in jsonData['estimatedSalary']:
                                currency = estimate.get('currency', 'USD')
                                if currency != 'USD':
                                    continue
                                minVal = estimate.get('percentile10', estimate.get('minValue', 0))
                                maxVal = estimate.get('percentile90', estimate.get('maxValue', 0))
                                medianVal = estimate.get('median', estimate.get('percentile50', 0))
                                jobTitle = estimate.get('name', searchSlug.replace('-', ' ').title())

                                if minVal or maxVal:
                                    rows.append({
                                        'Company': 'Salary.com',
                                        'Listing': f'{jobTitle} (Salary.com)',
                                        'Min': float(minVal) if minVal else 0,
                                        'Max': float(maxVal) if maxVal else 0,
                                        'Location': 'National',
                                        'State': 'US',
                                        'Discipline': discipline,
                                        'Seniority': seniority,
                                        'Link': url,
                                    })
                    except (json.JSONDecodeError, TypeError, KeyError):
                        continue

                # Fallback: extract salary values from meta description or page text
                if not rows or rows[-1].get('Link') != url:
                    metaDesc = soup.find('meta', attrs={'name': 'description'})
                    if metaDesc and metaDesc.get('content'):
                        descText = metaDesc['content']
                        salaryPattern = re.findall(r'\$(\d{2,3}(?:,\d{3})*)', descText)
                        if len(salaryPattern) >= 2:
                            try:
                                vals = sorted([float(v.replace(',', '')) for v in salaryPattern])
                                plausible = [v for v in vals if 30000 <= v <= 500000]
                                if len(plausible) >= 2:
                                    rows.append({
                                        'Company': 'Salary.com',
                                        'Listing': f'{searchSlug.replace("-", " ").title()} (Salary.com)',
                                        'Min': plausible[0],
                                        'Max': plausible[-1],
                                        'Location': 'National',
                                        'State': 'US',
                                        'Discipline': discipline,
                                        'Seniority': seniority,
                                        'Link': url,
                                    })
                            except ValueError:
                                pass

            except Exception as e:
                logger.error(f'Salary.com parsing error for {searchSlug}: {e}')

        if progressCallback:
            progressCallback(totalSteps, totalSteps, 'Salary.com scrape complete.')

        if not rows:
            logger.warning('No Salary.com data collected.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)
        return self._normalizeToSchema(rawDf, {
            'Company': 'Company',
            'Listing': 'Listing',
            'Min': 'Min',
            'Max': 'Max',
            'Location': 'Location',
            'State': 'State',
            'Discipline': 'Discipline',
            'Seniority': 'Seniority',
            'Link': 'Link',
        }, 'Salary.com')

    # ------------------------------------------------------------------ #
    # -- Data Source: Company Career Pages -- #
    # ------------------------------------------------------------------ #

    def scrapeCareerPages(self, progressCallback: Optional[Callable] = None) -> pd.DataFrame:

        '''

        Scrape job listings directly from company career websites.

        Delegates to CareerPageScraper which uses platform-specific parsers
        (Greenhouse JSON API, Workday direct HTML, generic HTML) based on
        ATS platform configs in compensationReference.md.

        Parameters:
        -----------
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized compensation data from career pages

        '''

        logger.info('Scraping company career pages...')
        if progressCallback:
            progressCallback(0, 1, 'Initializing career page scraper...')

        from careerPageScraper import CareerPageScraper

        careerScraper = CareerPageScraper(self)
        merged = careerScraper.scrapeAllMerged(
            companies=self.config.targetCompanies,
            progressCallback=progressCallback,
        )

        logger.info(f'Career pages: collected {len(merged)} total listings')
        return merged

    # ------------------------------------------------------------------ #
    # -- Orchestration -- #
    # ------------------------------------------------------------------ #

    def scrapeAll(
        self,
        sources: Optional[List[str]] = None,
        progressCallback: Optional[Callable] = None,
    ) -> Dict[str, pd.DataFrame]:
        
        '''

        Run multiple scrapers, returning dict of source name -> DataFrame.
        Catches exceptions per source so one failure does not stop others.

        Parameters:
        -----------
        sources : list, optional
            List of source keys to run (default: all available).
            Valid keys: 'dataUsa', 'bls', 'fred', 'h1b', 'levelsFyi',
            'glassdoor', 'payscale', 'ziprecruiter', 'comparably', 'indeed',
            'salaryCom', 'careerPages'
        progressCallback : callable, optional
            Function(step: int, total: int, message: str) for overall progress

        Returns:
        --------
        dict : Map of source key -> normalized DataFrame

        '''

        if sources is None:
            sources = list(self.availableSources.keys())

        # Map source keys to scraper methods
        scraperMethods = {
            'dataUsa': self.scrapeDataUsa,
            'bls': self.scrapeBls,
            'fred': self.scrapeFred,
            'h1b': self.scrapeH1b,
            'levelsFyi': self.scrapeLevelsFyi,
            'glassdoor': self.scrapeGlassdoor,
            'payscale': self.scrapePayscale,
            'ziprecruiter': self.scrapeZiprecruiter,
            'comparably': self.scrapeComparably,
            'indeed': self.scrapeIndeed,
            'salaryCom': self.scrapeSalaryCom,
            'careerPages': self.scrapeCareerPages,
        }

        results = {}
        errors = {}
        totalSources = len(sources)

        for idx, sourceKey in enumerate(sources):
            if progressCallback:
                sourceName = self.availableSources[sourceKey]['name']
                progressCallback(idx, totalSources, f'Running {sourceName}...')

            if sourceKey not in scraperMethods:
                logger.warning(f'Unknown source: {sourceKey}')
                continue

            try:
                # Create a sub-progress callback that scales within this source
                def subProgress(step, total, message, _idx=idx, _total=totalSources):
                    if progressCallback:
                        overallProgress = _idx + (step / max(total, 1))
                        progressCallback(overallProgress, _total, message)

                df = scraperMethods[sourceKey](progressCallback=subProgress)
                results[sourceKey] = df
                rowCount = len(df) if df is not None else 0
                logger.info(f'{sourceKey}: collected {rowCount} rows')
            except Exception as e:
                logger.error(f'Source {sourceKey} failed: {e}')
                errors[sourceKey] = str(e)
                results[sourceKey] = pd.DataFrame(columns=surveyColumns + ['DataSource'])

        if progressCallback:
            progressCallback(totalSources, totalSources, 'All sources complete.')

        # Attach errors dict as attribute for UI to access
        self._lastErrors = errors

        return results

    def mergeResults(self, resultsBySource: Dict[str, pd.DataFrame]) -> pd.DataFrame:

        '''

        Combine results from all sources into a single DataFrame.
        Deduplicates by (Company, Listing, Location).

        Parameters:
        -----------
        resultsBySource : dict
            Map of source key -> DataFrame

        Returns:
        --------
        pd.DataFrame : Combined and deduplicated DataFrame

        '''

        frames = [df for df in resultsBySource.values() if df is not None and not df.empty]

        if not frames:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        combined = pd.concat(frames, ignore_index=True)

        # Deduplicate
        combined = combined.drop_duplicates(
            subset=['Company', 'Listing', 'Location'], keep='first'
        )

        # Recalculate midpoint
        combined['Midpoint'] = (
            pd.to_numeric(combined['Min'], errors='coerce') +
            pd.to_numeric(combined['Max'], errors='coerce')
        ) / 2

        return combined.reset_index(drop=True)

    # ---------------------------------------------------------------------- #
    # -- Convenience Methods -- #
    # ---------------------------------------------------------------------- #

    def runFullScrape(
        self,
        sources: Optional[List[str]] = None,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Scrape all (or selected) sources and return a single merged DataFrame.
        Combines scrapeAll() and mergeResults() into one call.

        Parameters:
        -----------
        sources : list, optional
            Source keys to run. Default: all available.
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Merged and deduplicated results

        Examples:
        ---------
        >>> scraper = CompensationScraper(ScraperConfig())
        >>> df = scraper.runFullScrape()

        '''

        resultsBySource = self.scrapeAll(sources=sources, progressCallback=progressCallback)
        return self.mergeResults(resultsBySource)

    def runSingleSource(
        self,
        source: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Scrape a single data source and return its normalized DataFrame.

        Parameters:
        -----------
        source : str
            Source key (e.g. 'bls', 'h1b', 'glassdoor')
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized data from the single source

        Examples:
        ---------
        >>> scraper = CompensationScraper(ScraperConfig())
        >>> blsDf = scraper.runSingleSource('bls')

        '''

        resultsBySource = self.scrapeAll(sources=[source], progressCallback=progressCallback)
        return resultsBySource.get(source, pd.DataFrame())

    def exportToExcel(self, df: pd.DataFrame, outputPath: str) -> str:

        '''

        Export a DataFrame to Excel in a format compatible with the survey file.

        Parameters:
        -----------
        df : pd.DataFrame
            DataFrame to export
        outputPath : str
            Path for the output Excel file

        Returns:
        --------
        str : Absolute path to the output file

        Examples:
        ---------
        >>> scraper = CompensationScraper(ScraperConfig())
        >>> df = scraper.runFullScrape()
        >>> scraper.exportToExcel(df, 'compensationData.xlsx')

        '''

        absPath = os.path.abspath(outputPath)
        exportCols = [c for c in surveyColumns + ['DataSource', 'Midpoint'] if c in df.columns]
        df[exportCols].copy().to_excel(absPath, index=False, sheet_name='Scraped Data')
        return absPath

    def lastErrors(self) -> Dict[str, str]:

        '''

        Return errors from the last scrapeAll() call.

        Returns:
        --------
        dict : Map of source key -> error message

        '''

        return getattr(self, '_lastErrors', {})

    def clearCache(self):

        '''
        
        Delete all cached responses.
        
        '''

        cacheDir = self.config.cacheDir
        
        if os.path.exists(cacheDir):
            for filename in os.listdir(cacheDir):
                filepath = os.path.join(cacheDir, filename)
                if filepath.endswith('.json'):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass
            logger.info('Cache cleared.')
