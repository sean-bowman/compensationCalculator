
# -- Levels Overview Page -- #

'''

Engineering levels framework overview with salary bands,
management role eligibility matrix, and band visualizations.

Author: Sean Bowman
Date:   02/24/2026

'''

# Third-party imports
import streamlit as st
import plotly.graph_objects as go

# Local imports
from auditUtils import (
    levelsData, salaryBands, extendedBands, levelOrder,
    blsBenchmarks, colors, plotlyDarkLayout,
)

# ---------------------------------------------------------------------- #
# -- Levels Overview Page -- #
# ---------------------------------------------------------------------- #

def renderLevelsOverview():

    '''
    
    Render the engineering levels overview page.
    
    '''
    
    st.title('Engineering Levels Framework')
    st.markdown('---')

    # -- Level detail cards -- #
    for levelKey, levelInfo in levelsData.items():
        bandName = list(salaryBands.keys())[levelOrder.index(levelKey)]
        band = salaryBands[bandName]

        with st.expander(
            f'Level {levelKey} - {levelInfo["title"]}',
            expanded=False,
        ):
            col1, col2 = st.columns([2, 1])

            with col1:
                st.markdown(f'**Experience:** {levelInfo["experienceLabel"]}')
                st.markdown(f'**Primary Focus:** {levelInfo["primaryFocus"]}')
                st.markdown(f'**Supervision:** {levelInfo["supervision"]}')
                st.markdown(
                    f'**Leadership Role:** {levelInfo["leadershipRole"]} - '
                    f'{levelInfo["leadershipDescription"]}'
                )

                st.markdown('**Key Duties:**')
                for duty in levelInfo['keyDuties']:
                    st.markdown(f'- {duty}')

                st.markdown('**Learning Goals:**')
                for goal in levelInfo['learningGoals']:
                    st.markdown(f'- {goal}')

                st.markdown('**General Goals:**')
                for goal in levelInfo['generalGoals']:
                    st.markdown(f'- {goal}')

            with col2:
                st.markdown('**Compensation Band:**')
                st.markdown(f'- Min: \\${band["min"]:,.0f}')
                st.markdown(f'- Median: \\${band["median"]:,.0f}')
                st.markdown(f'- Max: \\${band["max"]:,.0f}')

                extended = extendedBands[bandName]
                st.markdown(f'- Extended Max: \\${extended["extendedMax"]:,.0f}')

                st.markdown('**Management Eligibility:**')
                eligibility = levelInfo['managementEligibility']
                for role, eligible in eligibility.items():
                    marker = 'Yes' if eligible else 'No'
                    st.markdown(f'- {role}: {marker}')

    # -- Salary bands chart -- #
    st.markdown('---')
    st.markdown('**Salary Bands by Level**')

    figBands = go.Figure()

    bandNames = list(salaryBands.keys())
    legendShown = {'standard': False, 'extended': False}

    for bandName in bandNames:
        band = salaryBands[bandName]
        extended = extendedBands[bandName]
        color = colors['levels'][bandName]

        # Extended range (lighter, hatched)
        figBands.add_trace(go.Bar(
            name='Extended Range',
            x=[bandName],
            y=[extended['extendedMax'] - band['max']],
            base=band['max'],
            marker_color=color,
            opacity=0.3,
            showlegend=not legendShown['extended'],
            legendgroup='extended',
            hovertemplate=f'Extended Max: ${extended["extendedMax"]:,.0f}<extra></extra>',
        ))
        legendShown['extended'] = True

        # Standard range
        figBands.add_trace(go.Bar(
            name='Standard Band',
            x=[bandName],
            y=[band['max'] - band['min']],
            base=band['min'],
            marker_color=color,
            opacity=0.8,
            showlegend=not legendShown['standard'],
            legendgroup='standard',
            hovertemplate=(
                f'Min: ${band["min"]:,.0f}<br>'
                f'Median: ${band["median"]:,.0f}<br>'
                f'Max: ${band["max"]:,.0f}<extra></extra>'
            ),
        ))
        legendShown['standard'] = True

        # Median marker
        figBands.add_trace(go.Scatter(
            x=[bandName],
            y=[band['median']],
            mode='markers',
            marker=dict(size=12, color=colors['bg'], line=dict(width=2, color=color)),
            showlegend=False,
            hovertemplate=f'Median: ${band["median"]:,.0f}<extra></extra>',
        ))

    # Benchmark median reference line (synthetic placeholder figure)
    figBands.add_hline(
        y=blsBenchmarks['median'],
        line_dash='dash',
        line_color=colors['textMuted'],
        annotation_text=f'Benchmark Median: ${blsBenchmarks["median"]:,.0f}',
        annotation_position='top right',
        annotation_font_color=colors['textSecondary'],
    )

    figBands.update_layout(
        yaxis_title='Annual Salary ($)',
        xaxis_title='Level',
        barmode='overlay',
        height=500,
        showlegend=True,
        **plotlyDarkLayout,
    )
    # Override legend positioning after dark layout defaults
    figBands.update_layout(legend=dict(orientation='h', yanchor='bottom', y=1.02))

    st.plotly_chart(figBands, width='stretch')

    st.caption(
        'Standard Band is the proposed min-max salary range per level. '
        'Extended Range reflects the maximum achievable with experience modifiers '
        '(relevance and complexity multipliers applied to the base salary). '
        'Circle markers indicate band median. '
        'Dashed line shows the benchmark median (a synthetic placeholder figure).'
    )

# Module-level execution for st.Page() compatibility
renderLevelsOverview()
