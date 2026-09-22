"""Inspect and render placeholders without rebuilding Word document layout."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Iterable, Mapping
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from lxml import etree


WORD_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_PARAGRAPH = f"{{{WORD_NAMESPACE}}}p"
WORD_TEXT = f"{{{WORD_NAMESPACE}}}t"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
PLACEHOLDER_PATTERN = re.compile(r"\{\{([^{}]+)\}\}")
MAX_UNCOMPRESSED_SIZE = 100 * 1024 * 1024


class TemplateInputError(ValueError):
    """Raised when a template is damaged or contains invalid placeholders."""

    def __init__(self, message: str, *, code: str = "template.invalid") -> None:
        super().__init__(message)
        self.code = code


class TemplateRenderError(ValueError):
    """Raised when a template cannot be rendered safely."""


@dataclass(frozen=True, slots=True)
class Placeholder:
    """A unique placeholder and its source occurrence details."""

    name: str
    occurrences: int
    parts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TemplateInspection:
    """Placeholders discovered in a Word template."""

    path: Path
    placeholders: tuple[Placeholder, ...]
    sha256: str = ""
    protected: bool = False
    preview_page_count: int | None = None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.placeholders)


@dataclass(slots=True)
class _PlaceholderAccumulator:
    occurrences: int
    parts: list[str]


def inspect_template(path: Path) -> TemplateInspection:
    """Discover valid placeholders in all supported Word story parts."""

    path = Path(path)
    if path.suffix.casefold() != ".docx":
        raise TemplateInputError(
            "Choose a macro-free .docx Word template.",
            code="template.unsupported_type",
        )
    members = _read_package(path)
    member_names = {info.filename for info, _data in members}
    if any(name.casefold().endswith("vbaproject.bin") for name in member_names):
        raise TemplateInputError(
            "The Word template contains macros and cannot be used safely.",
            code="template.macros_present",
        )
    if _has_editing_protection(members):
        raise TemplateInputError(
            "The Word template is protected against editing.",
            code="template.protected",
        )
    found: OrderedDict[str, _PlaceholderAccumulator] = OrderedDict()

    for part_name, data in _story_parts(members):
        root = _parse_xml(data, path)
        for paragraph in root.iter(WORD_PARAGRAPH):
            text = "".join(node.text or "" for node in _paragraph_text_nodes(paragraph))
            matches = list(PLACEHOLDER_PATTERN.finditer(text))
            remainder = PLACEHOLDER_PATTERN.sub("", text)
            if "{{" in remainder or "}}" in remainder:
                raise TemplateInputError(
                    f"Template '{path.name}' contains a malformed placeholder "
                    f"in '{part_name}'."
                )
            for match in matches:
                name = match.group(1).strip()
                if not name:
                    raise TemplateInputError(
                        f"Template '{path.name}' contains a malformed placeholder "
                        f"in '{part_name}'."
                    )
                item = found.setdefault(name, _PlaceholderAccumulator(0, []))
                item.occurrences += 1
                if part_name not in item.parts:
                    item.parts.append(part_name)

    return TemplateInspection(
        path=path,
        placeholders=tuple(
            Placeholder(name, item.occurrences, tuple(item.parts))
            for name, item in found.items()
        ),
        sha256=_sha256_file(path),
    )


def _has_editing_protection(members: Iterable[tuple[object, bytes]]) -> bool:
    for info, data in members:
        if info.filename != "word/settings.xml":
            continue
        root = _parse_xml(data, Path("settings.xml"))
        if root.find(f".//{{{WORD_NAMESPACE}}}documentProtection") is not None:
            return True
    return False


def _sha256_file(path: Path) -> str:
    from hashlib import sha256

    digest = sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def render_template(
    source: Path,
    destination: Path,
    replacements: Mapping[str, str],
) -> None:
    """Render a new DOCX while preserving the original package and run styles."""

    source = Path(source)
    destination = Path(destination)
    if source.resolve() == destination.resolve():
        raise TemplateRenderError("The output path cannot replace the source template.")

    inspection = inspect_template(source)
    unknown = sorted(set(replacements) - set(inspection.names))
    if unknown:
        joined = ", ".join(f"{{{{{name}}}}}" for name in unknown)
        raise TemplateRenderError(
            f"Replacement placeholder is not present in the template: {joined}"
        )

    normalized_replacements = {key: str(value) for key, value in replacements.items()}
    members = _read_package(source)
    rendered: list[tuple[object, bytes]] = []
    for info, data in members:
        if _is_story_part(info.filename):
            root = _parse_xml(data, source)
            for paragraph in root.iter(WORD_PARAGRAPH):
                _replace_in_paragraph(paragraph, normalized_replacements)
            data = etree.tostring(
                root,
                xml_declaration=True,
                encoding="UTF-8",
                standalone=True,
            )
        rendered.append((info, data))

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with ZipFile(temporary, "w") as package:
            for info, data in rendered:
                package.writestr(info, data)
        os.replace(temporary, destination)

        remaining = set(inspect_template(destination).names) & set(replacements)
        if remaining:
            joined = ", ".join(f"{{{{{name}}}}}" for name in sorted(remaining))
            destination.unlink(missing_ok=True)
            raise TemplateRenderError(
                f"Template placeholders were not fully replaced: {joined}"
            )
    except TemplateRenderError:
        raise
    except Exception as error:
        destination.unlink(missing_ok=True)
        raise TemplateRenderError(
            f"Certificate document '{destination.name}' could not be created safely."
        ) from error
    finally:
        temporary.unlink(missing_ok=True)


def _read_package(path: Path) -> list[tuple[object, bytes]]:
    try:
        with ZipFile(path, "r") as package:
            infos = package.infolist()
            if sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_SIZE:
                raise TemplateInputError(
                    f"Word template '{path.name}' is too large to process safely."
                )
            damaged = package.testzip()
            if damaged is not None:
                raise TemplateInputError(
                    f"Word template '{path.name}' contains a damaged file: {damaged}."
                )
            return [(item, package.read(item.filename)) for item in infos]
    except TemplateInputError:
        raise
    except (BadZipFile, OSError, KeyError) as error:
        raise TemplateInputError(
            f"Word template '{path.name}' could not be read. "
            "It may be damaged or not a valid .docx file."
        ) from error


def _story_parts(
    members: Iterable[tuple[object, bytes]],
) -> Iterable[tuple[str, bytes]]:
    for info, data in members:
        if _is_story_part(info.filename):
            yield info.filename, data


def _is_story_part(name: str) -> bool:
    if name == "word/document.xml":
        return True
    filename = name.rsplit("/", maxsplit=1)[-1]
    return name.startswith("word/") and (
        filename.startswith("header")
        or filename.startswith("footer")
        or filename in {"footnotes.xml", "endnotes.xml", "comments.xml"}
    ) and name.endswith(".xml")


def _parse_xml(data: bytes, path: Path):
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        recover=False,
        remove_blank_text=False,
        huge_tree=False,
    )
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as error:
        raise TemplateInputError(
            f"Word template '{path.name}' contains malformed document XML."
        ) from error


def _paragraph_text_nodes(paragraph) -> list:
    nodes = []
    for node in paragraph.iter(WORD_TEXT):
        ancestor = node.getparent()
        while ancestor is not None and ancestor.tag != WORD_PARAGRAPH:
            ancestor = ancestor.getparent()
        if ancestor is paragraph:
            nodes.append(node)
    return nodes


def _replace_in_paragraph(paragraph, replacements: Mapping[str, str]) -> None:
    nodes = _paragraph_text_nodes(paragraph)
    if not nodes:
        return
    full_text = "".join(node.text or "" for node in nodes)
    matches = [
        match
        for match in PLACEHOLDER_PATTERN.finditer(full_text)
        if match.group(1).strip() in replacements
    ]
    for match in reversed(matches):
        name = match.group(1).strip()
        _replace_span(nodes, match.start(), match.end(), replacements[name])


def _replace_span(nodes, start: int, end: int, replacement: str) -> None:
    positions: list[tuple[int, int]] = []
    cursor = 0
    for index, node in enumerate(nodes):
        text = node.text or ""
        positions.append((cursor, cursor + len(text)))
        cursor += len(text)

    start_index = next(
        index
        for index, (node_start, node_end) in enumerate(positions)
        if node_start <= start < node_end
    )
    end_index = next(
        index
        for index, (node_start, node_end) in enumerate(positions)
        if node_start < end <= node_end
    )
    start_offset = start - positions[start_index][0]
    end_offset = end - positions[end_index][0]

    if start_index == end_index:
        text = nodes[start_index].text or ""
        nodes[start_index].text = text[:start_offset] + replacement + text[end_offset:]
        _preserve_spaces(nodes[start_index])
        return

    start_text = nodes[start_index].text or ""
    end_text = nodes[end_index].text or ""
    nodes[start_index].text = start_text[:start_offset] + replacement
    _preserve_spaces(nodes[start_index])
    for index in range(start_index + 1, end_index):
        nodes[index].text = ""
    nodes[end_index].text = end_text[end_offset:]
    _preserve_spaces(nodes[end_index])


def _preserve_spaces(node) -> None:
    text = node.text or ""
    if text[:1].isspace() or text[-1:].isspace():
        node.set(XML_SPACE, "preserve")
