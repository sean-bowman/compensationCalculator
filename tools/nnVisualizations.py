
# -- Neural Network Visualizations -- #

'''

Plotly visualization suite for the level bucket neural network
classifier. Each function returns a Plotly figure object that
can be displayed in Streamlit or exported as HTML/PNG.

All figures follow the dark theme defined in auditUtils.plotlyDarkLayout
and use the shared color palette for consistency with the rest of the app.

Visualization suite:
1. Network architecture diagram
2. Weight heatmaps per layer
3. Feature importance bar chart
4. Confusion matrix heatmap
5. Confidence distribution histogram
6. 2D decision boundary (PCA projection)
7. Before/after classification comparison
8. Training loss curve

Author: Sean Bowman
Date:   03/07/2026

'''

# Standard library imports
from typing import List, Optional, Dict

# Third-party imports
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from sklearn.decomposition import PCA

# Local imports
from auditUtils import plotlyDarkLayout, colors


# ---------------------------------------------------------------------- #
# -- 1. Network Architecture Diagram -- #
# ---------------------------------------------------------------------- #

def plotNetworkArchitecture(
    layerSizes: List[int],
    weights: Optional[List[np.ndarray]] = None,
    featureNames: Optional[List[str]] = None,
    classNames: Optional[List[str]] = None,
    maxNodes: int = 20,
) -> go.Figure:

    '''

    Draw a node-and-edge diagram of the network architecture.
    Nodes are arranged in columns by layer; edges connect adjacent
    layers with thickness proportional to absolute weight magnitude.

    Parameters:
    -----------
    layerSizes : list of int
        Number of neurons per layer including input and output
    weights : list of np.ndarray, optional
        Weight matrices between layers (for edge thickness)
    featureNames : list of str, optional
        Names for input layer nodes
    classNames : list of str, optional
        Names for output layer nodes
    maxNodes : int
        Max nodes to draw per layer (truncates with '...' indicator)

    Returns:
    --------
    go.Figure : Plotly figure of the network

    '''

    fig = go.Figure()
    nLayers = len(layerSizes)
    xSpacing = 1.0

    # Truncate large layers for visual clarity
    displaySizes = []
    for size in layerSizes:
        displaySizes.append(min(size, maxNodes))

    maxHeight = max(displaySizes)

    for layerIdx, (actualSize, displaySize) in enumerate(zip(layerSizes, displaySizes)):
        x = layerIdx * xSpacing
        yPositions = _centerNodes(displaySize, maxHeight)

        # Draw edges to previous layer
        if layerIdx > 0 and weights is not None:
            prevDisplaySize = displaySizes[layerIdx - 1]
            prevYPositions = _centerNodes(prevDisplaySize, maxHeight)
            W = weights[layerIdx - 1]
            wMax = np.abs(W).max() if W.size > 0 else 1.0

            for i in range(min(prevDisplaySize, W.shape[0])):
                for j in range(min(displaySize, W.shape[1])):
                    wVal = W[i, j]
                    opacity = min(0.8, abs(wVal) / wMax * 0.8 + 0.05)
                    edgeColor = colors['accent'] if wVal > 0 else colors['danger']
                    width = max(0.3, abs(wVal) / wMax * 3.0)

                    fig.add_trace(go.Scatter(
                        x=[(layerIdx - 1) * xSpacing, x],
                        y=[prevYPositions[i], yPositions[j]],
                        mode='lines',
                        line=dict(color=edgeColor, width=width),
                        opacity=opacity,
                        hoverinfo='skip',
                        showlegend=False,
                    ))

        # Draw nodes
        nodeLabels = []
        for i in range(displaySize):
            if layerIdx == 0 and featureNames and i < len(featureNames):
                nodeLabels.append(featureNames[i])
            elif layerIdx == nLayers - 1 and classNames and i < len(classNames):
                nodeLabels.append(classNames[i])
            else:
                nodeLabels.append(f'n{i}')

        nodeColor = colors['accent'] if layerIdx == nLayers - 1 else colors['info']
        if layerIdx == 0:
            nodeColor = colors['textSecondary']

        fig.add_trace(go.Scatter(
            x=[x] * displaySize,
            y=yPositions,
            mode='markers+text',
            marker=dict(size=18, color=nodeColor, line=dict(width=1, color=colors['textPrimary'])),
            text=nodeLabels,
            textposition='middle right' if layerIdx == 0 else ('middle left' if layerIdx == nLayers - 1 else 'top center'),
            textfont=dict(size=8, color=colors['textSecondary']),
            hovertext=[f'Layer {layerIdx}, Node {i}' for i in range(displaySize)],
            hoverinfo='text',
            showlegend=False,
        ))

        # Add truncation indicator
        if actualSize > displaySize:
            fig.add_annotation(
                x=x, y=yPositions[-1] - 0.4,
                text=f'... +{actualSize - displaySize} more',
                showarrow=False,
                font=dict(size=9, color=colors['textMuted']),
            )

        # Layer label
        layerLabel = 'Input' if layerIdx == 0 else ('Output' if layerIdx == nLayers - 1 else f'Hidden {layerIdx}')
        fig.add_annotation(
            x=x, y=maxHeight / 2 + 0.8,
            text=f'{layerLabel}<br>({actualSize} nodes)',
            showarrow=False,
            font=dict(size=10, color=colors['textPrimary']),
        )

    archLayout = {k: v for k, v in plotlyDarkLayout.items() if k not in ('xaxis', 'yaxis')}
    fig.update_layout(
        **archLayout,
        title='Network Architecture',
        showlegend=False,
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        height=500,
        margin=dict(l=120, r=120, t=50, b=20),
    )

    return fig


