
# -- Market Tools Page -- #

'''

Consolidated market tools page combining:
  - Level Bands Editor: view and override the internal salary band boundaries
  - Scraper Runner: unified access to all compensation data scrapers
  - NN Classifier: neural network level classifier inspection and training

Author: Sean Bowman
Date:   03/12/2026

'''

# Standard library imports
import json
import os
import sys

# Third-party imports
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure tools/ is importable (GUI.py inserts it, but guard for direct use)
_viewsDir = os.path.dirname(os.path.abspath(__file__))
_appDir = os.path.dirname(_viewsDir)
_toolsDir = os.path.join(_appDir, 'tools')
if _toolsDir not in sys.path:
    sys.path.insert(0, _toolsDir)
if _viewsDir not in sys.path:
    sys.path.insert(0, _viewsDir)

from auditUtils import salaryBands, levelsData, managementPremiums, colors, plotlyDarkLayout

# Import render functions from existing pages (guarded at their call sites)
from dataScraper import renderDataScraper
from nnShowcase import renderNnShowcase
from validatedMarketAnalysis import renderValidatedMarketAnalysis

# ------------------------------------------------------------------------------- #
# -- Constants -- #
# ------------------------------------------------------------------------------- #

_bandOverridesPath    = os.path.join(_toolsDir, 'bandOverrides.json')
_premiumOverridesPath = os.path.join(_toolsDir, 'premiumOverrides.json')
_editableFields = ('min', 'median', 'max')


# ------------------------------------------------------------------------------- #
# -- Helpers -- #
# ------------------------------------------------------------------------------- #

