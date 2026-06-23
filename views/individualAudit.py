
# -- Individual Audit Page -- #

'''

Employee compensation audit tool that checks salary against
the salary bands, validates management role eligibility, and
compares to market benchmarks.

Author: Sean Bowman
Date:   02/23/2026

'''

# Standard library imports
import os
import tempfile
from datetime import date

# Third-party imports
import streamlit as st
import plotly.graph_objects as go
from fpdf import FPDF

# Local imports
from auditUtils import (
    levelsData, salaryBands, extendedBands, levelOrder, colors, plotlyDarkLayout,
    managementPremiums, calculateSalary,
    auditEmployee, filterMarketBenchmarks, renderDatasetSelector,
)

# ---------------------------------------------------------------------- #
# -- PDF Report Generator -- #
# ---------------------------------------------------------------------- #

def _drawDarkPageBg(pdf):

    '''
    
    Fill the current page with the dark background color.
    
    '''

    pdf.set_fill_color(51, 51, 51)  # #333333
    pdf.rect(0, 0, 210, 297, style='F')

def _drawFooter(pdf):

    '''
    
    Draw footer text at the bottom of the current page.
    
    '''

    pdf.set_y(-10)
    pdf.set_font('Helvetica', 'I', 6)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 3, 'Compensation Structure Audit Tool  |  '
             'Bands: synthetic salary framework  |  '
             'Market: synthetic survey dataset',
             new_x='LMARGIN', new_y='NEXT', align='C')

# Module-level kaleido scope (reuse to avoid spawning multiple subprocesses)
_kaleidoScope = None

def _resolveKaleidoScope():

    '''
    
    Get or create the shared kaleido PlotlyScope instance.
    
    '''

    global _kaleidoScope
    if _kaleidoScope is None:
        from kaleido.scopes.plotly import PlotlyScope
        _kaleidoScope = PlotlyScope()
    return _kaleidoScope

def _saveFigImage(fig, tmpFiles, width=800, height=300) -> str | None:
    
    '''

    Export a plotly figure to a temp PNG file. Returns path or None.
    On failure, resets the kaleido scope and retries with a simplified
    figure (HTML stripped from indicator titles) as a fallback.

    Parameters:
    -----------
    fig : plotly.graph_objects.Figure
        The figure to export.
    tmpFiles : list
        A list to append the temp file path to for later cleanup.
    width : int
        Image width in pixels.
    height : int
        Image height in pixels.

    Returns:
    --------
    str or None : File path of the saved image, or None if export failed.

    '''

    import re
    global _kaleidoScope

    def _doTransform(figDict):

        '''
        
        Run the kaleido transform and write to a temp file.
        
        '''

        scope = _resolveKaleidoScope()
        imgBytes = scope.transform(
            figDict, format='png', width=width, height=height, scale=2,
        )
        tmpDir = tempfile.gettempdir()
        tmpPath = os.path.join(tmpDir, f'audit_chart_{len(tmpFiles)}.png')
        
        with open(tmpPath, 'wb') as f:
            f.write(imgBytes)

        tmpFiles.append(tmpPath)

        return tmpPath

    # Attempt 1: render as-is
    try:
        return _doTransform(fig.to_dict())
    except Exception:
        pass

    # Reset scope (the previous error may have corrupted it)
    _kaleidoScope = None

    # Attempt 2: retry with fresh scope
    try:
        return _doTransform(fig.to_dict())
    except Exception:
        pass

    # Reset scope again
    _kaleidoScope = None

    # Attempt 3: simplify figure (strip HTML from titles, remove subtitle)
    try:
        simplified = go.Figure(fig.to_dict())
        for trace in simplified.data:
            if hasattr(trace, 'title') and trace.title is not None:
                rawText = trace.title.text or ''
                cleanText = re.sub(r'<br>.*', '', rawText, flags=re.DOTALL)
                trace.title.text = cleanText
        return _doTransform(simplified.to_dict())
    except Exception as e:
        import traceback
        traceback.print_exc()
        return None

