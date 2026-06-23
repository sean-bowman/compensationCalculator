
# -- Compensation Structure Audit Tool -- #

'''

Streamlit frontend launcher for the Compensation Structure Audit.
Uses st.navigation() with st.Page() for sidebar navigation.

Run with: streamlit run GUI.py

Author: Sean Bowman
Date:   02/24/2026

'''

# Standard library imports
import os
import sys

# Third-party imports
import streamlit as st

# Resolve paths relative to this script so the app works from any working directory
_appDir = os.path.dirname(os.path.abspath(__file__))
_viewsDir = os.path.join(_appDir, 'views')

# Ensure tools/ is importable (auditUtils, referenceParser, etc.)
sys.path.insert(0, os.path.join(_appDir, 'tools'))

# ---------------------------------------------------------------------- #
# -- App Configuration -- #
# ---------------------------------------------------------------------- #

st.set_page_config(
    page_title='Compensation Audit',
    page_icon=':bar_chart:',
    layout='wide',
)

# Text wordmark rendered in place of a logo image. Set as monospace type
# in the copper-amber accent color.
_wordmark = (
    "<div style=\"font-family:'Share Tech Mono','Consolas',monospace; "
    "font-weight:700; color:#E0975A; font-size:1.4rem; "
    "letter-spacing:0.02em; padding:0.25rem 0;\">Compensation Audit</div>"
)

# ---------------------------------------------------------------------- #
# -- Sidebar Wordmark -- #
# ---------------------------------------------------------------------- #

with st.sidebar:
    st.markdown(_wordmark, unsafe_allow_html=True)

# ---------------------------------------------------------------------- #
# -- Page Definitions -- #
# ---------------------------------------------------------------------- #

levelsPage           = st.Page(os.path.join(_viewsDir, 'levelsOverview.py'),         title = 'Engineering Levels')
calculatorPage       = st.Page(os.path.join(_viewsDir, 'compensationCalculator.py'), title = 'Salary Calculator')
marketComparisonPage = st.Page(os.path.join(_viewsDir, 'marketComparison.py'),       title = 'Market Comparison')
individualAuditPage  = st.Page(os.path.join(_viewsDir, 'individualAudit.py'),        title = 'Employee Audit')
marketExplorerPage   = st.Page(os.path.join(_viewsDir, 'marketDataExplorer.py'),     title = 'Job Listings Explorer')
marketToolsPage      = st.Page(os.path.join(_viewsDir, 'marketTools.py'),            title = 'Market Analysis')
referencesPage       = st.Page(os.path.join(_viewsDir, 'references.py'),             title = 'References & Sources')

# ---------------------------------------------------------------------- #
# -- Navigation Setup -- #
# ---------------------------------------------------------------------- #

pg = st.navigation(
    {
        'Framework': [calculatorPage, levelsPage, individualAuditPage],
        'Market Tools': [marketComparisonPage, marketExplorerPage, marketToolsPage],
        'Resources': [referencesPage],
    }
)

# ---------------------------------------------------------------------- #
# -- Run -- #
# ---------------------------------------------------------------------- #

pg.run()
