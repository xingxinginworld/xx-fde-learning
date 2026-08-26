"""generator.py — ③ 在线生成：把召回的段落 + 问题，交给大模型写出答案（Day 4 + Day 5）。

检索（retriever）负责「找材料」，本文件负责「写答案」。
核心做法：把 Top-K 段原文塞进 prompt 当「参考资料」，让大模型基于这些资料作答，
并强制输出 JSON（答案 + 引用出处 + 置信度），方便前端展示。
"""

import config
import model_client

# 系统提示词（system prompt）：给模型的「人设 + 硬规矩」。
# 这里把「招标文件问答助手」的行为边界写死，防止模型瞎编。
SYSTEM_PROMPT = """你是招标文件问答助手。基于用户提供的<参考资料>回答问题。
硬规矩：
1. 只用参考资料里的信息，不要编造。
2. 参考资料没写的，直接说"文档中未提及"。
3. 每个事实要标出处（来源文件 + 页码）。
4. 涉及金额、日期、责任主体（甲方/乙方/丙方）的，必须一字不改引用原文。
5. 输出严格 JSON 格式。"""


def generate(query, contexts):
    """根据问题 + 召回的参考段落，生成结构化答案。

    参数：
      query    ：用户问题
      contexts ：retriever 找回来的相关段落列表（每块含 text/page/source）
    返回：字典 {"answer": 答案, "citations": [出处...], "confidence": 置信度}
    """
    # 1) 把若干段参考资料拼成一段带编号的文本，塞进 <参考资料> 标签里。
    #    格式示例：[1] 来源：xxx.pdf 第3页\n 段落文字...
    context_str = "\n\n".join(
        f"[{i+1}] 来源：{c['source']} 第{c['page']}页\n{c['text']}"
        for i, c in enumerate(contexts)
    )
    # 2) 组装用户提示词：先给资料，再给问题，最后明确「要什么格式的 JSON」。
    user_prompt = f"""<参考资料>
{context_str}
</参考资料>

用户问题：{query}

请以 JSON 格式回答，字段：
- answer: 直接回答（基于参考资料，缺失即说"文档中未提及"）
- citations: 引用列表，每项含 source（文件名）和 page（页码）
- confidence: 置信度，取值 high / medium / low"""

    try:
        # 3) 调模型，拿结构化 JSON（model_client 已处理 JSON 解析与重试）。
        return model_client.chat_json(SYSTEM_PROMPT, user_prompt)
    except Exception as e:  # noqa: BLE001
        # 4) 兜底：生成失败也不让页面崩，返回一个友好的错误答案。
        return {"answer": f"⚠️ 生成失败：{e}", "citations": [], "confidence": "low"}
