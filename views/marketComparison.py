
# -- Market Comparison Dashboard Page -- #

'''

Compare the compensation bands against a synthetic market survey
of fictional job listings across fictional aerospace companies,
with geographic adjustment visualizations.

Author: Sean Bowman
Date:   02/23/2026

'''

# Third-party imports
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Local imports
from auditUtils import (
    salaryBands, blsBenchmarks, colors,
    plotlyDarkLayout, filterMarketBenchmarks, surveyCompanies,
    surveyDisciplines, renderDatasetSelector,
)

# ---------------------------------------------------------------------- #
# -- Market Comparison Page -- #
# ---------------------------------------------------------------------- #

def renderMarketComparison():

    '''

    Render the market comparison dashboard.
    Uses the dataset selector to allow switching between
    survey, scraped, merged, or imported datasets.

    '''
    
    st.title('Market Comparison Dashboard')
    st.markdown('Compare the compensation bands against the synthetic market survey dataset.')
    st.markdown('---')

    surveyDf = renderDatasetSelector()
    companies = surveyCompanies(surveyDf)
    disciplines = surveyDisciplines(surveyDf)

    # -- Filters -- #
    filterCol1, filterCol2, filterCol3 = st.columns(3)

    with filterCol1:
        selectedCompanies = st.multiselect('Companies', companies, default=companies)
    with filterCol2:
        selectedDiscipline = st.selectbox('Discipline', ['All'] + disciplines)
    with filterCol3:
        expRange = st.slider('Experience Range (years)', 0, 20, (0, 15))

    # Apply filters
    filtered = filterMarketBenchmarks(
        surveyDf,
        companies=selectedCompanies if len(selectedCompanies) < len(companies) else None,
        discipline=selectedDiscipline if selectedDiscipline != 'All' else None,
    )
    filtered = filtered[
        (filtered['Estimated'] >= expRange[0]) &
        (filtered['Estimated'] <= expRange[1])
    ]

    if filtered.empty:
        st.warning('No data matches the current filters. Try broadening your selection.')
        return

    # -- Summary metrics -- #
    metricCols = st.columns(4)
    with metricCols[0]:
        st.metric('Listings', f'{len(filtered):,}')
    with metricCols[1]:
        avgSalary = filtered['Midpoint'].mean()
        st.metric('Avg Midpoint', f'${avgSalary:,.0f}')
    with metricCols[2]:
        st.metric('Min Posted', f'${filtered["Min"].min():,.0f}')
    with metricCols[3]:
        st.metric('Max Posted', f'${filtered["Max"].max():,.0f}')

    st.markdown('---')

    # -- Chart 1: proposed bands vs market scatter -- #
    st.subheader('Proposed Bands vs Market Data by Experience')

    figMarket = go.Figure()

    # Shaded proposed band regions
    for bandName, band in salaryBands.items():
        color = colors['levels'][bandName]
        minYrs = band['minYrs']
        maxYrs = band['maxYrs'] or 15

        figMarket.add_shape(
            type='rect',
            x0=minYrs, x1=maxYrs,
            y0=band['min'], y1=band['max'],
            fillcolor=color,
            opacity=0.15,
            line=dict(width=1, color=color),
            layer='below',
        )

        figMarket.add_annotation(
            x=(minYrs + min(maxYrs, 15)) / 2,
            y=band['max'] + 2000,
            text=bandName,
            showarrow=False,
            font=dict(size=10, color=color),
        )

    # Market data scatter by company
    for company in sorted(filtered['Company'].unique()):
        companyData = filtered[filtered['Company'] == company]
        color = colors['companies'][company]

        figMarket.add_trace(go.Scatter(
            x=companyData['Estimated'],
            y=companyData['Midpoint'],
            mode='markers',
            name=company,
            marker=dict(size=8, color=color, opacity=0.7),
            hovertemplate=(
                f'<b>{company}</b><br>'
                'Experience: %{x} yrs<br>'
                'Midpoint: $%{y:,.0f}<br>'
                '<extra></extra>'
            ),
        ))

    # Benchmark median reference (synthetic placeholder figure)
    figMarket.add_hline(
        y=blsBenchmarks['median'],
        line_dash='dash',
        line_color=colors['textMuted'],
        annotation_text=f'Benchmark Median: ${blsBenchmarks["median"]:,.0f}',
        annotation_font_color=colors['textSecondary'],
    )

    figMarket.update_layout(
        xaxis_title='Years of Experience',
        xaxis_range=[expRange[0] - 0.5, expRange[1] + 0.5],
        yaxis_title='Salary ($)',
        height=550,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, bgcolor='rgba(0,0,0,0)'),
        **{k: v for k, v in plotlyDarkLayout.items() if k != 'legend'},
    )

    st.plotly_chart(figMarket, width='stretch')

    # -- Chart 2: Box plots by company with proposed band -- #
    st.subheader('Salary Distribution by Company')

    # Build proposed data points from all level band values (min, median, max)
    # so the box plot shows the proposed spread
    proposedPoints = []
    for band in salaryBands.values():
        proposedPoints.extend([band['min'], band['median'], band['max']])

    proposedDf = pd.DataFrame({
        'Company': ['Proposed'] * len(proposedPoints),
        'Midpoint': proposedPoints,
    })

    # Append the proposed series to the filtered data for a combined box plot
    combinedDf = pd.concat([
        filtered[['Company', 'Midpoint']],
        proposedDf,
    ], ignore_index=True)

    # Build color map with the proposed series in the accent color
    companyColors = dict(colors['companies'])
    companyColors['Proposed'] = colors['accent']

    figBox = px.box(
        combinedDf,
        x='Company',
        y='Midpoint',
        color='Company',
        color_discrete_map=companyColors,
        category_orders={'Company': sorted(filtered['Company'].unique().tolist()) + ['Proposed']},
    )

    figBox.update_layout(
        showlegend=False,
        height=500,
        xaxis_tickangle=-45,
        yaxis_title='Salary ($)',
        **plotlyDarkLayout,
    )
    st.plotly_chart(figBox, width='stretch')

    st.caption(
        'The Proposed box is derived from the min, median, and max of all five proposed salary bands.'
    )

# ---------------------------------------------------------------------- #
# -- Module-Level Execution -- #
# ---------------------------------------------------------------------- #

renderMarketComparison()
