
# -- Neural Network Showcase Page -- #

'''

Streamlit page demonstrating the neural network semantic filter
for the career page scraper. Provides model training controls,
visualization of model internals, live classification comparison,
and educational documentation of the implementation.

Author: Sean Bowman
Date:   03/07/2026

'''

# Standard library imports
import os
import sys

# Third-party imports
import streamlit as st
import pandas as pd
import numpy as np

# Ensure tools directory is importable
_viewsDir = os.path.dirname(os.path.abspath(__file__))
_appDir = os.path.dirname(_viewsDir)
_toolsDir = os.path.join(_appDir, 'tools')
if _toolsDir not in sys.path:
    sys.path.insert(0, _toolsDir)

# Local imports
from auditUtils import (
    colors, plotlyDarkLayout, loadMarketSurveyData,
)
from featureEngineering import (
    buildFeatureMatrix, buildLabelVector, extractFeatureVector,
    SENIORITY_KEYWORDS, DISCIPLINE_KEYWORDS,
)
from neuralClassifier import BucketClassifier, trainFromDataFrame
from nnVisualizations import (
    plotNetworkArchitecture, plotWeightHeatmap, plotFeatureImportance,
    plotConfusionMatrix, plotConfidenceDistribution, plotDecisionBoundary2D,
    plotBeforeAfterComparison, plotTrainingLoss, plotPredictionExplainer,
)


# ---------------------------------------------------------------------- #
# -- Page Renderer -- #
# ---------------------------------------------------------------------- #

def renderNnShowcase():

    '''

    Render the Neural Network Showcase page with 4 tabs:
    1. Model Overview - architecture, metrics, feature importance
    2. Training - configure and train the MLP
    3. Live Classification - compare keyword vs NN results
    4. Model Internals - weight heatmaps, decision boundary, explainer

    '''

    st.header('Neural Network Classifier')
    st.caption(
        'MLP-based semantic filter for classifying job listings into '
        'engineering levels. Built on scikit-learn with hand-engineered '
        'features for full transparency.'
    )

    # Initialize session state
    if 'nnClassifier' not in st.session_state:
        st.session_state.nnClassifier = None
    if 'nnTrainingResults' not in st.session_state:
        st.session_state.nnTrainingResults = None
    if 'nnFeatureMatrix' not in st.session_state:
        st.session_state.nnFeatureMatrix = None
    if 'nnLabels' not in st.session_state:
        st.session_state.nnLabels = None
    if 'nnFeatureNames' not in st.session_state:
        st.session_state.nnFeatureNames = None

    # Try to load existing model if none in session
    if st.session_state.nnClassifier is None:
        classifier = BucketClassifier()
        if classifier.load():
            st.session_state.nnClassifier = classifier

    tab1, tab2, tab3, tab4 = st.tabs([
        'Model Overview', 'Training', 'Live Classification', 'Model Internals',
    ])

    with tab1:
        _renderOverviewTab()

    with tab2:
        _renderTrainingTab()

    with tab3:
        _renderLiveClassificationTab()

    with tab4:
        _renderInternalsTab()


# ---------------------------------------------------------------------- #
# -- Tab 1: Model Overview -- #
# ---------------------------------------------------------------------- #