def _centerNodes(n: int, maxHeight: int) -> list:
    '''Center n nodes vertically within maxHeight space.'''
    if n == 1:
        return [maxHeight / 2]
    spacing = maxHeight / (n + 1)
    return [spacing * (i + 1) for i in range(n)]


# ---------------------------------------------------------------------- #
# -- 2. Weight Heatmaps -- #
# ---------------------------------------------------------------------- #

def plotWeightHeatmap(
    weights: List[np.ndarray],
    featureNames: Optional[List[str]] = None,
    classNames: Optional[List[str]] = None,
    layerIndex: int = 0,
) -> go.Figure:

    '''

    Plot a heatmap of the weight matrix for a specific layer.

    Parameters:
    -----------
    weights : list of np.ndarray
        Weight matrices from getWeights()
    featureNames : list of str, optional
        Names for rows (input features for layer 0)
    classNames : list of str, optional
        Names for columns of the output layer
    layerIndex : int
        Which layer's weights to display

    Returns:
    --------
    go.Figure : Heatmap figure

    '''

    W = weights[layerIndex]
    isLastLayer = layerIndex == len(weights) - 1

    yLabels = featureNames if layerIndex == 0 and featureNames else [f'node_{i}' for i in range(W.shape[0])]
    xLabels = classNames if isLastLayer and classNames else [f'node_{j}' for j in range(W.shape[1])]

    # Truncate labels for readability
    if len(yLabels) > 40:
        yLabels = yLabels[:40] + [f'... +{len(yLabels) - 40} more']
        W = W[:40, :]

    fig = go.Figure(data=go.Heatmap(
        z=W,
        x=xLabels,
        y=yLabels,
        colorscale='RdBu_r',
        zmid=0,
        colorbar=dict(title='Weight'),
    ))

    layerLabel = 'Input -> Hidden 1' if layerIndex == 0 else (
        f'Hidden {layerIndex} -> Output' if isLastLayer else f'Hidden {layerIndex} -> Hidden {layerIndex + 1}'
    )

    fig.update_layout(
        **plotlyDarkLayout,
        title=f'Weight Heatmap: {layerLabel}',
        xaxis_title='To',
        yaxis_title='From',
        height=max(400, len(yLabels) * 14),
        margin=dict(l=200, r=50, t=50, b=50),
    )

    return fig


