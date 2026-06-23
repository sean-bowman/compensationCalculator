
# -- Level Bucket Neural Network Classifier -- #

'''

MLP-based classifier for assigning job listings to
engineering levels (1-5). Wraps scikit-learn's MLPClassifier
with training, evaluation, persistence, and interpretability
methods designed for educational transparency.

Key design decisions:
- scikit-learn MLPClassifier (not TensorFlow) -- right-sized for
  ~500 training samples, full weight visibility, minimal boilerplate
- StandardScaler on inputs -- MLP requires normalized features
- Stratified K-Fold CV -- handles class imbalance in evaluation
- Balanced class weights via oversampling -- Level 5 has only 16 samples
- L2 regularization + early stopping -- overfitting prevention

Author: Sean Bowman
Date:   03/07/2026

'''

# Standard library imports
import os
import json
import logging
from typing import Tuple, Optional, List, Dict

# Third-party imports
import numpy as np
import pandas as pd
import joblib
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import (
    accuracy_score, f1_score, classification_report,
    confusion_matrix, precision_recall_fscore_support,
)
from sklearn.inspection import permutation_importance
from sklearn.utils import resample

# Local imports
from featureEngineering import buildFeatureMatrix, buildLabelVector, buildCompanyEncoder

logger = logging.getLogger('neuralClassifier')

# ---------------------------------------------------------------------- #
# -- Constants -- #
# ---------------------------------------------------------------------- #

# Default cache directory for trained models
_toolsDir = os.path.dirname(os.path.abspath(__file__))
_defaultCacheDir = os.path.join(_toolsDir, '.modelCache')


# ---------------------------------------------------------------------- #
# -- Classifier Class -- #
# ---------------------------------------------------------------------- #