def _renderOverviewTab():

    '''Render model overview with architecture, metrics, and importance.'''

    classifier = st.session_state.nnClassifier

    if classifier is None or not classifier.isTrained:
        st.info('No trained model available. Go to the Training tab to train one.')
        return

    # -- Architecture Diagram -- #
    st.subheader('Network Architecture')

    nFeatures = len(classifier.featureNames)
    nClasses = len(classifier.classes)
    layerSizes = [nFeatures] + list(classifier.hiddenLayers) + [nClasses]

    classNames = [f'Level {c}' for c in classifier.classes]
    archFig = plotNetworkArchitecture(
        layerSizes,
        weights=classifier.getWeights(),
        featureNames=classifier.featureNames[:20],  # truncate for readability
        classNames=classNames,
        maxNodes=15,
    )
    st.plotly_chart(archFig, width='stretch')

    # -- Metrics Summary -- #
    st.subheader('Cross-Validation Metrics')
    metrics = classifier.cvMetrics

    if metrics:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric('CV Accuracy', f'{metrics.get("cvAccuracy", 0):.1%}')
        col2.metric('CV Macro F1', f'{metrics.get("cvF1", 0):.1%}')
        col3.metric('Samples', f'{metrics.get("nSamples", 0):,}')
        col4.metric('CV Folds', f'{metrics.get("nFolds", 0)}')

        # Confusion matrix
        if 'confusionMatrix' in metrics:
            confMatrix = np.array(metrics['confusionMatrix'])
            confFig = plotConfusionMatrix(confMatrix, classNames)
            st.plotly_chart(confFig, width='stretch')

    # -- Feature Importance -- #
    st.subheader('Feature Importance')

    if st.session_state.nnFeatureMatrix is not None and st.session_state.nnLabels is not None:
        X = st.session_state.nnFeatureMatrix
        y = st.session_state.nnLabels
        mask = y > 0
        importanceDf = classifier.getFeatureImportance(X[mask], y[mask], nRepeats=5)
        impFig = plotFeatureImportance(importanceDf, topN=20)
        st.plotly_chart(impFig, width='stretch')
    else:
        st.caption('Train the model first to see feature importance (requires feature matrix in memory).')

    # -- Training Loss -- #
    history = classifier.trainingHistory
    if history and 'lossHistory' in history:
        st.subheader('Training Convergence')
        lossFig = plotTrainingLoss(history['lossHistory'])
        st.plotly_chart(lossFig, width='stretch')


# ---------------------------------------------------------------------- #
# -- Tab 2: Training -- #
# ---------------------------------------------------------------------- #

def _renderTrainingTab():

    '''Render training controls and results.'''

    st.subheader('Train Neural Network')

    # -- Hyperparameter Controls -- #
    with st.expander('Hyperparameters', expanded=True):
        col1, col2 = st.columns(2)

        with col1:
            layer1 = st.slider('Hidden Layer 1 Size', 16, 128, 64, step=16)
            layer2 = st.slider('Hidden Layer 2 Size', 8, 64, 32, step=8)
            maxIter = st.slider('Max Epochs', 100, 1000, 500, step=100)

        with col2:
            alpha = st.select_slider(
                'L2 Regularization (alpha)',
                options=[0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1],
                value=0.001,
            )
            learningRate = st.select_slider(
                'Learning Rate',
                options=[0.0001, 0.0005, 0.001, 0.005, 0.01],
                value=0.001,
            )
            nFolds = st.slider('CV Folds', 3, 10, 5)

    # -- Train Button -- #
    col1, col2 = st.columns([1, 3])

    with col1:
        trainBtn = st.button('Train Model', type='primary')

    with col2:
        if st.session_state.nnClassifier is not None:
            st.caption('A trained model exists. Training will overwrite it.')

    if trainBtn:
        with st.spinner('Loading training data...'):
            df = loadMarketSurveyData()
            X, featureNames, companyEncoder = buildFeatureMatrix(df)
            y = buildLabelVector(df)

        with st.spinner(f'Training MLP ({layer1}, {layer2}) with {nFolds}-fold CV...'):
            classifier = BucketClassifier(
                hiddenLayers=(layer1, layer2),
                alpha=alpha,
                learningRateInit=learningRate,
                maxIter=maxIter,
            )

            results = classifier.train(
                X, y,
                featureNames=featureNames,
                companyEncoder=companyEncoder,
                nFolds=nFolds,
            )

            # Save to disk and session
            classifier.save()
            st.session_state.nnClassifier = classifier
            st.session_state.nnTrainingResults = results
            st.session_state.nnFeatureMatrix = X
            st.session_state.nnLabels = y
            st.session_state.nnFeatureNames = featureNames

        st.success(
            f'Training complete. CV Accuracy: {results["cvAccuracy"]:.1%}, '
            f'CV Macro F1: {results["cvF1"]:.1%}'
        )

    # -- Show Results -- #
    results = st.session_state.nnTrainingResults
    if results is not None:
        st.divider()
        st.subheader('Training Results')

        col1, col2, col3 = st.columns(3)
        col1.metric('CV Accuracy', f'{results["cvAccuracy"]:.1%}')
        col2.metric('CV Macro F1', f'{results["cvF1"]:.1%}')
        col3.metric('Epochs', f'{results["nIter"]}')

        # Per-class metrics table
        if 'cvReport' in results:
            report = results['cvReport']
            reportRows = []
            for cls, metrics in report.items():
                if isinstance(metrics, dict) and 'precision' in metrics:
                    reportRows.append({
                        'Class': f'Level {cls}',
                        'Precision': f'{metrics["precision"]:.2f}',
                        'Recall': f'{metrics["recall"]:.2f}',
                        'F1': f'{metrics["f1-score"]:.2f}',
                        'Support': int(metrics['support']),
                    })
            if reportRows:
                st.dataframe(pd.DataFrame(reportRows), width='stretch', hide_index=True)

        # Confusion matrix and loss curve side by side
        if 'confusionMatrix' in results and 'lossHistory' in results:
            col1, col2 = st.columns(2)
            with col1:
                confMatrix = np.array(results['confusionMatrix'])
                classNames = [f'Level {c}' for c in sorted(st.session_state.nnClassifier.classes)]
                confFig = plotConfusionMatrix(confMatrix, classNames)
                st.plotly_chart(confFig, width='stretch')
            with col2:
                lossFig = plotTrainingLoss(results['lossHistory'])
                st.plotly_chart(lossFig, width='stretch')


