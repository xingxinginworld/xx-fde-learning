"""model_client.py — 模型调用封装层：把「和模型打交道」的细节全收在这里。

为什么单独抽一个文件？
----------------------
build_index / retriever / generator 三个模块都要调用模型（向量化、重排、对话）。
如果每家都自己写 HTTP 请求，代码又臭又长，换模型/换平台时要改三处。
所以这里统一封装成 3 个函数，外面只管「传文字、拿结果」：

  embed(texts)      → 文本向量化      （把文字变成数字向量，用来比相似度）
  rerank(...)       → 候选段落重排    （把一堆候选按相关度重新排序）
  chat_json(...)    → 对话并要 JSON   （让大模型读材料、产出结构化答案）

底层细节：
- 向量化(embed) 和 对话(chat) 走 OpenAI 官方 Python SDK（因为魔搭是 OpenAI 兼容协议，
  可以直接用这个 SDK，只要把 base_url 指到魔搭即可）。
- 重排(rerank) 魔搭没这接口，这里改用通用 requests 库直接发 HTTP 请求。
- 所有密钥都来自 config，本文件绝不写死任何 Key（安全 + 可移植）。
"""

import json
import re
import numpy as np
import requests
from openai import OpenAI

import config

# 创建一个「OpenAI 客户端」实例，后面 embed / chat 都复用它。
# base_url 指向魔搭的 API 入口；api_key 是通行证。
# 注意：这只是创建客户端对象，并不会立刻联网；真正联网发生在调用 .create() 时。
_client = OpenAI(base_url=config.MODELSCOPE_BASE_URL, api_key=config.API_KEY)


def embed(texts):
    """把一段段文字变成向量（数字数组），供后续算相似度。

    参数 texts：可以是一段文字(str)，或一串文字(list[str])。
    返回：一个二维 numpy 数组，形状为 (段数, 向量维度)。
          并且已经做了 L2 归一化（每行的长度都变成 1），
          这样后面用「内积」就能直接等价于「余弦相似度」，检索更快。

    小白科普——什么是 embedding（向量化）？
        人看文字，机器算数字。embedding 模型把一句话压缩成一长串有方向的「数字坐标」，
        意思越相近的句子，坐标越靠近。检索时，我们就拿「问题的坐标」去比对「文档的坐标」，
        谁离得近，谁就和答案相关。
    """
    # 容错：如果只传了一段字符串，先包成列表，统一按列表处理。
    if isinstance(texts, str):
        texts = [texts]
    vectors = []
    # 分批请求：每次最多送 EMBED_BATCH 段，避免一次塞太多触发限流或超时。
    for i in range(0, len(texts), config.EMBED_BATCH):
        batch = texts[i:i + config.EMBED_BATCH]
        # 调用魔搭的 /v1/embeddings 接口，拿回这一批的向量。
        resp = _client.embeddings.create(model=config.EMBED_MODEL, input=batch)
        # resp.data 里每一项 d.embedding 就是一段向量，转成 float32 数组收好。
        vectors.extend([np.array(d.embedding, dtype=np.float32) for d in resp.data])
    # 把所有向量堆成一个 (N, dim) 的二维数组。
    arr = np.array(vectors, dtype=np.float32)
    # L2 归一化：把每一行除以它自己的长度，使长度都变成 1。
    # 这样「内积」就等价于「余弦相似度」，FAISS 用内积检索时可以直接比大小。
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    arr = arr / np.clip(norms, 1e-12, None)  # 加 1e-12 防止除以 0
    return arr


def rerank(query, documents, top_n=None):
    """重排：给一堆候选段落，按「和问题的相关度」从高到低排好序。

    参数：
      query     ：用户的问题
      documents ：候选段落（字符串列表）
      top_n     ：只返回前 top_n 个（不传则返回全部，按相关度排）
    返回：results 列表，每项形如 {"index": 段落在原列表中的位置, "relevance_score": 相关度分数}

    会根据 config.RERANK_PROVIDER 选择用哪家的重排服务（默认 jina）。
    """
    # 读取配置里的提供商，转小写、空值兜底成 jina。
    provider = (getattr(config, "RERANK_PROVIDER", "jina") or "jina").lower()
    if provider == "jina":
        return _rerank_jina(query, documents, top_n)
    if provider == "dashscope":
        return _rerank_dashscope(query, documents, top_n)
    if provider == "modelscope":
        return _rerank_modelscope(query, documents, top_n)
    if provider in ("none", "off", "skip", ""):
        # 明确禁用重排：抛错，让 retriever 捕获后回退到「向量粗筛排序」。
        raise RuntimeError("RERANK_PROVIDER=none，已禁用重排（将回退向量粗排）")
    raise RuntimeError(f"未支持的 RERANK_PROVIDER={provider}")


