
# -- Career Page Scraper -- #

'''

Scrapes job listings directly from the career pages of target aerospace
companies. Uses platform-specific parsers for known ATS systems (Greenhouse,
Lever, Workday) and falls back to generic HTML scraping for unknown sites.

Platform Support:
    - Greenhouse: Free public JSON API (SpaceX, Rocket Lab)
    - Lever: Free public JSON API
    - Workday: Direct HTML request (JS-heavy pages may return limited data)
    - Pinpoint/Rippling/Taleo: Generic HTML scraping

All results are normalized to the surveyColumns schema defined in auditUtils.py,
making them directly mergeable with existing survey and aggregator data.

Author: Sean Bowman
Date:   02/28/2026

'''

# Standard library imports
import re
import logging
from typing import Optional, Dict, List, Callable, Tuple

# Third-party imports
import requests
import pandas as pd
from bs4 import BeautifulSoup

# Local imports
from auditUtils import surveyColumns
from referenceParser import loadReferenceData

logger = logging.getLogger('careerPageScraper')


# ---------------------------------------------------------------------- #
# -- Salary Extraction Helpers -- #
# ---------------------------------------------------------------------- #

def extractSalaryFromText(text: str) -> Tuple[Optional[float], Optional[float]]:

    '''

    Extract salary range (min, max) from unstructured text using regex.

    Handles common salary formats found in job listings:
    - "$120,000 - $160,000"
    - "$120K - $160K"
    - "$120,000 to $160,000 per year"
    - "$120,000-$160,000/yr"
    - "$120,000 annually"
    - "Salary: 163,200 - 250,000" (bare numbers with salary context)
    - "Base Compensation: 163200 to 250000"

    Parameters:
    -----------
    text : str
        Job description or listing text that may contain salary info

    Returns:
    --------
    Tuple[Optional[float], Optional[float]] : (minSalary, maxSalary) or (None, None)

    '''

    if not text:
        return (None, None)

    # Pattern for salary ranges like "$120,000 - $160,000" or "$120K-$160K".
    # Second dollar sign is optional to handle formats like "$163,200-250,000".
    rangePattern = re.compile(
        r'\$\s*([\d,]+(?:\.\d+)?)\s*[Kk]?\s*'     # min salary ($ required)
        r'(?:[-\u2013\u2014]|to)\s*'                 # separator
        r'\$?\s*([\d,]+(?:\.\d+)?)\s*[Kk]?'         # max salary ($ optional)
        r'(?:\s*(?:per\s+year|annually|/\s*yr|/\s*year|a\s+year))?',  # optional annual qualifier
        re.IGNORECASE,
    )

    # Pattern for bare number ranges preceded by a salary context word
    # e.g. "Salary: 163,200 - 250,000" or "Base Compensation: 163200 to 250000"
    contextRangePattern = re.compile(
        r'(?:salary|compensation|pay|base|range|annual|wage)'
        r'[^\d\n$]{0,60}'                             # allow up to 60 non-digit chars between keyword and value
        r'([\d,]+(?:\.\d+)?)\s*[Kk]?\s*'             # min value
        r'(?:[-\u2013\u2014]|to)\s*'                  # separator
        r'([\d,]+(?:\.\d+)?)\s*[Kk]?',               # max value
        re.IGNORECASE,
    )

    # Pattern for single salary like "$120,000 annually"
    singlePattern = re.compile(
        r'\$\s*([\d,]+(?:\.\d+)?)\s*[Kk]?'
        r'\s*(?:per\s+year|annually|/\s*yr|/\s*year|a\s+year)',
        re.IGNORECASE,
    )

    # Try dollar-prefixed range pattern first (most reliable)
    for match in rangePattern.finditer(text):
        minVal = _parseSalaryValue(match.group(1), 'K' in match.group(0).upper())
        maxVal = _parseSalaryValue(match.group(2), 'K' in match.group(0).upper())
        # Plausibility check -- aerospace engineering salaries
        if minVal and maxVal and 25000 <= minVal <= 500000 and 25000 <= maxVal <= 500000:
            return (min(minVal, maxVal), max(minVal, maxVal))

    # Try context-anchored bare-number range pattern
    for match in contextRangePattern.finditer(text):
        minVal = _parseSalaryValue(match.group(1), 'K' in match.group(0).upper())
        maxVal = _parseSalaryValue(match.group(2), 'K' in match.group(0).upper())
        if minVal and maxVal and 25000 <= minVal <= 500000 and 25000 <= maxVal <= 500000:
            return (min(minVal, maxVal), max(minVal, maxVal))

    # Try single salary pattern
    for match in singlePattern.finditer(text):
        val = _parseSalaryValue(match.group(1), 'K' in match.group(0).upper())
        if val and 25000 <= val <= 500000:
            return (val, val)

    return (None, None)


