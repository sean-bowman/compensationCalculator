
# -- Reference Document Parser -- #

'''

Parses the compensation reference markdown files to extract structured
data (companies, SOC codes, states) so the scraper and UI can use the
reference documents as the single source of truth instead of hardcoding
these values.

Each parse function returns an empty list on failure rather than crashing,
so a missing or malformed reference file does not break the scraper.

Author: Sean Bowman
Date:   02/25/2026

'''

# Standard library imports
import re
import logging
from typing import List, Tuple, Dict

# Local imports
from auditUtils import loadReferenceMarkdown

# Create a named logger for this module. Python's logging module routes messages
# through a hierarchy of loggers by name. By using getLogger('referenceParser'),
# messages from this module can be filtered or configured independently of other
# modules (e.g., 'compensationScraper'). Log messages go to whatever handler the
# calling application configures -- in CLI mode (scraperInterface.py), they print
# to the terminal; in Streamlit mode, they're typically silent unless a handler
# is attached. The logger is NOT used for user-facing feedback in the web UI.
logger = logging.getLogger('referenceParser')

# ---------------------------------------------------------------------- #
# -- Markdown Parsing Functions -- #
# ---------------------------------------------------------------------- #

def parseCompaniesFromReferences(md: str) -> List[str]:

    '''

    Extract company names from the "Salary Aggregator Data" section
    of the compensation references markdown.

    Looks for ### numbered headers (e.g., "### 1. Levels.fyi: SpaceX...")
    and extracts the company name from each entry. Also parses entries
    in the format "### N. Source: Company Name..." where the company
    is the subject of the entry.

    Parameters:
    -----------
    md : str
        Full text of compensationReferences.md

    Returns:
    --------
    List[str] : Unique company names in the order they appear
    e.g., ['SpaceX', 'Blue Origin', 'Boeing', 'Lockheed Martin', 'Northrop Grumman', ...]

    '''

    if not md:
        return []

    companies = []
    seen = set()

    # Only parse the "Salary Aggregator Data" section -- company-specific
    # entries live here, numbered as "### N. Source: Company Name..."
    aggregatorMatch = re.search(
        r'## Salary Aggregator Data\s*\n(.*?)(?=\n## [^#]|\Z)',
        md, re.DOTALL,
    )
    if not aggregatorMatch:
        logger.warning('Could not find "Salary Aggregator Data" section in references.')
        return []

    section = aggregatorMatch.group(1)

    # Match headers like "### 1. Levels.fyi: SpaceX Engineering..."
    # or "### 12. Glassdoor: Relativity Space Engineering..."
    # The company name is the first word(s) after the source colon,
    # up to common suffixes like "Engineering", "Salaries", etc.
    headerPattern = re.compile(
        r'###\s+\d+\.\s+(?:Levels\.fyi|Glassdoor|PayScale|ZipRecruiter|Comparably|SpaceCrew)'
        r':\s+(.+?)(?:\s+Engineering|\s+Salaries|\s+Compensation|\s+Salary)\b'
    )

    for match in headerPattern.finditer(section):
        name = match.group(1).strip()
        # Handle special cases: "Aerojet Rocketdyne (now L3Harris)" -> "L3Harris"
        if 'now L3Harris' in name or 'now l3harris' in name.lower():
            name = 'L3Harris'
        # Strip parenthetical qualifiers like "(RTX)" from company names
        name = re.sub(r'\s*\([^)]*\)\s*', ' ', name).strip()
        # "NASA" is not a target company for scraping -- it's a federal agency
        if name.upper() == 'NASA':
            continue
        if name not in seen:
            companies.append(name)
            seen.add(name)

    return companies