# ---------------------------------------------------------------------- #
# -- Tab 3: Live Classification -- #
# ---------------------------------------------------------------------- #

def _renderLiveClassificationTab():

    '''Render side-by-side comparison of keyword vs NN classification.'''

    classifier = st.session_state.nnClassifier

    if classifier is None or not classifier.isTrained:
        st.info('Train a model first to see live classification results.')
        return

    st.subheader('Keyword vs NN Classification Comparison')

    # Load survey data and run both classifiers
    if st.button('Run Comparison on Survey Data'):
        with st.spinner('Running comparison...'):
            df = loadMarketSurveyData()

            # Build features for NN predictions
            X, featureNames, companyEncoder = buildFeatureMatrix(df, classifier.companyEncoder)
            nnPredictions, nnConfidences = classifier.predictWithConfidence(X)

            # Get keyword-only predictions (using existing pipeline logic)
            from validatedAnalysis import _inferLevelFromTitle, _inferLevelFromSalary

            keywordBuckets = []
            for _, row in df.iterrows():
                title = str(row.get('Listing', ''))
                titleLevel = _inferLevelFromTitle(title)
                minVal = pd.to_numeric(row.get('Min'), errors='coerce')
                maxVal = pd.to_numeric(row.get('Max'), errors='coerce')
                midpoint = 0
                if pd.notna(minVal) and pd.notna(maxVal) and minVal > 0 and maxVal > 0:
                    midpoint = (minVal + maxVal) / 2
                salaryLevel = _inferLevelFromSalary(midpoint)

                # Simple keyword-only assignment (no YoE, no NN)
                if titleLevel is not None:
                    keywordBuckets.append(f'Level {titleLevel}')
                elif salaryLevel is not None:
                    keywordBuckets.append(f'Level {salaryLevel}')
                else:
                    keywordBuckets.append('Unclassified')

            df['KeywordBucket'] = keywordBuckets
            df['NNBucket'] = [f'Level {p}' for p in nnPredictions]
            df['NNConfidence'] = nnConfidences
            df['TrueLevel'] = df['Vlvl'].apply(
                lambda v: f'Level {int(v)}' if pd.notna(v) else 'Unknown'
            )

            st.session_state.nnComparisonDf = df

    # Display comparison results
    if 'nnComparisonDf' in st.session_state:
        df = st.session_state.nnComparisonDf

        # Accuracy comparison
        trueLevels = df[df['TrueLevel'] != 'Unknown']

        keywordCorrect = (trueLevels['KeywordBucket'] == trueLevels['TrueLevel']).sum()
        nnCorrect = (trueLevels['NNBucket'] == trueLevels['TrueLevel']).sum()
        total = len(trueLevels)

        col1, col2, col3 = st.columns(3)
        col1.metric('Keyword Accuracy', f'{keywordCorrect / total:.1%}')
        col2.metric('NN Accuracy', f'{nnCorrect / total:.1%}')
        improvement = (nnCorrect - keywordCorrect) / total * 100
        col3.metric('Improvement', f'{improvement:+.1f}%')

        # Distribution comparison chart
        compFig = plotBeforeAfterComparison(
            df['KeywordBucket'],
            df['NNBucket'],
        )
        st.plotly_chart(compFig, width='stretch')

        # Confidence distribution
        confFig = plotConfidenceDistribution(
            df['NNBucket'].apply(lambda b: int(b.split(' ')[1]) if b != 'Unclassified' else 0).values,
            df['NNConfidence'].values,
        )
        st.plotly_chart(confFig, width='stretch')

        # Show rows where classification changed
        changed = df[df['KeywordBucket'] != df['NNBucket']]
        st.subheader(f'Classification Changes ({len(changed)} rows)')
        if not changed.empty:
            displayCols = ['Company', 'Listing', 'TrueLevel', 'KeywordBucket', 'NNBucket', 'NNConfidence']
            displayCols = [c for c in displayCols if c in changed.columns]
            st.dataframe(
                changed[displayCols].head(50),
                width='stretch',
                hide_index=True,
            )


