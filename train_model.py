"""train_model.py -- trains the Health Agent's Random Forest on the synthetic simulation dataset."""
import os
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import GroupShuffleSplit
import health_model as hm
from generate_data import build_dataset, FEATURES


def train(path="health_model.joblib", pilgrims=10000, verbose=True):
    df = build_dataset(pilgrims, 2, 42)
    os.makedirs("data", exist_ok=True)
    df.to_csv("data/health_dataset.csv", index=False)
    # Each pilgrim has two snapshots, so split by pilgrim: a pilgrim is either in training or in testing.
    tr_idx, te_idx = next(GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
                          .split(df, groups=df["pilgrim_id"]))
    X_tr, y_tr = df.iloc[tr_idx][FEATURES], df.iloc[tr_idx]["risk_class"]
    X_te, y_te = df.iloc[te_idx][FEATURES], df.iloc[te_idx]["risk_class"]
    model = RandomForestClassifier(n_estimators=200, min_samples_leaf=5, random_state=42, n_jobs=-1)
    model.fit(X_tr, y_tr)
    pred = model.predict(X_te)
    acc = accuracy_score(y_te, pred)
    if verbose:
        print("hold-out accuracy:", round(acc, 3))
        print(classification_report(y_te, pred, target_names=hm.CLASS_NAMES))
    joblib.dump({"model": model, "features": FEATURES, "class_names": hm.CLASS_NAMES,
                 "class_midpoints": [15, 40, 60, 85]}, path)
    return acc


def _compatible(path):
    """True when the saved model uses the same features and class names as the current code."""
    try:
        b = joblib.load(path)
        return (list(b["features"]) == list(FEATURES) and list(b["class_names"]) == list(hm.CLASS_NAMES)
                and list(b["model"].feature_names_in_) == list(FEATURES))
    except Exception:
        return False


def ensure_model(path="health_model.joblib"):
    """Load the saved model if it matches the current features, otherwise train a new one (a few seconds)."""
    if os.path.exists(path) and _compatible(path):
        return "loaded"
    retrain = os.path.exists(path)
    train(path, verbose=False)
    return "retrained (saved model did not match)" if retrain else "trained"


if __name__ == "__main__":
    train()