def parseSocCodesFromReferences(md: str) -> List[Tuple[str, str]]:

    '''

    Extract SOC codes and their occupation names from the references markdown.

    Looks for patterns like "SOC 17-2011" or "(SOC 17-2011)" along with
    the occupation name from the header or key finding text.

    Parameters:
    -----------
    md : str
        Full text of compensationReferences.md

    Returns:
    --------
    List[Tuple[str, str]] : (socCode, occupationName) pairs, e.g.
        [('17-2011', 'Aerospace Engineers'), ('17-2141', 'Mechanical Engineers')]

    '''

    if not md:
        return []

    socCodes = []
    seen = set()

    # Match BLS section headers like:
    # "### 18. Bureau of Labor Statistics: ... Aerospace Engineers (SOC 17-2011)"
    # or "### 19. Bureau of Labor Statistics: Mechanical Engineers (SOC 17-2141)"
    headerPattern = re.compile(
        r'###\s+\d+\.\s+Bureau of Labor Statistics:\s*'
        r'(?:Occupational Employment and Wages:\s*)?'
        r'(.+?)\s*\(SOC\s+([\d-]+)\)'
    )

    for match in headerPattern.finditer(md):
        occupation = match.group(1).strip()
        code = match.group(2).strip()
        if code not in seen:
            socCodes.append((code, occupation))
            seen.add(code)

    # Also catch any SOC codes mentioned in body text as "SOC XX-XXXX"
    # that weren't captured by headers (e.g., inline references)
    bodyPattern = re.compile(r'SOC\s+(17-\d{4})')
    for match in bodyPattern.finditer(md):
        code = match.group(1).strip()
        if code not in seen:
            # Use a generic label for codes found only in body text
            socCodes.append((code, f'SOC {code}'))
            seen.add(code)

    return socCodes

def parseStatesFromReferences(md: str, supplement: str = '') -> List[str]:

    '''

    Extract state abbreviations mentioned in the reference documents.

    Focuses on states with explicit wage data or geographic comparisons
    (e.g., "Florida", "California", "Washington") rather than every
    incidental state mention.

    Parameters:
    -----------
    md : str
        Full text of compensationReferences.md
    supplement : str
        Full text of marketResearchSupplement.md

    Returns:
    --------
    List[str] : State abbreviations (e.g., ['FL', 'CA', 'WA', 'TX'])

    '''

    combined = (md or '') + '\n' + (supplement or '')
    if not combined.strip():
        return []

    # Map of state names to abbreviations for states commonly referenced
    # in aerospace compensation context
    stateMap = {
        'Florida': 'FL',
        'California': 'CA',
        'Washington': 'WA',
        'Texas': 'TX',
        'Colorado': 'CO',
        'Alabama': 'AL',
        'Virginia': 'VA',
        'Maryland': 'MD',
        'Arizona': 'AZ',
    }

    states = []
    seen = set()

    # Look for state names near wage/salary/compensation keywords
    # to avoid capturing incidental mentions
    for stateName, abbrev in stateMap.items():
        # Check if the state appears near compensation-related context
        pattern = re.compile(
            rf'{stateName}.{{0,200}}(?:wage|salary|compensation|average|median|\$|cost of living)',
            re.IGNORECASE | re.DOTALL,
        )
        if pattern.search(combined):
            if abbrev not in seen:
                states.append(abbrev)
                seen.add(abbrev)

    return states

def parseCareerPagesFromReferences(md: str) -> List[Dict[str, str]]:

    '''

    Extract company career page configurations from the "Company Career Pages"
    section of compensationReference.md.

    Parses the markdown table with columns: Company, ATS Platform, Career URL,
    Board Slug. Each row becomes a dict used by the career page scraper to
    determine which scraping strategy to apply (Greenhouse API, Workday
    rendering, generic HTML, or screenshot+OCR fallback).

    Parameters:
    -----------
    md : str
        Full text of compensationReference.md

    Returns:
    --------
    List[Dict[str, str]] : List of dicts with keys:
        company : str - Company name (e.g., 'SpaceX')
        platform : str - ATS platform identifier (e.g., 'Greenhouse', 'Workday', 'Unknown')
        careerUrl : str - Career page URL
        boardSlug : str - API board slug for Greenhouse/Lever (empty string if N/A)

    Examples:
    ---------
    >>> pages = parseCareerPagesFromReferences(md)
    >>> pages[0]
    {'company': 'SpaceX', 'platform': 'Greenhouse', 'careerUrl': 'https://...', 'boardSlug': 'spacex'}

    '''

    if not md:
        return []

    # Find the "Company Career Pages" section
    sectionMatch = re.search(
        r'## Company Career Pages\s*\n(.*?)(?=\n## [^#]|\Z)',
        md, re.DOTALL,
    )
    if not sectionMatch:
        logger.warning('Could not find "Company Career Pages" section in references.')
        return []

    section = sectionMatch.group(1)

    # Parse markdown table rows. Skip the header row and separator row.
    # Expected format: | Company | ATS Platform | Career URL | Board Slug |
    pages = []
    tableRowPattern = re.compile(
        r'^\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|',
        re.MULTILINE,
    )

    for match in tableRowPattern.finditer(section):
        company = match.group(1).strip()
        platform = match.group(2).strip()
        careerUrl = match.group(3).strip()
        boardSlug = match.group(4).strip()

        # Skip header row and separator row
        if company.lower() == 'company' or company.startswith('-'):
            continue

        # Normalize the board slug -- '-' means no slug available
        if boardSlug == '-':
            boardSlug = ''

        pages.append({
            'company': company,
            'platform': platform,
            'careerUrl': careerUrl,
            'boardSlug': boardSlug,
        })

    logger.info(f'Parsed {len(pages)} career page configurations from references.')
    return pages

