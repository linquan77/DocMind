from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
from retriever import get_retriever
from config import *

PROMPT_TEMPLATE = """你是一个知识库问答助手。请根据以下参考内容回答问题。
如果参考内容中没有相关信息，请直接说"文档中未找到相关信息"，不要编造。

参考内容：
{context}

问题：{question}

请用中文回答。
"""

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

def get_qa_chain():
    llm = ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        streaming=True
    )
    prompt = PromptTemplate.from_template(PROMPT_TEMPLATE)
    retriever = get_retriever()

    chain = (
        {"context": retriever | format_docs, "question": RunnablePassthrough()}
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain