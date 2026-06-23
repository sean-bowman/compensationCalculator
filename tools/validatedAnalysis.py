
# -- Validated Market Analysis Backend -- #

'''

Backend logic for the Validated Market Analysis page. Provides
functions for all 8 objective features: career-page-only data
processing, geographic normalization, company-weighted averaging,
semantic role mapping, YoE extraction, band recalculation,
timestamp/dedup management, and trend analytics.

Author: Sean Bowman
Date:   03/01/2026

'''

# Standard library imports
import os
import re
import json
import hashlib
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple

# Third-party imports
import pandas as pd
import numpy as np

# Local imports
from auditUtils import (
    surveyColumns, geographicAdjustments, salaryBands, levelsData,
    levelForExperience, scraperCacheDir,
)

logger = logging.getLogger('validatedAnalysis')

# ---------------------------------------------------------------------- #
# -- Neural Network Lazy Loader -- #
# ---------------------------------------------------------------------- #

# The NN classifier is loaded lazily on first use to avoid import-time
# overhead and to degrade gracefully when no trained model exists.
_nnClassifier = None
_nnLoadAttempted = False


def _getClassifier():

    '''

    Lazy-load the trained neural network classifier. Returns the
    classifier instance if a trained model exists, or None if no
    model has been trained yet.

    '''

    global _nnClassifier, _nnLoadAttempted

    if _nnLoadAttempted:
        return _nnClassifier

    _nnLoadAttempted = True

    try:
        from neuralClassifier import BucketClassifier
        classifier = BucketClassifier()
        if classifier.load():
            _nnClassifier = classifier
            logger.info('Neural network classifier loaded successfully')
        else:
            logger.info('No trained neural network model found -- NN signal disabled')
    except Exception as e:
        logger.warning(f'Could not load neural network classifier: {e}')

    return _nnClassifier


def _inferLevelFromNN(row: pd.Series) -> Tuple[Optional[int], float]:

    '''

    Infer engineering level from a single row using the trained neural
    network classifier. Returns (None, 0.0) if no model is available.

    Parameters:
    -----------
    row : pd.Series
        A row from the career page DataFrame

    Returns:
    --------
    Tuple[int or None, float] : (predicted level 1-5, confidence 0.0-1.0)

    '''

    classifier = _getClassifier()
    if classifier is None:
        return (None, 0.0)

    try:
        from featureEngineering import extractFeatureVector
        featureVec = extractFeatureVector(row, classifier.companyEncoder)
        featureVec = featureVec.reshape(1, -1)
        predictions, confidences = classifier.predictWithConfidence(featureVec)
        return (int(predictions[0]), float(confidences[0]))
    except Exception as e:
        logger.debug(f'NN prediction failed for row: {e}')
        return (None, 0.0)

# ---------------------------------------------------------------------- #
# -- Constants -- #
# ---------------------------------------------------------------------- #

# Additional columns appended by the validated analysis pipeline.
# These are NOT changes to the base surveyColumns schema -- they are
# added on top of the existing schema for validated data only.
validatedExtraColumns = [
    'CollectedAt',
    'GeoFactor',
    'AdjustedMin',
    'AdjustedMax',
    'AdjustedMidpoint',
    'LevelBucket',
    'BucketConfidence',
    'ManagementFlag',
    'ManualReviewNeeded',
    'YoeEstimate',
    'YoeSource',
    'Description',
    'DedupeHash',
]

# Management-related keywords for detecting management roles in
# titles and descriptions. Separate from title-level inference.
_managementTitleKeywords = [
    'manager', 'director', 'lead', 'supervisor', 'head of',
    'chief', 'vp', 'vice president',
]

_managementDescriptionKeywords = [
    'manage a team', 'direct reports', 'supervise',
    'lead a team', 'responsible engineer', 'people management',
    'manage engineers', 'team leadership', 'reporting to you',
    'staff management', 'hire and develop', 'build and lead',
    'managing a team', 'oversee a team', 'lead and mentor',
]

# Validated cache directory name (parallel to .scraperCache)
_validatedCacheDirName = '.validatedCache'


# ---------------------------------------------------------------------- #
# -- Cache / Snapshot Directory -- #
# ---------------------------------------------------------------------- #

def validatedCacheDir() -> str:

    '''

    Return the path to the validated analysis cache directory.
    Creates it if it does not exist. Parallel to scraperCacheDir().

    Returns:
    --------
    str : Absolute path to validated cache directory

    '''

    toolsDir = os.path.dirname(os.path.abspath(__file__))
    cacheDir = os.path.join(toolsDir, _validatedCacheDirName)
    os.makedirs(cacheDir, exist_ok=True)

    return cacheDir


# ---------------------------------------------------------------------- #
# -- Engineering Role Filter -- #
# ---------------------------------------------------------------------- #

# Engineering-adjacent keywords -- if ANY of these appear in the title,
# the listing is kept (case-insensitive).
_engineeringIncludeKeywords = [
    # Generic technical roles
    'engineer', 'analyst', 'designer', 'scientist',
    'developer', 'architect', 'drafter', 'machinist', 'welder',
    'fabricator', 'assembler', 'inspector', 'tester', 'programmer',
    'integrator', 'technologist', 'researcher',
    # Discipline terms (catch roles like "Propulsion Specialist")
    'propulsion', 'avionics', 'gnc', 'guidance', 'navigation',
    'structures', 'structural', 'thermal', 'mechanical', 'electrical',
    'software', 'systems', 'manufacturing', 'production', 'quality',
    'materials', 'fluids', 'aerodynamic', 'aerospace', 'rocket',
    'combustion', 'turbomachinery', 'cad', 'cfd', 'fea',
    'embedded', 'firmware', 'hardware', 'rf ', 'radar',
    'optics', 'optical', 'laser', 'composites', 'additive',
    'metrology', 'ndt', 'nondestructive', 'weld',
]