# ---------------------------------------------------------------------- #
# -- Tab 4: Model Internals -- #
# ---------------------------------------------------------------------- #

def _renderInternalsTab():

    '''Render weight heatmaps, decision boundary, and prediction explainer.'''

    classifier = st.session_state.nnClassifier

    if classifier is None or not classifier.isTrained:
        st.info('Train a model first to explore its internals.')
        return

    # -- Weight Heatmaps -- #
    st.subheader('Weight Heatmaps')

    weights = classifier.getWeights()
    classNames = [f'Level {c}' for c in classifier.classes]

    layerIdx = st.selectbox(
        'Layer',
        list(range(len(weights))),
        format_func=lambda i: f'Layer {i}: {"Input" if i == 0 else f"Hidden {i}"} -> '
                               f'{"Output" if i == len(weights) - 1 else f"Hidden {i + 1}"} '
                               f'({weights[i].shape[0]} x {weights[i].shape[1]})',
    )

    heatmapFig = plotWeightHeatmap(
        weights,
        featureNames=classifier.featureNames,
        classNames=classNames,
        layerIndex=layerIdx,
    )
    st.plotly_chart(heatmapFig, width='stretch')

    # -- 2D Decision Boundary -- #
    st.subheader('2D Feature Space (PCA)')

    if st.session_state.nnFeatureMatrix is not None and st.session_state.nnLabels is not None:
        X = st.session_state.nnFeatureMatrix
        y = st.session_state.nnLabels
        mask = y > 0

        predictions = classifier.predict(X[mask])
        boundaryFig = plotDecisionBoundary2D(X[mask], y[mask], predictions)
        st.plotly_chart(boundaryFig, width='stretch')
    else:
        st.caption('Train the model to see the decision boundary (requires feature matrix in memory).')

    # -- Prediction Explainer -- #
    st.subheader('Single Prediction Explainer')

    df = loadMarketSurveyData()
    rowIdx = st.number_input('Row Index', min_value=0, max_value=len(df) - 1, value=0, step=1)
    row = df.iloc[rowIdx]

    st.caption(f'**{row["Company"]}** -- {row["Listing"]}')

    featureVec = extractFeatureVector(row, classifier.companyEncoder)
    probas = classifier.predictProba(featureVec.reshape(1, -1))[0]
    prediction, confidence = classifier.predictWithConfidence(featureVec.reshape(1, -1))

    st.caption(f'Predicted: **Level {prediction[0]}** (confidence: {confidence[0]:.2f})')

    explainerFig = plotPredictionExplainer(
        featureVec,
        classifier.featureNames,
        probas,
        classNames=classNames,
        topN=12,
    )
    st.plotly_chart(explainerFig, width='stretch')


# ---------------------------------------------------------------------- #
# -- Page Entry Point -- #
# ---------------------------------------------------------------------- #

# Run as standalone page; skipped when imported as a module by marketTools.py
if __name__ != 'nnShowcase':
    renderNnShowcase()