def extractSalaryFromHtml(html: str) -> Tuple[Optional[float], Optional[float]]:

    '''

    Extract salary range from a job listing HTML page.

    Checks structured data sources first (JSON-LD JobPosting schema), then
    falls back to parsing all visible text via extractSalaryFromText(). This
    catches salary data embedded in meta tags or structured schema blocks that
    may not appear in the plain-text description.

    Parameters:
    -----------
    html : str
        Raw HTML content of the job listing page

    Returns:
    --------
    Tuple[Optional[float], Optional[float]] : (minSalary, maxSalary) or (None, None)

    '''

    if not html:
        return (None, None)

    import json as _json

    soup = BeautifulSoup(html, 'html.parser')

    # -- Check JSON-LD structured data for JobPosting schema -- #
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = _json.loads(script.string or '')
        except (ValueError, TypeError):
            continue

        # Handle both single objects and arrays of objects
        if isinstance(data, list):
            candidates = data
        else:
            candidates = [data]

        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            objType = obj.get('@type', '')
            if objType != 'JobPosting':
                continue

            baseSalary = obj.get('baseSalary', {})
            if not isinstance(baseSalary, dict):
                continue

            salaryValue = baseSalary.get('value', {})
            if not isinstance(salaryValue, dict):
                # Direct numeric value
                try:
                    val = float(salaryValue)
                    if 25000 <= val <= 500000:
                        return (val, val)
                except (ValueError, TypeError):
                    pass
                continue

            # MonetaryAmountDistribution with minValue/maxValue
            minVal = salaryValue.get('minValue') or salaryValue.get('value')
            maxVal = salaryValue.get('maxValue') or salaryValue.get('value')
            try:
                minVal = float(minVal)
                maxVal = float(maxVal)
                if 25000 <= minVal <= 500000 and 25000 <= maxVal <= 500000:
                    return (min(minVal, maxVal), max(minVal, maxVal))
            except (ValueError, TypeError):
                pass

    # -- Fall back to plain-text extraction -- #
    plainText = soup.get_text(separator=' ')
    return extractSalaryFromText(plainText)


def _parseSalaryValue(valueStr: str, hasKSuffix: bool) -> Optional[float]:

    '''

    Parse a salary string into a float value.

    Parameters:
    -----------
    valueStr : str
        Salary value string (e.g., '120,000' or '120')
    hasKSuffix : bool
        Whether the original text had a K suffix (multiply by 1000)

    Returns:
    --------
    Optional[float] : Parsed salary value or None

    '''

    try:
        value = float(valueStr.replace(',', ''))
        if hasKSuffix and value < 1000:
            value *= 1000
        return value
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------- #
# -- Career Page Scraper Class -- #
# ---------------------------------------------------------------------- #

