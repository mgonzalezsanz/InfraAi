from state import validation_errors


def test_validation_errors_empty_when_no_result():
    assert validation_errors({}) == []
    assert validation_errors(None) == []


def test_validation_errors_reads_validate_failures():
    vr = {"valid": False, "validate": {"valid": False, "errors": ["bad syntax", "undeclared var"]}, "plan": None}
    assert validation_errors(vr) == ["bad syntax", "undeclared var"]


def test_validation_errors_reads_plan_failures_when_validate_passed():
    vr = {
        "valid": False,
        "validate": {"valid": True, "errors": []},
        "plan": {"valid": False, "summary": {}, "errors": ["AccessDenied on s3:CreateBucket"]},
    }
    assert validation_errors(vr) == ["AccessDenied on s3:CreateBucket"]
