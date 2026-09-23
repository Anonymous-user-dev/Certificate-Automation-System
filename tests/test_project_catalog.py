from datetime import datetime, timezone
import json
import sqlite3

import pytest

from certificate_automation.dataset import Column, DataRow, SourceSnapshot, TabularDataset
from certificate_automation.project import ProjectState, ProjectStore
from certificate_automation.project_catalog import ProjectCatalog, ProjectHealth


@pytest.fixture
def project_state(tmp_path):
    dataset = TabularDataset(
        (Column("name", "Name"),),
        (DataRow("row-1", 1, {"name": "Ana García"}),),
        SourceSnapshot(
            "manual", "Recipients", None, "a" * 64,
            datetime(2026, 9, 22, tzinfo=timezone.utc), {},
        ),
    )
    return ProjectState(
        revision=3,
        dataset=dataset,
        template_path=tmp_path / "private-template.docx",
        active_step="review",
    )


def test_catalog_does_not_store_recipient_values(tmp_path, project_state):
    path = tmp_path / "people.certproject"
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    catalog.remember(path, project_state)

    text = catalog.path.read_text("utf-8")
    summary = ProjectCatalog(catalog.path).list()[0]
    assert "Ana García" not in text
    assert summary.recipient_count == 1
    assert summary.template_name == "private-template.docx"
    assert summary.active_step == "review"


def test_catalog_reports_missing_project_without_removing_entry(tmp_path):
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    path = tmp_path / "missing.certproject"
    catalog.remember_path(path)

    summary = ProjectCatalog(catalog.path).list()[0]
    assert summary.health is ProjectHealth.MISSING
    assert summary.path == path


def test_catalog_health_reads_current_project_file(tmp_path, project_state):
    path = tmp_path / "people.certproject"
    store = ProjectStore.create(path)
    store.save(project_state)
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    catalog.remember(path, project_state)
    assert catalog.list()[0].health is ProjectHealth.READY

    path.write_bytes(b"not sqlite")
    assert catalog.list()[0].health is ProjectHealth.UNREADABLE


def test_catalog_uses_project_revision_save_time(tmp_path, project_state):
    path = tmp_path / "people.certproject"
    store = ProjectStore.create(path)
    store.save(project_state)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE revisions SET saved_at='2024-02-03T04:05:06+00:00' WHERE revision=3"
        )
    catalog = ProjectCatalog(tmp_path / "catalog.json")

    catalog.remember(path, project_state)

    assert catalog.list()[0].last_saved_at == datetime(2024, 2, 3, 4, 5, 6, tzinfo=timezone.utc)


def test_catalog_reports_newer_schema(tmp_path):
    path = tmp_path / "future.certproject"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', '999')")
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    catalog.remember_path(path)

    assert catalog.list()[0].health is ProjectHealth.NEWER_SCHEMA


def test_catalog_marks_malformed_schema_unreadable(tmp_path):
    path = tmp_path / "malformed.certproject"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES ('schema_version', 'unknown')")
    catalog = ProjectCatalog(tmp_path / "catalog.json")

    catalog.remember_path(path)

    assert catalog.list()[0].health is ProjectHealth.UNREADABLE


def test_catalog_keeps_twelve_most_recent_unique_paths_and_forgets(tmp_path):
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    paths = [tmp_path / f"project-{index}.certproject" for index in range(14)]
    for path in paths:
        catalog.remember_path(path)
    catalog.remember_path(paths[3])

    listed = [entry.path for entry in ProjectCatalog(catalog.path).list()]
    assert listed == [paths[3], *reversed(paths[2:3] + paths[4:14])][:12]
    assert len(listed) == 12
    catalog.forget(paths[3])
    assert paths[3] not in [entry.path for entry in catalog.list()]


def test_catalog_json_contains_only_minimal_metadata(tmp_path, project_state):
    catalog = ProjectCatalog(tmp_path / "catalog.json")
    catalog.remember(tmp_path / "people.certproject", project_state)
    raw = json.loads(catalog.path.read_text("utf-8"))

    serialized = json.dumps(raw, ensure_ascii=False)
    assert "row-1" not in serialized
    assert "Recipients" not in serialized
    assert "private-template.docx" in serialized
