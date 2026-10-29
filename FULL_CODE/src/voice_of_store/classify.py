"""Issue type, severity and actionable classifier. Trained at run time from the public labelled sample only."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import make_union
from sklearn.svm import LinearSVC

from . import config as C
from .text import model_input


def _vectoriser():
    return make_union(
        TfidfVectorizer(analyzer="char_wb", ngram_range=C.CHAR_NGRAM, min_df=C.MIN_DF, sublinear_tf=True),
        TfidfVectorizer(ngram_range=C.WORD_NGRAM, min_df=C.MIN_DF, sublinear_tf=True),
    )


def _svm(c: float) -> LinearSVC:
    return LinearSVC(C=c, class_weight="balanced", max_iter=5000, random_state=C.SEED)


def margin_confidence(scores: np.ndarray) -> np.ndarray:
    """Softmax over SVM margins: each row sums to 1 and keeps the margin order. A ranking score, not a calibrated probability."""
    z = scores * C.CONF_TEMPERATURE
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


class NotEnoughLabels(ValueError):
    """Too few public labels (for example an as-of week before most labels exist) to train a classifier."""


class FeedbackClassifier:
    def __init__(self, taxonomy: pd.DataFrame):
        self.floor = taxonomy["policy_severity_floor"].to_dict()
        self.vec = _vectoriser()
        self.issue = _svm(C.C_ISSUE)
        self.sev = _svm(C.C_SEVERITY)
        self.act = _svm(C.C_ACTIONABLE)

    def fit(self, feedback: pd.DataFrame, labels: pd.DataFrame) -> FeedbackClassifier:
        m = labels.merge(feedback[["feedback_id", "channel", "text"]], on="feedback_id", how="inner")
        if len(m) < C.MIN_TRAIN_ROWS:
            raise NotEnoughLabels(f"{len(m)} labelled rows are available, at least {C.MIN_TRAIN_ROWS} are needed to train")
        x = self.vec.fit_transform(model_input(m))
        self.issue.fit(x, m["issue_type_id"])
        self.sev.fit(x, m["severity"])
        self.act.fit(x, m["actionable"].astype(int))
        return self

    def proba(self, feedback: pd.DataFrame) -> pd.DataFrame:
        x = self.vec.transform(model_input(feedback))
        return pd.DataFrame(margin_confidence(self.issue.decision_function(x)), columns=self.issue.classes_, index=feedback.index)

    def predict(self, feedback: pd.DataFrame, resolved_store: pd.Series) -> pd.DataFrame:
        """Return feedback_id, issue_type_id, severity, actionable and the type confidence."""
        x = self.vec.transform(model_input(feedback))
        p_issue = margin_confidence(self.issue.decision_function(x))
        itype = pd.Series(self.issue.classes_[p_issue.argmax(axis=1)], index=feedback.index)
        conf = pd.Series(p_issue.max(axis=1), index=feedback.index)
        sev = pd.Series(self.sev.predict(x), index=feedback.index)
        act = pd.Series(self.act.predict(x), index=feedback.index).astype(int)
        sev = self._apply_policy(itype, sev)
        has_store = resolved_store.notna()
        non_issue = itype.isin(C.NON_ISSUE)
        act = act.where(~non_issue, 0)
        act = act.where(has_store | itype.isin(C.STORELESS_OK), 0)
        return pd.DataFrame(
            {
                "feedback_id": feedback["feedback_id"].values,
                "issue_type_id": itype.values,
                "severity": sev.values,
                "actionable": act.values,
                "type_confidence": conf.values,
            },
            index=feedback.index,
        )

    def explain(self, feedback: pd.DataFrame, top: int = 6) -> list[tuple[str, float]]:
        """Word-level terms that pushed one row toward its predicted type (largest positive contributions)."""
        x = self.vec.transform(model_input(feedback.iloc[[0]]))
        idx = int(self.issue.decision_function(x).argmax())
        coef = self.issue.coef_[idx]
        (_, char_v), (_, word_v) = self.vec.transformer_list
        offset = len(char_v.vocabulary_)
        names = word_v.get_feature_names_out()
        row = x.tocoo()
        contrib = [(names[j - offset], float(v * coef[j])) for j, v in zip(row.col, row.data, strict=False) if j >= offset]
        contrib = [c for c in contrib if c[1] > 0]
        return sorted(contrib, key=lambda kv: -kv[1])[:top]

    def _apply_policy(self, itype: pd.Series, sev: pd.Series) -> pd.Series:
        """severity = max(policy floor, model). Non-issues are low."""
        floor = itype.map(self.floor).fillna("low")
        rank = sev.map(C.SEV_RANK).combine(floor.map(C.SEV_RANK), max)
        out = rank.map(dict(enumerate(C.SEVERITIES)))
        return out.where(~itype.isin(C.NON_ISSUE), "low")
