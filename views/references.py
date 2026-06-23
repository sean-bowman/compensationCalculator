
# -- References & Research Page -- #

'''

Display research sources, annotated bibliography, and supplementary
market research used to develop the compensation framework.

Author: Sean Bowman
Date:   02/23/2026

'''

# Third-party imports
import streamlit as st

# Local imports
from auditUtils import blsBenchmarks, loadReferenceMarkdown

# ---------------------------------------------------------------------- #
# -- References & Research Page -- #
# ---------------------------------------------------------------------- #

def renderReferences(loadReference):

    '''

    Render the references and research page.

    Parameters:
    -----------
    loadReference : callable
        Cached function that returns the consolidated reference markdown string

    '''
    
    st.title('References & Research')
    st.markdown('Research sources and market data used to develop the compensation framework.')
    st.markdown('---')

    # -- Key statistics summary -- #
    # Figures below are synthetic placeholders from WAGE_BENCHMARKS in
    # tools/syntheticData.py -- they are fictional, not real market data.
    statsCols = st.columns(3)
    with statsCols[0]:
        st.metric('Benchmark Median', f'${blsBenchmarks["median"]:,.0f}')
    with statsCols[1]:
        st.metric('Regional Average', f'${blsBenchmarks["regionalAverage"]:,.0f}')
    with statsCols[2]:
        st.metric('Benchmark 90th Pct.', f'${blsBenchmarks["p90"]:,.0f}')

    st.markdown('---')

    # -- Consolidated reference documentation -- #
    referenceContent = loadReference()
    st.markdown(referenceContent)

# ---------------------------------------------------------------------- #
# -- Module-Level Execution -- #
# ---------------------------------------------------------------------- #

@st.cache_data
def _loadReference():

    '''
    
    Load and cache the consolidated reference markdown.
    
    '''

    return loadReferenceMarkdown()

renderReferences(_loadReference)
