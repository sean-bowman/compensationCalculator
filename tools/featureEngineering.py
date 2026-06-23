
# -- Neural Network Feature Engineering -- #

'''

Feature extraction pipeline for the level bucket neural network
classifier. Converts raw job listing data (title, salary, discipline,
company, experience) into a fixed-width numeric feature vector
suitable for training an MLP classifier.

Each feature group is documented and extractable independently,
making the pipeline transparent and inspectable -- a key design
goal for this educational implementation.

Author: Sean Bowman
Date:   03/07/2026

'''

# Standard library imports
import re
from typing import List, Tuple, Optional

# Third-party imports
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------- #
# -- Constants -- #
# ---------------------------------------------------------------------- #

# Seniority keywords matched against the job title. Order matters:
# more specific patterns are checked first to avoid partial matches.
SENIORITY_KEYWORDS = [
    'principal', 'fellow', 'distinguished', 'chief',
    'staff',
    'lead engineer', 'tech lead', 'team lead',
    'senior', 'sr.',
    'junior', 'jr.', 'associate', 'entry level', 'entry-level',
    'intern', 'co-op', 'new grad',
]

# Discipline keywords matched against title and discipline columns.
DISCIPLINE_KEYWORDS = [
    'propulsion', 'avionics', 'gnc', 'structures', 'thermal',
    'mechanical', 'electrical', 'software', 'test', 'manufacturing',
    'systems', 'quality', 'integration', 'fluids', 'materials',
    'analysis', 'gse', 'launch', 'instrumentation',
]

# Management-related title keywords.
MANAGEMENT_TITLE_KEYWORDS = [
    'manager', 'director', 'vp', 'vice president', 'head of',
    'supervisor', 'chief',
]

# Management-related description keywords.
MANAGEMENT_DESC_KEYWORDS = [
    'manage a team', 'direct reports', 'supervise',
    'people management', 'team leadership',
]

# Feature names are built dynamically in buildFeatureMatrix() but
# this constant tracks the expected groups for documentation.
FEATURE_GROUPS = {
    'seniority': len(SENIORITY_KEYWORDS),
    'title_structure': 4,
    'discipline': len(DISCIPLINE_KEYWORDS),
    'salary': 5,
    'experience': 2,
    'company': 0,  # dynamic -- depends on training data
    'management': 2,
}


# ---------------------------------------------------------------------- #
# -- Feature Extraction Functions -- #
# ---------------------------------------------------------------------- #

def _extractSeniorityFlags(title: str) -> List[float]:

    '''

    Extract binary flags for seniority keywords found in the title.
    Returns a list of 0.0/1.0 values, one per keyword in
    SENIORITY_KEYWORDS.

    Parameters:
    -----------
    title : str
        Job listing title

    Returns:
    --------
    List[float] : Binary flags for each seniority keyword

    '''

    titleLower = title.lower()
    return [1.0 if kw in titleLower else 0.0 for kw in SENIORITY_KEYWORDS]


def _extractTitleStructure(title: str) -> List[float]:

    '''

    Extract structural features from the title text:
    - word count (normalized by dividing by 10)
    - whether a roman numeral level indicator is present (I-V)
    - whether a numeric level indicator is present (1-5)
    - character length (normalized by dividing by 100)

    Parameters:
    -----------
    title : str
        Job listing title

    Returns:
    --------
    List[float] : [wordCount, hasRoman, hasNumeric, charLength]

    '''

    titleLower = title.lower()
    words = title.split()
    wordCount = len(words) / 10.0
    charLength = len(title) / 100.0

    # Roman numeral detection -- match standalone I-V patterns
    hasRoman = 1.0 if re.search(
        r'\b(?:level|grade|engineer)\s*([IViv]{1,3})\b', title
    ) else 0.0

    # Numeric level detection -- match "Level 3", "Engineer 2", etc.
    hasNumeric = 1.0 if re.search(
        r'\b(?:level|grade|engineer)\s*([1-5])\b', titleLower
    ) else 0.0

    return [wordCount, hasRoman, hasNumeric, charLength]