# Non-engineering keywords -- if ANY of these appear in the title,
# the listing is excluded regardless of inclusion matches.
_engineeringExcludeKeywords = [
    'accountant', 'accounting', 'payroll', 'accounts payable',
    'accounts receivable', 'bookkeeper',
    'recruiter', 'recruiting', 'talent acquisition',
    'human resources', 'hr specialist', 'hr manager',
    'hr generalist', 'hr coordinator', 'hr business partner',
    'finance manager', 'financial analyst', 'controller',
    'legal', 'counsel', 'attorney', 'paralegal',
    'technician', 'tech i', 'tech ii', 'tech iii',
    'cook', 'chef', 'janitor', 'custodial', 'custodian',
    'security guard', 'security officer',
    'receptionist', 'admin assistant', 'executive assistant',
    'office manager', 'office coordinator',
    'marketing', 'communications specialist', 'public relations',
    'graphic design', 'photographer', 'videographer',
    'copywriter', 'content writer',
    'nurse', 'medical', 'physician', 'dentist',
    'barista', 'cafeteria', 'cafe ', 'food and beverage',
    'benefits specialist', 'benefits analyst',
    'compliance officer', 'compliance analyst',
    'sales representative', 'sales manager', 'business development',
    'real estate', 'property manager',
    'executive chef', 'food service',
    # Business/operations roles whose titles pass the inclusion check via 'analyst'
    # but are not engineering positions (e.g. job boards return these for aerospace companies)
    'business analyst', 'data analyst', 'contract analyst',
    'supply chain analyst', 'operations analyst', 'financial planning analyst',
    'pricing analyst', 'policy analyst', 'marketing analyst',
    # Procurement / admin non-engineering roles
    'buyer', 'purchasing agent', 'procurement specialist',
    'program coordinator', 'project coordinator', 'event coordinator',
    'administrative coordinator', 'training coordinator',
    # People / culture
    'people operations', 'diversity', 'equity and inclusion',
]


def filterEngineeringRoles(df: pd.DataFrame) -> pd.DataFrame:

    '''

    Filter a scraped DataFrame to engineering-related roles only.
    Uses a two-pass keyword strategy on the Listing (title) column:
    first an inclusion pass, then an exclusion pass.

    Parameters:
    -----------
    df : pd.DataFrame
        Scraped career page data with a 'Listing' column

    Returns:
    --------
    pd.DataFrame : Filtered DataFrame with only engineering-related rows

    '''

    if df is None or df.empty or 'Listing' not in df.columns:
        return df

    titleLower = df['Listing'].str.lower().fillna('')

    # Exclusion pass first -- remove clearly non-engineering roles
    excludeMask = titleLower.apply(
        lambda t: any(kw in t for kw in _engineeringExcludeKeywords)
    )

    # Inclusion pass -- keep only rows with engineering-adjacent keywords
    includeMask = titleLower.apply(
        lambda t: any(kw in t for kw in _engineeringIncludeKeywords)
    )

    # Keep rows that pass inclusion AND do not match exclusion
    filtered = df[includeMask & ~excludeMask].reset_index(drop=True)

    logger.info(
        f'Engineering filter: {len(df)} -> {len(filtered)} listings '
        f'({len(df) - len(filtered)} removed)'
    )

    return filtered


# ---------------------------------------------------------------------- #
# -- Feature 5: Years of Experience Extraction -- #
# ---------------------------------------------------------------------- #

def extractYearsOfExperience(text: str) -> Tuple[Optional[float], str]:

    '''

    Extract years of experience from job listing text (title or full
    description). Uses multiple regex patterns to handle common formats
    found in aerospace job postings.

    Parameters:
    -----------
    text : str
        Job description or title text that may contain YoE info

    Returns:
    --------
    Tuple[Optional[float], str] : (yearsEstimate, source)
        source is 'explicit' if found in text, else 'none'

    '''

    if not text:
        return (None, 'none')

    # Normalize whitespace
    cleaned = re.sub(r'\s+', ' ', text)

    # Pattern 1: "X+ years of experience" or "X+ years' experience"
    matchPlus = re.search(
        r'(\d{1,2})\+?\s*(?:years?|yrs?)[\s\'-]*(?:of\s+)?(?:relevant\s+|related\s+|professional\s+|industry\s+)?experience',
        cleaned, re.IGNORECASE,
    )

    # Pattern 2: "X-Y years" or "X to Y years"
    matchRange = re.search(
        r'(\d{1,2})\s*[-\u2013\u2014]\s*(\d{1,2})\s*(?:years?|yrs?)',
        cleaned, re.IGNORECASE,
    )

    # Pattern 3: "minimum X years" or "at least X years"
    matchMinimum = re.search(
        r'(?:minimum|at\s+least|no\s+less\s+than)\s+(\d{1,2})\s*(?:years?|yrs?)',
        cleaned, re.IGNORECASE,
    )

    # Pattern 4: "BS/MS + X years" (degree-adjusted)
    matchDegree = re.search(
        r'(?:B\.?S\.?|Bachelor\'?s?|M\.?S\.?|Master\'?s?|Ph\.?D\.?)\s*(?:\+|and|with)\s*(\d{1,2})\s*(?:years?|yrs?)',
        cleaned, re.IGNORECASE,
    )

    candidates = []

    if matchRange:
        low = float(matchRange.group(1))
        high = float(matchRange.group(2))
        # Use midpoint of range
        candidates.append((low + high) / 2)

    if matchPlus:
        candidates.append(float(matchPlus.group(1)))

    if matchMinimum:
        candidates.append(float(matchMinimum.group(1)))

    if matchDegree:
        degreeYears = float(matchDegree.group(1))
        # Detect degree type and adjust -- MS typically means 2 fewer
        # required years, PhD ~4 fewer, relative to BS baseline
        degreeText = matchDegree.group(0).lower()
        if 'ph' in degreeText:
            degreeYears += 4
        elif 'm' in degreeText.split('+')[0].split('and')[0].split('with')[0]:
            degreeYears += 2
        candidates.append(degreeYears)

    if candidates:
        # Return the most common / median value if multiple patterns match
        return (float(np.median(candidates)), 'explicit')

    return (None, 'none')


# ---------------------------------------------------------------------- #
# -- Feature 4: Semantic Role Mapping / Level Bucket Assignment -- #
# ---------------------------------------------------------------------- #

def _detectManagement(title: str, description: str) -> bool:

    '''

    Detect whether a listing involves management responsibilities
    by scanning both the title and full description text.

    Parameters:
    -----------
    title : str
        Job title
    description : str
        Full job description text

    Returns:
    --------
    bool : True if management indicators are found

    '''

    titleLower = (title or '').lower()
    descLower = (description or '').lower()

    # Check title keywords
    for kw in _managementTitleKeywords:
        if kw in titleLower:
            return True

    # Check description keywords (more specific phrases)
    for kw in _managementDescriptionKeywords:
        if kw in descLower:
            return True

    return False


