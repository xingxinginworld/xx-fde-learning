"""app.py — ④ 在线界面：用 Streamlit 搭一个网页聊天界面（Day 9 交付最后一环）。

前面三个模块（build_index / retriever / generator）都是「后端逻辑」。
本文件把它们拼起来，做成客户/同事打开浏览器就能用的界面：
  输入问题 → 调用 retrieve 找材料 → 调用 generate 写答案 → 网页展示答案和引用。

Streamlit 特点：写普通 Python 函数式的脚本，它自动帮你渲染成网页，
20~50 行就能交付一个能演示的界面，非常适合做 Demo。

启动（务必在 .venv 里跑）：
  .venv/Scripts/streamlit run app.py  （自动打开 http://localhost:8501）
"""

import streamlit as st
from dotenv import load_dotenv

import config
from retriever import retrieve   # 检索模块
from generator import generate   # 生成模块

# 再加载一次 .env（让 Streamlit 子进程也能拿到环境变量；和 config 里加载不冲突）。
load_dotenv()

# ── 页面基础设置 ──
st.set_page_config(page_title="招标文件问答助手", page_icon="📑", layout="wide")
st.title("📑 招标文件问答助手")
st.caption("Powered by 魔搭 ModelScope API · 基于 RAG 的招标文件检索问答系统 · Demo v1")

# ── 前置检查：索引必须构建过 ──
# 如果没跑过 build_index.py，vecs.faiss 不存在，直接友好提示并停止，
# 避免后面检索时报一堆看不懂的报错。
if not (config.INDEX_DIR / "vecs.faiss").exists():
    st.error(
        "⚠️ 尚未构建索引。请按以下步骤操作：\n"
        "1) 把招标文件 PDF 放入 `data/` 目录；\n"
        "2) 运行 `python build_index.py` 构建向量索引；\n"
        "3) 再启动本 Demo：`streamlit run app.py`。"
    )
    st.stop()  # 终止本页后续渲染

# ── 聊天历史：用 session_state 跨多次交互保存 ──
# Streamlit 每次交互都会重跑整个脚本，用 st.session_state 才能记住之前聊过什么。
if "messages" not in st.session_state:
    st.session_state.messages = []

# ── 侧边栏：检索参数实时可调（不用改代码）──
with st.sidebar:
    st.header("🔧 检索参数")
    # 滑块调 Top-K：控制最终返回几条参考段落。
    top_k = st.slider("Top-K（返回条数）", 1, 10, config.TOP_K)
    # 滑块调相似度阈值：越高越严格（只返回高度相关的结果）。
    threshold = st.slider("相似度阈值", 0.0, 1.0, config.SIM_THRESHOLD, 0.05)
    st.divider()
    st.markdown("**演示前 5 关自检**")
    st.caption("能启动 / UI 能看 / 主流程通 / Bad Case 已知 / 换机器能跑")

# ── 把历史消息逐条渲染出来 ──
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        # 如果是 assistant 的回答且带了引用，用可折叠的「参考出处」展示。
        if msg.get("citations"):
            with st.expander(f"📚 参考出处（{len(msg['citations'])} 条）"):
                for c in msg["citations"]:
                    st.write(f"- {c.get('source', '')} · 第 {c.get('page', '?')} 页")

# ── 输入框：用户在底部输入问题 ──
# st.chat_input 返回用户输入的文字；为空时下面的代码块不执行。
if query := st.chat_input("请输入你的问题，例如：投标截止日期是什么时候？"):
    # 1) 把用户问题存入历史，并渲染出来。
    st.session_state.messages.append({"role": "user", "content": query})
    with st.chat_message("user"):
        st.markdown(query)

    # 2) 进入「助手」回答区。
    with st.chat_message("assistant"):
        # 2a) 检索阶段：转圈提示「检索中...」，调用 retriever 找相关段落。
        with st.spinner("检索中..."):
            contexts = retrieve(query, top_k=top_k, threshold=threshold)
        # 2b) 没检索到任何内容：直接给兜底话术，不调大模型。
        if not contexts:
            answer = "抱歉，知识库里没有找到相关内容，建议转人工咨询。"
            st.warning(answer)
            st.session_state.messages.append({"role": "assistant", "content": answer})
        else:
            # 2c) 生成阶段：把材料交给大模型写答案。
            with st.spinner("生成回答..."):
                result = generate(query, contexts)
            # 展示答案正文。
            st.markdown(result.get("answer", ""))
            # 展示引用出处（可折叠）。
            cites = result.get("citations", [])
            if cites:
                with st.expander(f"📚 参考出处（{len(cites)} 条）"):
                    for c in cites:
                        st.write(f"- {c.get('source', '')} · 第 {c.get('page', '?')} 页")
            # 展示置信度。
            st.caption(f"置信度：{result.get('confidence', '?')}")
            # 把这次回答（含引用）存入历史，刷新页面也能看到。
            st.session_state.messages.append({
                "role": "assistant",
                "content": result.get("answer", ""),
                "citations": cites,
            })

# ── 页脚免责声明 ──
st.divider()
st.caption("⚠️ 本 AI 输出仅供参考，正式效力以招标文件原文及法律法规为准。")
