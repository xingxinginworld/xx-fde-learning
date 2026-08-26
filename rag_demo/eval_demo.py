"""eval_demo.py — RAG Demo 效果评估脚本（FDE 交付用）

用法（在 .venv 下）：
    .venv/Scripts/python.exe eval_demo.py

做了什么：
1. 读取已构建好的 FAISS 索引（retriever）
2. 对 data/ 下 3 个标书构造 12 个真实业务问答（事实型 / 跨文档 / 未提及）
3. 每个问题走完整链路：retrieve() -> generate()
4. 统计：检索命中率、答案事实准确率、置信度分布、bad case
5. 把结果 dump 成 eval_result.json 供报告引用

说明：本脚本只用于评测，不改动索引与业务代码。
"""

import json
import re
from pathlib import Path

import config
import retriever
import generator

# ── 1. 评测问答集（基于 chunks.json 真实内容构造）────────────────────────
# gold_source : 答案应命中哪个 PDF（用于算检索命中）
# need        : 答案里必须出现的关键实体（任一候选命中即算该组通过）
# qtype       : factual 事实 / cross 跨文档 / unknown 文档未提及
QA = [
    # ── 标书 001：智能评标系统采购 ──
    dict(q="ZB2026-001 这个项目的预算金额是多少？", gold_source="tender_zb2026_001.pdf",
         need=[["580万", "5,800,000", "580万元"]], qtype="factual"),
    dict(q="智能评标系统采购项目的投标截止时间是什么时候？", gold_source="tender_zb2026_001.pdf",
         need=[["2026年7月15日", "7月15日09时30分", "7月15日"]], qtype="factual"),
    dict(q="智能评标系统项目的招标人是谁？", gold_source="tender_zb2026_001.pdf",
         need=[["某单位采购中心"]], qtype="factual"),
    dict(q="投标智能评标系统项目，对注册资本有什么要求？", gold_source="tender_zb2026_001.pdf",
         need=[["1000万元", "1000万"]], qtype="factual"),
    dict(q="智能评标系统项目接受联合体投标吗？", gold_source="tender_zb2026_001.pdf",
         need=[["不接受联合体", "不接受"]], qtype="factual"),
    dict(q="智能评标系统项目采用什么评标办法，各项权重是多少？", gold_source="tender_zb2026_001.pdf",
         need=[["报价30", "技术50", "商务20"]], qtype="factual"),
    dict(q="智能评标系统项目验收合格后质保期是多久？", gold_source="tender_zb2026_001.pdf",
         need=[["3年", "三年"]], qtype="factual"),

    # ── 标书 002：管理咨询服务采购 ──
    dict(q="管理咨询服务采购项目的招标文件获取时间是什么时候？", gold_source="tender_zb2026_002.pdf",
         need=[["2026年7月5日", "7月5日", "7月20日"]], qtype="factual"),
    dict(q="管理咨询服务项目对团队有什么硬性要求？", gold_source="tender_zb2026_002.pdf",
         need=[["高级咨询师", "咨询师不少于2", "2人"]], qtype="factual"),

    # ── 标书 003：数据中心运维服务 ──
    dict(q="数据中心运维服务采购项目要求投标人具备什么资质？", gold_source="tender_zb2026_003.pdf",
         need=[["ITSS"]], qtype="factual"),
    dict(q="数据中心运维服务的服务期是多久？", gold_source="tender_zb2026_003.pdf",
         need=[["2年", "两年"]], qtype="factual"),

    # ── 跨文档 / 未提及（边界测试）──
    dict(q="请列出本次所有招标项目的名称和招标编号。", gold_source=None,
         need=[["ZB2026-001", "ZB2026-002", "ZB2026-003"]], qtype="cross"),
    dict(q="智能评标系统项目的项目经理需要持有什么资格证书？", gold_source=None,
         need=[["未提及", "文档中未提及", "没有提供", "没有提及"]], qtype="unknown"),
]


def norm(s: str) -> str:
    """去掉空格/全角，便于做子串匹配。"""
    return re.sub(r"\s+", "", s)


def main():
    print(f"索引分块数: {len(retriever.CHUNKS)} | 向量维度: {retriever.INDEX.d}")
    print(f"Rerank 供应商: {config.RERANK_PROVIDER} | TopK: {config.TOP_K}\n")

    rows = []
    for i, item in enumerate(QA, 1):
        q = item["q"]
        retrieved = retriever.retrieve(q, top_k=config.TOP_K)
        # 检索命中：gold 来源是否出现在召回结果里（跨文档/未提及题忽略此项）
        srcs = [c["source"] for c in retrieved]
        hit = (item["gold_source"] in srcs) if item["gold_source"] else None

        # 生成答案
        ans = generator.generate(q, retrieved)
        answer = ans.get("answer", "")
        conf = ans.get("confidence", "low")

        # 答案事实校验：need 里每组至少命中一个候选
        groups_pass = []
        for grp in item["need"]:
            ok = any(g in answer or norm(g) in norm(answer) for g in grp)
            groups_pass.append(ok)
        answer_ok = all(groups_pass)

        rows.append(dict(
            n=i, q=q, qtype=item["qtype"], retrieval_hit=hit,
            answer_ok=answer_ok, confidence=conf,
            answer=answer, citations=ans.get("citations", []),
        ))
        flag = "✅" if answer_ok else "❌"
        rh = "—" if hit is None else ("命中" if hit else "漏召")
        print(f"{i:2d}. [{item['qtype']:8s}] 检索:{rh:4s} 答案:{flag} 置信:{conf}")
        print(f"     Q: {q}")
        print(f"     A: {answer[:120]}{'…' if len(answer) > 120 else ''}")

    # ── 汇总 ──
    factual = [r for r in rows if r["qtype"] == "factual"]
    retrieve_hits = [r["retrieval_hit"] for r in factual if r["retrieval_hit"] is not None]
    ret_hit_rate = sum(retrieve_hits) / len(retrieve_hits) if retrieve_hits else 0
    ans_rate = sum(r["answer_ok"] for r in rows) / len(rows)
    conf_dist = {}
    for r in rows:
        conf_dist[r["confidence"]] = conf_dist.get(r["confidence"], 0) + 1

    summary = dict(
        total=len(rows),
        retrieval_hit_rate=round(ret_hit_rate, 3),
        answer_accuracy=round(ans_rate, 3),
        confidence_dist=conf_dist,
        bad_cases=[dict(n=r["n"], q=r["q"], qtype=r["qtype"],
                        retrieval_hit=r["retrieval_hit"], answer=r["answer"])
                   for r in rows if not r["answer_ok"]],
    )
    out = dict(summary=summary, rows=rows)
    Path("eval_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    print("\n========== 汇总 ==========")
    print(f"总题数: {summary['total']}")
    print(f"检索命中率(事实题): {summary['retrieval_hit_rate']*100:.1f}%")
    print(f"答案事实准确率: {summary['answer_accuracy']*100:.1f}%")
    print(f"置信度分布: {summary['confidence_dist']}")
    print(f"Bad case 数: {len(summary['bad_cases'])}")
    print("结果已写入 eval_result.json")


if __name__ == "__main__":
    main()