def _inferLevelFromTitle(title: str) -> Optional[int]:

    '''

    Infer engineering level (1-5) from title keywords. Mirrors the logic
    in CompensationScraper._inferLevel() but returns None when
    ambiguous instead of defaulting to 2.

    Parameters:
    -----------
    title : str
        Job title string

    Returns:
    --------
    int or None : Inferred level 1-5, or None if ambiguous

    '''

    if not title:
        return None

    titleLower = title.lower()

    if any(kw in titleLower for kw in ['principal', 'chief', 'fellow', 'distinguished']):
        return 5
    if any(kw in titleLower for kw in ['staff', 'lead engineer', 'tech lead']):
        return 4
    if any(kw in titleLower for kw in ['senior', 'sr.', 'sr ']):
        return 3
    if any(kw in titleLower for kw in ['junior', 'jr.', 'jr ', 'associate', 'entry', 'intern']):
        return 1

    # Explicit level numbers in title (e.g., "Engineer II", "Level 3")
    levelMatch = re.search(r'(?:level|grade|engineer)\s*([IViv]{1,3}|\d)', titleLower)
    if levelMatch:
        romanMap = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5}
        val = levelMatch.group(1).lower()
        if val in romanMap:
            return romanMap[val]
        elif val.isdigit() and 1 <= int(val) <= 5:
            return int(val)

    return None


def _inferLevelFromSalary(midpoint: float) -> Optional[int]:

    '''

    Infer engineering level from salary midpoint using range-based matching
    against the salary bands. Instead of finding the nearest median
    (which creates circular dependency with proposed bands), this
    checks which band range(s) the salary falls within and picks
    the best fit proportionally.

    Parameters:
    -----------
    midpoint : float
        Salary midpoint (geo-adjusted or raw)

    Returns:
    --------
    int or None : Best-fit level 1-5, or None if salary is NaN

    '''

    if pd.isna(midpoint) or midpoint <= 0:
        return None

    # Score each level by how well the salary fits within its band range
    bestLevel = None
    bestScore = -1.0

    for bandName, band in salaryBands.items():
        levelNum = int(bandName.split(' ')[1])
        bandMin = band['min']
        bandMax = band['max']
        bandRange = max(bandMax - bandMin, 1)

        if bandMin <= midpoint <= bandMax:
            # Salary is within band -- score by proximity to median
            dist = abs(midpoint - band['median'])
            score = 1.0 - (dist / bandRange)
        elif midpoint < bandMin:
            # Below band -- penalize by distance below
            overshoot = (bandMin - midpoint) / bandRange
            score = max(0, 0.5 - overshoot)
        else:
            # Above band -- penalize by distance above
            overshoot = (midpoint - bandMax) / bandRange
            score = max(0, 0.5 - overshoot)

        if score > bestScore:
            bestScore = score
            bestLevel = levelNum

    # Fallback: if all scores are 0 (salary far outside all bands),
    # use nearest-median distance as tiebreaker
    if bestScore <= 0:
        bestDist = float('inf')
        for bandName, band in salaryBands.items():
            levelNum = int(bandName.split(' ')[1])
            dist = abs(midpoint - band['median'])
            if dist < bestDist:
                bestDist = dist
                bestLevel = levelNum

    return bestLevel


def _computeBucketAssignment(
    yoeLevel: Optional[int],
    titleLevel: Optional[int],
    salaryLevel: Optional[int],
    nnLevel: Optional[int] = None,
) -> Tuple[str, float]:

    '''

    Compute final bucket assignment and confidence from multiple signals
    using weighted voting. When a trained neural network model is
    available, its prediction is included as an additional signal.

    Weight scheme (with NN):
      With YoE:    YoE 40%, Title 20%, Salary 10%, NN 30%
      Without YoE: Title 35%, Salary 25%, NN 40%

    Weight scheme (without NN -- original behavior):
      With YoE:    YoE 55%, Title 35%, Salary 10%
      Without YoE: Title 60%, Salary 40%

    Parameters:
    -----------
    yoeLevel : int or None
        Level from years of experience
    titleLevel : int or None
        Level from title keywords
    salaryLevel : int or None
        Level from salary range
    nnLevel : int or None
        Level from neural network classifier

    Returns:
    --------
    Tuple[str, float] : (bucketName like 'Level 3', confidence 0.0-1.0)

    '''

    signals = []
    weights = []
    hasYoe = yoeLevel is not None
    hasNn = nnLevel is not None

    if yoeLevel is not None:
        signals.append(yoeLevel)
        weights.append(0.40 if hasNn else 0.55)

    if titleLevel is not None:
        signals.append(titleLevel)
        if hasNn:
            weights.append(0.20 if hasYoe else 0.35)
        else:
            weights.append(0.35 if hasYoe else 0.60)

    if salaryLevel is not None:
        signals.append(salaryLevel)
        if hasNn:
            weights.append(0.10 if hasYoe else 0.25)
        else:
            weights.append(0.10 if hasYoe else 0.40)

    if nnLevel is not None:
        signals.append(nnLevel)
        weights.append(0.30 if hasYoe else 0.40)

    if not signals:
        return ('Unclassified', 0.0)

    # Weighted vote -- round to nearest integer level
    totalWeight = sum(weights)
    weightedSum = sum(s * w for s, w in zip(signals, weights))
    bestLevel = max(1, min(5, round(weightedSum / totalWeight)))

    # Confidence: how much do the signals agree?
    if len(signals) == 1:
        confidence = 0.5  # Only one signal -- moderate confidence
    else:
        # Compute agreement: fraction of signals within 1 level of the winner
        agreeing = sum(1 for s in signals if abs(s - bestLevel) <= 1)
        confidence = agreeing / len(signals)
        # Boost confidence if all signals agree exactly
        if all(s == bestLevel for s in signals):
            confidence = 1.0

    return (f'Level {bestLevel}', confidence)


