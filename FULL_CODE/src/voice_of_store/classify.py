"""Issue type, severity and actionable classifier. Trained at run time from the public labelled sample only."""
from __future__ import annotations

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_union

from . import config as C
from .text import model_input


def _vectoriser():
    return make_union(
        TfidfVectorizer(analyzer="char_wb", ngram_range=C.CHAR_NGRAM, min_df=2, sublinear_tf=True),
        TfidfVectorizer(ngram_range=C.WORD_NGRAM, min_df=2, sublinear_tf=True),
    )


class FeedbackClassifier:
    def __init__(self, taxonomy: pd.DataFrame):
        self.floor = taxonomy["policy_severity_floor"].to_dict()
        self.vec = _vectoriser()
        self.issue = LogisticRegression(C=C.C_ISSUE, max_iter=3000, class_weight="balanced")
        self.sev = LogisticRegression(C=C.C_SEVERITY, max_iter=3000, class_weight="balanced")
        self.act = LogisticRegression(C=C.C_ACTIONABLE, max_iter=3000, class_weight="balanced")

    def fit(self, feedback: pd.DataFrame, labels: pd.DataFrame) -> FeedbackClassifier:
        m = labels.merge(feedback[["feedback_id", "channel", "text"]], on="feedback_id", how="inner")
        if m.empty:
            raise ValueError("no labelled rows available for training")
        x = self.vec.fit_transform(model_input(m))
        self.issue.fit(x, m["issue_type_id"])
        self.sev.fit(x, m["severity"])
        self.act.fit(x, m["actionable"].astype(int))
        return self

    def proba(self, feedback: pd.DataFrame) -> pd.DataFrame:
        x = self.vec.transform(model_input(feedback))
        return pd.DataFrame(self.issue.predict_proba(x), columns=self.issue.classes_, index=feedback.index)

    def predict(self, feedback: pd.DataFrame, resolved_store: pd.Series) -> pd.DataFrame:
        """Return feedback_id, issue_type_id, severity, actionable and the type confidence."""
        x = self.vec.transform(model_input(feedback))
        p_issue = self.issue.predict_proba(x)
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
        idx = int(self.issue.predict_proba(x).argmax())
        coef = self.issue.coef_[idx]
        (_, char_v), (_, word_v) = self.vec.transformer_list
        offset = len(char_v.vocabulary_)
        names = word_v.get_feature_names_out()
        row = x.tocoo()
        contrib = [(names[j - offset], float(v * coef[j])) for j, v in zip(row.col, row.data) if j >= offset]
        contrib = [c for c in contrib if c[1] > 0]
        return sorted(contrib, key=lambda kv: -kv[1])[:top]

    def _apply_policy(self, itype: pd.Series, sev: pd.Series) -> pd.Series:
        """severity = max(policy floor, model). Non-issues are low."""
        floor = itype.map(self.floor).fillna("low")
        rank = sev.map(C.SEV_RANK).combine(floor.map(C.SEV_RANK), max)
        out = rank.map(dict(enumerate(C.SEVERITIES)))
        return out.where(~itype.isin(C.NON_ISSUE), "low")