def _applyLightLayout(fig):

    '''

    Return an independent copy of a plotly figure with a light/print-friendly
    layout. Uses to_dict() serialization to avoid deepcopy shared-state issues.

    Parameters:
    -----------
    fig : plotly.graph_objects.Figure
        The figure to apply the light layout to.

    Returns:
    --------
    plotly.graph_objects.Figure
        A new figure instance with the light layout applied.

    '''

    lightFig = go.Figure(fig.to_dict())
    lightFig.update_layout(
        paper_bgcolor='#FFFFFF',
        plot_bgcolor='#F5F5F5',
        font_color='#333333',
    )
    # Update axis colors if present
    lightFig.update_xaxes(gridcolor='#DDDDDD', zerolinecolor='#CCCCCC')
    lightFig.update_yaxes(gridcolor='#DDDDDD', zerolinecolor='#CCCCCC')

    # Update indicator-specific text colors (gauge number, delta, title)
    for trace in lightFig.data:
        if hasattr(trace, 'number') and trace.number is not None:
            trace.number.font.color = '#333333'
        if hasattr(trace, 'title') and trace.title is not None:
            trace.title.font.color = '#444444'
        if hasattr(trace, 'gauge') and trace.gauge is not None:
            trace.gauge.bgcolor = '#E8E8E8'
            if trace.gauge.axis is not None:
                trace.gauge.axis.tickcolor = '#666666'
            # Lighten gauge step colors for print
            if trace.gauge.steps:
                lightSteps = ['#C8E6C9', '#A5D6A7', '#E8E0B0']
                for i, step in enumerate(trace.gauge.steps):
                    if i < len(lightSteps):
                        step.color = lightSteps[i]

    return lightFig