def assignBuckets(
    df: pd.DataFrame,
) -> pd.DataFrame:

    '''

    Assign each listing to a level bucket using a weighted
    scoring approach combining YoE (50%), title keywords (30%), and
    salary range (20%). Also detects management roles and flags rows
    needing manual review.

    Expects the DataFrame to already have AdjustedMidpoint and Description
    columns (from geo normalization and career page scraping).

    Parameters:
    -----------
    df : pd.DataFrame
        Career page data with salary and description columns

    Returns:
    --------
    pd.DataFrame : Input DataFrame with added bucket columns:
        LevelBucket, BucketConfidence, ManagementFlag,
        ManualReviewNeeded, YoeEstimate, YoeSource

    '''

    if df.empty:
        for col in ['LevelBucket', 'BucketConfidence', 'ManagementFlag',
                     'ManualReviewNeeded', 'YoeEstimate', 'YoeSource']:
            df[col] = None
        return df

    result = df.copy()

    buckets = []
    confidences = []
    mgmtFlags = []
    reviewFlags = []
    yoeEstimates = []
    yoeSources = []

    for idx, row in result.iterrows():
        title = str(row.get('Listing', ''))
        description = str(row.get('Description', ''))
        combinedText = f'{title} {description}'

        # -- Extract YoE -- #
        yoe, yoeSource = extractYearsOfExperience(combinedText)
        yoeEstimates.append(yoe)
        yoeSources.append(yoeSource)

        # -- Compute level signals -- #
        yoeLevel = None
        if yoe is not None:
            levelKey = levelForExperience(yoe)
            romanToInt = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5}
            yoeLevel = romanToInt.get(levelKey)

        titleLevel = _inferLevelFromTitle(title)

        midpoint = row.get('AdjustedMidpoint')
        if pd.isna(midpoint) or midpoint is None:
            midpoint = row.get('Midpoint')
        if pd.isna(midpoint) or midpoint is None:
            # Compute midpoint from Min/Max as last resort
            minVal = pd.to_numeric(row.get('Min'), errors='coerce')
            maxVal = pd.to_numeric(row.get('Max'), errors='coerce')
            if pd.notna(minVal) and pd.notna(maxVal) and minVal > 0 and maxVal > 0:
                midpoint = (minVal + maxVal) / 2
            else:
                midpoint = 0
        salaryLevel = _inferLevelFromSalary(midpoint if not pd.isna(midpoint) else 0)

        # -- Neural network signal -- #
        nnLevel, nnConfidence = _inferLevelFromNN(row)

        # -- Assign bucket -- #
        bucket, confidence = _computeBucketAssignment(yoeLevel, titleLevel, salaryLevel, nnLevel)
        buckets.append(bucket)
        confidences.append(confidence)

        # -- Detect management -- #
        isMgmt = _detectManagement(title, description)
        mgmtFlags.append(isMgmt)

        # -- Determine review need -- #
        needsReview = (
            isMgmt
            or confidence < 0.6
            or bucket == 'Unclassified'
        )
        reviewFlags.append(needsReview)

    result['LevelBucket'] = buckets
    result['BucketConfidence'] = confidences
    result['ManagementFlag'] = mgmtFlags
    result['ManualReviewNeeded'] = reviewFlags
    result['YoeEstimate'] = yoeEstimates
    result['YoeSource'] = yoeSources

    # -- Monotonicity check -- #
    # Verify that median salary increases with level. Flag inversions
    # so the user can review and correct in the data editor.
    _checkBucketMonotonicity(result)

    return result


def _checkBucketMonotonicity(df: pd.DataFrame) -> List[str]:

    '''

    Check that median salary increases monotonically with level.
    Logs warnings for any inversions found.

    Parameters:
    -----------
    df : pd.DataFrame
        Data with LevelBucket and salary columns

    Returns:
    --------
    List[str] : Warning messages for any inversions found

    '''

    warnings = []
    midCol = 'AdjustedMidpoint' if 'AdjustedMidpoint' in df.columns else 'Midpoint'
    if midCol not in df.columns:
        # Compute from Min/Max
        minVals = pd.to_numeric(df.get('Min'), errors='coerce')
        maxVals = pd.to_numeric(df.get('Max'), errors='coerce')
        df[midCol] = (minVals.fillna(0) + maxVals.fillna(0)) / 2

    prevMedian = 0
    for levelNum in range(1, 6):
        bucketName = f'Level {levelNum}'
        bucketData = df[df['LevelBucket'] == bucketName]
        salaries = pd.to_numeric(bucketData.get(midCol), errors='coerce').dropna()
        salaries = salaries[salaries > 0]

        if len(salaries) < 1:
            continue

        median = salaries.median()
        if median < prevMedian and prevMedian > 0:
            msg = (
                f'Monotonicity warning: {bucketName} median (${median:,.0f}) '
                f'is lower than Level {levelNum - 1} (${prevMedian:,.0f})'
            )
            warnings.append(msg)
            logger.warning(msg)

        prevMedian = median

    return warnings


# ---------------------------------------------------------------------- #
# -- Feature 2: Geographic Salary Normalization -- #
# ---------------------------------------------------------------------- #

def computeGeoFactors(
    careerDf: pd.DataFrame,
    referenceFactors: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, float], pd.DataFrame]:

    '''

    Compute geographic salary adjustment factors from career page data
    by analyzing multi-location postings (same Company + Listing posted
    in multiple locations with different salary ranges).

    Strategy:
    1. Find multi-location postings and compute salary ratios
    2. Normalize all ratios relative to the HQ baseline (FL) = 1.0
    3. Fall back to referenceFactors for locations without evidence

    Parameters:
    -----------
    careerDf : pd.DataFrame
        Career page data with Company, Listing, Location, State, Midpoint
    referenceFactors : dict, optional
        Existing geographic adjustments from auditUtils. Used as fallback.

    Returns:
    --------
    Tuple[dict, pd.DataFrame] :
        - dict mapping location/state -> adjustment factor (1.0 = HQ baseline)
        - DataFrame of multi-location evidence pairs used to derive factors

    '''

    if referenceFactors is None:
        referenceFactors = geographicAdjustments.copy()

    # Ensure Midpoint exists
    df = careerDf.copy()
    if 'Midpoint' not in df.columns:
        minCol = pd.to_numeric(df.get('Min'), errors='coerce')
        maxCol = pd.to_numeric(df.get('Max'), errors='coerce')
        df['Midpoint'] = (minCol + maxCol) / 2

    # Filter to rows with valid salary and location
    valid = df[
        (pd.to_numeric(df['Midpoint'], errors='coerce') > 0) &
        (df['State'].notna()) &
        (df['State'] != 'Unknown')
    ].copy()
    valid['Midpoint'] = pd.to_numeric(valid['Midpoint'], errors='coerce')

    if valid.empty:
        return (referenceFactors, pd.DataFrame())

    # Find multi-location postings: same Company + Listing in 2+ states
    grouped = valid.groupby(['Company', 'Listing']).filter(
        lambda g: g['State'].nunique() >= 2
    )

    evidenceRows = []

    if not grouped.empty:
        for (company, listing), group in grouped.groupby(['Company', 'Listing']):
            # Compute average midpoint per state for this posting
            stateAvgs = group.groupby('State')['Midpoint'].mean()

            if len(stateAvgs) < 2:
                continue

            # Generate pairwise ratios
            states = stateAvgs.index.tolist()
            for i in range(len(states)):
                for j in range(i + 1, len(states)):
                    stateA = states[i]
                    stateB = states[j]
                    ratio = stateAvgs[stateA] / stateAvgs[stateB]
                    evidenceRows.append({
                        'Company': company,
                        'Listing': listing,
                        'StateA': stateA,
                        'StateB': stateB,
                        'MidpointA': stateAvgs[stateA],
                        'MidpointB': stateAvgs[stateB],
                        'Ratio': ratio,
                    })

    evidenceDf = pd.DataFrame(evidenceRows)

    # Build validated factors from evidence
    validatedFactors = referenceFactors.copy()

    if not evidenceDf.empty:
        # Compute average factor per state relative to FL
        # First, collect all ratios involving FL as one side
        flRatios = {}
        for _, row in evidenceDf.iterrows():
            if row['StateA'] == 'FL':
                state = row['StateB']
                # Factor = how much more expensive stateB is vs FL
                flRatios.setdefault(state, []).append(row['Ratio'])
            elif row['StateB'] == 'FL':
                state = row['StateA']
                flRatios.setdefault(state, []).append(1.0 / row['Ratio'])

        for state, ratios in flRatios.items():
            if len(ratios) >= 1:
                avgFactor = float(np.mean(ratios))
                # Map state abbr to city name if possible for compatibility
                # with existing geographicAdjustments dict keys
                validatedFactors[state] = round(avgFactor, 4)

    return (validatedFactors, evidenceDf)


