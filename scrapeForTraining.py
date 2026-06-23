
# -- Training Data Scrape Script -- #

'''

Scrapes career page job listings from all configured companies and exports
them to a dated Excel file for manual Vlvl labeling. The labeled output is
intended as additional training data for the NN level classifier, merged
with the existing ~500 survey records.

Author: Sean Bowman
Date:   03/12/2026

Usage:
    python scrapeForTraining.py

Output:
    documentation/training_scrape_YYYYMMDD.xlsx

    Sheet 1 "Listings" : one row per job listing, with empty Vlvl and Notes
                         columns for manual labeling.
    Sheet 2 "Instructions" : labeling guide (Vlvl 1-5 definitions, workflow).

Columns exported:
    Company, Listing, Discipline, Seniority, Location, State, Min, Max, Link,
    Vlvl (fill in 1-5), Notes (optional)

'''

# Standard library imports
import os
import re
import sys
from datetime import date

# Ensure tools/ is importable
_scriptDir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_scriptDir, 'tools'))

# Third-party imports
import pandas as pd

# Local imports
from compensationScraper import CompensationScraper, ScraperConfig


# ------------------------------------------------------------------------------- #
# -- Configuration -- #
# ------------------------------------------------------------------------------- #

# Force fresh fetches: set TTL to 0 so no cached responses are reused.
# This ensures we get the current live job board state from each company.
_config = ScraperConfig(
    cacheTtlHours = 0,
    requestDelaySeconds = 1.5,
)

_outputDir  = os.path.join(_scriptDir, 'documentation')
_outputFile = os.path.join(_outputDir, f'training_scrape_{date.today().strftime("%Y%m%d")}.xlsx')

# Columns to include in the labeling sheet (in display order)
_exportCols = ['Company', 'Listing', 'Discipline', 'Seniority', 'Location', 'State', 'Min', 'Max', 'ManagementRole', 'Vlvl', 'Notes', 'Link']

# Instructions sheet content
_instructionsRows = [
    ('Column', 'Instructions'),
    ('Vlvl', 'Enter an integer 1-5 to assign this listing to an engineering level.'),
    ('', 'Leave blank (or enter 0) to exclude the row from training.'),
    ('Notes', 'Optional free-text note. Not used in training -- for your reference only.'),
    ('', ''),
    ('Vlvl', 'Level Reference'),
    ('1', 'Level 1 -- Associate Engineer  (0-2 yrs, junior/entry)'),
    ('2', 'Level 2 -- Engineer            (2-5 yrs, individual contributor)'),
    ('3', 'Level 3 -- Senior Engineer     (5-9 yrs, independent)'),
    ('4', 'Level 4 -- Principal / Staff   (9-15 yrs, expert/lead IC)'),
    ('5', 'Level 5 -- Director / Fellow   (15+ yrs, org leader or deep specialist)'),
    ('', ''),
    ('Workflow', 'Instructions'),
    ('1', 'Sort or filter by Discipline to batch similar listings.'),
    ('2', 'Use the Listing title + Seniority column as the primary signal.'),
    ('3', 'Use Min/Max salary as a secondary signal where present.'),
    ('4', 'When in doubt between two levels, note it in Notes and pick the lower.'),
    ('5', 'Rows without a clear engineering title (e.g. HR, Finance) should be left blank (excluded).'),
    ('', ''),
    ('Merge', 'After labeling, import via the NN Classifier tab in the Streamlit app,'),
    ('', 'or manually place the file in documentation/ and run retraining from the CLI.'),
]


# ------------------------------------------------------------------------------- #
# -- Progress Callback -- #
# ------------------------------------------------------------------------------- #

def _progress(step: int, total: int, message: str) -> None:
    '''Print scrape progress to console.'''
    if total > 0:
        pct = int(100 * step / total)
        print(f'  [{pct:3d}%] {message}')
    else:
        print(f'  [---] {message}')


def _detectManagementRole(title: str) -> str:

    '''

    Detect whether a job title carries inherent management responsibility.

    Identifies roles where the title itself signals people management or
    organizational leadership scope, independent of the technical seniority
    level. This column is used only for training data annotation -- the
    management dimension is intentionally excluded from the technical Vlvl
    assignment so that level mapping stays purely technical.

    Parameters:
    -----------
    title : str
        Job listing title

    Returns:
    --------
    str : Management role label, or empty string if none detected.
          Possible values: 'Director', 'Lead', 'Chief', 'RE', 'Manager'

    '''

    if not title:
        return ''

    titleLower = title.lower()

    if 'director' in titleLower:
        return 'Director'
    if re.search(r'\blead\b', titleLower):
        return 'Lead'
    if 'chief' in titleLower:
        return 'Chief'
    # RE = Responsible Engineer (component-level role with accountability scope)
    if re.search(r'\bre\b', titleLower):
        return 'RE'
    if 'manager' in titleLower:
        return 'Manager'

    return ''