def _generateAuditPdf(
    displayName, displayLevel, displaySalary, displayMgmtRole,
    displayRelevance, displayComplexity, discipline, yearsExperience,
    results, marketData, figGauge, figMgmtGauge=None, figMkt=None,
    lightMode=False,
):
    
    '''

    Generate a PDF report of the audit results.
    Targets 1 page; spills to 2 if market chart is included.

    Parameters:
    -----------
    lightMode : bool
        If True, generate a light-themed (print-friendly) PDF.

    Returns:
    --------
    bytes : PDF file content

    '''

    if lightMode:
        textPrimary = (30, 30, 30)
        textSecondary = (80, 80, 80)
        textMuted = (120, 120, 120)
        accentRgb = (44, 120, 16)
        lineColor = (200, 200, 200)
        successRgb = (22, 140, 60)
        warningRgb = (180, 120, 0)
        dangerRgb = (200, 40, 40)
    else:
        textPrimary = (255, 255, 255)
        textSecondary = (200, 200, 200)
        textMuted = (150, 150, 150)
        accentRgb = (171, 208, 56)
        lineColor = (100, 100, 100)
        successRgb = (34, 197, 94)
        warningRgb = (245, 158, 11)
        dangerRgb = (239, 68, 68)

    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    pdf.set_margin(8)
    tmpFiles = []

    # ================================================================== #
    # -- Page 1 -- #
    # ================================================================== #
    pdf.add_page()
    if not lightMode:
        _drawDarkPageBg(pdf)

    # -- Header -- #
    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(*textPrimary)
    pdf.cell(0, 8, 'Compensation Audit Report', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*textMuted)
    reportTitle = displayName if displayName else 'Employee Audit'
    pdf.cell(0, 4, f'Compensation Audit  |  {reportTitle}  |  {date.today().strftime("%B %d, %Y")}', new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.ln(3)

    # -- Employee Details (2-column grid) -- #
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(*accentRgb)
    pdf.cell(0, 5, 'Employee Details', new_x='LMARGIN', new_y='NEXT')
    pdf.set_draw_color(*lineColor)
    pdf.line(8, pdf.get_y(), 202, pdf.get_y())
    pdf.ln(1.5)

    levelTitle = levelsData[displayLevel]['title']
    detailPairs = [
        ('Name', displayName or 'Not specified', 'Level', f'{displayLevel} - {levelTitle}'),
        ('Mgmt Role', displayMgmtRole if displayMgmtRole != 'None' else 'Engineer', 'Experience', f'{yearsExperience:.1f} yrs'),
        ('Discipline', discipline, 'Salary', f'${displaySalary:,.0f}'),
        ('Relevance', f'{displayRelevance:.3f}x', 'Complexity', f'{displayComplexity:.3f}x'),
    ]
    for labelL, valL, labelR, valR in detailPairs:
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_text_color(*textSecondary)
        pdf.cell(28, 4, f'{labelL}:', new_x='RIGHT')
        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(*textPrimary)
        pdf.cell(65, 4, valL, new_x='RIGHT')
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_text_color(*textSecondary)
        pdf.cell(28, 4, f'{labelR}:', new_x='RIGHT')
        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(*textPrimary)
        pdf.cell(0, 4, valR, new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)

    # -- Audit Result -- #
    status = results['complianceStatus']
    statusConfig = {
        'In Band': ('[PASS]', successRgb),
        'Below Band': ('[FAIL]', dangerRgb),
        'Above Band': ('[FAIL]', dangerRgb),
        'Extended Range': ('[WARNING]', warningRgb),
    }
    statusLabel, statusColor = statusConfig[status]

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(*accentRgb)
    pdf.cell(30, 5, 'Audit Result', new_x='RIGHT')
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(*statusColor)
    pdf.cell(0, 5, f'{statusLabel} {status}', new_x='LMARGIN', new_y='NEXT')
    pdf.line(8, pdf.get_y(), 202, pdf.get_y())
    pdf.ln(1.5)

    # -- Band + Salary side by side -- #
    yStart = pdf.get_y()
    delta = results['salaryVsMedian']
    direction = 'above' if delta > 0 else 'below'

    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(*textPrimary)
    pdf.cell(8)
    pdf.cell(87, 4,
             f'Band: {results["bandName"]}   |   '
             f'Min: ${results["bandMin"]:,.0f}   |   '
             f'Median: ${results["bandMedian"]:,.0f}   |   '
             f'Max: ${results["bandMax"]:,.0f}   |   '
             f'Ext: ${results["extendedMax"]:,.0f}',
             new_x='LMARGIN', new_y='NEXT')
    pdf.cell(8)
    pdf.cell(87, 4,
             f'Expected Median: ${results["expectedMedian"]:,.0f}   |   '
             f'vs Median: ${abs(delta):,.0f} {direction}   |   '
             f'Band Percentile: {results["salaryPercentInBand"]:.1f}%',
             new_x='LMARGIN', new_y='NEXT')

    # -- Management (inline if applicable) -- #
    hasMgmt = displayMgmtRole not in ('None', 'Engineer')
    if hasMgmt:
        mgmtPremium = managementPremiums[displayMgmtRole]
        bandName = results['bandName']
        mgmtCalcResult = calculateSalary(
            bandName, 'Median', displayRelevance, displayComplexity,
            displayMgmtRole,
        )
        mgmtExpectedMedian = mgmtCalcResult['finalSalary']
        mgmtDelta = displaySalary - mgmtExpectedMedian
        pdf.cell(8)
        pdf.cell(0, 4,
                 f'Mgmt: {displayMgmtRole} (+${mgmtPremium:,})   |   '
                 f'Mgmt Expected: ${mgmtExpectedMedian:,.0f}   |   '
                 f'vs Mgmt: ${abs(mgmtDelta):,.0f} {"above" if mgmtDelta > 0 else "below"}',
                 new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)

    # -- Issues -- #
    if results['issues']:
        pdf.set_font('Helvetica', 'B', 8)
        pdf.set_text_color(*warningRgb)
        for issue in results['issues']:
            pdf.cell(8)
            pdf.multi_cell(184, 4, f'Issue: {issue}', new_x='LMARGIN', new_y='NEXT')
    else:
        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(*successRgb)
        pdf.cell(8)
        pdf.cell(0, 4, 'No issues found.', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(2)

    # -- Gauge chart(s) -- #
    try:
        # Always create independent copies to prevent shared state issues
        if lightMode:
            exportGauge = _applyLightLayout(figGauge)
            exportMgmtGauge = _applyLightLayout(figMgmtGauge) if figMgmtGauge else None
        else:
            exportGauge = go.Figure(figGauge.to_dict())
            exportMgmtGauge = go.Figure(figMgmtGauge.to_dict()) if figMgmtGauge else None
        if hasMgmt and exportMgmtGauge is not None:
            pathL = _saveFigImage(exportGauge, tmpFiles, width=550, height=250)
            pathR = _saveFigImage(exportMgmtGauge, tmpFiles, width=550, height=250)
            gaugeY = pdf.get_y()
            if pathL:
                pdf.image(pathL, x=8, y=gaugeY, w=95)
            if pathR:
                pdf.image(pathR, x=105, y=gaugeY, w=95)
            pdf.set_y(gaugeY + 47)
        else:
            path = _saveFigImage(exportGauge, tmpFiles, width=700, height=260)
            if path:
                pdf.image(path, x=20, y=pdf.get_y(), w=170)
                pdf.set_y(pdf.get_y() + 50)
    except Exception as e:
        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(*dangerRgb)
        pdf.cell(0, 4, f'Chart export error: {e}', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(1)

    # -- Market Context -- #
    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(*accentRgb)
    pdf.cell(0, 5, 'Market Context', new_x='LMARGIN', new_y='NEXT')
    pdf.line(8, pdf.get_y(), 202, pdf.get_y())
    pdf.ln(1.5)

    hasMarket = marketData is not None and not marketData.empty
    if hasMarket:
        marketAvg = marketData['Midpoint'].mean()
        marketMin = marketData['Min'].min()
        marketMax = marketData['Max'].max()
        marketCount = len(marketData)
        vsMkt = displaySalary - marketAvg
        expLow = max(0, yearsExperience - 2)
        expHigh = yearsExperience + 2
        discLabel = discipline if discipline != 'Other' else 'All Disciplines'

        pdf.set_font('Helvetica', '', 7)
        pdf.set_text_color(*textMuted)
        pdf.cell(0, 3.5, f'Filter: {discLabel}, {expLow:.0f}-{expHigh:.0f} yrs exp', new_x='LMARGIN', new_y='NEXT')

        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(*textPrimary)
        pdf.cell(0, 4,
                 f'Listings: {marketCount}   |   '
                 f'Avg: ${marketAvg:,.0f}   |   '
                 f'Range: ${marketMin:,.0f}-${marketMax:,.0f}   |   '
                 f'vs Market: ${vsMkt:+,.0f}',
                 new_x='LMARGIN', new_y='NEXT')

        # Companies inline
        companyCounts = marketData['Company'].value_counts()
        companyStr = '   '.join(f'{c}: {n}' for c, n in companyCounts.items())
        pdf.set_font('Helvetica', '', 7)
        pdf.set_text_color(*textSecondary)
        pdf.multi_cell(0, 3.5, f'Companies: {companyStr}', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)

        # Market chart - check if it fits on this page
        try:
            if lightMode and figMkt:
                exportMkt = _applyLightLayout(figMkt)
            elif figMkt:
                exportMkt = go.Figure(figMkt.to_dict())
            else:
                exportMkt = None
            spaceRemaining = 287 - pdf.get_y()  # 297 - 10mm bottom margin
            if exportMkt is not None and spaceRemaining >= 55:
                path = _saveFigImage(exportMkt, tmpFiles, width=900, height=320)
                if path:
                    pdf.image(path, x=8, y=pdf.get_y(), w=194)
            elif exportMkt is not None:
                _drawFooter(pdf)
                pdf.add_page()
                if not lightMode:
                    _drawDarkPageBg(pdf)

                pdf.set_font('Helvetica', 'B', 9)
                pdf.set_text_color(*accentRgb)
                pdf.cell(0, 5, 'Market Context (continued)', new_x='LMARGIN', new_y='NEXT')
                pdf.line(8, pdf.get_y(), 202, pdf.get_y())
                pdf.ln(2)

                path = _saveFigImage(exportMkt, tmpFiles, width=900, height=400)
                if path:
                    pdf.image(path, x=8, w=194)
        except Exception as e:
            pdf.set_font('Helvetica', '', 8)
            pdf.set_text_color(*dangerRgb)
            pdf.cell(0, 4, f'Market chart error: {e}', new_x='LMARGIN', new_y='NEXT')
    else:
        pdf.set_font('Helvetica', '', 8)
        pdf.set_text_color(*textMuted)
        pdf.cell(0, 4, 'No matching market data found for the specified filters.', new_x='LMARGIN', new_y='NEXT')

    _drawFooter(pdf)

    # Cleanup temp files
    for f in tmpFiles:
        try:
            os.unlink(f)
        except OSError:
            pass

    return bytes(pdf.output())

# ---------------------------------------------------------------------- #
# -- Individual Audit Page -- #
# ---------------------------------------------------------------------- #

def renderIndividualAudit():

    '''

    Render the individual employee audit tool.
    Market context section uses the dataset selector to allow
    switching between survey, scraped, merged, or imported datasets.

    '''
    
    st.title('Individual Compensation Audit')
    st.markdown('Evaluate an employee\'s compensation against the salary bands and market data.')
    st.markdown('---')

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader('Employee Details')

        employeeName = st.text_input('Employee Name (optional)', '')
        level = st.selectbox(
            'Technical Level',
            levelOrder,
            format_func=lambda x: f'Level {x} - {levelsData[x]["title"]}',
        )
        managementRole = st.selectbox(
            'Management Role',
            ['None', 'RE', 'Lead', 'Director', 'Chief'],
        )
        yearsExperience = st.number_input(
            'Years of Experience',
            min_value=0.0,
            max_value=40.0,
            value=3.0,
            step=0.5,
        )
        currentSalary = st.number_input(
            'Current Annual Salary ($)',
            min_value=0,
            max_value=500000,
            value=90000,
            step=1000,
        )
        relevance = st.slider(
            'Experience Relevance',
            min_value=1.0, max_value=1.05, value=1.025, step=0.005,
            format='%.3fx',
            help='Prior experience in the exact field the role is in. Low = limited direct experience, High = deep relevant background.',
            key='audit_rel',
        )
        complexity = st.slider(
            'Experience Complexity',
            min_value=1.0, max_value=1.05, value=1.025, step=0.005,
            format='%.3fx',
            help='Technical rigor of the role. Low = routine tasks, High = cutting-edge or safety-critical work.',
            key='audit_comp',
        )
        discipline = st.selectbox(
            'Discipline',
            ['Mechanical', 'Propulsion', 'Structures', 'Avionics', 'Software', 'GNC', 'Systems', 'Other'],
            key='audit_disc',
        )

    with col2:
        # Compute audit results live on every rerun
        results = auditEmployee(
            level=level,
            managementRole=managementRole if managementRole != 'None' else 'Engineer',
            yearsExperience=yearsExperience,
            currentSalary=currentSalary,
            relevance=relevance,
            complexity=complexity,
        )
        displayName = employeeName
        displaySalary = currentSalary
        displayLevel = level

        st.subheader('Audit Results' + (f' - {displayName}' if displayName else ''))

        # -- Compliance status banner -- #
        statusColors = {
            'In Band': 'success',
            'Below Band': 'error',
            'Above Band': 'error',
            'Extended Range': 'warning',
        }
        statusType = statusColors[results['complianceStatus']]

        if statusType == 'success':
            st.success(f'Status: {results["complianceStatus"]}')
        elif statusType == 'warning':
            st.warning(f'Status: {results["complianceStatus"]}')
        else:
            st.error(f'Status: {results["complianceStatus"]}')

        # -- Band details -- #
        detailCol1, detailCol2 = st.columns(2)

        with detailCol1:
            st.markdown('**Band Details:**')
            st.markdown(f'- Band: {results["bandName"]}')
            st.markdown(f'- Min: \\${results["bandMin"]:,.0f}')
            st.markdown(f'- Median: \\${results["bandMedian"]:,.0f}')
            st.markdown(f'- Max: \\${results["bandMax"]:,.0f}')
            st.markdown(f'- Extended Max: \\${results["extendedMax"]:,.0f}')

        with detailCol2:
            st.markdown('**Salary Analysis:**')
            st.markdown(f'- Current: \\${displaySalary:,.0f}')
            st.markdown(f'- Expected Median: \\${results["expectedMedian"]:,.2f}')
            delta = results['salaryVsMedian']
            direction = 'above' if delta > 0 else 'below'
            st.markdown(f'- vs Median: \\${abs(delta):,.2f} {direction}')
            st.markdown(f'- Band Percentile: {results["salaryPercentInBand"]:.1f}%')

        # -- Gauge charts -- #
        displayMgmtRole = managementRole
        displayRelevance = relevance
        displayComplexity = complexity
        hasMgmt = displayMgmtRole not in ('None', 'Engineer')
        figMgmtGauge = None
        figMkt = None

        if hasMgmt:
            gaugeCol1, gaugeCol2 = st.columns(2)
        else:
            gaugeCol1 = st.container()

        with gaugeCol1:
            figAuditGauge = go.Figure(go.Indicator(
                mode='gauge+number+delta',
                value=displaySalary,
                number={
                    'prefix': '$', 'valueformat': ',.0f',
                    'font': {'color': colors['textPrimary']},
                },
                delta={
                    'reference': results['expectedMedian'],
                    'valueformat': ',.0f', 'prefix': '$',
                },
                gauge={
                    'axis': {
                        'range': [results['bandMin'], results['extendedMax']],
                        'tickcolor': colors['textMuted'],
                    },
                    'bar': {'color': colors['accent']},
                    'bgcolor': colors['surfaceSecondary'],
                    'steps': [
                        {'range': [results['bandMin'], results['bandMedian']], 'color': '#3a5a3a'},
                        {'range': [results['bandMedian'], results['bandMax']], 'color': '#4a6a4a'},
                        {'range': [results['bandMax'], results['extendedMax']], 'color': '#5a5a3a'},
                    ],
                    'threshold': {
                        'line': {'color': colors['danger'], 'width': 3},
                        'thickness': 0.8,
                        'value': results['expectedMedian'],
                    },
                },
                title={
                    'text': (
                        f'Technical Band (Level {displayLevel})'
                        f'<br><span style="font-size:12px;color:{colors["textMuted"]}">'
                        f'Red line = Expected Median (${results["expectedMedian"]:,.0f})'
                        f'  |  Delta = Current vs Expected</span>'
                    ),
                    'font': {'color': colors['textSecondary']},
                },
            ))
            figAuditGauge.update_layout(
                height=320,
                margin=dict(t=80, b=40, l=40, r=40),
                **plotlyDarkLayout,
            )
            st.plotly_chart(figAuditGauge, width='stretch')

        if hasMgmt:
            with gaugeCol2:
                # Compute management-adjusted values
                mgmtPremium = managementPremiums[displayMgmtRole]
                bandName = results['bandName']
                extended = extendedBands[bandName]

                # Management band range: base band min to extended max + premium
                mgmtMin = results['bandMin']
                mgmtMax = results['extendedMax'] + mgmtPremium
                mgmtBandMax = results['bandMax'] + mgmtPremium

                # Expected median with management premium included
                mgmtCalcResult = calculateSalary(
                    bandName, 'Median', displayRelevance, displayComplexity,
                    displayMgmtRole,
                )
                mgmtExpectedMedian = mgmtCalcResult['finalSalary']

                # Management band details
                mgmtMetrics = st.columns(3)
                with mgmtMetrics[0]:
                    st.metric('Role', displayMgmtRole)
                with mgmtMetrics[1]:
                    st.metric('Premium', f'${mgmtPremium:,}')
                with mgmtMetrics[2]:
                    st.metric('Mgmt Expected', f'${mgmtExpectedMedian:,.0f}')

                # Management gauge
                figMgmtGauge = go.Figure(go.Indicator(
                    mode='gauge+number+delta',
                    value=displaySalary,
                    number={
                        'prefix': '$', 'valueformat': ',.0f',
                        'font': {'color': colors['textPrimary']},
                    },
                    delta={
                        'reference': mgmtExpectedMedian,
                        'valueformat': ',.0f', 'prefix': '$',
                    },
                    gauge={
                        'axis': {
                            'range': [mgmtMin, mgmtMax],
                            'tickcolor': colors['textMuted'],
                        },
                        'bar': {'color': colors['accent']},
                        'bgcolor': colors['surfaceSecondary'],
                        'steps': [
                            {'range': [mgmtMin, results['bandMedian']], 'color': '#3a5a3a'},
                            {'range': [results['bandMedian'], mgmtBandMax], 'color': '#4a6a4a'},
                            {'range': [mgmtBandMax, mgmtMax], 'color': '#5a5a3a'},
                        ],
                        'threshold': {
                            'line': {'color': colors['danger'], 'width': 3},
                            'thickness': 0.8,
                            'value': mgmtExpectedMedian,
                        },
                    },
                    title={
                        'text': (
                            f'{displayMgmtRole} + Level {displayLevel}'
                            f'<br><span style="font-size:12px;color:{colors["textMuted"]}">'
                            f'Red line = Mgmt Expected Median (${mgmtExpectedMedian:,.0f})'
                            f'  |  Includes +${mgmtPremium:,} premium</span>'
                        ),
                        'font': {'color': colors['textSecondary']},
                    },
                ))
                figMgmtGauge.update_layout(
                    height=320,
                    margin=dict(t=80, b=40, l=40, r=40),
                    **plotlyDarkLayout,
                )
                st.plotly_chart(figMgmtGauge, width='stretch')

        st.caption(
            'Expected Median is the band median adjusted by relevance and complexity modifiers. '
            'The red threshold line marks this value on each gauge. '
            'The +/- delta shows how the current salary compares to the expected median.'
            + (
                f' The management gauge includes the {displayMgmtRole} premium '
                f'(+\\${managementPremiums[displayMgmtRole]:,}) '
                f'added to the base band range and expected median calculation.'
                if hasMgmt else ''
            )
            + ' Note: gauge text may overlap at high browser zoom levels — keep zoom at 100% or lower for best display.'
        )

        # -- Issues -- #
        if results['issues']:
            st.markdown('---')
            st.subheader('Issues Found')
            for issue in results['issues']:
                st.warning(issue.replace('$', r'\$'))
        else:
            st.markdown('---')
            st.success('No issues found. Compensation is within expected parameters.')

        # -- Market context -- #
        st.markdown('---')
        st.subheader('Market Context')

        surveyDf = renderDatasetSelector()
        marketData = filterMarketBenchmarks(
            surveyDf,
            experience=yearsExperience,
            discipline=discipline if discipline != 'Other' else None,
        )

        if not marketData.empty:
            # -- Filter criteria -- #
            expLow = max(0, yearsExperience - 2)
            expHigh = yearsExperience + 2
            discLabel = discipline if discipline != 'Other' else 'All Disciplines'
            st.markdown(
                f'**Filter Criteria:** {discLabel}, {expLow:.0f}-{expHigh:.0f} years experience '
                f'(+/- 2 years from {yearsExperience:.1f})'
            )

            # -- Market listings table (editable - delete rows to exclude from analysis) -- #
            tableKey = f'mktTable_{level}_{int(yearsExperience * 2)}_{discipline}'
            displayCols = ['Company', 'Title', 'Discipline', 'Min', 'Midpoint', 'Max', 'Estimated']
            availableCols = [c for c in displayCols if c in marketData.columns]
            st.markdown('**Market Listings** (select a row and press Delete to exclude it from the analysis):')
            editedMarket = st.data_editor(
                marketData[availableCols].reset_index(drop=True),
                key=tableKey,
                num_rows='dynamic',
                height=300,
                width='stretch',
            )

            if not editedMarket.empty:
                marketAvg = editedMarket['Midpoint'].mean()
                marketMin = editedMarket['Min'].min()
                marketMax = editedMarket['Max'].max()
                marketCount = len(editedMarket)

                # -- Summary metrics -- #
                mktCols = st.columns(4)
                with mktCols[0]:
                    st.metric('Market Listings', f'{marketCount}')
                with mktCols[1]:
                    st.metric('Market Avg Midpoint', f'${marketAvg:,.0f}')
                with mktCols[2]:
                    st.metric('Market Range', f'${marketMin:,.0f} - ${marketMax:,.0f}')
                with mktCols[3]:
                    vsMkt = displaySalary - marketAvg
                    st.metric('vs Market Avg', f'${vsMkt:+,.0f}')

                # -- Market salary distribution visualization -- #
                figMkt = go.Figure()

                # Box plot of matched market listings
                figMkt.add_trace(go.Box(
                    y=editedMarket['Midpoint'],
                    name='Market Listings',
                    marker_color=colors['info'],
                    boxmean=True,
                    hovertemplate='Midpoint: $%{y:,.0f}<extra></extra>',
                ))

                # Employee salary marker
                figMkt.add_trace(go.Scatter(
                    x=['Market Listings'],
                    y=[displaySalary],
                    mode='markers+text',
                    marker=dict(size=14, color=colors['accent'], symbol='diamond'),
                    text=[f'${displaySalary:,.0f}'],
                    textposition='top right',
                    textfont=dict(color=colors['accent'], size=11),
                    name='Current Salary',
                    hovertemplate='Current Salary: $%{y:,.0f}<extra></extra>',
                ))

                # Band median reference
                bandName = list(salaryBands.keys())[levelOrder.index(displayLevel)]
                bandMedian = salaryBands[bandName]['median']
                figMkt.add_hline(
                    y=bandMedian,
                    line_dash='dash',
                    line_color=colors['warning'],
                    annotation_text=f'Band Median: ${bandMedian:,.0f}',
                    annotation_font_color=colors['warning'],
                    annotation_position='top right',
                )

                figMkt.update_layout(
                    yaxis_title='Salary ($)',
                    height=350,
                    showlegend=True,
                    **plotlyDarkLayout,
                )
                figMkt.update_layout(legend=dict(orientation='h', yanchor='bottom', y=1.02))
                st.plotly_chart(figMkt, width='stretch')

            # -- Footnotes -- #
            st.caption(
                'Market data is a synthetic survey dataset of fictional job listings '
                'across fictional aerospace companies. '
                'Midpoint is the average of each listing\'s posted min and max salary. '
                'Experience window filters to listings within +/- 2 years of the entered value. '
                'The dashed line shows the band median for the selected level before experience modifiers. '
                'Diamond marker indicates the employee\'s current salary. '
                'Select a row and press Delete (or use the row menu) to exclude it from the analysis.'
            )
        else:
            editedMarket = marketData  # empty DataFrame
            st.info('No matching market data found for the specified experience and discipline.')

        # -- Export Report -- #
        st.markdown('---')
        nameSlug = displayName.replace(' ', '_') if displayName else 'audit'
        dateStr = date.today().strftime('%Y%m%d')

        pdfArgs = dict(
            displayName=displayName,
            displayLevel=displayLevel,
            displaySalary=displaySalary,
            displayMgmtRole=displayMgmtRole,
            displayRelevance=displayRelevance,
            displayComplexity=displayComplexity,
            discipline=discipline,
            yearsExperience=yearsExperience,
            results=results,
            marketData=editedMarket,
            figGauge=figAuditGauge,
            figMgmtGauge=figMgmtGauge,
            figMkt=figMkt,
        )

        pdfBytesDark = _generateAuditPdf(**pdfArgs, lightMode=False)
        pdfBytesLight = _generateAuditPdf(**pdfArgs, lightMode=True)

        exportCol1, exportCol2, exportSpacer = st.columns([1, 1, 2])
        with exportCol1:
            st.download_button(
                label='Export (Dark)',
                data=pdfBytesDark,
                file_name=f'{nameSlug}_audit_{dateStr}.pdf',
                mime='application/pdf',
                type='secondary',
                key='export_dark',
            )
        with exportCol2:
            st.download_button(
                label='Export (Print)',
                data=pdfBytesLight,
                file_name=f'{nameSlug}_audit_{dateStr}_print.pdf',
                mime='application/pdf',
                type='secondary',
                key='export_light',
            )

# ---------------------------------------------------------------------- #
# -- Module-Level Execution -- #
# ---------------------------------------------------------------------- #

renderIndividualAudit()