def applyGeoNormalization(
    df: pd.DataFrame,
    geoFactors: Dict[str, float],
) -> pd.DataFrame:

    '''

    Apply geographic normalization to salary columns, converting all
    salaries to the HQ-baseline equivalent by dividing by the location factor.

    Parameters:
    -----------
    df : pd.DataFrame
        Data with Min, Max, and State columns
    geoFactors : dict
        Location/state -> factor mapping (1.0 = HQ baseline)

    Returns:
    --------
    pd.DataFrame : Input with added GeoFactor, AdjustedMin, AdjustedMax,
        AdjustedMidpoint columns

    '''

    result = df.copy()

    # Build a state-level lookup from the factors dict.
    # The existing geographicAdjustments uses city names as keys with
    # negative discount percentages (e.g., -0.175 means 17.5% more
    # expensive than the HQ baseline). To convert to a multiplier:
    #   multiplier = 1.0 + discount  (e.g., 1.0 + (-0.175) = 0.825)
    # A salary in CA * 0.825 gives the HQ-baseline equivalent.
    # We also support direct multiplier values from validated factors
    # (state abbreviation keys with values > 0.5).
    stateLookup = {}
    cityToState = {
        'Seattle': 'WA', 'Los Angeles': 'CA', 'San Jose': 'CA',
        'San Francisco': 'CA', 'Denver': 'CO', 'Huntsville': 'AL',
        'Phoenix': 'AZ', 'Washington DC': 'DC', 'Austin': 'TX',
        'Houston': 'TX', 'Dallas': 'TX', 'Kent': 'WA',
        'Cocoa': 'FL', 'Cape Canaveral': 'FL', 'Merritt Island': 'FL',
        'Long Beach': 'CA', 'Hawthorne': 'CA', 'McGregor': 'TX',
        'Littleton': 'CO', 'Longmont': 'CO', 'Alameda': 'CA',
        'Redondo Beach': 'CA', 'Lancaster': 'CA',
    }

    for key, rawFactor in geoFactors.items():
        # Determine if this is a discount percentage or a direct multiplier.
        # geographicAdjustments uses discount percentages (negative, -1 < x <= 0).
        # Validated factors from computeGeoFactors use direct multipliers (> 0.5).
        if -1 < rawFactor <= 0:
            # Discount percentage: convert to multiplier
            multiplier = 1.0 + rawFactor
        elif rawFactor > 0.5:
            # Already a direct multiplier (from validated evidence)
            multiplier = rawFactor
        else:
            multiplier = 1.0

        # Map city name to state abbreviation
        if len(key) == 2 and key.isupper():
            stateLookup[key] = multiplier
        elif key in cityToState:
            state = cityToState[key]
            # Average if multiple cities in same state
            if state in stateLookup:
                stateLookup[state] = (stateLookup[state] + multiplier) / 2
            else:
                stateLookup[state] = multiplier

    # Default FL factor to 1.0 (baseline -- no adjustment)
    stateLookup['FL'] = 1.0

    minCol = pd.to_numeric(result.get('Min'), errors='coerce')
    maxCol = pd.to_numeric(result.get('Max'), errors='coerce')

    factors = result['State'].map(stateLookup).fillna(1.0).astype(float)

    result['GeoFactor'] = factors
    result['AdjustedMin'] = (minCol * factors).round(0)
    result['AdjustedMax'] = (maxCol * factors).round(0)
    result['AdjustedMidpoint'] = ((result['AdjustedMin'] + result['AdjustedMax']) / 2).round(0)

    return result


# ---------------------------------------------------------------------- #
# -- Feature 3: Company-Weighted Averaging -- #
# ---------------------------------------------------------------------- #

