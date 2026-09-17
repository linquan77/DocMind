"""Parse immutable MediaWiki JSON snapshots into semantic sections.

The parser intentionally depends on MediaWiki's semantic HTML structure rather
than page-specific fields. Building, critter, element, and resource pages can
therefore share the same pipeline while future special templates remain easy
to add as independent extractors.
"""

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import time
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag


_HEADING_TAGS = {"h2", "h3", "h4", "h5", "h6"}
_CONTENT_BLOCK_TAGS = {"p", "ul", "ol", "table", "dl", "blockquote", "pre"}
_NOISE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "template",
    ".mw-editsection",
    ".mbox",
    ".toc",
    ".navbox",
    ".vertical-navbox",
    ".catlinks",
    ".printfooter",
    ".mw-references-wrap",
    "sup.reference",
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WikiSection:
    """One independently retrievable semantic section from a Wiki page."""

    heading_path: tuple[str, ...]
    content: str
    section_type: str = "section"

    @property
    def title(self) -> str:
        return self.heading_path[-1]


@dataclass(frozen=True)
class ParsedWikiPage:
    """Normalized page metadata plus sections extracted from one snapshot."""

    schema_version: int
    page_id: int
    revision_id: int
    title: str
    canonical_url: str
    revision_timestamp: str
    categories: tuple[str, ...]
    content_sha256: str
    source_name: str
    snapshot_path: str
    sections: tuple[WikiSection, ...]


def _clean_text(value: str) -> str:
    value = value.replace("\xa0", " ").replace("\u200b", "")
    lines = []
    for raw_line in value.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def _clean_heading(value: str) -> str:
    value = re.sub(r"\[\s*编辑\s*\]", "", value)
    return _clean_text(value)


def _inside_nested_infobox_group(element: Tag, container: Tag) -> bool:
    """Return whether an infobox field belongs to a child semantic group."""

    parent_group = element.find_parent("section", class_="pi-group")
    return parent_group is not None and parent_group is not container


