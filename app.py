import streamlit as st
import tempfile, os
from ingest import ingest
from chain import get_qa_chain
from doc_manager import list_documents, delete_document, clear_all

st.set_page_config(page_title="RAG 知识库问答", page_icon="📚")
st.title("📚 RAG 知识库问答系统")

# 侧边栏：文档上传和管理
with st.sidebar:
    tab1, tab2 = st.tabs(["📂 上传文档", "🗂️ 文档管理"])

    # Tab1：上传
    with tab1:
        uploaded = st.file_uploader(
            "支持 PDF / Word / Excel / HTML",
            type=["pdf", "docx", "xlsx", "html", "htm"],
            accept_multiple_files=True
        )
        if uploaded and st.button("解析入库", type="primary"):
            for idx, f in enumerate(uploaded):
                st.write(f"📄 处理: {f.name}")
                progress_bar = st.progress(0)
                status_text = st.empty()

                def update_progress(progress: float, status: str):
                    progress_bar.progress(progress)
                    status_text.text(f"状态: {status}")

                with tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=f".{f.name.split('.')[-1]}"
                ) as tmp:
                    tmp.write(f.read())
                    tmp_path = tmp.name

                count = ingest(tmp_path, original_name=f.name, progress_callback=update_progress)
                os.unlink(tmp_path)

                if count == 0:
                    st.warning(f"{f.name} 已入库，跳过")
                else:
                    st.success(f"{f.name} 已入库，共 {count} 个切块")

    # Tab2：文档管理
    with tab2:
        docs = list_documents()

        if not docs:
            st.info("知识库暂无文档")
        else:
            st.caption(f"共 {len(docs)} 个文档，{sum(d['chunks'] for d in docs)} 个切块")
            st.divider()

            for doc in docs:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{doc['filename']}**")
                    st.caption(f"{doc['chunks']} 个切块")
                with col2:
                    if st.button("删除", key=f"del_{doc['filename']}"):
                        try:
                            n = delete_document(doc["source"])
                            st.success(f"已删除 {n} 个切块")
                            st.rerun()
                        except Exception as e:
                            st.error(f"删除失败：{e}")

            st.divider()
            if st.button("🗑️ 清空全部", type="secondary", use_container_width=True):
                if clear_all():
                    st.success("知识库已清空")
                    st.rerun()

    st.divider()
    all_docs = list_documents()
    doc_options = [doc["source"] for doc in all_docs]
    doc_labels = {
        doc["source"]: f"{doc['filename']}（{doc['chunks']} 块）"
        for doc in all_docs
    }
    selected_sources = st.multiselect(
        "文档选择",
        options=doc_options,
        default=doc_options,
        format_func=lambda source: doc_labels.get(source, source),
        help="只在选中的文档中检索；全选等同于整个知识库。",
    )


# 主区域：问答
st.header("💬 开始提问")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "is_thinking" not in st.session_state:
    st.session_state.is_thinking = False
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

# 第一次渲染：接收输入，禁用输入框，等待下一次渲染
if not st.session_state.is_thinking:
    if query := st.chat_input("请输入问题..."):
        st.session_state.messages.append({"role": "user", "content": query})
        st.session_state.pending_query = query
        st.session_state.is_thinking = True
        st.rerun()  # 立刻刷新 → 输入框变灰，开始第二次渲染
else:
    # 第二次渲染：输入框禁用，执行检索
    st.chat_input("请输入问题...", disabled=True)
    query = st.session_state.pending_query

    with st.chat_message("assistant"):
        with st.spinner("检索中..."):
            chain = get_qa_chain()
            metadata_filter = None
            if selected_sources and set(selected_sources) != set(doc_options):
                metadata_filter = {"source": {"$in": selected_sources}}
            result = chain.invoke({
                "question": query,
                "metadata_filter": metadata_filter,
            })
            answer = result["answer"]
            sources = result["sources"]

        st.write(answer)
        st.caption(
            f"改写查询：{result.get('rewritten_query', query)} · "
            f"平均/本次延迟统计字段：{result.get('latency_ms', 0)} ms"
        )

        if sources:
            with st.expander("📄 查看来源"):
                for doc in sources:
                    citation_id = doc.metadata.get("citation_id", "?")
                    source = doc.metadata.get("source", "未知文件")
                    doc_type = doc.metadata.get("type", "")
                    score = doc.metadata.get("score", 0)
                    rank_reason = doc.metadata.get("rank_reason", "")

                    if doc_type in ["price_table", "price_summary"]:
                        row = doc.metadata.get("row", "?")
                        location = f"第 {row} 行" if doc_type == "price_table" else "商品汇总"
                    else:
                        page = doc.metadata.get("page", "?")
                        location = f"第 {page} 页"

                    st.markdown(f"**[{citation_id}] {source}** · {location} · 相关度 {score:.3f}")
                    st.caption(rank_reason)
                    st.caption(doc.page_content[:200] + "...")

    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.session_state.is_thinking = False
    st.session_state.pending_query = None
    st.rerun()
