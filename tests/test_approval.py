"""Frozen approval binds the operator's decision to exact batch inputs."""

from dataclasses import replace

import pytest

from certificate_automation.approval import ApprovalInput, ApprovalService


@pytest.fixture
def approval_input(tmp_path):
    return ApprovalInput(
        project_revision=7,
        dataset_revision=3,
        dataset_sha256="a" * 64,
        source_sha256="b" * 64,
        template_sha256="c" * 64,
        mapping={"FULL_NAME": {"type": "column", "column_id": "name"}},
        health_review={"revision_key": "d" * 64, "expected_pages": 2},
        preview_hashes=("e" * 64,),
        warning_codes=("history.unavailable",),
        warning_ack_digest="f" * 64,
        outputs={"docx": True, "combined_pdf": True, "row_ids": ["r1"]},
        print_settings={"orientation": "landscape"},
        word_available=True,
        converter_identity="Microsoft Word",
        locale="en",
        recipient_count=1,
        excluded_count=0,
        output_counts={"docx": 1, "pdf": 0, "combined": 1, "separator": 0, "manifest": 1, "report": 1},
        expected_pages=2,
        destination=str(tmp_path),
        proposed_revision_folder="Batch-revision-001",
        template_name="official.docx",
    )


def test_digest_is_deterministic_and_value_sensitive(approval_input):
    first = ApprovalService.freeze(approval_input, "Preparer")
    second = ApprovalService.freeze(approval_input, "Preparer")
    assert first.snapshot.digest == second.snapshot.digest
    assert first.snapshot.digest != ApprovalService.freeze(
        replace(approval_input, recipient_count=51), "Preparer"
    ).snapshot.digest


@pytest.mark.parametrize("field,value", [
    ("project_revision", 8), ("dataset_sha256", "z" * 64),
    ("source_sha256", "z" * 64), ("template_sha256", "z" * 64),
    ("mapping", {"FULL_NAME": "different"}),
    ("health_review", {"revision_key": "changed"}),
    ("preview_hashes", ("changed",)),
    ("warning_codes", ("duplicate",)),
    ("warning_ack_digest", "changed"),
    ("outputs", {"docx": False}),
    ("print_settings", {"orientation": "portrait"}),
    ("word_available", False), ("converter_identity", "different"),
    ("recipient_count", 2), ("destination", "different"),
])
def test_relevant_change_invalidates_approval(approval_input, field, value):
    approved = ApprovalService.freeze(approval_input, "Preparer")
    assert not ApprovalService.verify(approved, replace(approval_input, **{field: value})).valid


def test_two_person_requires_distinct_later_reviewer_action(approval_input):
    frozen = ApprovalService.freeze(approval_input, "  Alice  ", two_person=True)
    assert not ApprovalService.verify(frozen, approval_input).valid
    with pytest.raises(ValueError):
        ApprovalService.review(frozen, approval_input, " alice ")
    reviewed = ApprovalService.review(frozen, approval_input, "Bob")
    assert ApprovalService.verify(reviewed, approval_input).valid


def test_blank_preparer_and_reviewer_are_rejected(approval_input):
    with pytest.raises(ValueError):
        ApprovalService.freeze(approval_input, "  ")
    frozen = ApprovalService.freeze(approval_input, "Alice", two_person=True)
    with pytest.raises(ValueError):
        ApprovalService.review(frozen, approval_input, "  ")


def test_approval_roundtrip_preserves_digest_and_verification(approval_input):
    approved = ApprovalService.review(
        ApprovalService.freeze(approval_input, "Alice", two_person=True),
        approval_input, "Bob",
    )
    loaded = type(approved).from_json(approved.to_json())
    assert ApprovalService.verify(loaded, approval_input).valid


def test_two_person_mode_cannot_be_removed_from_saved_record(approval_input):
    frozen = ApprovalService.freeze(approval_input, "Alice", two_person=True)
    changed = replace(frozen, two_person=False)
    assert not ApprovalService.verify(changed, approval_input).valid


def test_malformed_reviewer_time_cannot_crash_or_authorize(approval_input):
    approved = ApprovalService.review(
        ApprovalService.freeze(approval_input, "Alice", two_person=True),
        approval_input, "Bob",
    )
    altered = approved.to_json()
    altered["reviewed_at"] = "2026-09-22T12:00:00"  # missing timezone
    loaded = type(approved).from_json(altered)
    assert not ApprovalService.verify(loaded, approval_input).valid
