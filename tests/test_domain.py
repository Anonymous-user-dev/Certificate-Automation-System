from certificate_automation.domain import Issue, Recipient, Severity


def test_issue_exposes_blocking_state():
    assert Issue(Severity.ERROR, "workbook", "validation.missing_name").blocking is True
    assert Issue(Severity.WARNING, "workbook", "validation.long_value").blocking is False


def test_issue_is_language_neutral_immutable_and_located():
    issue = Issue(
        Severity.ERROR,
        "dataset",
        "validation.blank_mapped_value",
        {"placeholder": "FULL_NAME"},
        row_id="row-7",
        column_id="full_name",
    )

    assert not hasattr(issue, "message")
    assert issue.parameters["placeholder"] == "FULL_NAME"
    assert issue.row_id == "row-7"
    assert issue.column_id == "full_name"


def test_recipient_retains_source_row_and_values():
    recipient = Recipient(source_row=7, values={"full_name": "Ana García"})

    assert recipient.source_row == 7
    assert recipient.values["full_name"] == "Ana García"