def _extractDisciplineFlags(title: str, discipline: str) -> List[float]:

    '''

    Extract binary flags for discipline keywords found in
    either the title or the discipline column.

    Parameters:
    -----------
    title : str
        Job listing title
    discipline : str
        Discipline field from the listing

    Returns:
    --------
    List[float] : Binary flags for each discipline keyword

    '''

    combined = f'{title} {discipline}'.lower()
    return [1.0 if kw in combined else 0.0 for kw in DISCIPLINE_KEYWORDS]


def _extractSalaryFeatures(minSalary: float, maxSalary: float) -> List[float]:

    '''

    Extract normalized salary features. All values are scaled
    by dividing by 200,000 (approximate max aerospace salary)
    to keep features in a reasonable range for the MLP.

    Features:
    - normalized min
    - normalized max
    - normalized midpoint
    - normalized range width
    - log(midpoint) scaled (0 if no salary data)

    Parameters:
    -----------
    minSalary : float
        Minimum salary (may be NaN or 0)
    maxSalary : float
        Maximum salary (may be NaN or 0)

    Returns:
    --------
    List[float] : 5 salary features

    '''

    scale = 200000.0

    if pd.isna(minSalary) or pd.isna(maxSalary) or minSalary <= 0 or maxSalary <= 0:
        return [0.0, 0.0, 0.0, 0.0, 0.0]

    normMin = float(minSalary) / scale
    normMax = float(maxSalary) / scale
    midpoint = (float(minSalary) + float(maxSalary)) / 2.0
    normMid = midpoint / scale
    normRange = (float(maxSalary) - float(minSalary)) / scale
    logMid = np.log1p(midpoint) / np.log1p(scale)

    return [normMin, normMax, normMid, normRange, logMid]


def _extractExperienceFeatures(expReq: float) -> List[float]:

    '''

    Extract experience features from the ExpReq column.

    Features:
    - normalized YoE value (divided by 20, or -0.05 if missing)
    - has_experience flag (1.0 if value present, 0.0 if missing)

    Parameters:
    -----------
    expReq : float
        Required years of experience (may be NaN)

    Returns:
    --------
    List[float] : [normalizedYoe, hasExperience]

    '''

    if pd.isna(expReq):
        return [-0.05, 0.0]

    return [float(expReq) / 20.0, 1.0]


def _extractManagementFlags(title: str, description: str = '') -> List[float]:

    '''

    Extract management indicator flags from title and description.

    Parameters:
    -----------
    title : str
        Job listing title
    description : str
        Job description text (may be empty)

    Returns:
    --------
    List[float] : [titleMgmt, descMgmt]

    '''

    titleLower = title.lower()
    descLower = description.lower()

    titleMgmt = 1.0 if any(kw in titleLower for kw in MANAGEMENT_TITLE_KEYWORDS) else 0.0
    descMgmt = 1.0 if any(kw in descLower for kw in MANAGEMENT_DESC_KEYWORDS) else 0.0

    return [titleMgmt, descMgmt]


# ---------------------------------------------------------------------- #
# -- Company Encoding -- #
# ---------------------------------------------------------------------- #

def buildCompanyEncoder(df: pd.DataFrame, maxCompanies: int = 10) -> dict:

    '''

    Build a frequency-based company encoder from the training data.
    The top N most frequent companies each get their own feature;
    all others are grouped into an 'other' bucket.

    Parameters:
    -----------
    df : pd.DataFrame
        Training data with a 'Company' column
    maxCompanies : int
        Maximum number of individual company features

    Returns:
    --------
    dict : Mapping of company name -> feature index (0 to maxCompanies).
           Index maxCompanies is the 'other' bucket.

    '''

    counts = df['Company'].value_counts()
    topCompanies = counts.head(maxCompanies).index.tolist()
    encoder = {company: idx for idx, company in enumerate(topCompanies)}

    return encoder


def _extractCompanyFeatures(company: str, encoder: dict) -> List[float]:

    '''

    One-hot encode the company using the pre-built encoder.

    Parameters:
    -----------
    company : str
        Company name
    encoder : dict
        Mapping from buildCompanyEncoder()

    Returns:
    --------
    List[float] : One-hot vector of length len(encoder) + 1
                   (extra slot for 'other')

    '''

    numSlots = len(encoder) + 1  # +1 for 'other'
    features = [0.0] * numSlots

    if company in encoder:
        features[encoder[company]] = 1.0
    else:
        features[-1] = 1.0  # 'other' bucket

    return features