# ------------------------------------------------------------------------------- #
# -- Main -- #
# ------------------------------------------------------------------------------- #

def main() -> None:

    '''
    Run the career page scrape, add labeling columns, and export to Excel.
    '''

    print('Career page scrape for NN training data')
    print(f'Output: {_outputFile}')
    print()

    scraper = CompensationScraper(_config)

    print('Scraping career pages...')
    df = scraper.runSingleSource('careerPages', progressCallback=_progress)
    print()

    # Report any per-source errors
    errors = scraper.lastErrors()
    if errors:
        print('Errors encountered during scrape:')
        for source, msg in errors.items():
            print(f'  {source}: {msg}')
        print()

    if df is None or df.empty:
        print('No listings collected. Check that target companies are reachable and retry.')
        return

    # Keep only columns that exist in the result
    availableCols = [c for c in _exportCols if c in df.columns]
    exportDf = df[availableCols].copy()

    # Primary filter: global allowlist. A listing must contain at least one
    # strong engineering qualifier to be retained. This is the primary defense
    # against non-engineering roles (food service, operations, administrative,
    # trades, facilities, etc.) slipping through from high-volume scrapers like
    # SpaceX that post hundreds of non-engineering listings. An allowlist is
    # more robust than a blocklist because it does not require enumerating every
    # possible non-engineering job category.
    #
    # 'engineer' / 'engineering' -- all engineering disciplines
    # 'scientist'                -- research and applied science roles
    # 'developer'                -- software developer (distinct title from engineer)
    # 'architect'                -- software/systems architect
    # 'physicist'                -- research physics roles
    # 'technologist'             -- engineering technologist (degreed, not trade)
    # 'designer'                 -- hardware/systems designer (e.g. RF Designer)
    # 'analyst'                  -- engineering analysis roles (Structural Analyst,
    #                               Propulsion Analyst, Thermal Analyst, etc.)
    #                               Business/operations analyst variants are
    #                               caught by the blocklist below.
    #
    # Intentionally omitted from the allowlist:
    #   'lead'      -- too broad; Supply Chain Lead, Hospitality Lead would pass
    #   'director'  -- too broad; non-engineering directors would pass
    #   'specialist' -- too broad; hundreds of non-engineering specialist titles
    #   'principal'  -- 'principal' alone is rare; Principal Engineer has 'engineer'
    engAllowlist = [
        'engineer', 'engineering',
        'scientist',
        'developer',
        'architect',
        'physicist',
        'technologist',
        'designer',
        'analyst',
    ]
    engAllowMask = exportDf['Listing'].str.lower().apply(
        lambda t: any(q in t for q in engAllowlist)
    )

    # Secondary blocklist: catch known non-engineering titles that happen to
    # contain an allowlist term (e.g., 'instructional designer', 'brand architect').
    nonEngineeringKeywords = [
        # Food service
        'barista', 'cook', 'chef', 'mixologist', 'food service', 'hospitality',
        'catering',
        # Trade / technician (distinct from degreed engineering roles)
        'technician', 'machinist', 'operator',
        # Manufacturing trade roles (not engineering)
        'assembler', 'assembly technician', 'assembly associate',
        'production associate', 'production worker', 'production supervisor',
        'manufacturing associate', 'fabricator', 'welder', 'welding',
        'sheet metal', 'composite layup', 'material handler',
        'warehouse', 'inventory', 'shipping', 'receiving',
        # Quality non-engineering roles
        'quality inspector', 'quality auditor', 'quality representative',
        'quality specialist', 'quality technician', 'quality associate',
        'customer quality', 'supplier quality representative',
        'incoming inspection', 'source inspector',
        # Business / finance / legal / admin
        # Note: 'business analyst' and 'operations analyst' are blocked here
        # because 'analyst' is in the allowlist for engineering analysis roles.
        'business analyst', 'business operations analyst', 'operations analyst',
        'business operations', 'business development', 'business intelligence',
        'data analyst', 'market analyst', 'financial analyst', 'account specialist',
        'compliance analyst', 'regulatory compliance', 'policy analyst',
        'real estate', 'total rewards', 'material flow',
        'accountant', 'accounting', 'finance', 'financial', 'controller',
        'tax ', 'treasury', 'budget', 'contracts', 'contract admin',
        'procurement', 'buyer', 'purchasing', 'supply chain', 'logistics',
        'paralegal', 'attorney', 'counsel', 'compliance officer',
        'administrative', 'receptionist', 'executive assistant',
        'coordinator', 'scheduler', 'planner',
        # HR / talent / training / L&D
        'recruiter', 'recruiting', 'talent acquisition', 'human resources',
        'hr business', 'compensation analyst', 'benefits', 'payroll',
        'learning and development', 'training specialist', 'trainer',
        'instructional designer', 'facilitator',
        # Pre-employment / onboarding
        'pre-employment', 'pre employment', 'onboarding',
        # Program / project management (non-engineering scope)
        'program manager', 'project manager', 'program director',
        'capture manager', 'proposal manager',
        # Marketing / communications / PR
        'marketing', 'communications', 'public relations', 'copywriter',
        'social media', 'brand architect',
        # Customer / sales
        'customer success', 'customer support', 'customer service',
        'account manager', 'account executive', 'sales ',
        # IT support (distinct from software engineering)
        'help desk', 'it support', 'desktop support', 'service desk',
        # Security -- physical and non-engineering cyber/assurance roles
        # Note: 'cybersecurity engineer' is retained via the 'engineer' allowlist.
        # These analyst/assurance variants lack a clear engineering technical scope.
        'security officer', 'security guard',
        'security analyst', 'cyber assurance', 'industrial security',
        # Facilities / transport
        'custodian', 'janitor', 'driver', 'pilot',
    ]
    nonEngMask = exportDf['Listing'].str.lower().apply(
        lambda t: any(kw in t for kw in nonEngineeringKeywords)
    )

    exclusionMask = nonEngMask | ~engAllowMask
    nonEngCount = exclusionMask.sum()

    if nonEngCount:
        print(f'Excluded {nonEngCount} non-engineering listings.')
    exportDf = exportDf[~exclusionMask].reset_index(drop=True)

    # Detect management responsibility scope from title keywords.
    # This is kept separate from Vlvl so level assignment stays strictly technical.
    exportDf['ManagementRole'] = exportDf['Listing'].apply(_detectManagementRole)

    # Add empty labeling columns
    exportDf['Vlvl']  = None
    exportDf['Notes'] = ''

    # Enforce display column order (Vlvl/Notes before Link)
    finalCols = [c for c in _exportCols if c in exportDf.columns]
    exportDf = exportDf[finalCols]

    # Sort for easier manual review
    exportDf = exportDf.sort_values(['Company', 'Listing'], ignore_index=True)

    # Print per-company counts
    companyCounts = exportDf['Company'].value_counts().sort_index()
    print(f'Collected {len(exportDf)} listings across {len(companyCounts)} companies:')
    for company, count in companyCounts.items():
        print(f'  {company:<30s} {count:>4d} listings')
    print()

    # Build instructions DataFrame
    instructionsDf = pd.DataFrame(_instructionsRows, columns=['A', 'B'])

    # Export to Excel with two sheets
    os.makedirs(_outputDir, exist_ok=True)

    with pd.ExcelWriter(_outputFile, engine='openpyxl') as writer:

        exportDf.to_excel(writer, sheet_name='Listings', index=False)
        instructionsDf.to_excel(writer, sheet_name='Instructions', index=False, header=False)

        # Basic column width formatting for readability
        listingsSheet = writer.sheets['Listings']
        colWidths = {
            'A': 24,   # Company
            'B': 52,   # Listing
            'C': 20,   # Discipline
            'D': 14,   # Seniority
            'E': 20,   # Location
            'F': 8,    # State
            'G': 12,   # Min
            'H': 12,   # Max
            'I': 18,   # ManagementRole
            'J': 8,    # Vlvl
            'K': 40,   # Notes
            'L': 52,   # Link
        }
        for col, width in colWidths.items():
            listingsSheet.column_dimensions[col].width = width

        instrSheet = writer.sheets['Instructions']
        instrSheet.column_dimensions['A'].width = 16
        instrSheet.column_dimensions['B'].width = 80

    print(f'Saved: {_outputFile}')


if __name__ == '__main__':
    main()