def _post_rerank(url, headers, body):
    """重排的通用 HTTP 请求封装：发 POST，检查状态码，取出 results 字段。"""
    r = requests.post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()  # 如果返回 4xx/5xx，这里直接抛异常
    return r.json()["results"]


def _rerank_jina(query, documents, top_n=None):
    """用 Jina 的 rerank 接口做精排（默认路径）。"""
    if not getattr(config, "JINA_API_KEY", ""):
        # 没填 Key 就抛错，retriever 会捕获并回退到向量排序（主流程不中断）。
        raise RuntimeError("RERANK_PROVIDER=jina 但未配置 JINA_API_KEY")
    # 请求体：告诉 Jina 用哪个模型、针对什么问题、对哪些文档排序。
    body = {"model": config.JINA_RERANK_MODEL, "query": query,
            "documents": documents, "top_n": top_n or len(documents)}
    return _post_rerank(
        config.JINA_RERANK_URL,
        # 鉴权头：Bearer 后面跟你的 Key。
        {"Authorization": f"Bearer {config.JINA_API_KEY}", "Content-Type": "application/json"},
        body,
    )


def _rerank_dashscope(query, documents, top_n=None):
    """用阿里云百炼 DashScope 的 rerank 接口做精排（备用路径）。"""
    if not getattr(config, "DASHSCOPE_API_KEY", ""):
        raise RuntimeError("RERANK_PROVIDER=dashscope 但未配置 DASHSCOPE_API_KEY")
    body = {"model": config.DASHSCOPE_RERANK_MODEL, "query": query,
            "documents": documents, "top_n": top_n or len(documents)}
    return _post_rerank(
        config.DASHSCOPE_RERANK_URL,
        {"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}", "Content-Type": "application/json"},
        body,
    )


def _rerank_modelscope(query, documents, top_n=None):
    """用魔搭 ModelScope 的 rerank 接口（实测 404 不可用，仅保留作兼容）。"""
    if not config.API_KEY:
        raise RuntimeError("RERANK_PROVIDER=modelscope 但未配置 MODELSCOPE_API_KEY")
    url = config.MODELSCOPE_BASE_URL.rstrip("/") + "/rerank"
    body = {"model": config.RERANK_MODEL, "query": query, "documents": documents}
    if top_n:
        body["top_n"] = top_n
    return _post_rerank(
        url,
        {"Authorization": f"Bearer {config.API_KEY}", "Content-Type": "application/json"},
        body,
    )


def chat_json(system_prompt, user_prompt, temperature=0.1, max_retries=2):
    """让大模型读材料、产出「严格 JSON」格式的回答。失败抛 RuntimeError。

    参数：
      system_prompt ：给模型的「身份 + 规矩」设定（比如「你是招标问答助手，只引用资料」）
      user_prompt   ：真正的问题 + 参考资料
      temperature   ：随机性，越小越稳定（0.1 接近确定性输出，适合结构化场景）
      max_retries   ：网络抖动时最多重试几次

    小白科普——为什么非要 JSON？
        大模型默认输出一段「人话」。但程序更好处理「结构化数据」。
        所以我们强制它输出 JSON（如 {"answer": "...", "citations": [...], "confidence": "high"}），
        前端就能直接取出答案、引用、置信度分别展示。

    注：Qwen3 默认会「先思考再回答」，思考过程会用 <think> 标签包裹，
        会干扰 JSON 解析。这里用 extra_body={"enable_thinking": False} 关掉思考，
        直接拿到干净的答案。
    """
    last_err = None
    # 最多试 max_retries 次，应对偶发的网络超时/限流。
    for _ in range(max_retries):
        try:
            resp = _client.chat.completions.create(
                model=config.CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                # 强制模型输出合法 JSON 对象。
                response_format={"type": "json_object"},
                temperature=temperature,
                # 关闭 Qwen3 的思考模式，避免 <think> 污染 JSON。
                extra_body={"enable_thinking": False},
            )
            text = resp.choices[0].message.content
            # 模型通常直接返回 JSON 字符串，直接解析。
            return json.loads(text)
        except json.JSONDecodeError:
            # 万一还是混进了多余文字，用正则「抠」出第一个 {...} 再试一次。
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                return json.loads(m.group())
            last_err = "返回内容不是合法 JSON"
        except Exception as e:  # noqa: BLE001 — 其它异常（超时/限流等）也捕获，统一重试
            last_err = e
    # 重试耗尽仍失败，把最后一次错误抛出去，由调用方（generator）兜底。
    raise RuntimeError(f"chat_json 调用失败：{last_err}")