def companyWeightedAverage(
    df: pd.DataFrame,
    groupBy: str = 'LevelBucket',
    salaryMinCol: Optional[str] = None,
    salaryMaxCol: Optional[str] = None,
    salaryMidCol: Optional[str] = None,
) -> pd.DataFrame:

    '''

    Two-stage averaging: first average within each company for the
    given group, then average across companies so each company has
    equal weight regardless of how many listings it contributed.

    When salary column names are not provided, auto-detects whether
    geo-normalized columns (AdjustedMin/Max/Midpoint) exist and
    falls back to raw columns (Min/Max/Midpoint) if not.

    Parameters:
    -----------
    df : pd.DataFrame
        Data with company, bucket, and salary columns
    groupBy : str
        Column to group by (default 'LevelBucket')
    salaryMinCol : str, optional
        Min salary column name (auto-detected if None)
    salaryMaxCol : str, optional
        Max salary column name (auto-detected if None)
    salaryMidCol : str, optional
        Midpoint salary column name (auto-detected if None)

    Returns:
    --------
    pd.DataFrame : Per-bucket weighted averages with columns:
        [groupBy, CompanyCount, ListingCount, WeightedAvgMin,
         WeightedAvgMax, WeightedAvgMidpoint, StdDev]

    '''

    if df.empty or groupBy not in df.columns:
        return pd.DataFrame()

    # Auto-detect salary columns: prefer geo-normalized, fall back to raw
    if salaryMinCol is None:
        salaryMinCol = 'AdjustedMin' if 'AdjustedMin' in df.columns else 'Min'
    if salaryMaxCol is None:
        salaryMaxCol = 'AdjustedMax' if 'AdjustedMax' in df.columns else 'Max'
    if salaryMidCol is None:
        salaryMidCol = 'AdjustedMidpoint' if 'AdjustedMidpoint' in df.columns else 'Midpoint'

    # Ensure numeric salary columns and compute Midpoint if missing
    workDf = df.copy()
    for col in [salaryMinCol, salaryMaxCol]:
        if col in workDf.columns:
            workDf[col] = pd.to_numeric(workDf[col], errors='coerce')

    if salaryMidCol not in workDf.columns:
        # Compute midpoint from min/max
        workDf[salaryMidCol] = (
            workDf[salaryMinCol].fillna(0) + workDf[salaryMaxCol].fillna(0)
        ) / 2
    else:
        workDf[salaryMidCol] = pd.to_numeric(workDf[salaryMidCol], errors='coerce')

    # Filter to rows with valid midpoint
    workDf = workDf[workDf[salaryMidCol] > 0]

    if workDf.empty:
        return pd.DataFrame()

    # Stage 1: average within each company per bucket
    companyAvgs = workDf.groupby([groupBy, 'Company']).agg(
        CompanyAvgMin = (salaryMinCol, 'mean'),
        CompanyAvgMax = (salaryMaxCol, 'mean'),
        CompanyAvgMid = (salaryMidCol, 'mean'),
        CompanyListings = (salaryMidCol, 'count'),
    ).reset_index()

    # Stage 2: average across companies per bucket (equal weight)
    bucketStats = companyAvgs.groupby(groupBy).agg(
        CompanyCount = ('Company', 'nunique'),
        ListingCount = ('CompanyListings', 'sum'),
        WeightedAvgMin = ('CompanyAvgMin', 'mean'),
        WeightedAvgMax = ('CompanyAvgMax', 'mean'),
        WeightedAvgMidpoint = ('CompanyAvgMid', 'mean'),
        StdDev = ('CompanyAvgMid', 'std'),
    ).reset_index()

    # Round salary values
    for col in ['WeightedAvgMin', 'WeightedAvgMax', 'WeightedAvgMidpoint', 'StdDev']:
        if col in bucketStats.columns:
            bucketStats[col] = bucketStats[col].round(0)

    return bucketStats


# ---------------------------------------------------------------------- #
# -- Feature 6: Automated Band Recalculation -- #
# ---------------------------------------------------------------------- #

def recalculateSalaryBands(
    validatedDf: pd.DataFrame,
    currentBands: Optional[dict] = None,
    roundTo: int = 1000,
    allowOverlap: bool = True,
    minPercentile: float = 10,
    medianPercentile: float = 50,
    maxPercentile: float = 90,
) -> Tuple[dict, pd.DataFrame]:

    '''

    Recalculate salary bands from validated market data.

    For each LevelBucket:
    1. Compute percentiles from AdjustedMidpoint
    2. Round to nearest roundTo dollars
    3. Compute YoE breakpoints from YoeEstimate distribution

    Parameters:
    -----------
    validatedDf : pd.DataFrame
        Validated data with LevelBucket, AdjustedMidpoint, YoeEstimate
    currentBands : dict, optional
        Current salary bands for comparison (default: salaryBands from auditUtils)
    roundTo : int
        Rounding granularity in dollars (default 1000)
    allowOverlap : bool
        Allow adjacent bands to overlap (default True, per objective.md)
    minPercentile : float
        Percentile for band minimum (default 10)
    medianPercentile : float
        Percentile for band median (default 50)
    maxPercentile : float
        Percentile for band maximum (default 90)

    Returns:
    --------
    Tuple[dict, pd.DataFrame] :
        - dict in same format as salaryBands: {Level N: {min, median, max, minYrs, maxYrs}}
        - DataFrame with comparison: current vs proposed with deltas

    '''

    if currentBands is None:
        currentBands = salaryBands

    df = validatedDf.copy()

    # Use geo-normalized midpoint if available, fall back to raw Midpoint
    midCol = 'AdjustedMidpoint' if 'AdjustedMidpoint' in df.columns else 'Midpoint'
    if midCol not in df.columns:
        # Compute midpoint from Min/Max if neither adjusted nor raw exists
        df['Min'] = pd.to_numeric(df.get('Min'), errors='coerce')
        df['Max'] = pd.to_numeric(df.get('Max'), errors='coerce')
        df[midCol] = (df['Min'].fillna(0) + df['Max'].fillna(0)) / 2
    else:
        df[midCol] = pd.to_numeric(df.get(midCol), errors='coerce')
    df['YoeEstimate'] = pd.to_numeric(df.get('YoeEstimate'), errors='coerce')

    proposedBands = {}
    comparisonRows = []

    for levelNum in range(1, 6):
        bucketName = f'Level {levelNum}'
        bucketData = df[df['LevelBucket'] == bucketName]

        validSalaries = bucketData[midCol].dropna()
        # Filter out inf and negative values
        validSalaries = validSalaries[np.isfinite(validSalaries) & (validSalaries > 0)]
        validYoe = bucketData['YoeEstimate'].dropna()

        currentBand = currentBands.get(bucketName, {})

        if len(validSalaries) >= 3:
            # Compute percentiles and round
            pMin = np.percentile(validSalaries, minPercentile)
            pMed = np.percentile(validSalaries, medianPercentile)
            pMax = np.percentile(validSalaries, maxPercentile)

            proposedMin = int(round(pMin / roundTo) * roundTo) if np.isfinite(pMin) else currentBand.get('min', 0)
            proposedMedian = int(round(pMed / roundTo) * roundTo) if np.isfinite(pMed) else currentBand.get('median', 0)
            proposedMax = int(round(pMax / roundTo) * roundTo) if np.isfinite(pMax) else currentBand.get('max', 0)
        else:
            # Insufficient data -- keep current values
            proposedMin = currentBand.get('min', 0)
            proposedMedian = currentBand.get('median', 0)
            proposedMax = currentBand.get('max', 0)

        # Compute YoE breakpoints
        if len(validYoe) >= 3:
            proposedMinYrs = int(round(np.percentile(validYoe, 10)))
            proposedMaxYrs = int(round(np.percentile(validYoe, 90)))
        else:
            proposedMinYrs = currentBand.get('minYrs', 0)
            proposedMaxYrs = currentBand.get('maxYrs')

        # Enforce non-overlap if requested (adjust minimums upward)
        if not allowOverlap and levelNum > 1:
            prevBand = proposedBands.get(f'Level {levelNum - 1}', {})
            prevMax = prevBand.get('max', 0)
            if proposedMin <= prevMax:
                proposedMin = prevMax + roundTo

        proposedBands[bucketName] = {
            'min': proposedMin,
            'median': proposedMedian,
            'max': proposedMax,
            'minYrs': proposedMinYrs,
            'maxYrs': proposedMaxYrs,
        }

        # Build comparison row
        comparisonRows.append({
            'Level': bucketName,
            'DataPoints': len(validSalaries),
            'CurrentMin': currentBand.get('min', 0),
            'ProposedMin': proposedMin,
            'DeltaMin': proposedMin - currentBand.get('min', 0),
            'CurrentMedian': currentBand.get('median', 0),
            'ProposedMedian': proposedMedian,
            'DeltaMedian': proposedMedian - currentBand.get('median', 0),
            'CurrentMax': currentBand.get('max', 0),
            'ProposedMax': proposedMax,
            'DeltaMax': proposedMax - currentBand.get('max', 0),
            'CurrentMinYrs': currentBand.get('minYrs', 0),
            'ProposedMinYrs': proposedMinYrs,
            'CurrentMaxYrs': currentBand.get('maxYrs'),
            'ProposedMaxYrs': proposedMaxYrs,
        })

    comparisonDf = pd.DataFrame(comparisonRows)

    return (proposedBands, comparisonDf)


