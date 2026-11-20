"""Narrow, auditable checks for fully disclosed clinical score components."""

import re

CRB65_SOURCE = "https://www.nice.org.uk/guidance/ng250/chapter/recommendations"


def crb65(*, age_years, respiratory_rate, systolic_bp, diastolic_bp, confusion):
    """Calculate the named four-component score, without assessing care choices."""
    values = (age_years, respiratory_rate, systolic_bp, diastolic_bp)
    if any(type(v) not in (int, float) or not 0 <= v < float("inf") for v in values):
        raise ValueError("CRB65 requires finite nonnegative numeric components")
    if type(confusion) is not bool:
        raise ValueError("CRB65 confusion must be explicitly true or false")
    return (int(confusion) + int(respiratory_rate >= 30)
            + int(systolic_bp < 90 or diastolic_bp <= 60) + int(age_years >= 65))


def audit_crb65(text):
    """Flag arithmetic only when the text supplies one unambiguous input set.

    Missing or changing values are not inferred from clinical context. This
    deliberately sacrifices coverage rather than accuse a valid case on a guess.
    """
    result = {"kind": "CRB65", "source": CRB65_SOURCE,
              "status": "not_present", "clinical_validity": "not_assessed"}
    if not re.search(r"\bCRB[- ]?65\b", text, re.I):
        return result
    patterns = {
        "stated_total": r"\bCRB[- ]?65\s+(?:score\s*)?(?:(?:of|is)\s*|[=:]\s*)?(\d)\b",
        "age_years": r"\b(\d{1,3})[- ]year[- ]old\b|\bage\s*(\d{1,3})\b",
        "respiratory_rate": r"\b(?:RR|respiratory rate)\s*(?:(?:of|is)\s*|[=:]\s*)?(\d{1,3})\b",
        "bp": r"\b(?:BP|blood pressure)\s*(?:(?:of|is)\s*|[=:]\s*)?(\d{2,3})\s*/\s*(\d{2,3})\b",
    }
    found = {}
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text, re.I)
        if key == "bp":
            found[key] = {tuple(int(v) for v in match) for match in matches}
        elif key == "age_years":
            found[key] = {int(v) for match in matches for v in match if v}
        else:
            found[key] = {int(v) for v in matches}
    negative = bool(re.search(r"\b(?:no confusion|not confused|fully oriented|alert and oriented)\b", text, re.I))
    without_negative = re.sub(r"\b(?:no confusion|not confused)\b", "", text, flags=re.I)
    positive = bool(re.search(r"\b(?:new confusion|confused|confusion)\b", without_negative, re.I))
    if any(len(values) != 1 for values in found.values()) or negative == positive:
        return {**result, "status": "not_assessable", "reason": "Missing or ambiguous explicit components"}
    values = {key: next(iter(value)) for key, value in found.items()}
    systolic, diastolic = values.pop("bp")
    stated = values.pop("stated_total")
    components = {**values, "systolic_bp": systolic, "diastolic_bp": diastolic, "confusion": positive}
    calculated = crb65(**components)
    return {**result, "status": "consistent" if calculated == stated else "mismatch",
            "components": components, "stated_total": stated, "calculated_total": calculated}
