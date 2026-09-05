from src.compliance import check


def test_clean_text_passes():
    text = (
        "ADHD can look different in adults. An assessment can help you understand "
        "your attention patterns. Learn more at neuroaxis-adhd.com."
    )
    assert check(text) == []


def test_flags_cqc_registration_claim():
    assert check("We are CQC registered and fully accredited.")
    assert check("A CQC-registered clinic you can trust.")


def test_allows_operating_to_cqc_standards():
    assert check("Operating to CQC standards.") == []


def test_flags_cure_and_guarantee_language():
    assert check("We cure ADHD fast.")
    assert check("Guaranteed results or your money back.")
    assert check("This will fix your focus for good.")


def test_flags_self_diagnosis_overreach():
    assert check("You have ADHD — book now to confirm it.")


def test_flags_medication_claims():
    assert check("Get your methylphenidate prescription in days.")
    assert check("We prescribe Elvanse on your first appointment.")


def test_flags_unsubstantiated_superiority():
    assert check("The fastest ADHD assessment in the UK.")
    assert check("The best ADHD clinic, bar none.")


def test_flags_trustpilot_widget_language():
    assert check("See our Trustpilot widget below.")


def test_case_insensitive():
    assert check("we CURE adhd")
    assert check("cqc REGISTERED")


def test_returns_all_violations():
    violations = check("The best CQC registered clinic that will cure ADHD.")
    assert len(violations) >= 3
