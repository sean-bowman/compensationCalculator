# -- Compensation Calculator Page -- #

'''

Interactive salary calculator using the compensation formula
with real-time breakdown and band position visualization.

Author: Sean Bowman
Date:   02/24/2026

'''

# Third-party imports
import streamlit as st
import plotly.graph_objects as go

# Local imports
from auditUtils import (
    salaryBands, extendedBands, levelsData, experienceModifiers,
    managementPremiums, managementMinLevel, levelOrder,
    colors, plotlyDarkLayout, calculateSalary,
)

# ---------------------------------------------------------------------- #
# -- Compensation Calculator Page -- #
# ---------------------------------------------------------------------- #

def renderCompensationCalculator():

    '''
    
    Render the interactive salary calculator page.
    
    '''
    
    st.title('Compensation Calculator')
    st.markdown('---')

    col1, col2 = st.columns([1, 2])

    with col1:
        # -- Level selector as single-select pills with engineering titles -- #
        levelLabels = {
            k: f'{k} - {levelsData[v["levelKey"]]["title"]}'
            for k, v in salaryBands.items()
        }
        levelLabelList = list(levelLabels.values())
        labelToKey = {v: k for k, v in levelLabels.items()}

        selectedLevelLabel = st.pills(
            'Technical Level',
            levelLabelList,
            selection_mode='single',
            default=levelLabelList[0],
            help='Engineering level (I-V) based on experience and responsibilities',
        )
        if selectedLevelLabel is None:
            selectedLevelLabel = levelLabelList[0]
        level = labelToKey[selectedLevelLabel]

        # -- Band Position slider with Low/High labels -- #
        bandPosition = st.slider(
            'Band Position',
            min_value=0.0,
            max_value=1.0,
            value=0.5,
            step=0.01,
            help='Position within the proposed salary band for this level, from the low end to the high end',
        )

        # -- Experience Relevance slider with Low/High labels -- #
        relevance = st.slider(
            'Experience Relevance',
            min_value=1.0,
            max_value=1.05,
            value=1.025,
            step=0.005,
            format='%.3fx',
            help='Prior experience in the exact field the role is in. Low = limited direct experience, High = deep relevant background.',
        )

        # -- Experience Complexity slider with Low/High labels -- #
        complexity = st.slider(
            'Experience Complexity',
            min_value=1.0,
            max_value=1.05,
            value=1.025,
            step=0.005,
            format='%.3fx',
            help='Technical rigor of the role. Low = routine tasks, High = cutting-edge or safety-critical work.',
        )

        # -- Management role as single-select pills -- #
        managementRole = st.pills(
            'Management Role',
            list(managementPremiums.keys()),
            selection_mode='single',
            default='Engineer',
            help='Leadership role adds a flat premium on top of the base salary. Eligibility depends on level.',
        )
        if managementRole is None:
            managementRole = 'Engineer'

        # -- Global Modifier (renamed from Startup Multiple) -- #
        startupMultiple = st.slider(
            'Global Modifier',
            min_value=0.8,
            max_value=1.5,
            value=1.0,
            step=0.05,
            help='Overall scaling multiplier applied to the final calculated salary',
        )

        # Validation: check management role eligibility
        levelKey = salaryBands[level]['levelKey']
        if managementRole != 'Engineer':
            minLevelRequired = managementMinLevel[managementRole]
            minLevelIdx = levelOrder.index(minLevelRequired)
            currentLevelIdx = levelOrder.index(levelKey)
            if currentLevelIdx < minLevelIdx:
                st.warning(
                    f'{managementRole} role requires minimum Level {minLevelRequired}. '
                    f'Current level ({levelKey}) is not eligible.'
                )

    with col2:
        result = calculateSalary(level, bandPosition, relevance, complexity, managementRole, startupMultiple)

        # Prominent salary display using accent color
        st.markdown(
            f'<h1 style="text-align: center; color: {colors["accent"]};">'
            f'${result["finalSalary"]:,.2f}</h1>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p style="text-align: center; color: {colors["textMuted"]};">'
            f'Calculated Annual Salary</p>',
            unsafe_allow_html=True,
        )

        st.markdown('---')

        # Breakdown columns
        breakdownCol1, breakdownCol2 = st.columns(2)

        with breakdownCol1:
            st.markdown('**Calculation Breakdown:**')
            st.markdown(f'- Base Salary: \\${result["baseSalary"]:,.0f}')
            st.markdown(f'- Relevance Multiplier: {result["relevanceMultiplier"]}x')
            st.markdown(f'- Complexity Multiplier: {result["complexityMultiplier"]}x')
            st.markdown(f'- Adjusted Base: \\${result["adjustedBase"]:,.2f}')

        with breakdownCol2:
            st.markdown('**Premiums & Adjustments:**')
            st.markdown(f'- Management Premium: \\${result["managementPremium"]:,.0f}')
            st.markdown(f'- Subtotal: \\${result["totalBeforeMultiple"]:,.2f}')
            st.markdown(f'- Global Modifier: {result["startupMultiple"]}x')
            st.markdown(f'- **Final: \\${result["finalSalary"]:,.2f}**')

    # ---------------------------------------------------------------------- #
    # -- Salary Band Visualization (full width, below inputs/results) -- #
    # ---------------------------------------------------------------------- #

    st.markdown('---')
    st.markdown('**Salary Bands with Leadership Premiums:**')

    # Management role fill patterns to distinguish overlapping premiums
    mgmtPatterns = {
        'RE': {'shape': '/', 'fgcolor': colors['info'], 'bgcolor': 'rgba(0,0,0,0)', 'size': 8},
        'Lead': {'shape': '\\', 'fgcolor': colors['warning'], 'bgcolor': 'rgba(0,0,0,0)', 'size': 8},
        'Director': {'shape': 'x', 'fgcolor': colors['danger'], 'bgcolor': 'rgba(0,0,0,0)', 'size': 8},
    }

    figBars = go.Figure()

    # Base salary band for each level
    legendShown = {'base': False, 'RE': False, 'Lead': False, 'Director': False}

    for lvlName, lvlBand in salaryBands.items():
        lvlColor = colors['levels'][lvlName]
        lvlKey = lvlBand['levelKey']
        eligibility = levelsData[lvlKey]['managementEligibility']

        # Base band (min to max)
        figBars.add_trace(go.Bar(
            y=[lvlName],
            x=[lvlBand['max'] - lvlBand['min']],
            base=lvlBand['min'],
            orientation='h',
            marker_color=lvlColor,
            opacity=0.7,
            name='Base Band',
            showlegend=not legendShown['base'],
            legendgroup='base',
            hovertemplate=f'{lvlName} Base: ${lvlBand["min"]:,.0f} - ${lvlBand["max"]:,.0f}<extra></extra>',
        ))
        legendShown['base'] = True

        # Stack management premiums sequentially so each begins where the previous ends
        cumulativeBase = lvlBand['max']
        for role, premium in [('RE', managementPremiums['RE']),
                              ('Lead', managementPremiums['Lead']),
                              ('Director', managementPremiums['Director'])]:
            if eligibility[role]:
                pat = mgmtPatterns[role]
                figBars.add_trace(go.Bar(
                    y=[lvlName],
                    x=[premium],
                    base=cumulativeBase,
                    orientation='h',
                    marker=dict(
                        color='rgba(0,0,0,0)',
                        pattern=dict(
                            shape=pat['shape'],
                            fgcolor=pat['fgcolor'],
                            bgcolor=pat['bgcolor'],
                            size=pat['size'],
                            solidity=0.6,
                        ),
                        line=dict(color=pat['fgcolor'], width=1),
                    ),
                    name=role,
                    showlegend=not legendShown[role],
                    legendgroup=role,
                    hovertemplate=(
                        f'{lvlName} + {role}: +${premium:,.0f}<br>'
                        f'Range: ${cumulativeBase:,.0f} - ${cumulativeBase + premium:,.0f}<extra></extra>'
                    ),
                ))
                legendShown[role] = True
                cumulativeBase += premium

    # Calculated salary marker on the selected level
    figBars.add_trace(go.Scatter(
        x=[result['finalSalary']],
        y=[level],
        mode='markers+text',
        marker=dict(size=14, color=colors['accent'], symbol='diamond'),
        text=[f'${result["finalSalary"]:,.0f}'],
        textposition='top center',
        textfont=dict(color=colors['accent'], size=11),
        name='Calculated Salary',
        showlegend=True,
    ))

    # Dashed vertical line at calculated salary
    figBars.add_vline(
        x=result['finalSalary'],
        line_dash='dash',
        line_color=colors['accent'],
        opacity=0.5,
    )

    figBars.update_layout(
        height=400,
        xaxis_title='Salary ($)',
        xaxis_tickformat='$,.0f',
        barmode='stack',
        **plotlyDarkLayout,
    )
    # Override legend positioning after dark layout defaults
    figBars.update_layout(legend=dict(orientation='h', yanchor='bottom', y=1.02))
    st.plotly_chart(figBars, width='stretch')

    st.caption(
        'Base bands from the compensation structural proposal. '
        'Leadership premiums (RE +4K, Lead +12K, Director +36K) shown where eligible. '
        'Diamond marker shows calculated salary for current inputs.'
    )


# Module-level execution for st.Page() compatibility
renderCompensationCalculator()