def _loadOverrides() -> dict:
    '''
    Load the current band overrides from disk, or return an empty dict if none exist.

    Returns:
    --------
    dict : Override dict {levelName: {min, median, max}}
    '''
    if os.path.exists(_bandOverridesPath):
        with open(_bandOverridesPath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _saveOverrides(overrides: dict) -> None:
    '''
    Persist band overrides to disk.

    Parameters:
    -----------
    overrides : dict
        Full override dict {levelName: {min, median, max}} for all levels
    '''
    with open(_bandOverridesPath, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, indent=2)


def _loadPremiumOverrides() -> dict:
    '''
    Load management premium overrides from disk, or return an empty dict if none exist.

    Returns:
    --------
    dict : Override dict {role: premiumAmount}
    '''
    if os.path.exists(_premiumOverridesPath):
        with open(_premiumOverridesPath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def _savePremiumOverrides(overrides: dict) -> None:
    '''
    Persist management premium overrides to disk.

    Parameters:
    -----------
    overrides : dict
        Full override dict {role: premiumAmount} for all management roles
    '''
    with open(_premiumOverridesPath, 'w', encoding='utf-8') as f:
        json.dump(overrides, f, indent=2)


def _buildPremiumEditorDf() -> pd.DataFrame:
    '''
    Build the DataFrame used by st.data_editor for the Management Premiums Editor.
    Reads current managementPremiums (which already has overrides applied at module load).

    Returns:
    --------
    pd.DataFrame : One row per management role with Role and Premium columns
    '''
    rows = [{'Role': role, 'Premium': amount} for role, amount in managementPremiums.items()]
    return pd.DataFrame(rows)


def _buildEditorDf() -> pd.DataFrame:
    '''
    Build the DataFrame used by st.data_editor for the Level Bands Editor.
    Reads current salaryBands (which already has overrides applied at module load).

    Returns:
    --------
    pd.DataFrame : One row per level with Level, Title, Min, Median, Max columns
    '''
    rows = []
    for lvlName, band in salaryBands.items():
        lvlKey = band['levelKey']
        title = levelsData[lvlKey]['title']
        rows.append({
            'Level': lvlName,
            'Title': title,
            'Min': band['min'],
            'Median': band['median'],
            'Max': band['max'],
        })
    return pd.DataFrame(rows)


def _buildBandPreviewChart(df: pd.DataFrame) -> go.Figure:
    '''
    Build a horizontal bar chart previewing the edited salary bands.

    Parameters:
    -----------
    df : pd.DataFrame
        Edited band DataFrame from st.data_editor

    Returns:
    --------
    go.Figure : Plotly horizontal bar chart
    '''
    fig = go.Figure()
    for _, row in df.iterrows():
        lvlColor = colors['levels'].get(row['Level'], colors['accent'])
        width = max(0, int(row['Max']) - int(row['Min']))
        fig.add_trace(go.Bar(
            y=[row['Level']],
            x=[width],
            base=int(row['Min']),
            orientation='h',
            marker_color=lvlColor,
            opacity=0.8,
            name=row['Level'],
            showlegend=False,
            hovertemplate=(
                f'{row["Level"]} ({row["Title"]})<br>'
                f'Min: ${int(row["Min"]):,}<br>'
                f'Median: ${int(row["Median"]):,}<br>'
                f'Max: ${int(row["Max"]):,}<extra></extra>'
            ),
        ))
        # Median marker
        fig.add_trace(go.Scatter(
            x=[int(row['Median'])],
            y=[row['Level']],
            mode='markers',
            marker=dict(size=10, color=colors['accent'], symbol='diamond'),
            showlegend=False,
            hovertemplate=f'Median: ${int(row["Median"]):,}<extra></extra>',
        ))

    fig.update_layout(
        xaxis_title='Annual Salary ($)',
        height=260,
        margin=dict(t=20, b=20, l=10, r=10),
        barmode='overlay',
        **plotlyDarkLayout,
    )
    return fig


# ------------------------------------------------------------------------------- #
# -- Tab Renderers -- #
# ------------------------------------------------------------------------------- #

def _renderLevelBandsEditor() -> None:
    '''Render the Level Bands Editor tab.'''
    st.subheader('Level Bands Editor')
    st.markdown(
        'Edit the internal salary band boundaries. Changes are saved to `tools/bandOverrides.json` '
        'and applied on the next app restart (`streamlit run GUI.py`). '
        'Min/Median/Max must be set in ascending order.'
    )

    overrideActive = os.path.exists(_bandOverridesPath)
    if overrideActive:
        st.info('Active overrides are loaded from `tools/bandOverrides.json`. '
                'The values below reflect those overrides.')
    else:
        st.info('No overrides active. Values below are loaded directly from the source spreadsheet.')

    baseDf = _buildEditorDf()

    editedDf = st.data_editor(
        baseDf,
        column_config={
            'Level': st.column_config.TextColumn('Level', disabled=True),
            'Title': st.column_config.TextColumn('Title', disabled=True),
            'Min': st.column_config.NumberColumn('Min ($)', min_value=0, max_value=999999, step=1000, format='$%d'),
            'Median': st.column_config.NumberColumn('Median ($)', min_value=0, max_value=999999, step=1000, format='$%d'),
            'Max': st.column_config.NumberColumn('Max ($)', min_value=0, max_value=999999, step=1000, format='$%d'),
        },
        width='stretch',
        hide_index=True,
        key='bandEditorTable',
    )

    # Validate ordering
    validationErrors = []
    for _, row in editedDf.iterrows():
        lvlMin, lvlMed, lvlMax = int(row['Min']), int(row['Median']), int(row['Max'])
        if not (lvlMin <= lvlMed <= lvlMax):
            validationErrors.append(
                f'{row["Level"]}: Min (${lvlMin:,}) must be <= Median (${lvlMed:,}) <= Max (${lvlMax:,})'
            )

    if validationErrors:
        for err in validationErrors:
            st.error(err)

    # Band preview chart
    st.markdown('**Band Preview:**')
    st.plotly_chart(_buildBandPreviewChart(editedDf), width='stretch')

    # Save / Reset controls
    saveCol, resetCol, _ = st.columns([1, 1, 3])

    with saveCol:
        saveDisabled = bool(validationErrors)
        if st.button('Save Overrides', type='primary', disabled=saveDisabled, width='stretch'):
            overrides = {}
            for _, row in editedDf.iterrows():
                overrides[row['Level']] = {
                    'min': int(row['Min']),
                    'median': int(row['Median']),
                    'max': int(row['Max']),
                }
            _saveOverrides(overrides)
            st.success(
                'Overrides saved to `tools/bandOverrides.json`. '
                'Restart the app (`streamlit run GUI.py`) to apply to all calculations.'
            )

    with resetCol:
        resetDisabled = not os.path.exists(_bandOverridesPath)
        if st.button('Reset to Baseline', type='secondary', disabled=resetDisabled, width='stretch'):
            os.remove(_bandOverridesPath)
            st.success(
                'Overrides cleared. Restart the app to revert all calculations to the synthetic baseline values.'
            )
            st.rerun()

    st.caption(
        'Baseline values are loaded from the synthetic salary framework in `tools/syntheticData.py`. '
        'Overrides replace only the min/median/max for each level — experience range and level key are unchanged.'
    )

    st.divider()

    # -- Management Premiums Editor -- #
    st.subheader('Management Premiums Editor')
    st.markdown(
        'Edit the flat dollar premium added to base salary for each management role. '
        'Premiums are applied after relevance and complexity multipliers. '
        'Changes are saved to `tools/premiumOverrides.json` and applied on the next app restart.'
    )

    premiumOverrideActive = os.path.exists(_premiumOverridesPath)
    if premiumOverrideActive:
        st.info('Active premium overrides are loaded from `tools/premiumOverrides.json`.')
    else:
        st.info('No premium overrides active. Values below are loaded directly from the synthetic baseline.')

    premiumDf = _buildPremiumEditorDf()

    editedPremiumDf = st.data_editor(
        premiumDf,
        column_config={
            'Role': st.column_config.TextColumn('Role', disabled=True),
            'Premium': st.column_config.NumberColumn('Premium ($)', min_value=0, max_value=999999, step=500, format='$%d'),
        },
        width='stretch',
        hide_index=True,
        key='premiumEditorTable',
    )

    savePremCol, resetPremCol, _ = st.columns([1, 1, 3])

    with savePremCol:
        if st.button('Save Premium Overrides', type='primary', width='stretch', key='savePremiumBtn'):
            overrides = {row['Role']: int(row['Premium']) for _, row in editedPremiumDf.iterrows()}
            _savePremiumOverrides(overrides)
            st.success(
                'Premium overrides saved to `tools/premiumOverrides.json`. '
                'Restart the app (`streamlit run GUI.py`) to apply to all calculations.'
            )

    with resetPremCol:
        resetPremDisabled = not os.path.exists(_premiumOverridesPath)
        if st.button('Reset to Baseline', type='secondary', disabled=resetPremDisabled, width='stretch', key='resetPremiumBtn'):
            os.remove(_premiumOverridesPath)
            st.success(
                'Premium overrides cleared. Restart the app to revert to the synthetic baseline values.'
            )
            st.rerun()

    st.caption(
        'Baseline premium values are loaded from the synthetic salary framework in `tools/syntheticData.py`. '
        'Engineer premium is always $0 (individual contributor baseline).'
    )


# ------------------------------------------------------------------------------- #
# -- Main Render -- #
# ------------------------------------------------------------------------------- #

def renderMarketTools() -> None:
    '''
    Render the Market Analysis page with four tabs:
    Level Bands Editor, Scraper Runner, NN Classifier, and Validated Analysis.
    '''
    st.title('Market Analysis')

    bandsTab, scraperTab, nnTab, validatedTab = st.tabs([
        'Level Bands Editor',
        'Scraper Runner',
        'NN Classifier',
        'Validated Analysis',
    ])

    with bandsTab:
        _renderLevelBandsEditor()

    with scraperTab:
        renderDataScraper()

    with nnTab:
        renderNnShowcase()

    with validatedTab:
        renderValidatedMarketAnalysis()


# ---------------------------------------------------------------------- #
# -- Page Entry Point -- #
# ---------------------------------------------------------------------- #

renderMarketTools()