class BucketClassifier:

    '''

    Neural network classifier for engineering level assignment.
    Wraps MLPClassifier with training, evaluation, and persistence.

    The classifier operates on pre-extracted feature vectors from
    featureEngineering.py. It does NOT handle raw text -- feature
    extraction is a separate, inspectable step.

    '''

    def __init__(
        self,
        hiddenLayers: Tuple[int, ...] = (64, 32),
        alpha: float = 0.001,
        learningRateInit: float = 0.001,
        maxIter: int = 500,
        randomState: int = 42,
    ):

        '''

        Initialize the classifier with hyperparameters.

        Parameters:
        -----------
        hiddenLayers : tuple of int
            Sizes of hidden layers (e.g., (64, 32) = two layers)
        alpha : float
            L2 regularization strength
        learningRateInit : float
            Initial learning rate for Adam optimizer
        maxIter : int
            Maximum training iterations (epochs)
        randomState : int
            Random seed for reproducibility

        '''

        self.hiddenLayers = hiddenLayers
        self.alpha = alpha
        self.learningRateInit = learningRateInit
        self.maxIter = maxIter
        self.randomState = randomState

        self._model: Optional[MLPClassifier] = None
        self._scaler: Optional[StandardScaler] = None
        self._featureNames: List[str] = []
        self._companyEncoder: dict = {}
        self._classes: np.ndarray = np.array([])
        self._trainingHistory: Dict[str, list] = {}
        self._cvMetrics: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # -- Training -- #
    # ------------------------------------------------------------------ #

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        featureNames: Optional[List[str]] = None,
        companyEncoder: Optional[dict] = None,
        nFolds: int = 5,
        oversample: bool = True,
    ) -> dict:

        '''

        Train the MLP on the provided feature matrix and labels.
        Performs stratified K-fold cross-validation to estimate
        generalization performance, then trains the final model
        on all data.

        Parameters:
        -----------
        X : np.ndarray
            Feature matrix (n_samples x n_features)
        y : np.ndarray
            Label vector (n_samples,) with integer levels 1-5
        featureNames : list of str, optional
            Feature names for interpretability
        companyEncoder : dict, optional
            Company encoder for persistence
        nFolds : int
            Number of CV folds
        oversample : bool
            Whether to oversample minority classes to balance training

        Returns:
        --------
        dict : Training results with keys:
            cvAccuracy, cvF1, cvReport, confusionMatrix, lossHistory

        '''

        if featureNames is not None:
            self._featureNames = featureNames
        if companyEncoder is not None:
            self._companyEncoder = companyEncoder

        # Filter out unlabeled samples (class 0 = Unclassified)
        mask = y > 0
        X_labeled = X[mask]
        y_labeled = y[mask]

        self._classes = np.unique(y_labeled)
        logger.info(f'Training on {len(y_labeled)} labeled samples, {len(self._classes)} classes')

        # -- Cross-validation to estimate performance -- #
        skf = StratifiedKFold(n_splits=nFolds, shuffle=True, random_state=self.randomState)
        cvPredictions = np.zeros_like(y_labeled)

        for foldIdx, (trainIdx, valIdx) in enumerate(skf.split(X_labeled, y_labeled)):
            xTrain, xVal = X_labeled[trainIdx], X_labeled[valIdx]
            yTrain, yVal = y_labeled[trainIdx], y_labeled[valIdx]

            # Oversample minority classes in training fold
            if oversample:
                xTrain, yTrain = _oversampleMinority(xTrain, yTrain)

            # Scale features
            scaler = StandardScaler()
            xTrainScaled = scaler.fit_transform(xTrain)
            xValScaled = scaler.transform(xVal)

            # Train fold model
            foldModel = self._buildModel()
            foldModel.fit(xTrainScaled, yTrain)

            # Store predictions for this fold's validation set
            cvPredictions[valIdx] = foldModel.predict(xValScaled)

        # -- CV metrics -- #
        cvAccuracy = accuracy_score(y_labeled, cvPredictions)
        cvF1 = f1_score(y_labeled, cvPredictions, average='macro', zero_division=0)
        cvReport = classification_report(y_labeled, cvPredictions, zero_division=0, output_dict=True)
        confMatrix = confusion_matrix(y_labeled, cvPredictions, labels=self._classes)

        self._cvMetrics = {
            'cvAccuracy': float(cvAccuracy),
            'cvF1': float(cvF1),
            'cvReport': cvReport,
            'confusionMatrix': confMatrix.tolist(),
            'nSamples': int(len(y_labeled)),
            'nFolds': nFolds,
        }

        logger.info(f'CV Accuracy: {cvAccuracy:.3f}, CV Macro F1: {cvF1:.3f}')

        # -- Train final model on all data -- #
        xFinal = X_labeled.copy()
        yFinal = y_labeled.copy()

        if oversample:
            xFinal, yFinal = _oversampleMinority(xFinal, yFinal)

        self._scaler = StandardScaler()
        xFinalScaled = self._scaler.fit_transform(xFinal)

        self._model = self._buildModel()
        self._model.fit(xFinalScaled, yFinal)

        # Capture training loss history
        self._trainingHistory = {
            'lossHistory': list(self._model.loss_curve_),
            'nIter': self._model.n_iter_,
        }

        return {
            **self._cvMetrics,
            **self._trainingHistory,
        }

    def _buildModel(self) -> MLPClassifier:

        '''

        Build a fresh MLPClassifier with the configured hyperparameters.

        Returns:
        --------
        MLPClassifier : Untrained model instance

        '''

        return MLPClassifier(
            hidden_layer_sizes=self.hiddenLayers,
            activation='relu',
            solver='adam',
            alpha=self.alpha,
            learning_rate='adaptive',
            learning_rate_init=self.learningRateInit,
            max_iter=self.maxIter,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=20,
            random_state=self.randomState,
            verbose=False,
        )

    # ------------------------------------------------------------------ #
    # -- Prediction -- #
    # ------------------------------------------------------------------ #

    def predict(self, X: np.ndarray) -> np.ndarray:

        '''

        Predict engineering levels for feature vectors.

        Parameters:
        -----------
        X : np.ndarray
            Feature matrix (n_samples x n_features)

        Returns:
        --------
        np.ndarray : Predicted labels (n_samples,)

        '''

        if self._model is None or self._scaler is None:
            raise RuntimeError('Model not trained. Call train() or load() first.')

        xScaled = self._scaler.transform(X)
        return self._model.predict(xScaled)

    def predictWithConfidence(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:

        '''

        Predict engineering levels with confidence scores.

        Parameters:
        -----------
        X : np.ndarray
            Feature matrix (n_samples x n_features)

        Returns:
        --------
        Tuple[np.ndarray, np.ndarray] :
            - Predicted labels (n_samples,)
            - Confidence scores (n_samples,) -- max class probability

        '''

        if self._model is None or self._scaler is None:
            raise RuntimeError('Model not trained. Call train() or load() first.')

        xScaled = self._scaler.transform(X)
        predictions = self._model.predict(xScaled)
        probabilities = self._model.predict_proba(xScaled)
        confidence = probabilities.max(axis=1)

        return predictions, confidence

    def predictProba(self, X: np.ndarray) -> np.ndarray:

        '''

        Get full class probability distribution for each sample.

        Parameters:
        -----------
        X : np.ndarray
            Feature matrix (n_samples x n_features)

        Returns:
        --------
        np.ndarray : Probability matrix (n_samples x n_classes)

        '''

        if self._model is None or self._scaler is None:
            raise RuntimeError('Model not trained. Call train() or load() first.')

        xScaled = self._scaler.transform(X)
        return self._model.predict_proba(xScaled)

    # ------------------------------------------------------------------ #
    # -- Interpretability -- #
    # ------------------------------------------------------------------ #

    def getWeights(self) -> List[np.ndarray]:

        '''

        Get the weight matrices for each layer of the network.
        Layer 0 is input->hidden1, layer 1 is hidden1->hidden2, etc.

        Returns:
        --------
        List[np.ndarray] : Weight matrices [W1, W2, ..., Wn]

        '''

        if self._model is None:
            raise RuntimeError('Model not trained.')

        return [w.copy() for w in self._model.coefs_]

    def getBiases(self) -> List[np.ndarray]:

        '''

        Get the bias vectors for each layer.

        Returns:
        --------
        List[np.ndarray] : Bias vectors [b1, b2, ..., bn]

        '''

        if self._model is None:
            raise RuntimeError('Model not trained.')

        return [b.copy() for b in self._model.intercepts_]

    def getFeatureImportance(
        self,
        X: np.ndarray,
        y: np.ndarray,
        nRepeats: int = 10,
    ) -> pd.DataFrame:

        '''

        Compute permutation feature importance by shuffling each
        feature and measuring the drop in accuracy.

        Parameters:
        -----------
        X : np.ndarray
            Feature matrix (labeled samples only)
        y : np.ndarray
            True labels
        nRepeats : int
            Number of shuffling repetitions per feature

        Returns:
        --------
        pd.DataFrame : Columns [feature, importance_mean, importance_std]
                        sorted by importance descending

        '''

        if self._model is None or self._scaler is None:
            raise RuntimeError('Model not trained.')

        xScaled = self._scaler.transform(X)
        result = permutation_importance(
            self._model, xScaled, y,
            n_repeats=nRepeats,
            random_state=self.randomState,
            scoring='accuracy',
        )

        names = self._featureNames if self._featureNames else [f'feature_{i}' for i in range(X.shape[1])]

        importanceDf = pd.DataFrame({
            'feature': names,
            'importance_mean': result.importances_mean,
            'importance_std': result.importances_std,
        }).sort_values('importance_mean', ascending=False).reset_index(drop=True)

        return importanceDf

    # ------------------------------------------------------------------ #
    # -- Persistence -- #
    # ------------------------------------------------------------------ #

    def save(self, cacheDir: str = _defaultCacheDir) -> str:

        '''

        Save the trained model, scaler, and metadata to disk.

        Parameters:
        -----------
        cacheDir : str
            Directory to save model artifacts

        Returns:
        --------
        str : Path to the saved model directory

        '''

        if self._model is None:
            raise RuntimeError('No trained model to save.')

        os.makedirs(cacheDir, exist_ok=True)

        # Save model and scaler
        joblib.dump(self._model, os.path.join(cacheDir, 'trained_model.joblib'))
        joblib.dump(self._scaler, os.path.join(cacheDir, 'scaler.joblib'))

        # Save metadata as JSON
        metadata = {
            'featureNames': self._featureNames,
            'companyEncoder': self._companyEncoder,
            'classes': self._classes.tolist(),
            'hiddenLayers': list(self.hiddenLayers),
            'alpha': self.alpha,
            'learningRateInit': self.learningRateInit,
            'maxIter': self.maxIter,
            'cvMetrics': {
                k: v for k, v in self._cvMetrics.items()
                if k != 'cvReport'  # report is too verbose for JSON
            },
            'trainingHistory': self._trainingHistory,
        }

        with open(os.path.join(cacheDir, 'metadata.json'), 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f'Model saved to {cacheDir}')
        return cacheDir

    def load(self, cacheDir: str = _defaultCacheDir) -> bool:

        '''

        Load a previously trained model from disk.

        Parameters:
        -----------
        cacheDir : str
            Directory containing model artifacts

        Returns:
        --------
        bool : True if loaded successfully, False if no model found

        '''

        modelPath = os.path.join(cacheDir, 'trained_model.joblib')
        scalerPath = os.path.join(cacheDir, 'scaler.joblib')
        metadataPath = os.path.join(cacheDir, 'metadata.json')

        if not os.path.exists(modelPath):
            logger.warning(f'No trained model found at {cacheDir}')
            return False

        try:
            self._model = joblib.load(modelPath)
            self._scaler = joblib.load(scalerPath)
        except Exception as e:
            # Typically a numpy version mismatch (BitGenerator error) after
            # switching Python interpreters. Delete stale files and prompt retrain.
            logger.error(
                f'Failed to load model (likely numpy version mismatch after '
                f'interpreter change): {e}. Deleting stale files — retrain required.'
            )
            for stale in [modelPath, scalerPath, metadataPath]:
                if os.path.exists(stale):
                    os.remove(stale)
            return False

        if os.path.exists(metadataPath):
            with open(metadataPath, 'r') as f:
                metadata = json.load(f)
            self._featureNames = metadata.get('featureNames', [])
            self._companyEncoder = metadata.get('companyEncoder', {})
            self._classes = np.array(metadata.get('classes', []))
            self.hiddenLayers = tuple(metadata.get('hiddenLayers', [64, 32]))
            self.alpha = metadata.get('alpha', 0.001)
            self.learningRateInit = metadata.get('learningRateInit', 0.001)
            self.maxIter = metadata.get('maxIter', 500)
            self._cvMetrics = metadata.get('cvMetrics', {})
            self._trainingHistory = metadata.get('trainingHistory', {})

        logger.info(f'Model loaded from {cacheDir}')
        return True

    # ------------------------------------------------------------------ #
    # -- Accessors -- #
    # ------------------------------------------------------------------ #

    @property
    def isTrained(self) -> bool:
        '''Whether a model has been trained or loaded.'''
        return self._model is not None

    @property
    def featureNames(self) -> List[str]:
        '''Feature names used by the model.'''
        return self._featureNames

    @property
    def companyEncoder(self) -> dict:
        '''Company encoder used by the model.'''
        return self._companyEncoder

    @property
    def cvMetrics(self) -> dict:
        '''Cross-validation metrics from training.'''
        return self._cvMetrics

    @property
    def trainingHistory(self) -> dict:
        '''Training loss history.'''
        return self._trainingHistory

    @property
    def classes(self) -> np.ndarray:
        '''Class labels known to the model.'''
        return self._classes


# ---------------------------------------------------------------------- #
# -- Helper Functions -- #
# ---------------------------------------------------------------------- #

def _oversampleMinority(
    X: np.ndarray,
    y: np.ndarray,
    randomState: int = 42,
) -> Tuple[np.ndarray, np.ndarray]:

    '''

    Oversample minority classes to match the majority class count.
    This is a simple random oversampling strategy that duplicates
    minority samples. Appropriate for small datasets where SMOTE
    would introduce artifacts.

    Parameters:
    -----------
    X : np.ndarray
        Feature matrix
    y : np.ndarray
        Label vector
    randomState : int
        Random seed

    Returns:
    --------
    Tuple[np.ndarray, np.ndarray] : Oversampled (X, y)

    '''

    classes, counts = np.unique(y, return_counts=True)
    maxCount = counts.max()

    xParts = []
    yParts = []

    for cls, count in zip(classes, counts):
        mask = y == cls
        xClass = X[mask]
        yClass = y[mask]

        if count < maxCount:
            # Resample to match majority class
            xResampled, yResampled = resample(
                xClass, yClass,
                replace=True,
                n_samples=maxCount,
                random_state=randomState,
            )
            xParts.append(xResampled)
            yParts.append(yResampled)
        else:
            xParts.append(xClass)
            yParts.append(yClass)

    return np.vstack(xParts), np.concatenate(yParts)


# ---------------------------------------------------------------------- #
# -- Convenience: Train From DataFrame -- #
# ---------------------------------------------------------------------- #

def trainFromDataFrame(
    df: pd.DataFrame,
    labelCol: str = 'Vlvl',
    hiddenLayers: Tuple[int, ...] = (64, 32),
    alpha: float = 0.001,
    learningRateInit: float = 0.001,
    maxIter: int = 500,
    nFolds: int = 5,
    savePath: Optional[str] = None,
) -> Tuple[BucketClassifier, dict]:

    '''

    End-to-end convenience function: build features from a DataFrame,
    train the classifier, optionally save it, and return both the
    classifier and training results.

    Parameters:
    -----------
    df : pd.DataFrame
        Training data with label column and feature columns
    labelCol : str
        Column containing integer level labels
    hiddenLayers : tuple of int
        MLP hidden layer sizes
    alpha : float
        L2 regularization strength
    learningRateInit : float
        Initial learning rate
    maxIter : int
        Maximum training iterations
    nFolds : int
        Number of CV folds
    savePath : str, optional
        If provided, save the trained model to this directory

    Returns:
    --------
    Tuple[BucketClassifier, dict] : (trained classifier, training results)

    '''

    # Build features
    X, featureNames, companyEncoder = buildFeatureMatrix(df)
    y = buildLabelVector(df, labelCol)

    # Train
    classifier = BucketClassifier(
        hiddenLayers=hiddenLayers,
        alpha=alpha,
        learningRateInit=learningRateInit,
        maxIter=maxIter,
    )

    results = classifier.train(
        X, y,
        featureNames=featureNames,
        companyEncoder=companyEncoder,
        nFolds=nFolds,
    )

    # Save if requested
    if savePath is not None:
        classifier.save(savePath)

    return classifier, results
