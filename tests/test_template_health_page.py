from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter

from certificate_automation.domain import Issue, Severity
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.template_health import (
    LayoutReviewResult, RepresentativePreview, RepresentativeRecord,
    TemplateHealthReport,
)
from certificate_automation.ui.template_health_page import TemplateHealthPage


def _pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with path.open("wb") as stream:
        writer.write(stream)


def test_health_page_groups_issues_and_blocks_malformed_template(qtbot):
    page = TemplateHealthPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    report = TemplateHealthReport(
        "a" * 64,
        (
            Issue(Severity.ERROR, "template", "template.malformed_placeholder", {"location": "word/document.xml: paragraph 1"}),
            Issue(Severity.WARNING, "template", "template.comments"),
            Issue(Severity.INFO, "template", "template.duplicate_placeholder", {"placeholder": "NAME", "count": 2, "locations": "body; header"}),
        ), {}, (),
    )

    page.set_structure(report)

    assert page.must_fix_list.count() == 1
    assert page.review_list.count() == 1
    assert page.information_list.count() == 1
    assert not page.continue_button.isEnabled()
    assert page.limitation.text()


def test_layout_review_requires_visiting_each_representative(qtbot, tmp_path):
    page = TemplateHealthPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    page.set_structure(TemplateHealthReport("a" * 64, (), {"NAME": ()}, ()))
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    _pdf(first)
    _pdf(second)
    review = LayoutReviewResult(
        "revision-a",
        (RepresentativeRecord("first", ("first",), 3), RepresentativeRecord("second", ("last",), 4)),
        (RepresentativePreview("first", first, "a" * 64, 1), RepresentativePreview("second", second, "b" * 64, 1)),
        (Issue(Severity.WARNING, "template", "template.layout_review_required"),),
    )

    page.set_layout_result(review)

    assert not page.mark_reviewed_button.isEnabled()
    page.preview_selector.setCurrentIndex(1)
    assert page.mark_reviewed_button.isEnabled()
    assert page.pdf_document.pageCount() == 1


def test_layout_review_does_not_accept_partial_result(qtbot):
    page = TemplateHealthPage(CatalogSet.load(package_root(), "en"))
    qtbot.addWidget(page)
    review = LayoutReviewResult(
        "revision-a", (RepresentativeRecord("first", (), 1),), (),
        (Issue(Severity.ERROR, "template", "preview.stale_output", {"row": "first"}),),
    )

    page.set_layout_result(review)

    assert not page.mark_reviewed_button.isEnabled()
    assert page.must_fix_list.count() == 1