# ---------------------------------------------------------------------- #
# -- Feature 7: Timestamps and Deduplication -- #
# ---------------------------------------------------------------------- #

def addCollectionTimestamps(
    df: pd.DataFrame,
    timestamp: Optional[str] = None,
) -> pd.DataFrame:

    '''

    Add CollectedAt timestamp and DedupeHash to each row.

    Parameters:
    -----------
    df : pd.DataFrame
        Data to timestamp
    timestamp : str, optional
        ISO timestamp string. Uses now() if not provided.

    Returns:
    --------
    pd.DataFrame : Input with CollectedAt and DedupeHash columns added

    '''

    result = df.copy()

    if timestamp is None:
        timestamp = datetime.now().isoformat()

    result['CollectedAt'] = timestamp

    # Compute dedup hash from (Company, Listing, Location)
    def _computeHash(row):
        key = f'{row.get("Company", "")}__{row.get("Listing", "")}__{row.get("Location", "")}'
        return hashlib.md5(key.encode()).hexdigest()

    result['DedupeHash'] = result.apply(_computeHash, axis=1)

    return result


def deduplicateWithTimestamps(
    newDf: pd.DataFrame,
    existingDf: pd.DataFrame,
) -> pd.DataFrame:

    '''

    Merge new and existing data, keeping the most recent version of
    each listing based on DedupeHash. When duplicates exist, the row
    with the latest CollectedAt timestamp is retained.

    Parameters:
    -----------
    newDf : pd.DataFrame
        Newly scraped data with CollectedAt and DedupeHash
    existingDf : pd.DataFrame
        Previously saved data with CollectedAt and DedupeHash

    Returns:
    --------
    pd.DataFrame : Combined and deduplicated DataFrame

    '''

    if existingDf.empty:
        return newDf.copy()
    if newDf.empty:
        return existingDf.copy()

    combined = pd.concat([existingDf, newDf], ignore_index=True)

    # Sort by CollectedAt descending so the most recent row comes first
    combined['_sortKey'] = pd.to_datetime(combined['CollectedAt'], errors='coerce')
    combined = combined.sort_values('_sortKey', ascending=False)

    # Keep first occurrence per DedupeHash (most recent)
    combined = combined.drop_duplicates(subset=['DedupeHash'], keep='first')
    combined = combined.drop(columns=['_sortKey']).reset_index(drop=True)

    return combined


def saveValidatedSnapshot(
    df: pd.DataFrame,
    bands: Optional[dict] = None,
    cacheDir: Optional[str] = None,
) -> str:

    '''

    Save current validated dataset as a timestamped snapshot.

    Parameters:
    -----------
    df : pd.DataFrame
        Validated data to snapshot
    bands : dict, optional
        Proposed salary bands to include in metadata
    cacheDir : str, optional
        Cache directory path. Uses validatedCacheDir() if not provided.

    Returns:
    --------
    str : Snapshot filename (without path)

    '''

    if cacheDir is None:
        cacheDir = validatedCacheDir()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csvFilename = f'{timestamp}_validated.csv'
    metaFilename = f'{timestamp}_meta.json'

    csvPath = os.path.join(cacheDir, csvFilename)
    metaPath = os.path.join(cacheDir, metaFilename)

    # Save CSV
    df.to_csv(csvPath, index=False)

    # Save metadata
    meta = {
        'timestamp': datetime.now().isoformat(),
        'recordCount': len(df),
        'companies': sorted(df['Company'].dropna().unique().tolist()) if 'Company' in df.columns else [],
        'proposedBands': bands,
    }

    with open(metaPath, 'w', encoding='utf-8') as f:
        json.dump(meta, f, indent=2, default=str)

    logger.info(f'Saved validated snapshot: {csvFilename} ({len(df)} records)')

    return csvFilename


