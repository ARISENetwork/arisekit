from arisekit.evaluation.privacy_signal import (
    DISCLAIMER,
    PrivacySignalAssessment,
    PrivacySignalStatus,
    assess_text_signals,
)


def test_default_privacy_state_is_not_assessed() -> None:
    assessment = PrivacySignalAssessment.not_assessed()
    assert assessment.status == PrivacySignalStatus.NOT_ASSESSED
    assert assessment.signal_counts == {}


def test_background_check_returns_only_categories_and_never_a_clearance_claim() -> None:
    assessment = assess_text_signals(
        {"note": "Contact person@example.org or call 212-555-1212."}
    )
    payload = assessment.to_dict()

    assert assessment.status == PrivacySignalStatus.SIGNALS_DETECTED
    assert payload["signal_counts"] == {"email_like": 1, "phone_like": 1}
    assert "person@example.org" not in str(payload)
    assert payload["disclaimer"] == DISCLAIMER


def test_no_signal_state_remains_advisory() -> None:
    assessment = assess_text_signals({"note": "Synthetic fixture case."})
    assert assessment.status == PrivacySignalStatus.NO_SIGNALS_DETECTED
    assert "determination" in assessment.disclaimer