class CareerPageScraper:

    '''

    Scrapes job listings from company career pages using platform-specific
    parsers. Designed to be instantiated with a reference to the parent
    CompensationScraper for access to caching, rate limiting, and inference
    helpers.

    Parameters:
    -----------
    parentScraper : CompensationScraper
        Parent scraper instance providing _makeRequest(), _inferLevel(),
        _inferSeniority(), _inferDiscipline(), _mapLocation(), and
        _normalizeToSchema() helpers.

    Examples:
    ---------
    >>> from compensationScraper import CompensationScraper, ScraperConfig
    >>> scraper = CompensationScraper(ScraperConfig())
    >>> careerScraper = CareerPageScraper(scraper)
    >>> results = careerScraper.scrapeAll()

    '''

    # Platform dispatcher -- maps ATS platform name to scraper method name
    _platformMethods = {
        'greenhouse': '_scrapeGreenhouse',
        'lever': '_scrapeLever',
        'workday': '_scrapeWorkday',
        'talentbrew': '_scrapeTalentBrew',
    }

    def __init__(self, parentScraper) -> None:

        '''

        Initialize the career page scraper.

        Parameters:
        -----------
        parentScraper : CompensationScraper
            Parent scraper with shared helpers

        '''

        self._parent = parentScraper
        self._config = parentScraper.config
        self._careerPages = loadReferenceData().get('careerPages', [])

    # ------------------------------------------------------------------ #
    # -- Greenhouse (Public JSON API) -- #
    # ------------------------------------------------------------------ #

    def _scrapeGreenhouse(
        self,
        company: str,
        boardSlug: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Scrape job listings from the Greenhouse public JSON API.

        Greenhouse exposes a free, unauthenticated API at
        boards-api.greenhouse.io that returns structured JSON with job titles,
        locations, and full HTML descriptions. Salary data is extracted from
        the description text via regex.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        boardSlug : str
            Greenhouse board identifier (e.g., 'spacex', 'rocketlab')
        careerUrl : str
            Original career page URL (for Link column)
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized job listing data

        '''

        logger.info(f'Scraping Greenhouse API for {company} (board: {boardSlug})...')

        apiUrl = f'https://boards-api.greenhouse.io/v1/boards/{boardSlug}/jobs'

        content = self._parent._makeRequest(
            apiUrl,
            params={'content': 'true'},
            useCache=True,
            sourceName='careerPages',
        )

        if not content:
            logger.warning(f'No response from Greenhouse API for {company}')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        try:
            import json
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.error(f'Failed to parse Greenhouse JSON for {company}')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        jobs = data.get('jobs', [])
        logger.info(f'Greenhouse returned {len(jobs)} jobs for {company}')

        if progressCallback:
            progressCallback(0.5, 1, f'{company}: processing {len(jobs)} listings...')

        rows = []
        for job in jobs:
            title = job.get('title', '')
            locationName = ''
            state = 'Unknown'

            # Greenhouse location can be a dict or nested in 'location'
            locData = job.get('location', {})
            if isinstance(locData, dict):
                locationName = locData.get('name', '')
            elif isinstance(locData, str):
                locationName = locData

            # Parse location into (city, state)
            city, state = self._parent._mapLocation(locationName)

            # Extract salary from job description HTML content
            # extractSalaryFromHtml checks JSON-LD first, then falls back to text parsing
            descHtml = job.get('content', '')
            minSalary, maxSalary = extractSalaryFromHtml(descHtml) if descHtml else (None, None)

            # Build job listing URL
            jobId = job.get('id', '')
            jobUrl = f'https://boards.greenhouse.io/{boardSlug}/jobs/{jobId}' if jobId else careerUrl

            rows.append({
                'Company': company,
                'Listing': title,
                'Level': self._parent._inferLevel(title),
                'Seniority': self._parent._inferSeniority(title),
                'Location': city if city != 'Unknown' else locationName,
                'State': state,
                'Discipline': self._parent._inferDiscipline(title),
                'Min': minSalary,
                'Max': maxSalary,
                'Link': jobUrl,
            })

        if not rows:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)

        return self._parent._normalizeToSchema(
            rawDf,
            {col: col for col in rawDf.columns},
            f'Career Page ({company})',
            keepWithoutSalary=True,
        )

    # ------------------------------------------------------------------ #
    # -- Lever (Public JSON API) -- #
    # ------------------------------------------------------------------ #

    def _scrapeLever(
        self,
        company: str,
        boardSlug: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Scrape job listings from the Lever public JSON API.

        Lever exposes a public API at api.lever.co that returns structured
        JSON with job titles, locations, and description text.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        boardSlug : str
            Lever company identifier
        careerUrl : str
            Original career page URL (for Link column)
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized job listing data

        '''

        logger.info(f'Scraping Lever API for {company} (slug: {boardSlug})...')

        apiUrl = f'https://api.lever.co/v0/postings/{boardSlug}'

        content = self._parent._makeRequest(
            apiUrl,
            useCache=True,
            sourceName='careerPages',
        )

        if not content:
            logger.warning(f'No response from Lever API for {company}')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        try:
            import json
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.error(f'Failed to parse Lever JSON for {company}')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        if not isinstance(data, list):
            logger.warning(f'Lever returned unexpected format for {company}')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        logger.info(f'Lever returned {len(data)} jobs for {company}')

        if progressCallback:
            progressCallback(0.5, 1, f'{company}: processing {len(data)} listings...')

        rows = []
        for posting in data:
            title = posting.get('text', '')
            locationName = posting.get('categories', {}).get('location', '')
            city, state = self._parent._mapLocation(locationName)

            # Lever description may be HTML ('description') or plain text ('descriptionPlain').
            # Prefer the HTML field so extractSalaryFromHtml can check JSON-LD blocks.
            descHtml = posting.get('description', '')
            descText = posting.get('descriptionPlain', '')
            if descHtml:
                minSalary, maxSalary = extractSalaryFromHtml(descHtml)
            else:
                minSalary, maxSalary = extractSalaryFromText(descText)

            # Also check additional content sections for salary info
            if minSalary is None:
                for listItem in posting.get('lists', []):
                    listContent = listItem.get('content', '')
                    minSalary, maxSalary = extractSalaryFromHtml(listContent) if '<' in listContent else extractSalaryFromText(listContent)
                    if minSalary is not None:
                        break

            jobUrl = posting.get('hostedUrl', '') or posting.get('applyUrl', '') or careerUrl

            rows.append({
                'Company': company,
                'Listing': title,
                'Level': self._parent._inferLevel(title),
                'Seniority': self._parent._inferSeniority(title),
                'Location': city if city != 'Unknown' else locationName,
                'State': state,
                'Discipline': self._parent._inferDiscipline(title),
                'Min': minSalary,
                'Max': maxSalary,
                'Link': jobUrl,
            })

        if not rows:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)

        return self._parent._normalizeToSchema(
            rawDf,
            {col: col for col in rawDf.columns},
            f'Career Page ({company})',
            keepWithoutSalary=True,
        )

    # ------------------------------------------------------------------ #
    # -- Workday (Direct HTML Request) -- #
    # ------------------------------------------------------------------ #

    def _scrapeWorkday(
        self,
        company: str,
        boardSlug: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Scrape job listings from Workday-based career portals.

        Workday portals are JavaScript SPAs. A direct HTTP request is
        attempted first; most Workday portals return a minimal HTML shell
        without JS rendering, so results may be limited. If no content is
        returned the company is skipped.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        boardSlug : str
            Not used for Workday (URL is the primary identifier)
        careerUrl : str
            Workday career portal URL
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized job listing data

        '''

        logger.info(f'Scraping Workday portal for {company}: {careerUrl}')

        # Add engineering keyword filter to the URL if possible.
        searchUrl = careerUrl
        if '?' not in searchUrl:
            searchUrl += '?q=engineer'
        elif 'q=' not in searchUrl:
            searchUrl += '&q=engineer'

        # Workday portals return HTTP 406 to non-browser requests (JS-rendered SPA).
        # suppressWarnings=True logs non-200 at DEBUG so they don't appear as
        # actionable failures in the scrape log.
        content = self._parent._makeRequest(
            searchUrl,
            useCache=True,
            sourceName='careerPages',
            headers=self._parent._browserHeaders,
            suppressWarnings=True,
        )

        if not content:
            logger.debug(
                f'No response from Workday portal for {company}. '
                f'Workday is a JS-rendered SPA and returns 406 without JS rendering.'
            )
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        return self._parseWorkdayHtml(company, content, careerUrl, progressCallback)

    def _parseWorkdayHtml(
        self,
        company: str,
        html: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Parse Workday-rendered HTML to extract job listings.

        Workday uses a consistent component structure with job cards
        containing title, location, and posted date. Salary data is
        rarely present on listing pages but may appear in individual
        job descriptions.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        html : str
            Rendered HTML from Workday portal
        careerUrl : str
            Base career URL for building job links
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized job listing data

        '''

        soup = BeautifulSoup(html, 'html.parser')
        rows = []

        # Workday uses data-automation-id attributes for job elements.
        # Common patterns:
        #   data-automation-id="jobTitle" -> job title link
        #   data-automation-id="jobLocation" -> location text
        #   data-automation-id="jobPostingListItem" -> job card container

        # Try Workday's standard job list structure
        jobCards = soup.find_all(attrs={'data-automation-id': 'jobPostingListItem'})

        if not jobCards:
            # Try alternate Workday structure with section elements
            jobCards = soup.find_all('li', class_=re.compile(r'css-'))
            # Also look for any links with job-related href patterns
            if not jobCards:
                jobCards = soup.find_all('a', href=re.compile(r'/job/|/jobs/'))

        for card in jobCards:
            title = ''
            locationName = ''
            jobUrl = careerUrl

            # Extract title from Workday job card
            titleEl = card.find(attrs={'data-automation-id': 'jobTitle'})
            if titleEl:
                title = titleEl.get_text(strip=True)
                # Get link if available
                titleLink = titleEl.find('a') if titleEl.name != 'a' else titleEl
                if titleLink and titleLink.get('href'):
                    href = titleLink['href']
                    if href.startswith('http'):
                        jobUrl = href
                    else:
                        jobUrl = careerUrl.rstrip('/') + '/' + href.lstrip('/')
            else:
                # Fallback: look for any heading or link text
                heading = card.find(['h2', 'h3', 'a'])
                if heading:
                    title = heading.get_text(strip=True)
                    if heading.name == 'a' and heading.get('href'):
                        href = heading['href']
                        if href.startswith('http'):
                            jobUrl = href

            # Extract location
            locEl = card.find(attrs={'data-automation-id': 'jobLocation'})
            if locEl:
                locationName = locEl.get_text(strip=True)
            else:
                # Try finding location by common patterns
                locEl = card.find(string=re.compile(r'[A-Z][a-z]+,\s*[A-Z]{2}'))
                if locEl:
                    locationName = locEl.strip()

            if not title:
                continue

            city, state = self._parent._mapLocation(locationName)

            # Extract salary from card text (rarely present on Workday listing pages)
            cardText = card.get_text(separator=' ')
            minSalary, maxSalary = extractSalaryFromText(cardText)

            rows.append({
                'Company': company,
                'Listing': title,
                'Level': self._parent._inferLevel(title),
                'Seniority': self._parent._inferSeniority(title),
                'Location': city if city != 'Unknown' else locationName,
                'State': state,
                'Discipline': self._parent._inferDiscipline(title),
                'Min': minSalary,
                'Max': maxSalary,
                'Link': jobUrl,
            })

        logger.info(f'Parsed {len(rows)} job listings from Workday HTML for {company}')

        if progressCallback:
            progressCallback(0.8, 1, f'{company}: parsed {len(rows)} listings from Workday')

        if not rows:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)

        return self._parent._normalizeToSchema(
            rawDf,
            {col: col for col in rawDf.columns},
            f'Career Page ({company})',
            keepWithoutSalary=True,
        )

    # ------------------------------------------------------------------ #
    # -- Generic HTML Scraper -- #
    # ------------------------------------------------------------------ #

    def _scrapeGeneric(
        self,
        company: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Generic career page scraper for unknown ATS platforms.

        Attempts to extract job listings from HTML using common patterns
        (job cards, list items, links with job-related text). Falls back
        to screenshot+OCR if HTML extraction yields no results.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        careerUrl : str
            Career page URL
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized job listing data

        '''

        logger.info(f'Attempting generic HTML scrape for {company}: {careerUrl}')

        # Try direct request
        content = self._parent._makeRequest(
            careerUrl,
            useCache=True,
            sourceName='careerPages',
            headers=self._parent._browserHeaders,
        )

        if not content:
            logger.warning(f'No response from {company} career page. Skipping.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        soup = BeautifulSoup(content, 'html.parser')
        rows = []

        # Strategy 1: Look for job listing links with engineering-related text
        engineeringKeywords = [
            'engineer', 'propulsion', 'avionics', 'mechanical', 'systems',
            'structures', 'thermal', 'test', 'software', 'electrical',
            'manufacturing', 'quality', 'aerospace', 'gnc', 'guidance',
            'analyst', 'scientist', 'designer', 'director', 'lead', 'manager',
        ]

        # URL path segments that indicate blog, story, or profile pages rather
        # than actual job listings. These are common on career pages that mix
        # editorial content with open roles (e.g. Boeing's jobs.boeing.com).
        nonJobUrlSegments = [
            '/meet-', '/blog/', '/story/', '/stories/', '/article/',
            '/news/', '/learn-more', '/careers-in-', '/about/', '/press/',
            '/profile/', '/podcast/', '/video/', '/webinar/',
        ]

        # Title-level signals that a link is a blog post or story, not a job.
        # Matched as prefixes against lowercased link text.
        nonJobTitlePrefixes = (
            'meet ', 'from soccer', 'from interns', 'from excavating',
            'a passion for', 'an engineer', "ai creator", 'leading by',
            'continuous improvement', "lean into", 'learn more',
            'aim high', 'how ', 'why ', 'what ', 'when ',
        )

        # Find all links that look like job listings
        allLinks = soup.find_all('a', href=True)
        for link in allLinks:
            linkText = link.get_text(strip=True)
            if not linkText or len(linkText) < 5 or len(linkText) > 200:
                continue

            # Check if this looks like a job title
            textLower = linkText.lower()
            isJobLink = any(kw in textLower for kw in engineeringKeywords)

            if not isJobLink:
                continue

            # Exclude blog/story/profile content by URL pattern
            hrefCheck = link.get('href', '').lower()
            if any(seg in hrefCheck for seg in nonJobUrlSegments):
                continue

            # Exclude narrative blog-style titles
            if textLower.startswith(nonJobTitlePrefixes):
                continue

            from urllib.parse import urlparse
            href = link.get('href', '')
            if href.startswith('http'):
                jobUrl = href
            elif href.startswith('/'):
                # Build absolute URL from relative path
                parsed = urlparse(careerUrl)
                jobUrl = f'{parsed.scheme}://{parsed.netloc}{href}'
            else:
                jobUrl = careerUrl

            # Search up to 3 DOM levels above the link for a City, ST pattern.
            # Rippling and similar ATS platforms put location in a grandparent card
            # element rather than an immediate sibling.
            locationName = ''
            searchEl = link.parent
            locPattern = re.compile(r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)*,\s*[A-Z]{2}\b')
            for _ in range(3):
                if searchEl is None:
                    break
                for textNode in searchEl.find_all(string=locPattern):
                    locationName = textNode.strip()
                    break
                if locationName:
                    break
                searchEl = searchEl.parent

            city, state = self._parent._mapLocation(locationName)

            # Check for salary info in the card text (rarely present on list pages)
            cardEl = link.parent.parent if link.parent else link.parent
            cardText = cardEl.get_text(separator=' ') if cardEl else ''
            minSalary, maxSalary = extractSalaryFromText(cardText)

            rows.append({
                'Company': company,
                'Listing': linkText,
                'Level': self._parent._inferLevel(linkText),
                'Seniority': self._parent._inferSeniority(linkText),
                'Location': city if city != 'Unknown' else locationName,
                'State': state,
                'Discipline': self._parent._inferDiscipline(linkText),
                'Min': minSalary,
                'Max': maxSalary,
                'Link': jobUrl,
                '_jobUrl': jobUrl,  # kept for individual-page salary fallback below
            })

        logger.info(f'Generic scrape found {len(rows)} engineering job links for {company}')

        if progressCallback:
            progressCallback(0.7, 1, f'{company}: found {len(rows)} job links')

        if not rows:
            logger.warning(f'No job listings extracted from HTML for {company}.')
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        # -- Individual page salary fallback -- #
        # For rows where the card text had no salary, visit each individual listing
        # page. Many ATS platforms (Rippling, Pinpoint, etc.) only embed salary in
        # the per-job detail page, not the card on the listing index.
        missingSalaryRows = [r for r in rows if r.get('Min') is None and r.get('_jobUrl') and r['_jobUrl'] != careerUrl]
        if missingSalaryRows:
            logger.info(
                f'{company}: fetching {len(missingSalaryRows)} individual job pages for salary data...'
            )
        for row in missingSalaryRows:
            jobPageContent = self._parent._makeRequest(
                row['_jobUrl'],
                useCache=True,
                sourceName='careerPages',
                headers=self._parent._browserHeaders,
            )
            if jobPageContent:
                minVal, maxVal = extractSalaryFromHtml(jobPageContent)
                if minVal is not None:
                    row['Min'] = minVal
                    row['Max'] = maxVal

        # Drop the internal helper key before building the DataFrame
        for row in rows:
            row.pop('_jobUrl', None)

        rawDf = pd.DataFrame(rows)

        return self._parent._normalizeToSchema(
            rawDf,
            {col: col for col in rawDf.columns},
            f'Career Page ({company})',
            keepWithoutSalary=True,
        )

    # ------------------------------------------------------------------ #
    # -- Screenshot + Tesseract OCR Fallback -- #
    # ------------------------------------------------------------------ #

    def _screenshotAndParse(
        self,
        company: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Screenshot+OCR fallback — no longer available.

        This method previously used ZenRows for screenshot capture and
        Tesseract for OCR. ZenRows has been removed from this project.
        Method is retained as a stub so any stale call sites fail gracefully.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        careerUrl : str
            Career page URL (unused)
        progressCallback : callable, optional
            Unused

        Returns:
        --------
        pd.DataFrame : Empty DataFrame (screenshot+OCR is unavailable)

        '''

        logger.warning(
            f'Screenshot+OCR fallback is no longer available for {company}. '
            f'ZenRows has been removed. Skipping.'
        )
        return pd.DataFrame(columns=surveyColumns + ['DataSource'])

    def _parseOcrText(
        self,
        company: str,
        ocrText: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Parse OCR-extracted text into structured job listings.

        Looks for lines that match engineering job title patterns and
        extracts location and salary information from surrounding context.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        ocrText : str
            Raw text extracted from screenshot via OCR
        careerUrl : str
            Source URL for the Link column
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized job listing data

        '''

        rows = []
        lines = ocrText.split('\n')

        # Engineering-related title keywords to identify job listings
        titleKeywords = [
            'engineer', 'propulsion', 'avionics', 'mechanical', 'systems',
            'structures', 'thermal', 'test', 'software', 'electrical',
            'manufacturing', 'quality', 'aerospace', 'gnc', 'designer',
            'analyst', 'technician', 'specialist', 'architect', 'manager',
            'director', 'lead', 'principal', 'staff', 'senior',
        ]

        # Location pattern: "City, ST" or "City, State"
        locationPattern = re.compile(r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)*),\s*([A-Z]{2})\b')

        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) < 5:
                continue

            lineLower = line.lower()

            # Check if this line looks like a job title
            if not any(kw in lineLower for kw in titleKeywords):
                continue

            # Skip lines that are clearly not job titles
            if any(skip in lineLower for skip in ['apply', 'search', 'filter', 'sign in', 'log in', 'cookie']):
                continue

            title = line

            # Look at surrounding lines for location and salary context
            contextLines = lines[max(0, i - 2):min(len(lines), i + 3)]
            contextText = ' '.join(contextLines)

            # Extract location from context
            locationName = ''
            state = 'Unknown'
            locMatch = locationPattern.search(contextText)
            if locMatch:
                locationName = f'{locMatch.group(1)}, {locMatch.group(2)}'
                state = locMatch.group(2)

            # Extract salary from context
            minSalary, maxSalary = extractSalaryFromText(contextText)

            city, state = self._parent._mapLocation(locationName)

            rows.append({
                'Company': company,
                'Listing': title,
                'Level': self._parent._inferLevel(title),
                'Seniority': self._parent._inferSeniority(title),
                'Location': city if city != 'Unknown' else locationName,
                'State': state,
                'Discipline': self._parent._inferDiscipline(title),
                'Min': minSalary,
                'Max': maxSalary,
                'Link': careerUrl,
            })

        logger.info(f'OCR text parsing found {len(rows)} potential job listings for {company}')

        if progressCallback:
            progressCallback(0.9, 1, f'{company}: parsed {len(rows)} listings from OCR')

        if not rows:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        rawDf = pd.DataFrame(rows)

        return self._parent._normalizeToSchema(
            rawDf,
            {col: col for col in rawDf.columns},
            f'Career Page ({company})',
            keepWithoutSalary=True,
        )

    # ------------------------------------------------------------------ #
    # -- TalentBrew (Boeing) -- #
    # ------------------------------------------------------------------ #

    def _scrapeTalentBrew(
        self,
        company: str,
        boardSlug: str,
        careerUrl: str,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Scrape job listings from TalentBrew-powered career sites (e.g. Boeing).

        Uses the site's XML sitemap to get authoritative job URLs rather than
        the /search-jobs/ API endpoint, which is disallowed in robots.txt and
        subject to bot detection. Actual job listings are at /job/[city]/[title]/
        [orgId]/[jobId] — all other URLs (blog posts, category pages, story
        profiles) are excluded by this path pattern.

        Title and city are parsed directly from the URL slug, avoiding individual
        page fetches for the bulk listing. Only engineering-relevant roles
        (filtered by keyword) have their detail pages fetched for salary data.

        Parameters:
        -----------
        company : str
            Company name for labeling results
        boardSlug : str
            Not used for TalentBrew (URL drives the sitemap path)
        careerUrl : str
            Base career URL (e.g. https://jobs.boeing.com)
        progressCallback : callable, optional
            Function(step, total, message) for progress updates

        Returns:
        --------
        pd.DataFrame : Normalized job listing data

        '''

        from xml.etree import ElementTree as ET
        from urllib.parse import urlparse

        logger.info(f'Scraping TalentBrew sitemap for {company}: {careerUrl}')

        parsed = urlparse(careerUrl)
        sitemapUrl = f'{parsed.scheme}://{parsed.netloc}/sitemap.xml'

        sitemapContent = self._parent._makeRequest(
            sitemapUrl,
            useCache=True,
            sourceName='careerPages',
        )

        if not sitemapContent:
            logger.warning(f'Could not fetch sitemap for {company}, falling back to generic scraper')
            return self._scrapeGeneric(company, careerUrl, progressCallback)

        # Parse XML sitemap and extract /job/ URLs only.
        # _makeRequest may return content with the UTF-8 BOM decoded as latin-1
        # (ï»¿) rather than the unicode BOM (\ufeff), so strip both forms before
        # parsing. Re-encode to UTF-8 bytes as ET.fromstring expects bytes when
        # the XML declaration specifies an encoding.
        if isinstance(sitemapContent, str):
            cleaned = sitemapContent.lstrip('\ufeff')
            if cleaned.startswith('\xef\xbb\xbf') or cleaned[:3] == 'ï»¿':
                cleaned = cleaned[3:]
            cleaned = cleaned.strip()
            sitemapBytes = cleaned.encode('utf-8')
        else:
            sitemapBytes = sitemapContent

        try:
            root = ET.fromstring(sitemapBytes)
        except ET.ParseError:
            # Last-resort: strip any leading non-'<' characters
            sitemapStr = sitemapBytes.decode('utf-8', errors='replace')
            idx = sitemapStr.find('<')
            if idx > 0:
                sitemapStr = sitemapStr[idx:]
            root = ET.fromstring(sitemapStr.encode('utf-8'))

        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        allUrls = [
            url.find('sm:loc', ns).text
            for url in root.findall('sm:url', ns)
            if url.find('sm:loc', ns) is not None
        ]

        # Filter to actual job listings (/job/ path segment)
        jobUrls = [u for u in allUrls if '/job/' in u]
        logger.info(f'{company}: sitemap contains {len(allUrls)} URLs, {len(jobUrls)} are job listings')

        if progressCallback:
            progressCallback(0.2, 1, f'{company}: {len(jobUrls)} job URLs from sitemap')

        # Engineering-relevant title keywords for filtering
        engineeringKeywords = [
            'engineer', 'propulsion', 'avionics', 'mechanical', 'systems',
            'structures', 'thermal', 'test', 'software', 'electrical',
            'manufacturing', 'quality', 'aerospace', 'gnc', 'guidance',
            'analyst', 'scientist', 'designer', 'director', 'lead', 'manager',
        ]

        # Exclusion keywords for non-engineering roles (matched against URL slug,
        # which uses hyphens — spaces in the list become hyphen checks implicitly
        # since the slug has no spaces; use hyphens for multi-word phrases).
        exclusionKeywords = [
            # Trade / technician
            'technician', 'machinist', 'operator',
            # Business / finance / admin
            'accountant', 'accounting', 'finance', 'financial', 'controller',
            'auditor', 'tax-', 'treasury', 'budget', 'contracts-admin',
            'procurement', 'buyer', 'purchasing', 'supply-chain', 'logistics',
            'paralegal', 'attorney', 'counsel', 'administrative', 'receptionist',
            'coordinator', 'scheduler', 'planner',
            # HR / talent / training
            'recruiter', 'recruiting', 'talent-acquisition', 'human-resources',
            'compensation-analyst', 'benefits', 'payroll',
            'learning-and-development', 'training-specialist', 'trainer',
            'instructional-designer', 'facilitator',
            # Pre-employment / onboarding
            'pre-employment', 'onboarding',
            # Program / project management
            'program-manager', 'project-manager', 'program-director',
            'capture-manager', 'proposal-manager',
            # Marketing / communications
            'marketing', 'communications', 'public-relations', 'copywriter',
            'social-media',
            # IT support
            'help-desk', 'it-support', 'desktop-support', 'service-desk',
            # Legal
            'legal', 'specialist-entry',
        ]

        rows = []
        for jobUrl in jobUrls:
            # URL structure: /job/[city]/[title-slug]/[orgId]/[jobId]
            path = urlparse(jobUrl).path
            parts = [p for p in path.split('/') if p]
            # parts[0]='job', parts[1]=city, parts[2]=title-slug, parts[3]=orgId, parts[4]=jobId
            if len(parts) < 3:
                continue

            city = parts[1].replace('-', ' ').title()
            titleSlug = parts[2]

            # Check engineering relevance and exclusions before fetching detail page
            if not any(kw in titleSlug for kw in engineeringKeywords):
                continue
            if any(kw in titleSlug for kw in exclusionKeywords):
                continue

            # Convert slug to readable title
            title = titleSlug.replace('-', ' ').title()

            # Map city to state
            _, state = self._parent._mapLocation(city)

            rows.append({
                'Company': company,
                'Listing': title,
                'Level': self._parent._inferLevel(title),
                'Seniority': self._parent._inferSeniority(title),
                'Location': city,
                'State': state,
                'Discipline': self._parent._inferDiscipline(title),
                'Min': None,
                'Max': None,
                'Link': jobUrl,
                '_jobUrl': jobUrl,
            })

        logger.info(f'{company}: {len(rows)} engineering listings after keyword filter')

        if progressCallback:
            progressCallback(0.5, 1, f'{company}: {len(rows)} engineering listings, fetching salary data...')

        # Fetch individual job pages for salary data.
        # Cap at maxSalaryFetches to avoid spending minutes on large boards
        # (e.g. Boeing has 300+ engineering listings). Listings beyond the cap
        # are still included in the output — they just won't have salary data.
        maxSalaryFetches = 120
        salaryRows = rows[:maxSalaryFetches]
        if len(rows) > maxSalaryFetches:
            logger.info(
                f'{company}: capping salary fetches at {maxSalaryFetches} '
                f'(of {len(rows)} total listings)'
            )

        for i, row in enumerate(salaryRows):
            if progressCallback and i % 10 == 0:
                progressCallback(0.5 + 0.4 * i / max(len(salaryRows), 1), 1,
                                 f'{company}: fetching salary {i+1}/{len(salaryRows)}...')

            pageContent = self._parent._makeRequest(
                row['_jobUrl'],
                useCache=True,
                sourceName='careerPages',
                headers=self._parent._browserHeaders,
            )
            if pageContent:
                minVal, maxVal = extractSalaryFromHtml(pageContent)
                if minVal is not None:
                    row['Min'] = minVal
                    row['Max'] = maxVal

        for row in rows:
            row.pop('_jobUrl', None)

        if not rows:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        if progressCallback:
            progressCallback(1, 1, f'{company}: complete')

        rawDf = pd.DataFrame(rows)

        return self._parent._normalizeToSchema(
            rawDf,
            {col: col for col in rawDf.columns},
            f'Career Page ({company})',
            keepWithoutSalary=True,
        )

    # ------------------------------------------------------------------ #
    # -- Main Entry Point -- #
    # ------------------------------------------------------------------ #

    def scrapeAll(
        self,
        companies: Optional[List[str]] = None,
        progressCallback: Optional[Callable] = None,
    ) -> Dict[str, pd.DataFrame]:

        '''

        Scrape career pages for all (or selected) target companies.

        Dispatches to platform-specific scrapers based on the ATS platform
        configured in compensationReference.md. Unknown platforms use the
        generic HTML scraper with screenshot+OCR fallback.

        Parameters:
        -----------
        companies : list, optional
            Company names to scrape. Default: all configured companies.
        progressCallback : callable, optional
            Function(step, total, message) for overall progress

        Returns:
        --------
        Dict[str, pd.DataFrame] : Map of company name -> normalized DataFrame

        '''

        if not self._careerPages:
            logger.warning('No career page configurations found in reference data.')
            return {}

        # Filter to requested companies if specified
        pages = self._careerPages
        if companies:
            companiesLower = [c.lower() for c in companies]
            pages = [p for p in pages if p['company'].lower() in companiesLower]

        results = {}
        totalPages = len(pages)

        for idx, pageConfig in enumerate(pages):
            company = pageConfig['company']
            platform = pageConfig['platform'].lower()
            careerUrl = pageConfig['careerUrl']
            boardSlug = pageConfig['boardSlug']

            if progressCallback:
                progressCallback(idx, totalPages, f'Scraping {company} career page...')

            logger.info(f'Processing {company} ({platform})...')

            try:
                # Dispatch to platform-specific scraper
                methodName = self._platformMethods.get(platform, None)
                if methodName and hasattr(self, methodName):
                    method = getattr(self, methodName)
                    df = method(company, boardSlug, careerUrl, progressCallback=None)
                else:
                    # Unknown or unsupported platform -- use generic scraper
                    df = self._scrapeGeneric(company, careerUrl, progressCallback=None)

                results[company] = df
                rowCount = len(df) if df is not None and not df.empty else 0
                logger.info(f'{company}: collected {rowCount} job listings')

            except Exception as e:
                logger.error(f'Career page scrape failed for {company}: {e}')
                results[company] = pd.DataFrame(columns=surveyColumns + ['DataSource'])

        if progressCallback:
            progressCallback(totalPages, totalPages, 'Career page scraping complete.')

        return results

    def scrapeAllMerged(
        self,
        companies: Optional[List[str]] = None,
        progressCallback: Optional[Callable] = None,
    ) -> pd.DataFrame:

        '''

        Scrape career pages and return a single merged DataFrame.

        Parameters:
        -----------
        companies : list, optional
            Company names to scrape. Default: all configured companies.
        progressCallback : callable, optional
            Function(step, total, message) for overall progress

        Returns:
        --------
        pd.DataFrame : Combined results from all career pages

        '''

        resultsByCompany = self.scrapeAll(
            companies=companies,
            progressCallback=progressCallback,
        )

        dfs = [df for df in resultsByCompany.values() if df is not None and not df.empty]

        if not dfs:
            return pd.DataFrame(columns=surveyColumns + ['DataSource'])

        merged = pd.concat(dfs, ignore_index=True)

        # Deduplicate by (Company, Listing, Location)
        dedupeKeys = ['Company', 'Listing', 'Location']
        availableKeys = [k for k in dedupeKeys if k in merged.columns]
        if availableKeys:
            merged = merged.drop_duplicates(subset=availableKeys, keep='first')

        return merged.reset_index(drop=True)
