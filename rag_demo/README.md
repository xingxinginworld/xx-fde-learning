# 📑 招标文件问答助手 · 端到端 RAG Demo

基于 FDE v2 Day 9「端到端 RAG Demo」落地的可运行工程。把 Day 4-8 学的五个组件
（API 调用 / 结构化输出 / 文档预处理 / 向量化与检索 / Function Calling）组装成一个
能给客户演示的 RAG 应用：输入招标文件相关问题，返回答案 + 引用出处 + 置信度。

链路：**数据管道 → 向量索引 → 检索(含重排) → LLM 生成 → Web UI**

模型全部走 **魔搭 ModelScope API-Inference**（OpenAI 兼容协议，每天免费 2000 次）。

---

## 一、项目结构

```
rag_demo/
├── config.py            # 所有可调参数（路径/模型名/检索参数），免改业务代码
├── model_client.py      # 魔搭 API 封装：embed / rerank / chat_json
├── build_index.py       # ① 离线：PDF→分块→embedding→FAISS 索引
├── retriever.py         # ② 在线：向量粗筛→阈值→重排→Top-K
├── generator.py         # ③ 在线：拼 prompt→qwen→JSON(答案+引用+置信度)
├── app.py               # ④ Streamlit UI：对话 + 引用展开 + Loading
├── requirements.txt      # 依赖（锁版本）
├── .env.template        # Key 模板（真实 .env 不入库）
├── run.sh / run.bat     # 一键启动脚本
├── data/                # 放招标文件 PDF（.gitkeep 占位）
├── index/               # FAISS 索引 + chunks.json（build 后生成，.gitkeep 占位）
├── docs/                # 交付文档（设计/评估/用户手册/部署运维/安全脱敏）
└── eval_demo.py         # 效果评估脚本（实跑 13 题，结果落 eval_result.json）
```

## 二、快速启动

### 方式一：一键脚本（推荐，自动建虚拟环境）

- Windows：双击 `run.bat`
- Linux/Mac：`bash run.sh`

脚本会自动创建 `.venv`、安装依赖、首次自动建索引、再起 Streamlit（http://localhost:8501）。

### 方式二：手动（需 Python 3.13）

```bash
py -3.13 -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
# .venv/bin/pip install -r requirements.txt      # Linux/Mac

cp .env.template .env   # 填入 MODELSCOPE_API_KEY
#   获取地址：https://www.modelscope.cn → 头像 → 访问令牌 → 新建令牌

.venv/Scripts/python build_index.py     # 构建索引（一次性，离线跑）
.venv/Scripts/streamlit run app.py       # 启动 Demo
# 浏览器自动打开 http://localhost:8501
```

> ⚠️ **务必使用本项目 `.venv`，不要直接 `pip install` 到全局 Python。**
> 全局环境的 `openai==1.40` + `httpx==0.28` 不兼容（openai 会把 `proxies` 参数传给 httpx，
> 而 httpx 0.28 已移除该参数，会报 `TypeError: ... got an unexpected keyword argument 'proxies'`）。
> `requirements.txt` 已锁定 `httpx==0.27.2` 规避该问题，只有装在 `.venv` 里才生效。

## 三、模型配置

全部在 `.env` / `config.py` 里改，不用动业务代码：

| 能力 | 默认模型 | 说明 |
|------|----------|------|
| Embedding | `Qwen/Qwen3-Embedding-0.6B` | 文本向量化，输出归一化 |
| Rerank | `Qwen/Qwen3-Reranker-4B` | 候选精排，性价比首选 |
| Chat | `Qwen/Qwen3-8B` | 生成答案，强制 JSON 输出 |

模型需用 **带「API-Inference」闪电标** 的 Model Id（在 https://modelscope.cn 确认）。
免费额度：每位用户每天 2000 次 API 调用。

## 四、可调参数（config.py / .env）

| 参数 | 默认 | 含义 |
|------|------|------|
| `TOP_K` | 5 | 重排后返回的分块数 |
| `SIM_THRESHOLD` | 0.4 | 余弦相似度阈值（低于则视为未命中） |
| `COARSE_K` | 20 | 向量粗筛召回数 |
| `CHUNK_SIZE` | 500 | 分块目标字数 |
| `CHUNK_OVERLAP` | 80 | 分块重叠字数 |

## 五、演示前 5 关自检（进客户会议室前一遍过）

1. **能启动**：换台电脑 `pip install -r requirements.txt` + `streamlit run app.py`，10 分钟内能跑起来
2. **UI 能看**：输入框/对话流排版顺畅，Loading 有反馈，不白屏
3. **主流程通**：至少 10 条业务口高频问题都能答对
4. **Bad Case 已知**：知道自己哪些问题会翻车，演示时主动说明并给兜底
5. **换机器能跑**：Key 走环境变量、路径全相对、依赖锁版本、离线包备份

## 六、可移植性 7 条规矩（FDE 基本功）

Key 走环境变量 · 路径全相对 · 依赖锁版本 · 索引与代码分离 · 参数外置 ·
网络失败兜底 · 启动一行命令。做到这 7 条，客户现场部署不再翻车。

## 七、改造成其他场景（如合同问答）

- `build_index.py`：分块分隔符由"。"改"第 X 条"（合同天然单位是"条"）
- `generator.py`：system prompt 加"金额/日期/主体必须原文引用"，并加免责声明 UI
- `retriever.py` / 依赖 / UI 主结构：**不用动**（检索五维度通用）

> 本 Demo 为教学/演示用途。正式招投标场景请确保答案经人工复核，AI 输出仅供参考。

## 九、配套交付文档（docs/）

| 文档 | 读者 | 用途 |
|------|------|------|
| `docs/设计文档.md` | 技术评审 / 接手人 | 架构图、模块边界、选型理由、参数依据 |
| `docs/效果评估报告.md` | 交付验收 | 13 题实跑：检索 100%、答案 100%、置信度分布、bad case |
| `docs/用户操作手册.md` | 业务方（招标/采购） | 能问什么、怎么问、结果怎么读、已知局限 |
| `docs/部署运维手册.md` | 运维 / 接手开发 | 服务器部署、Docker、索引更新、故障排查 |
| `docs/安全与脱敏说明.md` | 合规 / 交付负责人 | 脱敏红线、数据出域边界、密钥与复核责任 |

效果复跑：`eval_demo.py`（需 `.env` 里的 Key）→ 结果写入 `eval_result.json`。

## 八、关于重排（rerank）的说明

ModelScope API-Inference 实测**没有 `/rerank` 路由**（请求返回 `404 page not found`），所以本 Demo 的 rerank 默认改用 **Jina Rerank**（免费额度、多语言，OpenAI 兼容）。

- 默认配置：`RERANK_PROVIDER=jina`，在 `.env` 里填 `JINA_API_KEY`（免费注册 https://jina.ai/reranker 获取）。
- 行为：rerank 正常时返回精排结果；若 `JINA_API_KEY` 未填或调用失败，`retriever.py` 会**自动回退为「向量相似度排序」**（代码内置兜底，不影响主流程）。
- 想换供应商：`RERANK_PROVIDER` 还支持 `dashscope`（阿里云百炼 `qwen3-rerank`，填 `DASHSCOPE_API_KEY`）或 `none`（直接关闭重排、只用向量排序）。都在 `config.py` / `.env` 里改，不用动业务代码。
