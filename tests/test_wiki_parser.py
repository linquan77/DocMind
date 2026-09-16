import json

from app.rag.splitter import split_wiki_page
from app.rag.wiki_parser import ParsedWikiPage, WikiSection, parse_wiki_snapshot


def write_snapshot(tmp_path, html: str, *, title: str = "电解器"):
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": {"name": "缺氧 Wiki（中文）"},
                "page": {
                    "page_id": 4925,
                    "revision_id": 37451,
                    "title": title,
                    "canonical_url": f"https://example.test/wiki/{title}",
                    "revision_timestamp": "2026-09-16T00:00:00Z",
                    "categories": ["氧气建筑"],
                },
                "content_sha256": "a" * 64,
                "html": html,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_parse_building_page_keeps_structure_and_removes_navigation(tmp_path):
    path = write_snapshot(
        tmp_path,
        """
        <div class="mw-parser-output">
          <div class="mbox">版本提示噪声</div>
          <aside class="portable-infobox pi-theme-building">
            <h2 class="pi-title">电解器</h2>
            <figure><figcaption class="pi-caption">把水转化为气体。</figcaption></figure>
            <div class="pi-data">
              <h3 class="pi-data-label">ID</h3>
              <div class="pi-data-value">Electrolyzer</div>
            </div>
            <div class="pi-data">
              <h3 class="pi-data-label">功率</h3>
              <div class="pi-data-value">120 瓦</div>
            </div>
          </aside>
          <p>电解器使用水制造氧气和氢气。</p>
          <h2>机制 <span class="mw-editsection">[编辑]</span></h2>
          <p>每秒消耗 1000 克水。</p>
          <table>
            <tr><th>产物</th><th>质量</th></tr>
            <tr><td>氧气</td><td>888 克</td></tr>
          </table>
          <aside class="portable-infobox pi-theme-navbox">
            <div class="pi-data"><div class="pi-data-value">大量建筑导航噪声</div></div>
          </aside>
          <div class="mw-references-wrap">参考文献噪声</div>
        </div>
        """,
    )

    page = parse_wiki_snapshot(path)

    assert [section.heading_path for section in page.sections] == [
        ("信息框",),
        ("摘要",),
        ("机制",),
    ]
    assert "ID：Electrolyzer" in page.sections[0].content
    assert "功率：120 瓦" in page.sections[0].content
    assert "产物 | 质量" in page.sections[2].content
    all_text = "\n".join(section.content for section in page.sections)
    assert "建筑导航噪声" not in all_text
    assert "版本提示噪声" not in all_text
    assert "参考文献噪声" not in all_text
    assert "编辑" not in "".join(page.sections[2].heading_path)


def test_parse_tabbed_critter_infobox_without_hardcoded_fields(tmp_path):
    path = write_snapshot(
        tmp_path,
        """
        <div class="mw-parser-output">
          <aside class="portable-infobox pi-theme-critter">
            <ul class="pi-section-navigation">
              <li class="pi-section-tab" data-ref="0">好吃哈奇</li>
              <li class="pi-section-tab" data-ref="1">石壳哈奇</li>
            </ul>
            <div class="pi-section-content" data-ref="0">
              <div class="pi-data">
                <h3 class="pi-data-label">每周期代谢</h3>
                <div class="pi-data-value">140 千克</div>
              </div>
            </div>
            <div class="pi-section-content" data-ref="1">
              <div class="pi-data">
                <h3 class="pi-data-label">任意新字段</h3>
                <div class="pi-data-value">仍然可以被提取</div>
              </div>
            </div>
          </aside>
          <p>哈奇会生产煤炭。</p>
          <h2>养殖方式</h2>
          <h3>煤炭产出</h3>
          <p>可通过喂食提高煤炭产量。</p>
        </div>
        """,
        title="好吃哈奇",
    )

    page = parse_wiki_snapshot(path)

    assert page.sections[0].heading_path == ("信息框", "好吃哈奇")
    assert page.sections[1].heading_path == ("信息框", "石壳哈奇")
    assert "每周期代谢：140 千克" in page.sections[0].content
    assert "任意新字段：仍然可以被提取" in page.sections[1].content
    assert page.sections[-1].heading_path == ("养殖方式", "煤炭产出")


def test_parse_classic_table_infobox(tmp_path):
    path = write_snapshot(
        tmp_path,
        """
        <div class="mw-parser-output">
          <table class="infobox">
            <tr><th>熔点</th><td>1000°C</td></tr>
            <tr><th>状态</th><td>固体</td></tr>
          </table>
          <p>这是一种元素。</p>
        </div>
        """,
        title="测试元素",
    )

    page = parse_wiki_snapshot(path)

    assert page.sections[0].section_type == "infobox"
    assert page.sections[0].content == "熔点：1000°C\n状态：固体"
    assert page.sections[1].heading_path == ("摘要",)


def test_split_wiki_page_never_crosses_section_boundaries():
    page = ParsedWikiPage(
        schema_version=1,
        page_id=1,
        revision_id=2,
        title="测试页面",
        canonical_url="https://example.test/wiki/test",
        revision_timestamp="2026-09-16T00:00:00Z",
        categories=("建筑", "电力"),
        content_sha256="b" * 64,
        source_name="测试 Wiki",
        snapshot_path="data/raw/wiki/1/2.json",
        sections=(
            WikiSection(("机制",), "甲" * 120),
            WikiSection(("技巧",), "乙" * 80),
        ),
    )

    chunks = split_wiki_page(
        page,
        document_id="document-1",
        chunk_size=60,
        chunk_overlap=10,
    )

    assert len(chunks) > 2
    assert all(not ("甲" in chunk.page_content and "乙" in chunk.page_content) for chunk in chunks)
    assert {chunk.metadata["section"] for chunk in chunks} == {"机制", "技巧"}
    assert all(chunk.metadata["document_id"] == "document-1" for chunk in chunks)
    assert all(chunk.metadata["categories"] == "建筑|电力" for chunk in chunks)
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.metadata["chunk_total"] == len(chunks) for chunk in chunks)