# ---------------------------------------------------------------------- #
# -- 3. Feature Importance -- #
# ---------------------------------------------------------------------- #

def plotFeatureImportance(
    importanceDf: pd.DataFrame,
    topN: int = 20,
) -> go.Figure:

    '''

    Plot a horizontal bar chart of feature importance scores.

    Parameters:
    -----------
    importanceDf : pd.DataFrame
        From BucketClassifier.getFeatureImportance()
    topN : int
        Number of top features to display

    Returns:
    --------
    go.Figure : Bar chart figure

    '''

    topFeatures = importanceDf.head(topN).sort_values('importance_mean', ascending=True)

    fig = go.Figure(go.Bar(
        y=topFeatures['feature'],
        x=topFeatures['importance_mean'],
        error_x=dict(type='data', array=topFeatures['importance_std'].values),
        orientation='h',
        marker_color=colors['accent'],
    ))

    fig.update_layout(
        **plotlyDarkLayout,
        title=f'Top {topN} Feature Importance (Permutation)',
        xaxis_title='Mean Accuracy Decrease',
        yaxis_title='',
        height=max(400, topN * 25),
        margin=dict(l=200, r=50, t=50, b=50),
    )

    return fig


# ---------------------------------------------------------------------- #
# -- 4. Confusion Matrix -- #
# ---------------------------------------------------------------------- #

def plotConfusionMatrix(
    confMatrix: np.ndarray,
    classNames: Optional[List[str]] = None,
) -> go.Figure:

    '''

    Plot the confusion matrix as an annotated heatmap.

    Parameters:
    -----------
    confMatrix : np.ndarray
        Confusion matrix (n_classes x n_classes)
    classNames : list of str, optional
        Class labels for axes

    Returns:
    --------
    go.Figure : Heatmap figure

    '''

    if classNames is None:
        classNames = [f'Level {i+1}' for i in range(confMatrix.shape[0])]

    # Compute percentages for annotation text
    rowSums = confMatrix.sum(axis=1, keepdims=True)
    rowSums = np.where(rowSums == 0, 1, rowSums)  # avoid division by zero
    pctMatrix = confMatrix / rowSums * 100

    # Build annotation text: count (percentage)
    annotations = []
    for i in range(confMatrix.shape[0]):
        for j in range(confMatrix.shape[1]):
            annotations.append(f'{confMatrix[i, j]}<br>{pctMatrix[i, j]:.0f}%')

    annotationText = np.array(annotations).reshape(confMatrix.shape)

    fig = go.Figure(data=go.Heatmap(
        z=confMatrix,
        x=classNames,
        y=classNames,
        colorscale=[[0, colors['bg']], [1, colors['accent']]],
        text=annotationText,
        texttemplate='%{text}',
        textfont=dict(size=12),
        hovertemplate='True: %{y}<br>Predicted: %{x}<br>Count: %{z}<extra></extra>',
    ))

    fig.update_layout(
        **plotlyDarkLayout,
        title='Confusion Matrix (Cross-Validation)',
        xaxis_title='Predicted',
        yaxis_title='Actual',
        height=450,
        width=550,
    )

    return fig


# ---------------------------------------------------------------------- #
# -- 5. Confidence Distribution -- #
# ---------------------------------------------------------------------- #

def plotConfidenceDistribution(
    predictions: np.ndarray,
    confidences: np.ndarray,
    classNames: Optional[List[str]] = None,
) -> go.Figure:

    '''

    Plot histogram of prediction confidence scores, colored by
    predicted class.

    Parameters:
    -----------
    predictions : np.ndarray
        Predicted class labels
    confidences : np.ndarray
        Confidence scores (max class probability)
    classNames : list of str, optional
        Class label names

    Returns:
    --------
    go.Figure : Histogram figure

    '''

    df = pd.DataFrame({
        'prediction': predictions,
        'confidence': confidences,
    })

    if classNames is None:
        classNames = {i: f'Level {i}' for i in sorted(df['prediction'].unique())}
    elif isinstance(classNames, list):
        classNames = {i + 1: name for i, name in enumerate(classNames)}

    df['label'] = df['prediction'].map(classNames)

    fig = go.Figure()

    for cls in sorted(df['prediction'].unique()):
        subset = df[df['prediction'] == cls]
        levelColor = colors['levels'].get(f'Level {cls}', colors['accent'])
        fig.add_trace(go.Histogram(
            x=subset['confidence'],
            name=classNames.get(cls, f'Level {cls}'),
            marker_color=levelColor,
            opacity=0.7,
            nbinsx=20,
        ))

    fig.update_layout(
        **plotlyDarkLayout,
        title='Prediction Confidence Distribution',
        xaxis_title='Confidence (Max Class Probability)',
        yaxis_title='Count',
        barmode='overlay',
        height=400,
    )

    return fig


