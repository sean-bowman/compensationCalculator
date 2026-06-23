# Neural Network Classifier

## Overview

The neural network classifier is a scikit-learn `MLPClassifier` trained to map aerospace job listings into engineering levels (1-5). It operates on hand-engineered features extracted from job title, salary, experience, company, and discipline fields, and integrates into the existing classification pipeline as a weighted voting signal alongside keyword-based heuristics.

**Location:** `tools/featureEngineering.py`, `tools/neuralClassifier.py`, `tools/nnVisualizations.py`

**Streamlit page:** `views/nnShowcase.py` (sidebar: Neural Network > NN Classifier)

---

## Table of Contents

- [Background and Motivation](#background-and-motivation)
- [Model Selection Justification](#model-selection-justification)
- [Architecture](#architecture)
- [Feature Engineering](#feature-engineering)
- [Training Pipeline](#training-pipeline)
- [Pipeline Integration](#pipeline-integration)
- [Streamlit Showcase](#streamlit-showcase)
- [Model Persistence](#model-persistence)
- [Performance Baseline](#performance-baseline)
- [Limitations and Future Work](#limitations-and-future-work)
- [API Reference](#api-reference)
- [References](#references)

---

## Background and Motivation

The original classification pipeline in `validatedAnalysis.py` assigns job listings to engineering levels (1-5) using three heuristic signals:

1. **Title keywords** -- pattern-matching for seniority terms ('senior', 'staff', 'principal')
2. **Years of experience** -- regex extraction from job descriptions
3. **Salary band proximity** -- scoring how well a salary midpoint fits each band's range

These signals are combined via weighted voting in `_computeBucketAssignment()`. The system works but has structural limitations:

- **No learning from data.** All rules are manually curated keyword lists. When the labor market introduces new title patterns (e.g., 'MTS' for Member of Technical Staff), the system misclassifies until someone manually adds the keyword.
- **No nonlinear feature combinations.** A 'Senior Engineer' at a seed-stage startup with a low salary band and a 'Senior Engineer' at a large company with a high salary band both match the 'senior' keyword, but they belong in different levels. The keyword system cannot distinguish them without separate salary logic that operates independently.
- **Class imbalance blindness.** The heuristic weights are manually tuned and do not adapt to the actual distribution of labeled data.
- **No confidence calibration.** The existing confidence score measures signal agreement, not predictive accuracy.

The neural network addresses these by learning from the labeled job listings in the synthetic market survey (`documentation/marketSurveySynthetic.csv`). It discovers feature interactions that the keyword system cannot express. Note: the bundled synthetic survey is small, so the classifier is intended as a demonstration of the pipeline rather than a production-accurate model.

---

## Model Selection Justification

**Selected approach:** scikit-learn `MLPClassifier` (multi-layer perceptron) on hand-engineered features.

Four alternatives were evaluated:

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **scikit-learn MLP** | Full weight visibility, minimal code, works with 500 samples, fast training | Limited to fixed features, no automatic feature learning | Selected |
| **TensorFlow / Keras** | Industry standard, GPU support, extensive ecosystem | Massive overhead for 500 samples, same math as scikit-learn MLP, no educational advantage at this scale | Rejected |
| **NEAT (neuroevolution)** | Discovers network topology automatically, biologically interesting | `neat-python` library is poorly maintained, slow convergence, evolved topologies are hard to interpret | Rejected |
| **Fine-tuned transformer** | State-of-the-art NLP, handles raw text | Catastrophic overfitting on 500 samples, requires GPU, hides all learning inside pretrained weights | Rejected |
| **Sentence embeddings + small classifier** | Powerful text representation, no manual feature engineering | Embedding model does the hard work -- you learn nothing about neural networks; educational value is minimal | Rejected |

**Why scikit-learn MLP is the right choice for this problem:**

1. **Data scale.** 499 labeled samples with 5 classes. A 2-hidden-layer MLP with 60 input features and (64, 32) neurons has ~6,500 trainable parameters -- well within the regime where 500 samples can train a useful model with proper regularization.

2. **Educational transparency.** Every weight is directly accessible via `model.coefs_`. You can visualize exactly which features connect to which neurons and how the network makes decisions. This is the primary design goal stated in the project objectives.

3. **Interpretability.** Permutation importance, weight heatmaps, and per-prediction explanations are all straightforward with a small MLP. These would be meaningless or prohibitively expensive with a transformer.

4. **Integration simplicity.** scikit-learn is a single `pip install` with no C++ compilation, no CUDA setup, and no model download. The trained model serializes to a 158 KB joblib file.

---

## Architecture

The classifier uses a feedforward neural network (multi-layer perceptron) with the following topology:

```txt
Input Layer          Hidden Layer 1       Hidden Layer 2       Output Layer
(60 features)        (64 neurons)         (32 neurons)         (5 classes)
                       ReLU                  ReLU                Softmax
    x_0  ----\
    x_1  -----\------> h1_0  ----\
    x_2  ------\------> h1_1  ----\------> h2_0  ----\
     .          \------> ...       \------> ...       \------> Level 1
     .           \-----> h1_63      \-----> h2_31      \-----> Level 2
     .                                                  \----> Level 3
    x_59                                                 \---> Level 4
                                                          \--> Level 5
```

**Key hyperparameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `hiddenLayers` | `(64, 32)` | Two hidden layers with 64 and 32 neurons |
| `activation` | `relu` | Rectified Linear Unit: f(x) = max(0, x) |
| `solver` | `adam` | Adaptive Moment Estimation optimizer [Kingma & Ba, 2015] |
| `alpha` | `0.001` | L2 regularization strength (weight decay) |
| `learningRateInit` | `0.001` | Initial learning rate for Adam |
| `learning_rate` | `adaptive` | Reduces LR when loss stops improving |
| `early_stopping` | `True` | Stops training when validation loss plateaus |
| `validation_fraction` | `0.15` | 15% of training data held out for early stopping |
| `n_iter_no_change` | `20` | Patience: 20 epochs of no improvement before stopping |
| `maxIter` | `500` | Hard cap on training epochs |

All hyperparameters are configurable via the Streamlit Training tab.

---

## Feature Engineering

The feature pipeline (`featureEngineering.py`) converts each job listing row into a fixed-width numeric vector. Features are organized into 7 groups:

| Group | Count | Source Columns | Description |
|-------|-------|----------------|-------------|
| **Seniority flags** | 17 | `Listing` | Binary flags for seniority keywords: principal, fellow, distinguished, chief, staff, lead engineer, tech lead, team lead, senior, sr., junior, jr., associate, entry level, entry-level, intern, co-op, new grad |
| **Title structure** | 4 | `Listing` | Word count (/10), has roman numeral level, has numeric level, character length (/100) |
| **Discipline flags** | 19 | `Listing`, `Discipline` | Binary flags for: propulsion, avionics, gnc, structures, thermal, mechanical, electrical, software, test, manufacturing, systems, quality, integration, fluids, materials, analysis, gse, launch, instrumentation |
| **Salary features** | 5 | `Min`, `Max` | Normalized min (/200K), max (/200K), midpoint (/200K), range width (/200K), log(midpoint) scaled. All zero if salary data is missing. |
| **Experience features** | 2 | `ExpReq` | Normalized YoE (/20, or -0.05 if missing), has_experience flag (1.0/0.0) |
| **Management flags** | 2 | `Listing`, `Description` | Binary: title contains management keywords, description contains management phrases |
| **Company encoding** | 10 | `Company` | One-hot encoding of top 9 companies by frequency + 'other' bucket. Companies are frequency-ranked from the training data. |

**Total: 59 fixed features + company encoding = ~60 features** (exact count depends on unique companies in training data).

**Normalization strategy:**

- Binary features (keywords): 0.0 or 1.0, no scaling needed
- Continuous features (salary, YoE, title length): manually scaled to [0, 1] range during feature extraction
- All features are then standardized by `StandardScaler` (zero mean, unit variance) before being passed to the MLP -- this is critical because MLPs are sensitive to feature scale

**Missing data handling:**

- Missing salary: all 5 salary features are set to 0.0
- Missing experience: YoE is set to -0.05 (distinguishable from 0 years), has_data flag is 0.0
- Missing description: management description flag is 0.0
- Unknown company: activates the 'other' one-hot slot

---

## Training Pipeline

Training follows a rigorous evaluation-first approach: cross-validation metrics are computed before the final model is trained.

**Step 1: Data preparation**

- Load 500-row survey spreadsheet via `loadMarketSurveyData()`
- Extract feature matrix (60 features) and label vector (`Vlvl` column, levels 1-5)
- Filter out 1 unlabeled sample (class 0) -- 499 samples used for training

**Step 2: Stratified K-Fold cross-validation** (default k=5)

For each fold:

1. Split data into ~399 training and ~100 validation samples, preserving class proportions
2. **Oversample minority classes** in training fold only (not validation) -- Level 5 has only 16 samples vs Level 3's 170. Random oversampling with replacement duplicates minority samples to match majority class count. This is preferred over SMOTE for small, high-dimensional datasets where synthetic interpolation can create implausible feature combinations [He & Garcia, 2009].
3. Fit `StandardScaler` on training fold, transform both folds
4. Train a fresh `MLPClassifier` on scaled training data
5. Record predictions on validation fold

After all folds, compute:

- **Accuracy** -- overall fraction correct
- **Macro F1** -- unweighted average of per-class F1 scores (penalizes poor minority-class performance)
- **Confusion matrix** -- true vs predicted for each class pair
- **Per-class precision, recall, F1** -- diagnostic for which levels the model struggles with

**Step 3: Final model training**

- Oversample the full labeled dataset
- Fit a final `StandardScaler` on all data
- Train the production `MLPClassifier` on all scaled data
- Record the training loss curve for convergence diagnostics

**Class distribution in training data:**

| Level | Count | Percentage |
|-------|-------|------------|
| Level 1 (Associate) | 54 | 10.8% |
| Level 2 (Engineer) | 141 | 28.3% |
| Level 3 (Senior) | 170 | 34.1% |
| Level 4 (Staff) | 118 | 23.6% |
| Level 5 (Principal) | 16 | 3.2% |

---

## Pipeline Integration

The neural network integrates into the existing classification pipeline in `validatedAnalysis.py` as a 4th weighted signal alongside YoE, title keywords, and salary band proximity.

**Lazy loading:** The trained model is loaded on first use via `_getClassifier()`. If no trained model exists in `.modelCache/`, the NN signal is `None` and the pipeline falls back to the original 3-signal behavior with no error.

**Per-row inference:** `_inferLevelFromNN(row)` extracts features from a single DataFrame row, runs the model, and returns `(predictedLevel, confidence)`.

**Weight scheme in `_computeBucketAssignment()`:**

When a trained NN model is available:

| Signal | Weight (YoE available) | Weight (no YoE) |
|--------|----------------------|-----------------|
| Years of Experience | 40% | -- |
| Title Keywords | 20% | 35% |
| Salary Band | 10% | 25% |
| **Neural Network** | **30%** | **40%** |

When no NN model is loaded (original behavior preserved):

| Signal | Weight (YoE available) | Weight (no YoE) |
|--------|----------------------|-----------------|
| Years of Experience | 55% | -- |
| Title Keywords | 35% | 60% |
| Salary Band | 10% | 40% |

The NN receives higher weight when YoE is missing because it has learned to infer level from the full feature combination (title + salary + company + discipline), partially compensating for the absent experience signal.

---

## Streamlit Showcase

The NN Showcase page (`views/nnShowcase.py`) is accessible via the "Neural Network" section in the sidebar. It has 4 tabs:

### Tab 1: Model Overview

Displays the trained model's architecture and performance at a glance.

**Visualizations:**

1. **Network Architecture Diagram** (`plotNetworkArchitecture`) -- A node-and-edge graph showing all layers of the network. Input nodes are labeled with feature names, output nodes with level labels. Edges connect adjacent layers with line thickness proportional to the absolute weight value and color indicating sign (green = positive, red = negative). Large layers are truncated to 15 nodes with an overflow indicator. *What it tells you:* The overall shape and scale of the model -- how many parameters connect each layer, and which connections carry the most weight.

2. **Confusion Matrix** (`plotConfusionMatrix`) -- A 5x5 heatmap where row *i*, column *j* shows how many Level *i* samples were predicted as Level *j* during cross-validation. Each cell includes the raw count and the row-normalized percentage. A perfect classifier would have all weight on the diagonal. *What it tells you:* Where the model confuses levels -- e.g., if Level 2 and Level 3 are frequently swapped, the model struggles to distinguish mid-career roles.

3. **Feature Importance** (`plotFeatureImportance`) -- A horizontal bar chart showing the top 20 features ranked by permutation importance. For each feature, the model's accuracy is measured with that feature's values randomly shuffled. Features whose shuffling causes the largest accuracy drop are the most important. Error bars show standard deviation across shuffling repetitions. *What it tells you:* Which input signals the model relies on most. Salary and experience features typically dominate, followed by seniority keywords and company identity.

4. **Training Loss Curve** (`plotTrainingLoss`) -- A line chart showing the cross-entropy loss at each training epoch. A healthy curve decreases rapidly in early epochs, then flattens. If the curve is still decreasing steeply when training stops, `maxIter` may need increasing. If it oscillates, the learning rate may be too high. *What it tells you:* Whether the model converged during training and whether the hyperparameters are appropriate.

### Tab 2: Training

Interactive training controls with real-time feedback.

- **Hyperparameter sliders:** Hidden layer sizes (16-128), L2 alpha (0.0001-0.1), learning rate (0.0001-0.01), max epochs (100-1000), CV folds (3-10)
- **Train button:** Loads data, builds features, runs stratified CV, trains final model, saves to disk
- **Results display:** Accuracy/F1 metrics, per-class precision/recall/F1 table, confusion matrix + loss curve side-by-side

### Tab 3: Live Classification

Side-by-side comparison of the keyword-only system vs the NN-augmented system on the survey dataset.

**Visualizations:**

5. **Before/After Comparison** (`plotBeforeAfterComparison`) -- Grouped bar chart showing how many listings each system assigns to each level. Highlights systematic shifts -- e.g., if the NN moves many listings from Level 3 to Level 2, the keyword system may be over-crediting the 'senior' keyword. *What it tells you:* The aggregate impact of adding the NN signal to the classification pipeline.

6. **Confidence Distribution** (`plotConfidenceDistribution`) -- Overlaid histograms showing the distribution of prediction confidence (max class probability) for each predicted level. A well-calibrated model has high confidence for correct predictions and low confidence for uncertain ones. *What it tells you:* Whether the model is appropriately uncertain -- if all predictions are >0.95 confidence, the model may be overconfident; if many are below 0.5, the features may be insufficient.

- **Classification Changes Table** -- DataFrame showing rows where the keyword and NN systems disagree, with true labels for comparison.

### Tab 4: Model Internals

Deep inspection of the trained model's learned representations.

**Visualizations:**

7. **Weight Heatmap** (`plotWeightHeatmap`) -- A color-coded matrix showing the weight values for a selected layer. For the input-to-hidden1 layer, rows are feature names and columns are hidden neurons. Red/blue diverging colorscale centered at zero. *What it tells you:* Which features each hidden neuron responds to. A neuron with strong positive weights on salary features and strong negative weights on junior keywords has learned to detect senior-level roles.

8. **2D Decision Boundary** (`plotDecisionBoundary2D`) -- PCA projection of the 60-dimensional feature space down to 2 dimensions. Points are colored by true class label. Correctly classified points are circles; misclassified points are X markers. Axis labels show the percentage of variance captured by each principal component. *What it tells you:* How separable the classes are in feature space. If classes overlap heavily in the 2D projection, the classification problem is inherently difficult and higher accuracy may require richer features.

9. **Prediction Explainer** (`plotPredictionExplainer`) -- Two-panel figure for a single selected row. Left panel: top 10 features by absolute magnitude (showing which features are "active" for this listing). Right panel: class probability distribution (showing how confident the model is about each level). *What it tells you:* Why the model made a specific prediction -- which features drove the decision and how close the runner-up class was.

---

## Model Persistence

Trained models are saved to `tools/.modelCache/` (gitignored). Three files are produced:

| File | Format | Size | Contents |
|------|--------|------|----------|
| `trained_model.joblib` | joblib (pickle) | ~158 KB | Serialized `MLPClassifier` with all learned weights and biases |
| `scaler.joblib` | joblib (pickle) | ~2 KB | `StandardScaler` fitted on training data (mean and variance per feature) |
| `metadata.json` | JSON | ~5 KB | Feature names, company encoder, class labels, hyperparameters, CV metrics, loss history |

The model loads automatically when `validatedAnalysis.py` is first used (lazy loading via `_getClassifier()`). If the cache directory is deleted, the pipeline falls back to keyword-only classification.

---

## Performance Baseline

Initial training on the full 499-sample dataset with default hyperparameters:

**Aggregate metrics (5-fold stratified CV):**

| Metric | Value |
|--------|-------|
| CV Accuracy | 63.7% |
| CV Macro F1 | 0.60 |
| Training Epochs | 73 (early stopping) |
| Final Training Loss | 0.1133 |

**Per-class metrics:**

| Class | Precision | Recall | F1 | Support |
|-------|-----------|--------|-----|---------|
| Level 1 | 0.51 | 0.72 | 0.60 | 54 |
| Level 2 | 0.63 | 0.50 | 0.56 | 141 |
| Level 3 | 0.68 | 0.72 | 0.70 | 170 |
| Level 4 | 0.73 | 0.64 | 0.68 | 118 |
| Level 5 | 0.38 | 0.56 | 0.45 | 16 |

**Top 5 features by permutation importance:**

| Feature | Mean Accuracy Drop |
|---------|-------------------|
| `salary_log_midpoint` | +0.080 |
| `experience_yoe` | +0.080 |
| `salary_midpoint` | +0.061 |
| `company_blue_origin` | +0.056 |
| `seniority_senior` | +0.053 |

Salary and experience features dominate, which aligns with the intuition that compensation level is most strongly determined by pay range and career stage. Company identity matters because different employers use different title conventions and pay scales.

---

## Limitations and Future Work

**Current limitations:**

- **Level 5 scarcity.** Only 16 Principal-level samples in the training data. Oversampling helps but cannot substitute for genuine data diversity. The model achieves only 0.45 F1 on Level 5.
- **No description text features.** The model uses only title keywords, not the full job description. Adding TF-IDF or bag-of-words features from descriptions could capture duty-level signals ('lead a team', 'architecting systems') that title alone misses.
- **Static company encoding.** New companies not in the training set all map to a single 'other' bucket. The model cannot distinguish between an unknown startup and an unknown defense prime.
- **No temporal features.** The model does not account for salary inflation or market shifts over time.
- **Training on survey data, inference on scraped data.** The survey data has curated, clean titles; scraped data may have formatting artifacts, HTML entities, or truncated titles that reduce feature quality.

**Potential improvements:**

- Add sentence-level embeddings (e.g., `sentence-transformers/all-MiniLM-L6-v2`) as additional features for description-level semantics -- but only after expanding the training set to >1000 samples to avoid overfitting on the embedding dimensions.
- Collect more Level 5 / Principal-level labeled examples from targeted scraping.
- Implement active learning: flag low-confidence predictions for human review, then add reviewed labels back to the training set.
- Add time-based features if scrape history accumulates (salary trend relative to historical median for the same company/role).

---

## API Reference

### featureEngineering.py

```python
# Build a company encoder from training data
buildCompanyEncoder(df: pd.DataFrame, maxCompanies: int = 10) -> dict

# Extract feature vector for a single row
extractFeatureVector(row: pd.Series, companyEncoder: dict) -> np.ndarray

# Build full feature matrix from a DataFrame
buildFeatureMatrix(df: pd.DataFrame, companyEncoder: Optional[dict] = None) -> Tuple[np.ndarray, List[str], dict]

# Extract label vector (Vlvl column -> integer array)
buildLabelVector(df: pd.DataFrame, labelCol: str = 'Vlvl') -> np.ndarray
```

### neuralClassifier.py

```python
class BucketClassifier:
    def __init__(self, hiddenLayers=(64,32), alpha=0.001, learningRateInit=0.001, maxIter=500, randomState=42)

    # Training
    def train(self, X, y, featureNames=None, companyEncoder=None, nFolds=5, oversample=True) -> dict

    # Prediction
    def predict(self, X) -> np.ndarray
    def predictWithConfidence(self, X) -> Tuple[np.ndarray, np.ndarray]
    def predictProba(self, X) -> np.ndarray

    # Interpretability
    def getWeights(self) -> List[np.ndarray]
    def getBiases(self) -> List[np.ndarray]
    def getFeatureImportance(self, X, y, nRepeats=10) -> pd.DataFrame

    # Persistence
    def save(self, cacheDir='.modelCache') -> str
    def load(self, cacheDir='.modelCache') -> bool

    # Properties
    isTrained: bool
    featureNames: List[str]
    companyEncoder: dict
    cvMetrics: dict
    trainingHistory: dict
    classes: np.ndarray

# Convenience function: build features + train + optionally save
trainFromDataFrame(df, labelCol='Vlvl', hiddenLayers=(64,32), alpha=0.001,
                   learningRateInit=0.001, maxIter=500, nFolds=5, savePath=None)
    -> Tuple[BucketClassifier, dict]
```

### nnVisualizations.py

All functions return `plotly.graph_objects.Figure`.

```python
# 1. Network architecture node-and-edge diagram
plotNetworkArchitecture(layerSizes, weights=None, featureNames=None, classNames=None, maxNodes=20)

# 2. Weight matrix heatmap for a specific layer
plotWeightHeatmap(weights, featureNames=None, classNames=None, layerIndex=0)

# 3. Horizontal bar chart of permutation feature importance
plotFeatureImportance(importanceDf, topN=20)

# 4. Annotated confusion matrix heatmap
plotConfusionMatrix(confMatrix, classNames=None)

# 5. Confidence histogram colored by predicted class
plotConfidenceDistribution(predictions, confidences, classNames=None)

# 6. PCA-projected 2D scatter (circles=correct, X=misclassified)
plotDecisionBoundary2D(X, y, predictions, classNames=None)

# 7. Grouped bar chart: keyword vs NN classification distribution
plotBeforeAfterComparison(keywordBuckets, nnBuckets)

# 8. Training loss over epochs
plotTrainingLoss(lossHistory)

# 9. Two-panel per-sample explainer (top features + class probabilities)
plotPredictionExplainer(featureVector, featureNames, classProbabilities, classNames=None, topN=10)
```

---

## References

### Software

- **scikit-learn MLPClassifier.** Multi-layer Perceptron classifier. scikit-learn documentation. https://scikit-learn.org/stable/modules/generated/sklearn.neural_network.MLPClassifier.html
- **scikit-learn StandardScaler.** Standardize features by removing mean and scaling to unit variance. https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html
- **scikit-learn StratifiedKFold.** Stratified K-Folds cross-validator. https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.StratifiedKFold.html
- **scikit-learn permutation_importance.** Permutation feature importance. https://scikit-learn.org/stable/modules/permutation_importance.html

### Literature

- Pedregosa, F. et al. (2011). *Scikit-learn: Machine Learning in Python.* Journal of Machine Learning Research, 12, 2825-2830. The foundational paper for the scikit-learn library used throughout this implementation.
- Bishop, C. M. (2006). *Pattern Recognition and Machine Learning.* Chapter 5: Neural Networks. Springer. Provides the mathematical foundation for feedforward networks, backpropagation, and regularization techniques used in the MLP.
- Kingma, D. P. & Ba, J. (2015). *Adam: A Method for Stochastic Optimization.* ICLR 2015. Describes the Adam optimizer used for training, which adapts the learning rate per-parameter based on first and second moment estimates of the gradient.
- He, H. & Garcia, E. A. (2009). *Learning from Imbalanced Data.* IEEE Transactions on Knowledge and Data Engineering, 21(9), 1263-1284. Surveys class imbalance handling strategies including the random oversampling approach used here to address the Level 5 scarcity problem.
- Breiman, L. (2001). *Random Forests.* Machine Learning, 45, 5-32. Introduces the permutation importance concept later generalized to any model by scikit-learn's `permutation_importance` function.
- Jolliffe, I. T. (2002). *Principal Component Analysis.* 2nd ed. Springer. Describes PCA, used in the 2D decision boundary visualization to project the 60-dimensional feature space into two interpretable dimensions.