def deriveCompanyUrlSlugs(companies: List[str]) -> Dict[str, str]:

    '''

    Programmatically generate Levels.fyi URL slugs from company names.

    Most slugs are simple lowercase-hyphenated versions of the company name.
    Edge cases (abbreviations, special characters) use an override dict.

    Parameters:
    -----------
    companies : List[str]
        Company names as they appear in the references

    Returns:
    --------
    Dict[str, str] : {companyName: urlSlug} mapping
    e.g., {'SpaceX': 'spacex', 'Blue Origin': 'blue-origin', 'L3Harris': 'l3harris'}

    '''

    # Override dict for company names that don't follow the simple
    # lowercase-hyphenate pattern
    overrides = {
        'L3Harris': 'l3harris',
        'GE Aerospace': 'ge-aerospace',
        'The Aerospace Corporation': 'the-aerospace-corporation',
    }

    slugs = {}
    for company in companies:
        if company in overrides:
            slugs[company] = overrides[company]
        else:
            # Lowercase, replace spaces with hyphens, remove non-alphanumeric
            # characters except hyphens
            slug = company.lower().replace(' ', '-')
            slug = re.sub(r'[^a-z0-9-]', '', slug)
            # Collapse multiple consecutive hyphens
            slug = re.sub(r'-+', '-', slug).strip('-')
            slugs[company] = slug

    return slugs

# ---------------------------------------------------------------------- #
# -- Engineering Levels Parser -- #
# ---------------------------------------------------------------------- #

def parseLevelsData(md: str) -> dict:

    '''

    Parse the engineering levels markdown into the levelsData dict format
    expected by the rest of the application.

    The markdown must follow the structured format in engineeringLevels.md:
    each level starts with "## Level X - Title" and contains metadata bullets
    and subsections for duties, learning goals, leadership, etc.

    Parameters:
    -----------
    md : str
        Full text of engineeringLevels.md

    Returns:
    --------
    dict : Keyed by roman numeral ('I', 'II', etc.), each value is a dict
        with title, subtitle, experience range, duties, etc.

    '''

    if not md:
        return {}

    levelsData = {}

    # Split into level sections on "## Level X" headers
    levelPattern = re.compile(
        r'^## Level\s+(I{1,3}|IV|V)\s*[-–]\s*(.+)$',
        re.MULTILINE,
    )
    matches = list(levelPattern.finditer(md))

    for i, match in enumerate(matches):
        numeral = match.group(1)
        title = match.group(2).strip()

        # Extract the section text between this header and the next level header
        # (or end of file)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        section = md[start:end]

        levelsData[numeral] = _parseLevelSection(title, section)

    return levelsData

