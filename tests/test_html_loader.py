from app.rag.loaders import load_html
from app.rag.splitter import split_documents


def test_local_html_loader_extracts_visible_text_and_metadata(tmp_path):
    html_path = tmp_path / "guide.html"
    html_path.write_text(
        """
        <html>
          <head>
            <title>Docmind 使用指南</title>
            <style>.secret { display: none; }</style>
            <script>window.secret = '不可索引';</script>
          </head>
          <body>
            <h1>本地 HTML 问答</h1>
            <p>系统会提取页面中的可见文本。</p>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    documents = load_html(str(html_path))
    chunks = split_documents(documents, str(html_path))

    assert len(documents) == 1
    assert "本地 HTML 问答" in documents[0].page_content
    assert "不可索引" not in documents[0].page_content
    assert documents[0].metadata["source"] == "guide.html"
    assert documents[0].metadata["title"] == "Docmind 使用指南"
    assert documents[0].metadata["type"] == "html"
    assert chunks[0].metadata["chunk_index"] == 0
