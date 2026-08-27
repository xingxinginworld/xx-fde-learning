"""ask.py — 命令行问答入口（Capstone 增强 1：交付物可脱离 Streamlit 独立运行）

用法（在 .venv 下）：
    python ask.py "ZB2026-001 项目的预算是多少？"
    python ask.py "资质要求有哪些？" --top-k 8

做了什么：
1. 走完整链路 retrieve() -> generate()，打印答案 / 引用出处 / 耗时 / 置信度
2. 检索为空时给出明确兜底话术（而不是空答案或报错）
3. 任何异常写入 logs/ask_error.log（结构化，不含密钥），程序不崩溃、给友好提示
4. 每次调用打印分段耗时（检索段 / 总计），便于延迟剖析与验收

说明：与 app.py（Streamlit 交互界面）并存，CLI 便于评审复现、脚本化批量提问与 CI。
"""

import argparse
import logging
import sys
import time

import config
import retriever
import generator

LOG_PATH = config.BASE / "logs" / "ask_error.log"

logger = logging.getLogger("ask")


def _setup_logger():
    """错误日志：只落盘、结构化（时间/级别/问题摘要/异常类型/截断详情），绝不写密钥。"""
    LOG_PATH.parent.mkdir(exist_ok=True)
    logger.setLevel(logging.ERROR)
    if not logger.handlers:
        h = logging.FileHandler(LOG_PATH, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)


_setup_logger()


def main():
    ap = argparse.ArgumentParser(description="招标文件智能问答 CLI")
    ap.add_argument("question", help="要问的问题")
    ap.add_argument("--top-k", type=int, default=config.TOP_K, help="最终返回段落数")
    ap.add_argument("--role", default="public",
                    choices=["public", "staff", "manager", "admin"],
                    help="请求方角色（政企权限分级：只召回该角色可见的文档块）")
    args = ap.parse_args()

    t0 = time.time()
    try:
        contexts = retriever.retrieve(args.question, top_k=args.top_k, role=args.role)
        t_retrieve = time.time() - t0

        if not contexts:
            # 兜底 1：检索为空 → 明确拒答话术，不硬编答案
            print("未在知识库中检索到相关内容。")
            print("建议：换个问法 / 确认问题是否在标书范围内 / 检查索引是否为最新。")
            print(f"(检索耗时 {t_retrieve:.1f}s)")
            return

        ans = generator.generate(args.question, contexts)
        t_total = time.time() - t0

        print("=== 答案 ===")
        print(ans.get("answer", ""))
        cits = ans.get("citations") or []
        if cits:
            print("\n=== 引用来源 ===")
        for i, c in enumerate(cits, 1):
            pg = str(c.get("page", "?"))
            # 部分块元数据的 page 自带「第N页」前缀，避免重复拼接
            page = pg if pg.startswith("第") else f"第{pg}页"
            print(f"  [{i}] {c.get('source', '?')} {page}")
        print(f"\n置信度: {ans.get('confidence', '?')} | 检索 {t_retrieve:.1f}s | 总计 {t_total:.1f}s")
    except Exception as e:  # noqa: BLE001 — 兜底 2：任何异常都记录并友好退出
        # 只记录异常类型与截断详情，详情里不含任何密钥（OpenAI/requests 报错不带 Key）
        logger.error("question=%s error_type=%s detail=%s",
                     args.question[:50], type(e).__name__, str(e)[:300])
        print("⚠️ 本次问答失败，已记录错误日志（logs/ask_error.log）。请稍后重试。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