def _parseLevelSection(title: str, section: str) -> dict:

    '''

    Parse a single level's markdown section into a structured dict.

    Parameters:
    -----------
    title : str
        Level title (e.g., 'Associate Engineer')
    section : str
        Markdown text for this level's section
    
    Returns:
    --------
    dict : Structured level data with keys:
        title : str
        subtitle : str
        minExperience : int
        maxExperience : int or None
        experienceLabel : str
        supervision : str
        primaryFocus : str
        keyDuties : List[str]
        learningGoals : List[str]
        leadershipRole : str
        leadershipDescription : str
        generalGoals : List[str]
        managementEligibility : Dict[str, bool] (keys: 'RE', 'Lead', 'Director', 'Chief')

    '''

    data = {
        'title': title,
        'subtitle': '',
        'minExperience': 0,
        'maxExperience': None,
        'experienceLabel': '',
        'supervision': '',
        'primaryFocus': '',
        'keyDuties': [],
        'learningGoals': [],
        'leadershipRole': '',
        'leadershipDescription': '',
        'generalGoals': [],
        'managementEligibility': {
            'RE': False,
            'Lead': False,
            'Director': False,
            'Chief': False,
        },
    }

    # Parse metadata bullets at the top of the section.
    # Use [^\n]* instead of .* to avoid matching across line boundaries,
    # since \s* would consume newlines and bleed into the next bullet.
    subtitleMatch = re.search(r'\*\*Subtitle:\*\*[ \t]*([^\n]*)', section)
    if subtitleMatch:
        data['subtitle'] = subtitleMatch.group(1).strip()

    expMatch = re.search(r'\*\*Experience:\*\*[ \t]*([^\n]*)', section)
    if expMatch:
        expText = expMatch.group(1).strip()
        data['experienceLabel'] = expText
        # Parse min/max from patterns like "0-2 years", "4+ years", "12+ years"
        rangeMatch = re.match(r'(\d+)\s*[-–]\s*(\d+)', expText)
        plusMatch = re.match(r'(\d+)\+', expText)
        if rangeMatch:
            data['minExperience'] = int(rangeMatch.group(1))
            data['maxExperience'] = int(rangeMatch.group(2))
        elif plusMatch:
            data['minExperience'] = int(plusMatch.group(1))
            data['maxExperience'] = None

    supervisionMatch = re.search(r'\*\*Supervision:\*\*[ \t]*([^\n]*)', section)
    if supervisionMatch:
        data['supervision'] = supervisionMatch.group(1).strip()

    # Parse subsections by splitting on ### headers
    subsections = _splitSubsections(section)

    # Primary Focus
    if 'Primary Focus' in subsections:
        data['primaryFocus'] = _extractPlainText(subsections['Primary Focus'])

    # Duties -> keyDuties
    if 'Duties' in subsections:
        data['keyDuties'] = _extractBulletList(subsections['Duties'])

    # Learning & Growth -> learningGoals
    if 'Learning & Growth' in subsections:
        data['learningGoals'] = _extractBulletList(subsections['Learning & Growth'])

    # Leadership
    if 'Leadership' in subsections:
        leadershipText = subsections['Leadership']
        roleMatch = re.search(r'\*\*Role:\*\*[ \t]*([^\n]*)', leadershipText)
        descMatch = re.search(r'\*\*Description:\*\*[ \t]*([^\n]*)', leadershipText)
        if roleMatch:
            data['leadershipRole'] = roleMatch.group(1).strip()
        if descMatch:
            data['leadershipDescription'] = descMatch.group(1).strip()

    # General Goals
    if 'General Goals' in subsections:
        data['generalGoals'] = _extractBulletList(subsections['General Goals'])

    # Management Eligibility
    if 'Management Eligibility' in subsections:
        eligText = subsections['Management Eligibility']
        for role in ['RE', 'Lead', 'Director', 'Chief']:
            pattern = re.compile(rf'{role}:\s*(Yes|No)', re.IGNORECASE)
            roleMatch = pattern.search(eligText)
            if roleMatch:
                data['managementEligibility'][role] = roleMatch.group(1).lower() == 'yes'

    return data

def _splitSubsections(section: str) -> Dict[str, str]:

    '''
    
    Split a level section into subsections keyed by ### header name.

    Parameters:
    -----------
    section : str
        Markdown text for a single level section

    Returns:
    --------
    Dict[str, str] : {subsectionName: subsectionText}
    e.g., {'Primary Focus': '...', 'Duties': '- Duty 1\n- Duty 2', ...}
    
    '''

    subsections = {}
    headerPattern = re.compile(r'^###\s+(.+)$', re.MULTILINE)
    matches = list(headerPattern.finditer(section))

    for i, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        subsections[name] = section[start:end].strip()

    return subsections

