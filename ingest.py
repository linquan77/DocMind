from langchain_community.document_loaders import PyMuPDFLoader, Docx2txtLoader, WebBaseLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from config import *

def get_embeddings():
    return OpenAIEmbeddings(
        model="deepseek-embedding",
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
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

def ingest(file_path: str):
    # 1. 加载文档
    docs = load_file(file_path)

    # 2. 切块
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(docs)

    # 3. 存入 Chroma
    vectorstore = Chroma(
        persist_directory=CHROMA_DB_PATH,
        embedding_function=get_embeddings()
    )
    vectorstore.add_documents(chunks)
    return len(chunks)