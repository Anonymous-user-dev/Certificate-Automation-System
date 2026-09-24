from __future__ import annotations

from certificate_automation.domain import BatchResult, BatchState
from certificate_automation.domain import Issue, Severity
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.results_page import ResultsPage


def test_published_result_explains_failed_history_index_without_hiding_output(qtbot, tmp_path):
    catalogs = CatalogSet.load(package_root(), "en")
    page = ResultsPage(catalogs)
    qtbot.addWidget(page)
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    page.set_published(BatchResult(BatchState.PUBLISHED, folder, 2, history_indexed=False))
    assert page.state == "published"
    assert catalogs.text("history.record_failed") in page.status_label.text()
    assert page.open_output_button.isEnabled()


def test_published_result_shows_journal_durability_warning(qtbot, tmp_path):
    catalogs = CatalogSet.load(package_root(), "en")
    page = ResultsPage(catalogs)
    qtbot.addWidget(page)
    folder = tmp_path / "Awards-revision-1"
    folder.mkdir()
    warning = Issue(Severity.WARNING, "journal", "journal.durability_uncertain")
    page.set_published(BatchResult(BatchState.PUBLISHED, folder, 2, (warning,)))
    assert catalogs.text("journal.durability_uncertain") in page.status_label.text()