def _extractPlainText(text: str) -> str:

    '''
    
    Extract plain text from a subsection, stripping markdown formatting.
    
    Parameters:
    -----------
    text : str
        Markdown text for a subsection

    Returns:
    --------
    str : Plain text from the subsection

    '''
    # Remove bullet markers and join lines
    lines = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('---'):
            line = re.sub(r'^[-*]\s+', '', line)
            lines.append(line)
    return ' '.join(lines).strip()

def _extractBulletList(text: str) -> List[str]:

    '''
    
    Extract a list of bullet items from a subsection.
    
    Parameters:
    -----------
    text : str
        Markdown text for a subsection containing bullet points

    Returns:
    --------
    List[str] : List of bullet items, e.g. ['Item 1', 'Item 2', 'Item 3']

    '''

    items = []
    for line in text.strip().split('\n'):
        line = line.strip()
        bulletMatch = re.match(r'^[-*]\s+(.+)', line)
        if bulletMatch:
            items.append(bulletMatch.group(1).strip())
    return items

def deriveLevelOrder(levelsData: dict) -> List[str]:

    '''

    Derive the ordered list of level numerals from parsed levelsData.
    Returns them in roman numeral order (I, II, III, IV, V).

    Parameters:
    -----------
    levelsData : dict
        Parsed levels data from parseLevelsData()

    Returns:
    --------
    List[str] : Level numerals in order, e.g. ['I', 'II', 'III', 'IV', 'V']

    '''

    # Roman numeral sort order
    romanOrder = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5}
    return sorted(levelsData.keys(), key=lambda k: romanOrder[k])

def deriveManagementMinLevel(levelsData: dict) -> Dict[str, str]:

    '''

    Derive the minimum level required for each management role by scanning
    the management eligibility matrices across all levels.

    For each role (RE, Lead, Director, Chief), finds the lowest level
    where that role becomes eligible. Also adds 'Engineer' with level 'I'
    as the base non-management role.

    Parameters:
    -----------
    levelsData : dict
        Parsed levels data from parseLevelsData()

    Returns:
    --------
    Dict[str, str] : {roleName: minimumLevelNumeral}
    e.g., {'Engineer': 'I', 'RE': 'II', 'Lead': 'III', 'Director': 'IV', 'Chief': 'V'}

    '''

    romanOrder = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5}
    ordered = sorted(levelsData.keys(), key=lambda k: romanOrder[k])

    minLevels = {'Engineer': ordered[0] if ordered else 'I'}

    for role in ['RE', 'Lead', 'Director', 'Chief']:
        for numeral in ordered:
            eligibility = levelsData[numeral]['managementEligibility']
            if eligibility[role]:
                minLevels[role] = numeral
                break

    return minLevels

# ---------------------------------------------------------------------- #
# -- Master Loading Function -- #
# ---------------------------------------------------------------------- #

def loadReferenceData() -> dict:

    '''

    Load and parse both reference markdown files, returning a dict with
    all extracted structured data. This is the primary entry point --
    consumers should call this once and use the returned dict.

    Returns:
    --------
    dict with keys:
        companies : List[str] - target company names
        socCodes : List[Tuple[str, str]] - (code, occupationName) pairs
        states : List[str] - state abbreviations
        companySlugs : Dict[str, str] - {companyName: levelsFyiSlug}
        careerPages : List[Dict[str, str]] - career page configurations

    '''
    md = loadReferenceMarkdown()

    companies = parseCompaniesFromReferences(md)
    socCodes = parseSocCodesFromReferences(md)
    states = parseStatesFromReferences(md)
    companySlugs = deriveCompanyUrlSlugs(companies)
    careerPages = parseCareerPagesFromReferences(md)

    logger.info(
        f'Loaded reference data: {len(companies)} companies, '
        f'{len(socCodes)} SOC codes, {len(states)} states, '
        f'{len(careerPages)} career pages'
    )

    return {
        'companies': companies,
        'socCodes': socCodes,
        'states': states,
        'companySlugs': companySlugs,
        'careerPages': careerPages,
    }
