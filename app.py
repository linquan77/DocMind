import streamlit as st
import tempfile, os
from ingest import ingest
from chain import get_qa_chain

st.set_page_config(page_title="RAG 知识库问答", page_icon="📚")
st.title("📚 RAG 知识库问答系统")

# 侧边栏：文档上传
with st.sidebar:
    st.header("📂 上传文档")
    uploaded = st.file_uploader(
        "支持 PDF / Word",
        type=["pdf", "docx"],
        accept_multiple_files=True
    )
    if uploaded and st.button("解析入库"):
        for f in uploaded:
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{f.name.split('.')[-1]}") as tmp:
                tmp.write(f.read())
                count = ingest(tmp.name)
                os.unlink(tmp.name)
            st.success(f"{f.name} 已入库，共 {count} 个切块")

# 主区域：问答
st.header("💬 开始提问")
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

if query := st.chat_input("请输入问题..."):
    st.session_state.messages.append({"role": "user", "content": query})
    st.chat_message("user").write(query)

    with st.chat_message("assistant"):
        with st.spinner("检索中..."):
            # 提问时才初始化，避免 chroma_db 不存在报错
            chain = get_qa_chain()
            result = chain.invoke(query)
            answer = result["answer"]
            sources = result["sources"]

        st.write(answer)

        if sources:
            with st.expander("📄 查看来源"):
                for doc in sources:
                    st.markdown(f"**{doc.metadata.get('source', '未知文件')}**  "
                                f"第 {doc.metadata.get('page', '?')} 页")
                    st.caption(doc.page_content[:200] + "...")

    st.session_state.messages.append({"role": "assistant", "content": answer})