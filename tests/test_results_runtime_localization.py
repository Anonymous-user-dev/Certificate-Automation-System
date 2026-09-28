from __future__ import annotations

import pytest

from certificate_automation.batch import BatchGenerationError, ProgressEvent
from certificate_automation.i18n import CatalogSet, package_root
from certificate_automation.ui.results_page import ResultsPage


@pytest.mark.parametrize(
    ("locale", "phase", "expected"),
    [
        ("ru", "preflight", "Проверка всего пакета: 2 из 3."),
        ("ru", "docx", "Создание сертификатов Word: 2 из 3."),
        ("ru", "pdf", "Создание сертификатов PDF: 2 из 3."),
        ("ru", "combined_pdf", "Создание и проверка общего PDF: 2 из 3."),
        ("ru", "verification", "Проверка созданных документов: 2 из 3."),
        ("ru", "publication", "Публикация проверенного пакета: 2 из 3."),
        ("zh_CN", "preflight", "检查整个批次：2/3。"),
        ("zh_CN", "docx", "正在创建 Word 证书：2/3。"),
        ("zh_CN", "pdf", "正在创建 PDF 证书：2/3。"),
        ("zh_CN", "combined_pdf", "创建并验证合并 PDF：2/3。"),
        ("zh_CN", "verification", "正在验证生成的文档：2/3。"),
        ("zh_CN", "publication", "正在发布已验证批次：2/3。"),
        ("ru", "future_phase", "Создание и проверка официального пакета…: 2 из 3."),
        ("zh_CN", "future_phase", "正在生成并验证正式批次…：2/3。"),
    ],
)
def test_results_progress_renders_structured_phase_and_counts_in_locale(
    qtbot, locale, phase, expected
):
    page = ResultsPage(CatalogSet.load(package_root(), locale))
    qtbot.addWidget(page)
    page.set_running()

    page.update_progress(ProgressEvent(phase, 2, 3, "English core progress message"))

    assert page.status_label.text() == expected
    assert page.progress.value() == 2
    assert page.progress.maximum() == 3


@pytest.mark.parametrize(
    ("locale", "code", "expected"),
    [
        (
            "ru", "output.authoritative_destination_required",
            "Для официального пакета выберите папку на локальном несъёмном диске NTFS.",
        ),
        (
            "zh_CN", "output.authoritative_destination_required",
            "请为正式批次选择本地固定 NTFS 磁盘上的文件夹。",
        ),
        (
            "ru", "output.publication_ambiguous",
            "Не удалось подтвердить публикацию пакета. Откройте восстановление и проверьте папку вывода перед повторной попыткой.",
        ),
        (
            "zh_CN", "output.publication_ambiguous",
            "无法确认批次是否已发布。请先打开恢复并检查输出文件夹，再重试。",
        ),
    ],
)
def test_results_generation_failure_renders_stable_code_without_raw_error(
    qtbot, locale, code, expected
):
    page = ResultsPage(CatalogSet.load(package_root(), locale))
    qtbot.addWidget(page)
    page.set_running()

    page.set_failed(BatchGenerationError("English error with private recipient", code=code))

    assert page.status_label.text() == expected
    assert page.generate_button.isEnabled()
    assert not page.cancel_button.isEnabled()
    assert not page.open_output_button.isEnabled()


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("ru", "Не удалось безопасно завершить пакет. Проверьте результаты проверки и восстановление перед повторной попыткой."),
        ("zh_CN", "无法安全完成批次。请检查验证结果和恢复信息，再重试。"),
    ],
)
@pytest.mark.parametrize("code", (None, "future.failure", "validation.blank_mapped_value"))
def test_results_unknown_or_unformattable_failure_uses_localized_safe_fallback(
    qtbot, locale, expected, code
):
    page = ResultsPage(CatalogSet.load(package_root(), locale))
    qtbot.addWidget(page)
    error = RuntimeError("English error with private recipient")
    if code is not None:
        error.code = code

    page.set_failed(error)

    assert page.status_label.text() == expected


def test_results_active_progress_and_failure_retranslate_when_locale_changes(qtbot):
    catalogs = CatalogSet.load(package_root(), "en")
    page = ResultsPage(catalogs)
    qtbot.addWidget(page)
    page.set_running()
    page.update_progress(ProgressEvent("docx", 2, 3, "Created Word certificate 2 of 3."))

    catalogs.set_locale("ru")
    assert page.status_label.text() == "Создание сертификатов Word: 2 из 3."

    page.set_failed(BatchGenerationError("English NTFS error", code="output.authoritative_destination_required"))
    catalogs.set_locale("zh_CN")
    assert page.status_label.text() == "请为正式批次选择本地固定 NTFS 磁盘上的文件夹。"


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("ru", "Операция безопасно отменена. Официальный пакет не опубликован."),
        ("zh_CN", "已安全取消。未发布正式批次。"),
    ],
)
def test_results_cancelled_state_is_localized_and_can_retry_without_result_actions(
    qtbot, locale, expected
):
    page = ResultsPage(CatalogSet.load(package_root(), locale))
    qtbot.addWidget(page)
    page.set_running()

    page.set_cancelled()

    assert page.state == "cancelled"
    assert page.status_label.text() == expected
    assert page.generate_button.isEnabled()
    assert not page.cancel_button.isEnabled()
    for control in (
        page.open_output_button, page.open_combined_button, page.open_summary_button,
        page.open_manifest_button, page.export_button,
    ):
        assert not control.isEnabled()


def test_results_cancelled_state_retranslates_and_new_run_clears_prior_progress(qtbot):
    catalogs = CatalogSet.load(package_root(), "en")
    page = ResultsPage(catalogs)
    qtbot.addWidget(page)
    page.set_running()
    page.update_progress(ProgressEvent("docx", 2, 3, "English core message"))
    page.set_cancelled()

    catalogs.set_locale("ru")
    assert page.status_label.text() == "Операция безопасно отменена. Официальный пакет не опубликован."

    page.set_running()
    catalogs.set_locale("zh_CN")
    assert page.status_label.text() == "正在生成并验证正式批次…"
