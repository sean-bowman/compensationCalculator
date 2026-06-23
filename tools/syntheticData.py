
# -- Synthetic Compensation Data -- #

'''

Synthetic, fictional compensation data for the Compensation Audit Tool.

This module replaces the original binary spreadsheet inputs with readable,
version-controlled Python constants. Every dollar figure here is invented
for demonstration purposes and does not represent any real company's
compensation structure.

The data STRUCTURES (dict keys, value shapes) match exactly what the rest
of the application expects -- only the source and the numbers are synthetic.
`auditUtils.py` imports these constants directly instead of parsing Excel.

Three datasets are provided:
  - SALARY_BANDS          : 5-level base salary framework (min/median/max + years)
  - EXPERIENCE_MODIFIERS  : relevance and complexity multipliers
  - MANAGEMENT_PREMIUMS   : flat dollar premiums by management role
  - EXTENDED_BANDS        : extended maxima and manager-track ranges
  - GEOGRAPHIC_ADJUSTMENTS: cost-of-living factors relative to the HQ baseline

Author: Sean Bowman
Date:   05/22/2026

'''

# ---------------------------------------------------------------------- #
# -- Salary Bands (5-Level Framework) -- #
# ---------------------------------------------------------------------- #
# Fictional five-level individual-contributor band structure. Each level
# maps to a roman numeral key ('I'-'V') used by levelsData elsewhere.
# Figures are invented round numbers for a demonstration dataset.

SALARY_BANDS = {
    'Level 1': {'min': 70000,  'median': 80000,  'max': 90000,  'minYrs': 0,  'maxYrs': 6,    'levelKey': 'I'},
    'Level 2': {'min': 90000,  'median': 100000, 'max': 110000, 'minYrs': 2,  'maxYrs': 12,   'levelKey': 'II'},
    'Level 3': {'min': 110000, 'median': 125000, 'max': 140000, 'minYrs': 4,  'maxYrs': None, 'levelKey': 'III'},
    'Level 4': {'min': 140000, 'median': 160000, 'max': 180000, 'minYrs': 7,  'maxYrs': None, 'levelKey': 'IV'},
    'Level 5': {'min': 180000, 'median': 205000, 'max': 230000, 'minYrs': 12, 'maxYrs': None, 'levelKey': 'V'},
}

# ---------------------------------------------------------------------- #
# -- Experience Modifiers -- #
# ---------------------------------------------------------------------- #
# Multipliers applied to the base salary before management premiums.
# Two categories (relevance, complexity), each Low/Medium/High. Capped at
# +5% per category so band position dominates the calculation.

EXPERIENCE_MODIFIERS = {
    'relevance':  {'Low': 1.0, 'Medium': 1.025, 'High': 1.05},
    'complexity': {'Low': 1.0, 'Medium': 1.025, 'High': 1.05},
}

# ---------------------------------------------------------------------- #
# -- Management Premiums -- #
# ---------------------------------------------------------------------- #
# Flat dollar amounts added after base-salary modification. Additive (not
# multiplicative) so premiums do not compound with experience modifiers.
# The 'RE' key is the Responsible Engineer role.

MANAGEMENT_PREMIUMS = {
    'Engineer': 0,
    'RE': 5000,
    'Lead': 15000,
    'Director': 40000,
}

# ---------------------------------------------------------------------- #
# -- Extended Bands -- #
# ---------------------------------------------------------------------- #
# Extended salary ranges that account for experience modifiers pushing a
# salary above the standard band max. 'extendedMax' is the band max plus a
# headroom allowance. Manager-track ranges apply only to Levels 4-5.

EXTENDED_BANDS = {
    'Level 1': {'extendedMax': 99000,  'mgrMin': None,   'mgrMax': None,   'mgrExtended': None},
    'Level 2': {'extendedMax': 121000, 'mgrMin': None,   'mgrMax': None,   'mgrExtended': None},
    'Level 3': {'extendedMax': 154000, 'mgrMin': None,   'mgrMax': None,   'mgrExtended': None},
    'Level 4': {'extendedMax': 198000, 'mgrMin': 175000, 'mgrMax': 205000, 'mgrExtended': 225000},
    'Level 5': {'extendedMax': 253000, 'mgrMin': 215000, 'mgrMax': 250000, 'mgrExtended': 275000},
}

# ---------------------------------------------------------------------- #
# -- Geographic Adjustments -- #
# ---------------------------------------------------------------------- #
# Cost-of-living adjustment factors relative to the company HQ baseline
# (0.0 = baseline). Negative values mean the source location is more
# expensive than HQ -- an employee relocating from that city to HQ would
# accept a lower base salary. All factors are fictional.

GEOGRAPHIC_ADJUSTMENTS = {
    'Metro City':    -0.175,
    'Coastal City':  -0.165,
    'Harbor Town':   -0.252,
    'Bay District':  -0.150,
    'Mountain View': -0.104,
    'Highland Park': -0.127,
    'River Bend':    -0.114,
    'Lakeside':      -0.106,
    'HQ City':        0.0,
}

# ---------------------------------------------------------------------- #
# -- Wage Benchmarks -- #
# ---------------------------------------------------------------------- #
# Fictional national wage percentiles used as reference lines on charts.
# 'regionalAverage' is the geographic baseline used for cost-of-living
# normalization; the UI renders it as a generic regional average.

WAGE_BENCHMARKS = {
    'median': 130000,
    'p10': 78000,
    'p25': 105000,
    'p75': 165000,
    'p90': 200000,
    'regionalAverage': 110000,
}
