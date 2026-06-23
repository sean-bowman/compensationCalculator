
# -- Market Data Explorer Page -- #

'''

Browse and analyze job listings from the synthetic compensation survey
with filtering, salary distribution, and heatmap visualizations.

Author: Sean Bowman
Date:   02/23/2026

'''

# Third-party imports
import streamlit as st
import plotly.express as px

# Local imports
from auditUtils import (
    colors, plotlyDarkLayout, surveyCompanies,
    surveyDisciplines, surveyStates, renderDatasetSelector,
)

# ---------------------------------------------------------------------- #
# -- Market Data Explorer Page -- #
# ---------------------------------------------------------------------- #

def renderMarketDataExplorer():

    '''

    Render the market data explorer page.
    Uses the dataset selector to allow switching between
    survey, scraped, merged, or imported datasets.

    '''
    
    st.title('Market Data Explorer')
    st.markdown('Browse and analyze job listings from the synthetic compensation survey.')
    st.markdown('---')

    surveyDf = renderDatasetSelector()
    companies = surveyCompanies(surveyDf)
    disciplines = surveyDisciplines(surveyDf)
    states = surveyStates(surveyDf)

    # -- Filters -- #
    fCol1, fCol2, fCol3, fCol4 = st.columns(4)

    with fCol1:
        filterCompanies = st.multiselect(
            'Companies', companies, default=companies, key='explorer_companies',
        )
    with fCol2:
        filterDiscipline = st.selectbox(
            'Discipline', ['All'] + disciplines, key='explorer_disc',
        )
    with fCol3:
        filterState = st.selectbox('State', ['All'] + states, key='explorer_state')
    with fCol4:
        filterExpRange = st.slider(
            'Experience (years)', 0, 20, (0, 15), key='explorer_exp',
        )

    # Apply filters
    filtered = surveyDf.copy()
    if len(filterCompanies) < len(companies):
        filtered = filtered[filtered['Company'].isin(filterCompanies)]
    if filterDiscipline != 'All':
        filtered = filtered[
            filtered['Discipline'].str.contains(filterDiscipline, case=False, na=False)
        ]
    if filterState != 'All':
        filtered = filtered[filtered['State'] == filterState]
    filtered = filtered[
        (filtered['Estimated'] >= filterExpRange[0]) &
        (filtered['Estimated'] <= filterExpRange[1])
    ]

    # -- Summary metrics -- #
    if not filtered.empty:
        metricCols = st.columns(4)
        with metricCols[0]:
            st.metric('Listings', f'{len(filtered):,}')
        with metricCols[1]:
            st.metric('Avg Salary', f'${filtered["Midpoint"].mean():,.0f}')
        with metricCols[2]:
            st.metric('Min', f'${filtered["Midpoint"].min():,.0f}')
        with metricCols[3]:
            st.metric('Max', f'${filtered["Midpoint"].max():,.0f}')

    st.markdown('---')

    # -- Data table -- #
    displayCols = [
        'Company', 'Listing', 'Seniority', 'Estimated', 'Location',
        'Discipline', 'PositionType', 'Min', 'Max', 'Midpoint', 'Vlvl',
    ]

    availableCols = [c for c in displayCols if c in filtered.columns]
    st.dataframe(
        filtered[availableCols].reset_index(drop=True),
        width='stretch',
        height=400,
    )

    st.markdown('---')

    # -- Charts -- #
    if not filtered.empty:
        chartCol1, chartCol2 = st.columns(2)

        with chartCol1:
            st.subheader('Salary Distribution')
            figHist = px.histogram(
                filtered,
                x='Midpoint',
                nbins=30,
                color='Company',
                color_discrete_map=colors['companies'],
                title='Salary Distribution',
                labels={'Midpoint': 'Salary ($)'},
            )
            figHist.update_layout(height=400, barmode='stack', **plotlyDarkLayout)
            st.plotly_chart(figHist, width='stretch')

        with chartCol2:
            st.subheader('Experience vs Salary')
            figScatter = px.scatter(
                filtered,
                x='Estimated',
                y='Midpoint',
                color='Company',
                color_discrete_map=colors['companies'],
                title='Experience vs Salary by Company',
                labels={'Estimated': 'Years of Experience', 'Midpoint': 'Salary ($)'},
                hover_data=['Listing', 'Discipline'],
            )
            figScatter.update_layout(height=400, **plotlyDarkLayout)
            st.plotly_chart(figScatter, width='stretch')

        # -- Heatmap: Company x Discipline -- #
        st.subheader('Average Salary: Company x Discipline')

        heatData = filtered.groupby(['Company', 'Discipline'])['Midpoint'].mean().reset_index()
        if not heatData.empty:
            heatPivot = heatData.pivot_table(
                index='Company',
                columns='Discipline',
                values='Midpoint',
                aggfunc='mean',
            )
            if not heatPivot.empty:
                figHeat = px.imshow(
                    heatPivot.values,
                    x=heatPivot.columns.tolist(),
                    y=heatPivot.index.tolist(),
                    color_continuous_scale='Viridis',
                    title='Average Salary Heatmap',
                    labels=dict(color='Avg Salary ($)'),
                    aspect='auto',
                )
                figHeat.update_layout(height=400, **plotlyDarkLayout)
                st.plotly_chart(figHeat, width='stretch')
    else:
        st.warning('No data matches the current filters.')

# ---------------------------------------------------------------------- #
# -- Module-Level Execution -- #
# ---------------------------------------------------------------------- #

renderMarketDataExplorer()