def _extract_infobox_lines(container: Tag) -> list[str]:
    lines: list[str] = []
    for caption in container.select(".pi-caption"):
        if _inside_nested_infobox_group(caption, container):
            continue
        text = _clean_text(caption.get_text(" ", strip=True))
        if text:
            lines.append(f"说明：{text}")

    for item in container.select(".pi-data"):
        if _inside_nested_infobox_group(item, container):
            continue
        label_tag = item.select_one(".pi-data-label")
        value_tag = item.select_one(".pi-data-value")
        label = _clean_text(label_tag.get_text(" ", strip=True)) if label_tag else ""
        value = _clean_text(value_tag.get_text(" ", strip=True)) if value_tag else ""
        if label and value:
            lines.append(f"{label}：{value}")
        elif value:
            lines.append(value)

    # Some older Wiki skins use a classic table instead of a portable infobox.
    for row in container.select("tr"):
        if _inside_nested_infobox_group(row, container):
            continue
        cells = [_clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            lines.append(f"{cells[0]}：{' | '.join(cells[1:])}")
        elif cells:
            lines.append(cells[0])

    return list(dict.fromkeys(lines))


def _extract_portable_infobox_sections(
    container: Tag,
    heading_path: tuple[str, ...],
) -> list[WikiSection]:
    """Keep portable-infobox group headers as retrievable section context.

    A long group such as ``食谱`` may be split into several chunks. Making the
    group a separate WikiSection ensures the splitter repeats that title in
    every resulting chunk instead of leaving it only at the start of a large
    flattened infobox.
    """

    base_lines = _extract_infobox_lines(container)
    grouped_sections: list[WikiSection] = []
    for group in container.select("section.pi-group"):
        # Nested groups are handled by their nearest top-level group so fields
        # are not emitted more than once.
        if group.find_parent("section", class_="pi-group") is not None:
            continue
        header = group.find(class_="pi-header", recursive=False)
        group_title = (
            _clean_heading(header.get_text(" ", strip=True)) if header else ""
        )
        lines = _extract_infobox_lines(group)
        if not lines:
            continue
        if not group_title:
            # Headerless groups still belong to the variant-level information.
            base_lines.extend(lines)
            continue
        grouped_sections.append(
            WikiSection(
                heading_path=(*heading_path, group_title),
                content="\n".join(lines),
                section_type="infobox",
            )
        )

    sections: list[WikiSection] = []
    if base_lines:
        sections.append(
            WikiSection(
                heading_path=heading_path,
                content="\n".join(list(dict.fromkeys(base_lines))),
                section_type="infobox",
            )
        )
    sections.extend(grouped_sections)
    return sections


def _extract_infobox_sections(root: Tag) -> list[WikiSection]:
    sections: list[WikiSection] = []

    for box in list(root.select("aside.portable-infobox")):
        classes = set(box.get("class", []))
        # Wiki navigation boxes use the same base component but contain links
        # to hundreds of unrelated pages, so they are retrieval noise.
        if "pi-theme-navbox" not in classes:
            tabs = {
                str(tab.get("data-ref")): _clean_text(tab.get_text(" ", strip=True))
                for tab in box.select(".pi-section-tab[data-ref]")
            }
            tab_contents = box.select(".pi-section-content[data-ref]")
            if tab_contents:
                for content in tab_contents:
                    ref = str(content.get("data-ref"))
                    variant = tabs.get(ref) or f"变种 {ref}"
                    sections.extend(
                        _extract_portable_infobox_sections(
                            content,
                            ("信息框", variant),
                        )
                    )
            else:
                sections.extend(
                    _extract_portable_infobox_sections(
                        box,
                        ("信息框",),
                    )
                )
        box.decompose()

    for table in list(root.select("table.infobox")):
        lines = _extract_infobox_lines(table)
        if lines:
            sections.append(
                WikiSection(
                    heading_path=("信息框",),
                    content="\n".join(lines),
                    section_type="infobox",
                )
            )
        table.decompose()

    return sections


def _extract_block(element: Tag) -> str:
    if element.name in {"ul", "ol"}:
        marker = "-" if element.name == "ul" else "1."
        items = [
            _clean_text(item.get_text(" ", strip=True))
            for item in element.find_all("li", recursive=False)
        ]
        return "\n".join(f"{marker} {item}" for item in items if item)

    if element.name == "table":
        rows: list[str] = []
        for row in element.find_all("tr"):
            cells = [
                _clean_text(cell.get_text(" ", strip=True))
                for cell in row.find_all(["th", "td"], recursive=False)
            ]
            cells = [cell for cell in cells if cell]
            if cells and re.search(r"[\w\u4e00-\u9fff]", " ".join(cells)):
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    if element.name == "dl":
        return _clean_text(element.get_text("\n", strip=True))

    return _clean_text(element.get_text(" ", strip=True))


def _extract_body_sections(root: Tag) -> list[WikiSection]:
    for selector in _NOISE_SELECTORS:
        for element in list(root.select(selector)):
            element.decompose()

    # Any remaining aside is an auxiliary panel rather than article prose.
    for aside in list(root.find_all("aside")):
        aside.decompose()

    sections: list[WikiSection] = []
    heading_stack: list[tuple[int, str]] = []
    current_path = ("摘要",)
    current_blocks: list[str] = []

    def flush() -> None:
        content = "\n\n".join(block for block in current_blocks if block)
        if content:
            sections.append(WikiSection(heading_path=current_path, content=content))

    wanted_tags = sorted(_HEADING_TAGS | _CONTENT_BLOCK_TAGS)
    for element in root.find_all(wanted_tags):
        if not isinstance(element, Tag):
            continue
        if element.name in _HEADING_TAGS:
            flush()
            current_blocks = []
            level = int(element.name[1])
            heading = _clean_heading(element.get_text(" ", strip=True))
            if not heading:
                continue
            heading_stack = [(old_level, value) for old_level, value in heading_stack if old_level < level]
            heading_stack.append((level, heading))
            current_path = tuple(value for _, value in heading_stack)
            continue

        # Do not extract a nested list or paragraph again when its containing
        # table/list/blockquote is already treated as one semantic block.
        if element.find_parent(list(_CONTENT_BLOCK_TAGS)) is not None:
            continue
        block = _extract_block(element)
        if block:
            current_blocks.append(block)

    flush()
    return sections


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Wiki 快照缺少有效的 {name}")
    return value


def parse_wiki_snapshot(file_path: str | Path) -> ParsedWikiPage:
    """Read one JSON snapshot and return page-type-independent sections."""

    started = time.perf_counter()
    path = Path(file_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 Wiki 快照: {path}") from exc

    payload = _require_mapping(payload, "根对象")
    page = _require_mapping(payload.get("page"), "page")
    source = _require_mapping(payload.get("source"), "source")
    html = payload.get("html")
    if not isinstance(html, str) or not html.strip():
        raise ValueError(f"Wiki 快照没有可解析的 HTML: {path}")

    try:
        page_id = int(page["page_id"])
        revision_id = int(page["revision_id"])
        title = str(page["title"]).strip()
        canonical_url = str(page["canonical_url"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Wiki 快照 page 元数据不完整: {path}") from exc
    if not title:
        raise ValueError(f"Wiki 快照标题为空: {path}")

    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".mw-parser-output") or soup.body or soup
    infobox_sections = _extract_infobox_sections(root)
    body_sections = _extract_body_sections(root)
    sections = tuple(infobox_sections + body_sections)
    if not sections:
        raise ValueError(f"Wiki 快照没有可索引正文: {path}")

    raw_categories = page.get("categories", [])
    categories = (
        tuple(str(category).strip() for category in raw_categories if str(category).strip())
        if isinstance(raw_categories, list)
        else ()
    )
    parsed_page = ParsedWikiPage(
        schema_version=int(payload.get("schema_version", 1)),
        page_id=page_id,
        revision_id=revision_id,
        title=title,
        canonical_url=canonical_url,
        revision_timestamp=str(page.get("revision_timestamp", "")),
        categories=categories,
        content_sha256=str(payload.get("content_sha256", "")),
        source_name=str(source.get("name", "MediaWiki")),
        snapshot_path=path.as_posix(),
        sections=sections,
    )
    logger.info(
        "Wiki snapshot parsed page_id=%d revision_id=%d sections=%d latency_ms=%d",
        parsed_page.page_id,
        parsed_page.revision_id,
        len(parsed_page.sections),
        int((time.perf_counter() - started) * 1000),
    )
    return parsed_page
