"""retriever.py — ② 在线检索：用户提问 → 召回最相关的段落（Day 8 五维度）。

这是「用户提问后」第一步要做的：从成千上万段文档里，找出最该被参考答案的那几段。

完整检索链路：
  用户问题 → 向量化(embed) → FAISS 向量粗筛(召回 COARSE_K 个候选)
           → 相似度阈值过滤 → 重排(rerank 精排) → 返回 Top-K 段

模块加载时就把索引读进内存（只做一次），之后每次提问直接查，速度很快。
"""

import json
import faiss
import numpy as np

import config
import model_client

# ── 模块加载时：把离线构建好的索引读进内存 ──
# 同样的中文路径坑：faiss.read_index 底层不支持中文路径，
# 所以先 read_bytes 用 Python 读出字节，再用 np.frombuffer 包成 uint8 数组，最后 deserialize_index 还原。
_buf = np.frombuffer((config.INDEX_DIR / "vecs.faiss").read_bytes(), dtype=np.uint8)
INDEX = faiss.deserialize_index(_buf)
# 原文块（含 text/page/source 等元数据），检索时用来把「向量编号」还原成「可读文字」。
CHUNKS = json.load(open(config.INDEX_DIR / "chunks.json", encoding="utf-8"))


def retrieve(query, top_k=config.TOP_K, coarse_k=config.COARSE_K, threshold=config.SIM_THRESHOLD):
    """检索主函数：返回与问题最相关的 Top-K 个原文块（带元数据）。

    参数：
      query     ：用户问题
      top_k     ：最终返回几条（默认 5）
      coarse_k  ：向量粗筛先召回几条候选（默认 20，宁多勿少，交给 rerank 精挑）
      threshold ：相似度门槛，低于此值视为「不相关」直接丢弃
    """
    # 1) 把问题也向量化，才能和文档向量比距离。形状 (1, 维度)。
    q = model_client.embed([query])
    # 2) FAISS 检索：在索引里找和 q 最像的 coarse_k 个向量。
    #    返回 scores(相似度分数) 和 ids(这些向量在索引里的编号)。
    scores, ids = INDEX.search(q, coarse_k)
    # 3) 阈值过滤：只保留分数 ≥ threshold 的候选，并带上它的原文块和分数。
    #    zip(ids[0], scores[0]) 把「编号」和「分数」一一对应；CHUNKS[i] 就是第 i 块原文。
    candidates = [(CHUNKS[i], float(s)) for i, s in zip(ids[0], scores[0]) if s >= threshold]
    # 4) 一个都没命中 → 直接返回空，上层会提示「没找到」。
    if not candidates:
        return []
    try:
        # 5) 重排精排：把候选段落交给 rerank 模型，按相关度重新排序，取前 top_k。
        #    返回 results 里每项带 index（指向 candidates 的位置）和 relevance_score。
        results = model_client.rerank(query, [c[0]["text"] for c in candidates], top_n=top_k)
        # 用 rerank 给的 index，从 candidates 里捞出真正要返回的那 top_k 块原文。
        return [candidates[r["index"]][0] for r in results]
    except Exception as e:  # noqa: BLE001
        # 兜底：万一 rerank 挂了（比如没配 JINA_API_KEY、网络超时），
        # 不中断主流程，退而求其次 —— 直接用向量相似度分数降序排，取前 top_k。
        print(f"⚠️  重排失败，回退向量粗排：{e}")
        candidates.sort(key=lambda x: x[1], reverse=True)
        return [c[0] for c in candidates[:top_k]]
