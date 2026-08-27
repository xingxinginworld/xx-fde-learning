"""build_index.py — ① 离线构建：把 PDF 变成「可秒级检索」的向量索引（只需跑一次）。

这是整个 RAG Demo 的「准备阶段」。它做什么？
  PDF 文件 → 读文字 → 清洗 → 切块 → 加元数据 → 向量化 → 存进 FAISS 索引

为什么是「离线、只跑一次」？
  招标文档相对稳定，没必要每次用户提问都重新读 PDF、重新向量化（又慢又费钱）。
  所以把「慢活」提前做完，产出 index/vecs.faiss（向量库）+ index/chunks.json（原文）。
  之后 app.py 起服务时直接读这两个文件，冷启动秒开。
  只有当你往 data/ 里换了新 PDF，才需要重跑本脚本。

运行方式（务必在 .venv 里跑）：
  .venv/Scripts/python build_index.py
"""

import json
import hashlib
from pathlib import Path

import pdfplumber   # 解析 PDF、抽取文字的库
import faiss        # Facebook 开源的向量检索库（存向量、算相似度、秒级返回）
import numpy as np

import config
import model_client


def read_and_chunk(pdf_path, chunk_size=config.CHUNK_SIZE, overlap=config.CHUNK_OVERLAP):
    """Day 7 文档预处理：读 → 清 → 切 → 加元数据。

    关键思路：尽量「按句号切」，保证每一块都是语义完整的一句话/一段话，
    而不是在句子中间硬切，那样向量会失真。

    参数 pdf_path：单个 PDF 的完整路径
    返回：分块列表，每块是一个 dict：
          {"text": 文字内容, "page": 起始页, "source": 文件名,
           "chunk_id": 块编号, "hash": 内容指纹}
    """
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        buffer = ""          # 缓冲区：还没凑够一块的文字先放这里
        start_page = 1       # 当前缓冲区文字起始于第几页（用于引用出处）
        total = len(pdf.pages)
        # 逐页扫描
        for i, page in enumerate(pdf.pages, start=1):
            # 抽取本页文字；有些页抽不到（图片/扫描件）会得到 None，用空串兜底。
            text = (page.extract_text() or "").replace("\n\n", "\n")
            if text.strip():
                if not buffer:
                    start_page = i   # 缓冲区本空，这一页就是新一块的起点
                buffer += text + "\n"
            # 只要缓冲区够长了，就切出一块
            while len(buffer) >= chunk_size:
                # 在 [0, chunk_size] 范围内找最后一个句号「。」作为切点，
                # 这样切出来的是完整句子，而不是半句话。
                cut = buffer.rfind("。", 0, chunk_size) + 1
                # 万一这一段里根本没有句号（比如全是条款编号），就直接在 chunk_size 处硬切。
                if cut < chunk_size // 2:
                    cut = chunk_size
                piece = buffer[:cut].strip()
                if piece:
                    # 记下这块文字、起点页、来源文件 —— 这些是后续「引用出处」的元数据。
                    chunks.append({"text": piece, "page": start_page, "source": pdf_path.name})
                # 切掉已处理的部分；保留末尾 overlap 个字符作为下一块的开头，避免切断语义。
                buffer = buffer[cut - overlap:]
                # 更新下一块的起点页：还有剩文字就按当前页，否则翻到下一页。
                start_page = i if buffer.strip() else (i + 1 if i < total else i)
        # 循环结束，缓冲区可能还剩一小段不足 chunk_size，也把它作为最后一块。
        if buffer.strip():
            chunks.append({"text": buffer.strip(), "page": start_page, "source": pdf_path.name})

    # 给每个块补两个「身份标识」字段：
    for j, c in enumerate(chunks):
        # chunk_id：文件名 + 序号，保证全局唯一，方便排查。
        c["chunk_id"] = f"{pdf_path.stem}_{j:04d}"
        # hash：对文字内容取 MD5 前 10 位，作为内容指纹（可用于去重/变更检测）。
        c["hash"] = hashlib.md5(c["text"].encode()).hexdigest()[:10]
    return chunks


if __name__ == "__main__":
    # 确保目录存在（exist_ok=True 表示已有也不报错）。
    config.DATA_DIR.mkdir(exist_ok=True)
    config.INDEX_DIR.mkdir(exist_ok=True)
    # 扫描 data/ 下所有 PDF。
    pdfs = list(config.DATA_DIR.glob("*.pdf"))
    if not pdfs:
        print("⚠️  data/ 目录下没有 PDF。请把招标文件 PDF 放进去后再运行。")
        raise SystemExit(1)   # 没数据直接退出，避免后面空跑。

    # 1) 逐个 PDF 读取并切块，汇总到 all_chunks。
    all_chunks = []
    for pdf in pdfs:
        print(f"处理 {pdf.name} ...")
        all_chunks.extend(read_and_chunk(pdf))
    print(f"共切出 {len(all_chunks)} 个分块")

    # 2) 向量化：把每块文字变成向量（已归一化）。
    vectors = model_client.embed([c["text"] for c in all_chunks])  # 形状 (块数, 维度)
    # 3) 建 FAISS 索引：用「内积(IP)」索引，因为向量已归一化，内积=余弦相似度。
    index = faiss.IndexFlatIP(vectors.shape[1])  # shape[1]=向量维度
    index.add(vectors)                            # 把全部向量灌进去

    # 4) 持久化。
    # 注意坑：faiss.write_index 的 C++ 底层不支持「中文路径」（目录含「AI项目经理成长」会报错），
    # 所以改用语 Python 先把索引序列化成字节，再 write_bytes 写文件，绕开 C++ 路径限制。
    (config.INDEX_DIR / "vecs.faiss").write_bytes(faiss.serialize_index(index))
    # 原文块（含元数据）存成 JSON，供检索时把「向量」对应回「可读文字 + 出处」。
    json.dump(all_chunks, open(config.INDEX_DIR / "chunks.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("✅ 索引构建完成 -> index/vecs.faiss + index/chunks.json")