# ---------------------------------------------------------------------- #
# -- 6. 2D Decision Boundary (PCA) -- #
# ---------------------------------------------------------------------- #

def plotDecisionBoundary2D(
    X: np.ndarray,
    y: np.ndarray,
    predictions: np.ndarray,
    classNames: Optional[List[str]] = None,
) -> go.Figure:

    '''

    Project the feature space to 2D using PCA and plot the
    data points colored by true class, with markers shaped
    by whether the prediction matches the true label.

    Parameters:
    -----------
    X : np.ndarray
        Feature matrix (n_samples x n_features)
    y : np.ndarray
        True labels
    predictions : np.ndarray
        Model predictions
    classNames : list of str, optional
        Class label names

    Returns:
    --------
    go.Figure : Scatter plot figure

    '''

    pca = PCA(n_components=2, random_state=42)
    X2d = pca.fit_transform(X)

    if classNames is None:
        classNames = {i: f'Level {i}' for i in sorted(set(y))}
    elif isinstance(classNames, list):
        classNames = {i + 1: name for i, name in enumerate(classNames)}

    correct = predictions == y

    fig = go.Figure()

    for cls in sorted(set(y)):
        mask = y == cls
        correctMask = mask & correct
        incorrectMask = mask & ~correct

        levelColor = colors['levels'].get(f'Level {cls}', colors['accent'])
        label = classNames.get(cls, f'Level {cls}')

        # Correct predictions: filled circles
        if correctMask.any():
            fig.add_trace(go.Scatter(
                x=X2d[correctMask, 0],
                y=X2d[correctMask, 1],
                mode='markers',
                marker=dict(size=8, color=levelColor, opacity=0.7),
                name=f'{label} (correct)',
                legendgroup=label,
            ))

        # Incorrect predictions: x markers
        if incorrectMask.any():
            fig.add_trace(go.Scatter(
                x=X2d[incorrectMask, 0],
                y=X2d[incorrectMask, 1],
                mode='markers',
                marker=dict(size=8, color=levelColor, symbol='x', opacity=0.9),
                name=f'{label} (misclassified)',
                legendgroup=label,
            ))

    varExplained = pca.explained_variance_ratio_
    fig.update_layout(
        **plotlyDarkLayout,
        title='2D Feature Space (PCA Projection)',
        xaxis_title=f'PC1 ({varExplained[0]:.1%} variance)',
        yaxis_title=f'PC2 ({varExplained[1]:.1%} variance)',
        height=500,
    )

    return fig


# ---------------------------------------------------------------------- #
# -- 7. Before/After Comparison -- #
# ---------------------------------------------------------------------- #

