from __future__ import annotations

import json
import pytest

from certificate_automation.dataset import Column
from certificate_automation.mapping import ColumnValue, FixedValue, FormattedDateValue, JoinValue, MappingPlan, SequenceValue
from certificate_automation.profiles import MappingProfile, ProfileError, ProfileMatchStatus, ProfileStore, compare_profile
from certificate_automation.dataset import DataRow, SourceSnapshot, TabularDataset
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.match_page import MatchPage
from datetime import datetime, timezone
from PySide6.QtCore import Qt


def test_profile_roundtrip_and_hash_do_not_include_recipient_rows(tmp_path):
    plan = MappingPlan({"NAME": ColumnValue("full_name"), "NUMBER": SequenceValue(7, 1, 3)})
    profile = MappingProfile.from_plan("Annual awards", plan, ("NAME", "NUMBER"), (Column("full_name", "Full Name"),), template_sha256="a" * 64)
    saved = ProfileStore(tmp_path).save(profile)
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert saved.suffix == ".certprofile"
    assert "rows" not in saved.read_text(encoding="utf-8")
    assert len(payload["payload_sha256"]) == 64
    assert ProfileStore(tmp_path).load(saved) == profile


def test_profile_rejects_fixed_value_without_explicit_opt_in(tmp_path):
    profile = MappingProfile.from_plan("Private", MappingPlan({"SIGNATORY": FixedValue("Secret")}), ("SIGNATORY",), ())
    with pytest.raises(ProfileError, match="profile.sensitive_fixed_value"):
        ProfileStore(tmp_path).save(profile)
    assert not tuple(tmp_path.iterdir())
    saved = ProfileStore(tmp_path).save(profile, allow_fixed_values=True)
    assert ProfileStore(tmp_path).load(saved).mappings["SIGNATORY"]["value"] == "Secret"


def test_profile_rejects_corruption_unknown_fields_and_duplicate_name(tmp_path):
    store = ProfileStore(tmp_path)
    profile = MappingProfile.from_plan("Annual awards", MappingPlan({"NAME": ColumnValue("name")}), ("NAME",), (Column("name", "Name"),))
    saved = store.save(profile)
    with pytest.raises(ProfileError, match="profile.already_exists"):
        store.save(profile)
    data = json.loads(saved.read_text(encoding="utf-8"))
    data["payload"]["unexpected"] = "x"
    saved.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProfileError, match="profile.invalid_schema"):
        store.load(saved)
    assert store.list() == ()


def test_profile_rejects_path_outside_store(tmp_path):
    with pytest.raises(ProfileError, match="profile.path_outside_store"):
        ProfileStore(tmp_path / "profiles").load(tmp_path / "other.certprofile")


def test_profile_rejects_outside_symlink_pointing_into_store(tmp_path):
    store = ProfileStore(tmp_path / "profiles")
    inside = store.save(MappingProfile.from_plan("Inside", MappingPlan({"N": ColumnValue("name")}), ("N",), (Column("name", "Name"),)))
    outside = tmp_path / "shortcut.certprofile"
    outside.symlink_to(inside)
    with pytest.raises(ProfileError, match="profile.path_outside_store"):
        store.load(outside)


def test_changed_profile_hash_is_rejected_before_mapping(tmp_path):
    store = ProfileStore(tmp_path)
    saved = store.save(MappingProfile.from_plan("Awards", MappingPlan({"NAME": ColumnValue("name")}), ("NAME",), (Column("name", "Name"),)))
    record = json.loads(saved.read_text(encoding="utf-8"))
    record["payload"]["mappings"]["NAME"]["column_id"] = "wrong"
    saved.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ProfileError, match="profile.hash_mismatch"):
        store.load(saved)


def test_duplicate_normalized_column_ids_remain_for_review():
    profile = MappingProfile.from_plan("Awards", MappingPlan({"NAME": ColumnValue("first_name")}), ("NAME",), (Column("first_name", "Name"),))
    comparison = compare_profile(profile, (Column("first-name", "Alias"), Column("first_name", "Other")), ("NAME",))
    assert comparison.matches["NAME"].status is ProfileMatchStatus.REVIEW_REQUIRED
    assert comparison.applied_plan.sources == {}


def test_duplicate_json_keys_and_wrong_source_types_are_rejected(tmp_path):
    path = tmp_path / "bad.certprofile"
    path.write_text('{"payload":{},"payload":{},"payload_sha256":"a"}', encoding="utf-8")
    with pytest.raises(ProfileError, match="profile.invalid_schema"):
        ProfileStore(tmp_path).load(path)
    with pytest.raises(ProfileError, match="profile.invalid_schema"):
        MappingProfile.from_plan("Bad", MappingPlan({"N": SequenceValue()}), ("N",), (), defaults={"rows": ["Ana"]})


def test_nonstandard_json_and_unrepresentable_sequence_are_rejected(tmp_path):
    path = tmp_path / "bad.certprofile"
    path.write_text('{"payload":NaN,"payload_sha256":"a"}', encoding="utf-8")
    with pytest.raises(ProfileError, match="profile.invalid_schema"):
        ProfileStore(tmp_path).load(path)
    with pytest.raises(ProfileError, match="profile.invalid_schema"):
        MappingProfile.from_plan("Bad", MappingPlan({"N": SequenceValue(1, 1, 101)}), ("N",), ())


def test_profile_mapping_cannot_be_mutated_after_validation():
    profile = MappingProfile.from_plan(
        "Dates", MappingPlan({"DATE": FormattedDateValue(ColumnValue("date"), "%Y-%m-%d", "%Y")}),
        ("DATE",), (Column("date", "Date"),),
    )
    with pytest.raises(TypeError):
        profile.mappings["DATE"]["source"]["column_id"] = "other"
    assert profile.mappings["DATE"]["source"]["column_id"] == "date"


def test_comparison_applies_exact_id_or_unique_label_and_never_fuzzy():
    profile = MappingProfile.from_plan(
        "Annual", MappingPlan({"NAME": ColumnValue("full_name"), "DATE": FormattedDateValue(ColumnValue("award_date"), "%Y-%m-%d", "%B %d"), "FULL": JoinValue(("first", "last")), "SERIAL": SequenceValue()}),
        ("NAME", "DATE", "FULL", "SERIAL"),
        (Column("full_name", "Full Name"), Column("award_date", "Award Date"), Column("first", "First"), Column("last", "Last")),
    )
    comparison = compare_profile(profile, (Column("full_name", "Full Name"), Column("new_date", "Award Date"), Column("firstname", "First Name"), Column("surname", "Last")), ("NAME", "DATE", "FULL", "SERIAL", "EXTRA"))
    assert comparison.matches["NAME"].status is ProfileMatchStatus.EXACT
    assert comparison.matches["DATE"].status is ProfileMatchStatus.EXACT
    assert comparison.matches["FULL"].status is ProfileMatchStatus.REVIEW_REQUIRED
    assert comparison.matches["EXTRA"].status is ProfileMatchStatus.MISSING
    assert set(comparison.applied_plan.sources) == {"NAME", "DATE", "SERIAL"}
    assert comparison.applied_plan.sources["DATE"].source.column_id == "new_date"


def test_duplicate_exact_label_requires_review():
    profile = MappingProfile.from_plan("Awards", MappingPlan({"NAME": ColumnValue("old")}), ("NAME",), (Column("old", "Full Name"),))
    comparison = compare_profile(profile, (Column("one", "Full Name"), Column("two", "Full Name")), ("NAME",))
    assert comparison.matches["NAME"].status is ProfileMatchStatus.REVIEW_REQUIRED
    assert comparison.applied_plan.sources == {}


def test_match_page_shows_profile_comparison_without_assigning_review_required_column(qtbot):
    page = MatchPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    dataset = TabularDataset(
        (Column("name", "Name"), Column("other", "Student Name")),
        (DataRow("r1", None, {"name": "Ana", "other": "Ana"}),),
        SourceSnapshot("manual", "People", None, "a" * 64, datetime.now(timezone.utc)),
    )
    page.set_context(dataset, ("NAME", "AWARD"))
    profile = MappingProfile.from_plan("Awards", MappingPlan({"NAME": ColumnValue("old"), "AWARD": FixedValue("Gold")}), ("NAME", "AWARD", "UNUSED"), (Column("old", "Student"),))
    comparison = compare_profile(profile, dataset.columns, ("NAME", "AWARD"))
    page.show_profile_comparison(comparison)
    assert page.comparison_table.rowCount() == 3
    assert page.cards["NAME"].mapping_source() is None
    assert not page.continue_button.isEnabled()
    assert page.comparison_table.item(0, 1).text() == page._catalogs.text("profile.status.review_required")
    assert page.save_profile_button.accessibleName()
    assert page.apply_profile_button.accessibleName()


def test_match_page_can_apply_exact_partial_plan_and_leave_missing_field_unresolved(qtbot):
    page = MatchPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    dataset = TabularDataset(
        (Column("name", "Name"),),
        (DataRow("r1", None, {"name": "Ana"}),),
        SourceSnapshot("manual", "People", None, "a" * 64, datetime.now(timezone.utc)),
    )
    page.set_context(dataset, ("NAME", "AWARD"))
    page.cards["AWARD"].set_mapping_source(FixedValue("old"))
    page.set_plan(MappingPlan({"NAME": ColumnValue("name")}))
    assert page.mapping_plan().to_json() == {"NAME": {"type": "column", "column_id": "name"}}
    assert not page.continue_button.isEnabled()


def test_match_page_preserves_saved_sequence_parameters(qtbot):
    page = MatchPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    dataset = TabularDataset(
        (Column("name", "Name"),), (DataRow("r1", None, {"name": "Ana"}),),
        SourceSnapshot("manual", "People", None, "a" * 64, datetime.now(timezone.utc)),
    )
    page.set_context(dataset, ("SERIAL",))
    plan = MappingPlan({"SERIAL": SequenceValue(41, 2, 5, "CERT-", "-A")})
    page.set_plan(plan)
    assert page.mapping_plan() == plan
