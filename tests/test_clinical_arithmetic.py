import pytest

from arisekit.generation.clinical_arithmetic import audit_crb65, crb65


@pytest.mark.parametrize("age,rr,sbp,dbp,confusion,expected", [
    (59, 28, 110, 70, False, 0), (65, 30, 89, 60, True, 4),
    (64, 29, 90, 61, False, 0), (64, 29, 110, 60, False, 1),
    (64, 29, 89, 70, False, 1),
])
def test_crb65_boundaries(age, rr, sbp, dbp, confusion, expected):
    assert crb65(age_years=age, respiratory_rate=rr, systolic_bp=sbp, diastolic_bp=dbp, confusion=confusion) == expected


def test_detects_observed_generated_case_error():
    result = audit_crb65("A 59-year-old woman has a CRB65 score of 1 (age 59, RR 28, BP 110/70, no confusion).")
    assert result["status"] == "mismatch"
    assert result["calculated_total"] == 0
    assert result["stated_total"] == 1


def test_does_not_invent_missing_or_changing_components():
    assert audit_crb65("CRB65 score of 2; he is stable.")["status"] == "not_assessable"
    text = "A 59-year-old with CRB65 score of 1 has RR 28, later RR 32, BP 110/70, no confusion."
    assert audit_crb65(text)["status"] == "not_assessable"
    assert audit_crb65("A case without a named risk score.")["status"] == "not_present"


def test_rejects_nonfinite_or_implicit_boolean_components():
    with pytest.raises(ValueError):
        crb65(age_years=float("nan"), respiratory_rate=28, systolic_bp=110, diastolic_bp=70, confusion=False)
    with pytest.raises(ValueError):
        crb65(age_years=59, respiratory_rate=28, systolic_bp=110, diastolic_bp=70, confusion=0)
