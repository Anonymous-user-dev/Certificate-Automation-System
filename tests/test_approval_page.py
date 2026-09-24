from dataclasses import replace

from certificate_automation.approval import ApprovalService
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.approval_page import ApprovalPage

from test_approval import approval_input


def test_page_shows_exact_batch_facts_and_blocks_until_freeze(qtbot, approval_input):
    page = ApprovalPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.set_summary(approval_input, warnings_acknowledged=True)
    text = page.summary_label.text()
    for value in (
        "1", "0", "2", "Batch-revision-001", "official.docx",
        approval_input.template_sha256[:12], approval_input.destination,
        "Microsoft Word",
    ):
        assert value in text
    assert not page.generate_button.isEnabled()
    page.preparer_name.setText("Alice")
    assert page.freeze_button.isEnabled()


def test_page_requires_current_acknowledgement_and_distinct_reviewer(qtbot, approval_input):
    page = ApprovalPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.set_summary(approval_input, warnings_acknowledged=False)
    page.preparer_name.setText("Alice")
    assert not page.freeze_button.isEnabled()
    page.set_summary(approval_input, warnings_acknowledged=True)
    frozen = ApprovalService.freeze(approval_input, "Alice", two_person=True)
    page.set_approval(frozen, allow_review=False)
    assert not page.review_button.isEnabled()
    assert not page.generate_button.isEnabled()
    page.set_approval(frozen, allow_review=True)
    page.reviewer_name.setText("alice")
    assert not page.review_button.isEnabled()
    page.reviewer_name.setText("Bob")
    assert not page.review_button.isEnabled()
    page.set_summary(approval_input, warnings_acknowledged=True, reviewer_previews_reviewed=True)
    assert page.review_button.isEnabled()
    page.set_approval(ApprovalService.review(frozen, approval_input, "Bob"), allow_review=True)
    assert page.generate_button.isEnabled()


def test_page_invalidated_snapshot_disables_generation(qtbot, approval_input):
    page = ApprovalPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.set_summary(approval_input, warnings_acknowledged=True)
    page.set_approval(ApprovalService.freeze(approval_input, "Alice"), allow_review=True)
    assert page.generate_button.isEnabled()
    page.set_summary(replace(approval_input, recipient_count=3), warnings_acknowledged=True)
    assert not page.generate_button.isEnabled()