def loadValidatedHistory(
    cacheDir: Optional[str] = None,
) -> List[dict]:

    '''

    Load previously saved validated data snapshots.

    Parameters:
    -----------
    cacheDir : str, optional
        Cache directory path. Uses validatedCacheDir() if not provided.

    Returns:
    --------
    List[dict] : List of snapshot metadata dicts with keys:
        timestamp, recordCount, companies, proposedBands, csvPath, metaPath

    '''

    if cacheDir is None:
        cacheDir = validatedCacheDir()

    snapshots = []

    if not os.path.exists(cacheDir):
        return snapshots

    metaFiles = sorted(
        [f for f in os.listdir(cacheDir) if f.endswith('_meta.json')],
        reverse=True,
    )

    for metaFile in metaFiles:
        metaPath = os.path.join(cacheDir, metaFile)
        csvFile = metaFile.replace('_meta.json', '_validated.csv')
        csvPath = os.path.join(cacheDir, csvFile)

        if not os.path.exists(csvPath):
            continue

        try:
            with open(metaPath, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            meta['csvPath'] = csvPath
            meta['metaPath'] = metaPath
            snapshots.append(meta)
        except (json.JSONDecodeError, OSError):
            continue

    return snapshots


def loadSnapshotData(csvPath: str) -> pd.DataFrame:

    '''

    Load a validated snapshot CSV file.

    Parameters:
    -----------
    csvPath : str
        Path to the snapshot CSV file

    Returns:
    --------
    pd.DataFrame : Snapshot data

    '''

    if os.path.exists(csvPath):
        return pd.read_csv(csvPath)
    return pd.DataFrame()


# ---------------------------------------------------------------------- #
# -- Market Position Adjustment -- #
# ---------------------------------------------------------------------- #

def applyMarketPositionAdjustment(
    proposedBands: dict,
    adjustmentPct: float,
    roundTo: int = 1000,
) -> dict:

    '''

    Apply a global market position adjustment (knockdown or boost)
    to proposed salary bands. Useful for adjusting market data from
    large/established companies to reflect a smaller, pre-revenue,
    or regionally different employer.

    Parameters:
    -----------
    proposedBands : dict
        Proposed bands in the format {Level N: {min, median, max, ...}}
    adjustmentPct : float
        Adjustment percentage (e.g., -20 for 20% knockdown, +10 for 10% boost)
    roundTo : int
        Rounding granularity in dollars (default 1000)

    Returns:
    --------
    dict : Adjusted bands in the same format

    '''

    multiplier = 1.0 + (adjustmentPct / 100.0)
    adjusted = {}

    for levelKey, band in proposedBands.items():
        adjustedBand = dict(band)  # shallow copy
        for salaryKey in ['min', 'median', 'max']:
            if salaryKey in adjustedBand and adjustedBand[salaryKey] is not None:
                rawVal = adjustedBand[salaryKey] * multiplier
                adjustedBand[salaryKey] = int(round(rawVal / roundTo) * roundTo)
        adjusted[levelKey] = adjustedBand

    return adjusted


# ---------------------------------------------------------------------- #
# -- Feature 8: Trend Analytics -- #
# ---------------------------------------------------------------------- #

def computeTrendAnalytics(
    snapshots: List[pd.DataFrame],
    snapshotTimestamps: List[str],
    groupBy: str = 'LevelBucket',
    windowSize: int = 3,
) -> pd.DataFrame:

    '''

    Compute moving average salary trends across data collection snapshots.

    For each snapshot and bucket, computes the company-weighted average
    midpoint, then applies a simple moving average with the configured
    window size.

    Parameters:
    -----------
    snapshots : List[pd.DataFrame]
        List of snapshot DataFrames (oldest first)
    snapshotTimestamps : List[str]
        ISO timestamps corresponding to each snapshot
    groupBy : str
        Column to group by (default 'LevelBucket')
    windowSize : int
        Moving average window size (default 3)

    Returns:
    --------
    pd.DataFrame : Trend data with columns:
        [Timestamp, LevelBucket, AvgMidpoint, MovingAvg, SnapshotLabel]

    '''

    if not snapshots:
        return pd.DataFrame()

    trendRows = []

    for i, (snapDf, ts) in enumerate(zip(snapshots, snapshotTimestamps)):
        if snapDf.empty:
            continue

        # Compute company-weighted average per bucket for this snapshot
        weighted = companyWeightedAverage(snapDf, groupBy=groupBy)

        if weighted.empty:
            continue

        for _, row in weighted.iterrows():
            trendRows.append({
                'Timestamp': ts,
                'LevelBucket': row[groupBy],
                'AvgMidpoint': row.get('WeightedAvgMidpoint', 0),
                'SnapshotLabel': f'Snapshot {i + 1}',
            })

    if not trendRows:
        return pd.DataFrame()

    trendDf = pd.DataFrame(trendRows)

    # Compute moving average per bucket
    trendDf['Timestamp'] = pd.to_datetime(trendDf['Timestamp'], errors='coerce')
    trendDf = trendDf.sort_values(['LevelBucket', 'Timestamp'])

    trendDf['MovingAvg'] = trendDf.groupby('LevelBucket')['AvgMidpoint'].transform(
        lambda x: x.rolling(window=min(windowSize, len(x)), min_periods=1).mean()
    )

    return trendDf


def compareReferenceToScraped(
    referenceDf: pd.DataFrame,
    scrapedDf: pd.DataFrame,
    groupBy: str = 'LevelBucket',
) -> pd.DataFrame:

    '''

    Compare baseline reference survey data against newly scraped data.
    Returns per-bucket delta metrics.

    Parameters:
    -----------
    referenceDf : pd.DataFrame
        Baseline survey data (with LevelBucket and AdjustedMidpoint)
    scrapedDf : pd.DataFrame
        Newly scraped validated data
    groupBy : str
        Column to group by

    Returns:
    --------
    pd.DataFrame : Comparison with columns:
        [LevelBucket, RefAvgMidpoint, ScrapedAvgMidpoint, Delta, DeltaPct]

    '''

    refWeighted = companyWeightedAverage(referenceDf, groupBy=groupBy)
    scrapedWeighted = companyWeightedAverage(scrapedDf, groupBy=groupBy)

    if refWeighted.empty or scrapedWeighted.empty:
        return pd.DataFrame()

    merged = refWeighted[[groupBy, 'WeightedAvgMidpoint']].rename(
        columns={'WeightedAvgMidpoint': 'RefAvgMidpoint'}
    ).merge(
        scrapedWeighted[[groupBy, 'WeightedAvgMidpoint']].rename(
            columns={'WeightedAvgMidpoint': 'ScrapedAvgMidpoint'}
        ),
        on=groupBy,
        how='outer',
    )

    merged['Delta'] = (merged['ScrapedAvgMidpoint'] - merged['RefAvgMidpoint']).round(0)
    merged['DeltaPct'] = (
        (merged['Delta'] / merged['RefAvgMidpoint']) * 100
    ).round(1)

    return merged