# ---------------------------------------------------------------------- #
# -- Public Interface -- #
# ---------------------------------------------------------------------- #

def extractFeatureVector(
    row: pd.Series,
    companyEncoder: dict,
) -> np.ndarray:

    '''

    Extract a complete feature vector from a single row.
    Combines all feature groups into a single flat array.

    Parameters:
    -----------
    row : pd.Series
        A row from the survey/scraper DataFrame
    companyEncoder : dict
        Company encoder from buildCompanyEncoder()

    Returns:
    --------
    np.ndarray : Feature vector (1D)

    '''

    title = str(row.get('Listing', ''))
    discipline = str(row.get('Discipline', ''))
    description = str(row.get('Description', ''))
    company = str(row.get('Company', ''))
    minSalary = row.get('Min', np.nan)
    maxSalary = row.get('Max', np.nan)
    expReq = row.get('ExpReq', np.nan)

    # Coerce salary and experience to numeric
    minSalary = pd.to_numeric(minSalary, errors='coerce')
    maxSalary = pd.to_numeric(maxSalary, errors='coerce')
    expReq = pd.to_numeric(expReq, errors='coerce')

    features = []
    features.extend(_extractSeniorityFlags(title))
    features.extend(_extractTitleStructure(title))
    features.extend(_extractDisciplineFlags(title, discipline))
    features.extend(_extractSalaryFeatures(minSalary, maxSalary))
    features.extend(_extractExperienceFeatures(expReq))
    features.extend(_extractManagementFlags(title, description))
    features.extend(_extractCompanyFeatures(company, companyEncoder))

    return np.array(features, dtype=np.float64)


def buildFeatureMatrix(
    df: pd.DataFrame,
    companyEncoder: Optional[dict] = None,
) -> Tuple[np.ndarray, List[str], dict]:

    '''

    Build the full feature matrix from a DataFrame.
    If no company encoder is provided, one is built from
    the data (use this for training; pass the encoder
    explicitly for inference).

    Parameters:
    -----------
    df : pd.DataFrame
        Survey or scraped data
    companyEncoder : dict, optional
        Pre-built company encoder. If None, built from df.

    Returns:
    --------
    Tuple[np.ndarray, List[str], dict] :
        - Feature matrix (n_samples x n_features)
        - Feature names list
        - Company encoder used

    '''

    if companyEncoder is None:
        companyEncoder = buildCompanyEncoder(df)

    # Build feature names for documentation and visualization
    featureNames = []

    # Seniority flags
    for kw in SENIORITY_KEYWORDS:
        featureNames.append(f'seniority_{kw.replace(" ", "_")}')

    # Title structure
    featureNames.extend(['title_word_count', 'title_has_roman', 'title_has_numeric', 'title_char_length'])

    # Discipline flags
    for kw in DISCIPLINE_KEYWORDS:
        featureNames.append(f'discipline_{kw}')

    # Salary features
    featureNames.extend(['salary_min', 'salary_max', 'salary_midpoint', 'salary_range', 'salary_log_midpoint'])

    # Experience features
    featureNames.extend(['experience_yoe', 'experience_has_data'])

    # Management flags
    featureNames.extend(['mgmt_title', 'mgmt_description'])

    # Company features
    for company in sorted(companyEncoder.keys(), key=lambda c: companyEncoder[c]):
        featureNames.append(f'company_{company.lower().replace(" ", "_")}')
    featureNames.append('company_other')

    # Extract feature vectors
    rows = []
    for _, row in df.iterrows():
        rows.append(extractFeatureVector(row, companyEncoder))

    X = np.vstack(rows)

    return X, featureNames, companyEncoder


def buildLabelVector(df: pd.DataFrame, labelCol: str = 'Vlvl') -> np.ndarray:

    '''

    Extract the target label vector from the DataFrame.
    Labels are integer engineering levels 1-5. NaN values are
    mapped to 0 (Unclassified).

    Parameters:
    -----------
    df : pd.DataFrame
        Data with a label column
    labelCol : str
        Column name containing integer level labels

    Returns:
    --------
    np.ndarray : Integer label array (n_samples,)

    '''

    labels = pd.to_numeric(df[labelCol], errors='coerce').fillna(0).astype(int)

    return labels.values
