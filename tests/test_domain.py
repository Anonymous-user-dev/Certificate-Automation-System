from certificate_automation.domain import Issue, Recipient, Severity


def test_issue_exposes_blocking_state():
    assert Issue(Severity.ERROR, "workbook", "Missing name").blocking is True
    assert Issue(Severity.WARNING, "workbook", "Long value").blocking is False


def test_recipient_retains_source_row_and_values():
    recipient = Recipient(source_row=7, values={"full_name": "Ana García"})

    assert recipient.source_row == 7
    assert recipient.values["full_name"] == "Ana García"
