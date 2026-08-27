"""config.py — 全局配置中心：把「所有能改的参数」集中在这里。

为什么要有这个文件？
----------------------
一个能交付的 AI 应用，最怕把参数写死在业务代码里。比如：
- 想换个模型，却要去改 10 个文件？不行。
- 把 Key（密钥）直接写在代码里，一提交到 Git 就泄露了？不行。
所以 Day 9 的规矩是「参数外置」：所有路径、模型名、阈值、Key 都放本文件，
业务代码（build_index / retriever / generator / app）只负责「做事」，不负责「记参数」。

本文件做三件事：
1) 确定项目根目录，加载同目录下的 .env（里面放密钥）；
2) 从环境变量读取各项配置（没填就用默认值）；
3) 把这些配置以「大写常量」的形式暴露给其它模块 import 使用。

整个 RAG 链路怎么串起来（先看一眼全局，后面每个文件会细讲）：
  data/*.pdf  →[build_index]→  index/vecs.faiss + chunks.json
  用户提问     →[retriever]→   召回相关段落
  相关段落     →[generator]→   大模型生成答案(JSON)
  答案         →[app]→         Streamlit 网页展示
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# BASE = 本文件(config.py)所在的目录，也就是 rag_demo 根目录。
# 用 Path(__file__).parent 而不是写死 "D:/..."，是为了「换台电脑也能直接跑」。
BASE = Path(__file__).parent

# 加载同目录的 .env 文件（里面是 MODELSCOPE_API_KEY 等密钥）。
# .env 被写进了 .gitignore，不会随代码提交，避免密钥泄露。
# load_dotenv 会把 .env 里的 "KEY=VALUE" 注入到「环境变量」，
# 之后用 os.getenv("KEY") 就能读到（见下方各配置项）。
load_dotenv(BASE / ".env")


# ─────────────────────────────────────────────────────────────
# 一、路径配置（全部用相对路径，跟着项目走）
# ─────────────────────────────────────────────────────────────
# 放招标文件 PDF 的目录。build_index.py 会扫描这个目录下的所有 .pdf。
DATA_DIR = BASE / "data"
# 向量索引产物的目录。build_index.py 会生成 vecs.faiss（向量库）和 chunks.json（原文段落）。
# 这俩文件是「构建一次、反复读」，所以和源码分开存放。
INDEX_DIR = BASE / "index"


# ─────────────────────────────────────────────────────────────
# 二、魔搭 ModelScope 平台配置（文本向量化 + 对话生成走这里）
# ─────────────────────────────────────────────────────────────
# 凭证（API Key）获取地址：https://www.modelscope.cn → 头像 → 访问令牌 → 新建令牌
# 协议：OpenAI 兼容协议，所有接口都在 /v1 路径下。
# base_url：API 的「总入口」。后面 embedding / chat 都在这个地址后面拼具体接口。
MODELSCOPE_BASE_URL = os.getenv("MODELSCOPE_BASE_URL", "https://api-inference.modelscope.cn/v1")
# API Key：调用任何模型都必须带的「身份凭证」，相当于你的通行证。
# 默认空串；如果没在 .env 里填，运行时调用会报 401 未授权。
API_KEY = os.getenv("MODELSCOPE_API_KEY", "")

# 三个模型的「模型名」（Model Id）。
# 注意：必须在 modelscope.cn 上确认该模型带「API-Inference」闪电标，否则不能这么调用。
# 1) 嵌入模型：把一段文字变成一串数字（向量），用来算相似度。
EMBED_MODEL = os.getenv("EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
# 2) 重排模型：把候选段落按「和问题的相关度」重新排序。
#    （注：ModelScope 实测无此接口，默认改用 Jina，见下方「三、重排提供商」）
RERANK_MODEL = os.getenv("RERANK_MODEL", "Qwen/Qwen3-Reranker-4B")
# 3) 对话模型：真正「读材料、写答案」的大语言模型。
CHAT_MODEL = os.getenv("CHAT_MODEL", "Qwen/Qwen3-8B")


# ─────────────────────────────────────────────────────────────
# 三、重排（rerank）提供商配置
# ─────────────────────────────────────────────────────────────
# 背景：RAG 检索分两步 —— 先「粗筛」(向量召回一堆候选)，再「精排」(rerank 重排优劣)。
# 但实测 ModelScope 的 API 没有 /rerank 路由（返回 404），所以 rerank 默认改用 Jina（免费额度）。
# RERANK_PROVIDER 决定用哪家重排服务，可选值：
#   jina       → 默认，免费额度，支持多语言（https://api.jina.ai/v1/rerank）
#   dashscope  → 阿里云百炼的 qwen3-rerank（需另外的 DASHSCOPE_API_KEY）
#   modelscope → 原魔搭（实测 404 不可用，仅保留作兼容）
#   none       → 完全不做重排，retriever 会直接用向量粗筛结果
RERANK_PROVIDER = os.getenv("RERANK_PROVIDER", "jina")

# Jina Rerank 配置（默认选用）
# Key 获取：https://jina.ai/reranker 注册后在控制台获取（有免费额度）。
JINA_API_KEY = os.getenv("JINA_API_KEY", "")
# Jina 的 rerank 接口地址。
JINA_RERANK_URL = os.getenv("JINA_RERANK_URL", "https://api.jina.ai/v1/rerank")
# 使用的重排模型（多语言、轻量）。
JINA_RERANK_MODEL = os.getenv("JINA_RERANK_MODEL", "jina-reranker-v2-base-multilingual")

# 阿里云百炼 DashScope 重排配置（备用，默认不用）
# 若想用，把 RERANK_PROVIDER 改成 dashscope，并填上 DASHSCOPE_API_KEY。
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_RERANK_URL = os.getenv("DASHSCOPE_RERANK_URL", "https://dashscope.aliyuncs.com/compatible-api/v1/rerank")
DASHSCOPE_RERANK_MODEL = os.getenv("DASHSCOPE_RERANK_MODEL", "qwen3-rerank")


# ─────────────────────────────────────────────────────────────
# 四、文档预处理（分块）参数 —— Day 7 知识点
# ─────────────────────────────────────────────────────────────
# 什么是「分块」？
#   招标文件动辄几十页，直接整篇丢给模型会超长、还会稀释重点。
#   所以要把长文切成一段段「语义完整的块」（chunk），再分别向量化、检索。
# 每个分块的目标字数。太大→检索不精准；太小→语义被切断。500 字是中文文档常用值。
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
# 分块之间的「重叠字数」。相邻两块重叠一小段，避免一句话被硬生生切断在两块之间。
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "80"))


# ─────────────────────────────────────────────────────────────
# 五、检索参数 —— Day 8 知识点
# ─────────────────────────────────────────────────────────────
# 向量粗筛时，先「召回」多少个候选段落。先多召回一些，交给 rerank 再精挑。
COARSE_K = int(os.getenv("COARSE_K", "20"))
# 重排之后，最终返回给用户的段落条数。一般 3~5 条足够回答一个问题。
TOP_K = int(os.getenv("TOP_K", "5"))
# 相似度阈值（0~1）。只有相似度 ≥ 此值的段落才算「命中」。
# 因为向量已做 L2 归一化，这里的内积就等于余弦相似度，所以直接用 0~1 比较。
SIM_THRESHOLD = float(os.getenv("SIM_THRESHOLD", "0.4"))


# ─────────────────────────────────────────────────────────────
# 六、其它杂项
# ─────────────────────────────────────────────────────────────
# 调用嵌入模型时，一次最多送多少段文字（批量请求，省时间也省额度）。
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "16"))
