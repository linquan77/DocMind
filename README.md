# RAG 知识库问答系统

基于 LangChain + DeepSeek V4 + Chroma 的多格式文档智能问答系统。

## 功能
- 支持 PDF、Word、网页文档解析
- 基于向量语义检索
- DeepSeek V4 生成回答，支持流式输出
- 来源引用展示

## 快速开始

1. 克隆项目
```bash
git clone https://github.com/linquan77/RAG-.git
cd RAG-
```

2. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 填入你的 DeepSeek API Key
```

3. 启动
```bash
docker compose up --build
```

4. 打开浏览器访问 `http://localhost:8501`

## 技术栈
- LangChain
- DeepSeek V4 API
- Chroma 向量数据库
- Streamlit