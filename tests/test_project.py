from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3

from PySide6.QtTest import QSignalSpy
import pytest

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.mapping import ColumnValue, MappingPlan
from certificate_automation.output_options import OutputOptions
from certificate_automation.project import (
    ProjectCoordinator,
    ProjectCorruptError,
    ProjectSaveError,
    ProjectState,
    ProjectStore,
)


def _dataset() -> TabularDataset:
    return TabularDataset(
        (Column("full_name", "姓名 / Имя"), Column("award", "奖项 / Награда")),
        (
            DataRow("row-cn", 2, {"full_name": "李明", "award": "优秀奖"}),
            DataRow("row-ru", 3, {"full_name": "Ирина", "award": "Золото"}),
        ),
        SourceSnapshot(
            "manual",
            "Официальный список",
            None,
            "c" * 64,
            datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc),
            {"reviewed": True},
        ),
        revision=3,
        order=("row-ru", "row-cn"),
    )


def _state(tmp_path, revision=1, *, template_hash="old") -> ProjectState:
    template = tmp_path / "template.docx"
    template.write_bytes(b"old template")
    return ProjectState(
        revision=revision,
        dataset=_dataset(),
        mapping_plan={"FULL_NAME": {"type": "column", "column_id": "full_name"}},
        template_path=template,
        template_sha256=template_hash,
        template_inspection={"placeholders": ["FULL_NAME"]},
        output_options={"docx": True, "individual_pdf": False},
        locale="ru",
        acknowledgements=("warning.long_name",),
        active_step="review",
        preview_revision=3,
    )


def test_project_round_trip_preserves_ids_order_unicode_and_settings(tmp_path):
    state = _state(tmp_path)
    store = ProjectStore.create(tmp_path / "awards.certproject")

    store.save(state)
    reopened = ProjectStore.open(store.path).load()

    assert reopened == state
    assert reopened.dataset.order == ("row-ru", "row-cn")
    assert reopened.dataset.row("row-cn").value("full_name") == "李明"
    assert reopened.mapping_plan["FULL_NAME"]["column_id"] == "full_name"


def test_failed_save_leaves_last_valid_revision(tmp_path, monkeypatch):
    store = ProjectStore.create(tmp_path / "draft.certproject")
    store.save(_state(tmp_path, revision=1))

    def raise_disk_full(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(store, "_commit", raise_disk_full)
    with pytest.raises(ProjectSaveError) as caught:
        store.save(_state(tmp_path, revision=2))

    assert caught.value.code == "project.save_failed"
    assert ProjectStore.open(store.path).load().revision == 1


def test_only_three_rotating_valid_backups_are_retained(tmp_path):
    store = ProjectStore.create(tmp_path / "draft.certproject")
    for revision in range(1, 6):
        store.save(_state(tmp_path, revision=revision))

    backups = store.backup_paths()

    assert len(backups) == 3
    assert all(path.is_file() for path in backups)
    assert [ProjectStore.open(path).load().revision for path in backups] == [5, 4, 3]


def test_recover_latest_uses_newest_valid_backup_when_main_is_corrupt(tmp_path):
    store = ProjectStore.create(tmp_path / "draft.certproject")
    store.save(_state(tmp_path, revision=1))
    store.save(_state(tmp_path, revision=2))
    store.path.write_bytes(b"not sqlite")

    recovered = ProjectStore.recover_latest(store.path)

    assert recovered.revision == 2


def test_corrupt_revision_hash_is_rejected(tmp_path):
    store = ProjectStore.create(tmp_path / "draft.certproject")
    store.save(_state(tmp_path))
    with closing(sqlite3.connect(store.path)) as connection, connection:
        connection.execute("UPDATE revisions SET payload_sha256 = 'bad'")

    with pytest.raises(ProjectCorruptError) as caught:
        ProjectStore.open(store.path).load()

    assert caught.value.code == "project.no_valid_revision"


def test_changed_template_hash_invalidates_all_downstream_state(tmp_path):
    state = replace(
        _state(tmp_path, template_hash=sha256(b"old template").hexdigest()),
        approval={"snapshot": {"digest": "a" * 64}},
    )
    state.template_path.write_bytes(b"new template")

    reconciled = state.reconcile_template()

    assert reconciled.template_sha256 == sha256(b"new template").hexdigest()
    assert reconciled.template_inspection is None
    assert reconciled.mapping_plan is None
    assert reconciled.preview_revision is None
    assert reconciled.acknowledgements == ()
    assert reconciled.approval is None
    assert reconciled.active_step == "template"


def test_newer_schema_is_opened_read_only(tmp_path):
    path = tmp_path / "future.certproject"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '999')")

    opened = ProjectStore.open(path)

    assert opened.read_only is True
    assert opened.issue_code == "project.newer_schema"
    with pytest.raises(ProjectSaveError):
        opened.save(_state(tmp_path))