def plotBeforeAfterComparison(
    keywordBuckets: pd.Series,
    nnBuckets: pd.Series,
) -> go.Figure:

    '''

    Side-by-side bar chart comparing classification distributions
    between the keyword-only system and the NN-augmented system.

    Parameters:
    -----------
    keywordBuckets : pd.Series
        LevelBucket assignments from keyword-only pipeline
    nnBuckets : pd.Series
        LevelBucket assignments from NN-augmented pipeline

    Returns:
    --------
    go.Figure : Grouped bar chart figure

    '''

    levelNames = ['Level 1', 'Level 2', 'Level 3', 'Level 4', 'Level 5', 'Unclassified']

    keywordCounts = keywordBuckets.value_counts()
    nnCounts = nnBuckets.value_counts()

    keywordVals = [keywordCounts.get(lvl, 0) for lvl in levelNames]
    nnVals = [nnCounts.get(lvl, 0) for lvl in levelNames]

    fig = go.Figure()

    fig.add_trace(go.Bar(
        name='Keyword-Only',
        x=levelNames,
        y=keywordVals,
        marker_color=colors['info'],
        opacity=0.8,
    ))

    fig.add_trace(go.Bar(
        name='NN-Augmented',
        x=levelNames,
        y=nnVals,
        marker_color=colors['accent'],
        opacity=0.8,
    ))

    fig.update_layout(
        **plotlyDarkLayout,
        title='Classification Distribution: Keyword vs NN',
        xaxis_title='Level Bucket',
        yaxis_title='Count',
        barmode='group',
        height=400,
    )

    return fig


# ---------------------------------------------------------------------- #
# -- 8. Training Loss Curve -- #
# ---------------------------------------------------------------------- #

def plotTrainingLoss(
    lossHistory: List[float],
) -> go.Figure:

    '''

    Plot the training loss curve over epochs.

    Parameters:
    -----------
    lossHistory : list of float
        Loss values per epoch from training

    Returns:
    --------
    go.Figure : Line chart figure

    '''

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=list(range(1, len(lossHistory) + 1)),
        y=lossHistory,
        mode='lines+markers',
        marker=dict(size=4, color=colors['accent']),
        line=dict(color=colors['accent'], width=2),
        name='Training Loss',
    ))

    fig.update_layout(
        **plotlyDarkLayout,
        title='Training Loss Curve',
        xaxis_title='Epoch',
        yaxis_title='Loss',
        height=350,
    )

    return fig


# ---------------------------------------------------------------------- #
# -- 9. Per-Row Prediction Explainer -- #
# ---------------------------------------------------------------------- #

def plotPredictionExplainer(
    featureVector: np.ndarray,
    featureNames: List[str],
    classProbabilities: np.ndarray,
    classNames: Optional[List[str]] = None,
    topN: int = 10,
) -> go.Figure:

    '''

    For a single sample, show the top features contributing to
    the prediction alongside the class probability distribution.

    Creates a two-panel figure:
    - Left: Top N features by absolute value
    - Right: Class probability bar chart

    Parameters:
    -----------
    featureVector : np.ndarray
        Feature values for one sample (1D)
    featureNames : list of str
        Feature names
    classProbabilities : np.ndarray
        Class probabilities for this sample (1D)
    classNames : list of str, optional
        Class labels
    topN : int
        Number of top features to show

    Returns:
    --------
    go.Figure : Combined explainer figure

    '''

    from plotly.subplots import make_subplots

    if classNames is None:
        classNames = [f'Level {i+1}' for i in range(len(classProbabilities))]

    # Top N features by absolute value
    absVals = np.abs(featureVector)
    topIdx = np.argsort(absVals)[::-1][:topN]
    topNames = [featureNames[i] for i in topIdx]
    topValues = [featureVector[i] for i in topIdx]

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=['Active Features (Top by Magnitude)', 'Class Probabilities'],
        column_widths=[0.6, 0.4],
    )

    # Feature bars
    barColors = [colors['accent'] if v > 0 else colors['danger'] for v in topValues]
    fig.add_trace(go.Bar(
        y=topNames[::-1],
        x=topValues[::-1],
        orientation='h',
        marker_color=barColors[::-1],
        showlegend=False,
    ), row=1, col=1)

    # Probability bars
    levelColors = [colors['levels'].get(name, colors['accent']) for name in classNames]
    fig.add_trace(go.Bar(
        x=classNames,
        y=classProbabilities,
        marker_color=levelColors,
        showlegend=False,
    ), row=1, col=2)

    fig.update_layout(
        **plotlyDarkLayout,
        title='Prediction Explainer',
        height=400,
        margin=dict(l=150, r=50, t=70, b=50),
    )

    return fig
