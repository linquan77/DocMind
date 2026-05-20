from langchain_community.document_loaders import PyMuPDFLoader, Docx2txtLoader, WebBaseLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from config import *

def get_embeddings():
    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True}
    )

def load_file(file_path: str):
    ext = file_path.split(".")[-1].lower()
    if ext == "pdf":
        return PyMuPDFLoader(file_path).load()
    elif ext == "docx":
        return Docx2txtLoader(file_path).load()
    elif file_path.startswith("http"):
        return WebBaseLoader(file_path).load()
    else:
        raise ValueError(f"不支持的格式: {ext}")

def ingest(file_path: str, original_name: str = None):
    # 1. 加载文档
    docs = load_file(file_path)

    #2. 设置 source 元数据为原始文件名（如果提供）或路径
    display_name = original_name or file_path
    for doc in docs:
        doc.metadata["source"] = display_name

    # 3. 切块
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(docs)

    # 4. 存入 Chroma
    vectorstore = Chroma(
        persist_directory=CHROMA_DB_PATH,
        embedding_function=get_embeddings()
    )

    # 去重检查：如果已存在相同 source 的切块，则认为文档已入库，跳过
    file_name = os.path.basename(file_path)
    existing = vectorstore.get(where={"source": display_name})
    if existing and len(existing["ids"]) > 0:
        return 0

    vectorstore.add_documents(chunks)
    return len(chunks)