def test_coordinator_debounces_and_flushes_pending_state(qtbot, tmp_path):
    store = ProjectStore.create(tmp_path / "draft.certproject")
    coordinator = ProjectCoordinator(store, debounce_ms=10)
    saved = QSignalSpy(coordinator.saved)

    coordinator.mark_dirty(_state(tmp_path, revision=1))
    coordinator.mark_dirty(_state(tmp_path, revision=2))
    qtbot.waitUntil(lambda: saved.count() == 1)

    assert saved.at(0) == [2]
    assert store.load().revision == 2
    assert coordinator.has_pending is False


def test_failed_coordinator_flush_keeps_pending_for_retry(qtbot, tmp_path, monkeypatch):
    store = ProjectStore.create(tmp_path / "draft.certproject")
    coordinator = ProjectCoordinator(store, debounce_ms=10000)
    failures = QSignalSpy(coordinator.save_failed)
    coordinator.mark_dirty(_state(tmp_path))
    monkeypatch.setattr(store, "save", lambda _state: (_ for _ in ()).throw(ProjectSaveError("project.save_failed")))

    assert coordinator.flush() is False
    assert coordinator.has_pending is True
    assert failures.count() == 1


def test_project_accepts_typed_mapping_and_output_records(tmp_path):
    dataset = _dataset()
    state = ProjectState(
        revision=1,
        dataset=dataset,
        mapping_plan=MappingPlan({"FULL_NAME": ColumnValue("full_name")}),
        output_options=OutputOptions(
            True,
            False,
            False,
            tmp_path / "output",
            "Awards",
            dataset.order,
        ),
    )
    store = ProjectStore.create(tmp_path / "typed.certproject")

    store.save(state)
    reopened = store.load()

    assert MappingPlan.from_json(reopened.mapping_plan).sources["FULL_NAME"] == ColumnValue("full_name")
    assert reopened.output_options["row_ids"] == ["row-ru", "row-cn"]


def test_schema2_project_fields_survive_round_trip(tmp_path):
    state = ProjectState(
        revision=1,
        dataset=_dataset(),
        project_name="奖项 Анна",
        profile_path=tmp_path / "settings.profile",
        approval={"digest": "abc", "reviewer": "Mira"},
        published_revisions=("batch-001", "batch-002"),
        print_settings={"duplex": True, "copies": 2},
    )
    store = ProjectStore.create(tmp_path / "schema2.certproject")
    store.save(state)

    reopened = ProjectStore.open(store.path).load()
    assert reopened.schema_version == 2
    assert reopened.project_name == "奖项 Анна"
    assert reopened.profile_path == tmp_path / "settings.profile"
    assert reopened.approval == {"digest": "abc", "reviewer": "Mira"}
    assert reopened.published_revisions == ("batch-001", "batch-002")
    assert reopened.print_settings == {"duplex": True, "copies": 2}


def test_duplicate_policy_survives_project_round_trip_with_safe_legacy_default(tmp_path):
    state = ProjectState(
        revision=1, dataset=_dataset(),
        duplicate_policy={
            "certificate_id_column": "certificate_id",
            "identity_columns": ["full_name", "birth_date"],
            "check_history": True,
        },
    )
    store = ProjectStore.create(tmp_path / "duplicate-policy.certproject")
    store.save(state)
    assert ProjectStore.open(store.path).load().duplicate_policy == state.duplicate_policy

    old_payload = state.to_payload()
    old_payload.pop("duplicate_policy")
    assert ProjectState.from_payload(old_payload).duplicate_policy == {
        "certificate_id_column": None, "identity_columns": [], "check_history": False,
    }


def test_invalid_latest_duplicate_policy_falls_back_to_last_valid_revision(tmp_path):
    store = ProjectStore.create(tmp_path / "policy-corrupt.certproject")
    store.save(_state(tmp_path, revision=1))
    store.save(_state(tmp_path, revision=2))
    with sqlite3.connect(store.path) as connection:
        payload = json.loads(connection.execute(
            "SELECT payload_json FROM revisions WHERE revision=2"
        ).fetchone()[0])
        payload["duplicate_policy"] = {"identity_columns": "full_name", "check_history": True}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        connection.execute(
            "UPDATE revisions SET payload_json=?, payload_sha256=? WHERE revision=2",
            (encoded, sha256(encoded.encode("utf-8")).hexdigest()),
        )
    assert ProjectStore.open(store.path).load().revision == 1


def test_schema1_payload_reads_with_safe_defaults(tmp_path):
    payload = _state(tmp_path).to_payload()
    for field in ("schema_version", "project_name", "profile_path", "approval", "published_revisions", "print_settings"):
        payload.pop(field, None)

    reopened = ProjectState.from_payload(payload)

    assert reopened.schema_version == 1
    assert reopened.project_name is None
    assert reopened.profile_path is None
    assert reopened.approval is None
    assert reopened.published_revisions == ()
    assert reopened.print_settings is None
