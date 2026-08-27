# -*- coding: utf-8 -*-
"""
FDE 中级证书签发 —— 纯逻辑核心（无 Streamlit 依赖，可独立单测/复用）
────────────────────────────────────────────────────────────────
issuance_gui.py（界面层）import 本模块的函数完成实际工作；
CLI、定时任务、其它入口也可直接复用这里的函数。

职责：
  - parse_quiz_score(link)   从成绩卡链接解析 score
  - load_ledger/save_ledger  capstone/results.json 台账读写
  - append_ledger(entry)     追加一条台账（通过/不通过都留痕）
  - make_entry(...)          构造一条符合 grading.md 格式的台账记录
  - find_latest_entry(...)   查某学员最近一条台账
  - pick_comment(passed)     按结论从 comments.json 随机抽 1 条评语
签发动作（编号/hash/双注册表/HTML）仍由 certs/generator.py 的 issue() 完成，
本模块不重复造轮子。
"""
import json
import random
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent          # certs/
ROOT = BASE.parent                               # 仓库根
COMMENTS = BASE / "comments.json"
CAPSTONE_LEDGER = ROOT / "capstone" / "results.json"

VERIFY_BASE = "https://xingxinginworld.github.io/xx-fde-learning/certs/verify.html"

# 五维度上限（与 capstone/grading.md 一致）
DIMS = [
    ("功能完整性", 20),
    ("效果质量", 25),
    ("性能", 15),
    ("异常兜底", 20),
    ("环境适配", 20),
]
DIM_MAX = {k: v for k, v in DIMS}
PASS_TOTAL = 70          # 硬闸：总分 ≥ 70
PASS_ENV = 12            # 硬闸：环境适配 ≥ 12


def parse_quiz_score(link: str):
    """从成绩卡链接解析测验分（如 ?score=97）。失败或超范围返回 None。"""
    m = re.search(r"[?&]score=(\d{1,3})(?:&|$)", link or "")
    if not m:
        return None
    v = int(m.group(1))
    return v if 0 <= v <= 100 else None


def load_comments():
    data = json.loads(COMMENTS.read_text(encoding="utf-8"))
    # 只取两个池，忽略 _说明 等元字段
    return {"pass": data.get("pass", []), "fail": data.get("fail", [])}


def pick_comment(passed: bool):
    """按结论从 10 条评语池随机抽 1 条。池为空返回占位。"""
    pool = load_comments()["pass" if passed else "fail"]
    return random.choice(pool) if pool else ("（评语池为空）" if passed else "（评语池为空）")


def load_ledger():
    if not CAPSTONE_LEDGER.exists():
        return []
    try:
        data = json.loads(CAPSTONE_LEDGER.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def save_ledger(data):
    CAPSTONE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    CAPSTONE_LEDGER.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_ledger(entry):
    data = load_ledger()
    data.append(entry)
    save_ledger(data)
    return data


def find_latest_entry(name: str, ledger=None):
    if ledger is None:
        ledger = load_ledger()
    mine = [r for r in ledger if r.get("name") == name]
    if not mine:
        return None
    return max(mine, key=lambda r: r.get("submit_date", ""))


def make_entry(name, scores, total, passed, comment, review_date,
               quiz_link="", capstone_link="", cert_id=None):
    """构造一条符合 capstone/grading.md 台账格式的 dict。"""
    scores = dict(scores)
    gates = {
        "交付物齐全": bool(passed),
        "可运行": bool(passed),
        "环境适配≥12": scores.get("环境适配", 0) >= PASS_ENV,
        "红线无违规": bool(passed),
    }
    e = {
        "name": name,
        "submit_date": review_date,
        "scores": scores,
        "total": total,
        "pass": bool(passed),
        "gates": gates,
        "comment": comment,
    }
    if quiz_link:
        e["quiz_link"] = quiz_link
    if capstone_link:
        e["capstone_link"] = capstone_link
    if cert_id:
        e["cert_id"] = cert_id
    return e


def validate(name, scores, total, passed, quiz_link, quiz_score_manual):
    """提交前统一校验。返回错误列表（空 = 可提交）。"""
    errors = []
    if not (name or "").strip():
        errors.append("姓名必填")
    for label, mx in DIMS:
        v = scores.get(label)
        if v is None:
            errors.append(f"{label}未填（0–{mx}）")
        elif not (0 <= v <= mx):
            errors.append(f"{label}超出范围（0–{mx}）")
    if total is None or not (0 <= total <= 100):
        errors.append("总分必填（0–100）")
    # 测验成绩：有链接须能解析或手填；无链接必手填
    parsed = parse_quiz_score(quiz_link)
    if (quiz_link or "").strip():
        if parsed is None and quiz_score_manual is None:
            errors.append("已填成绩链接但解析不到 score，请手动填写分值")
    else:
        if quiz_score_manual is None:
            errors.append("未填成绩链接，中级测验成绩（分值）必填")
    # 通过硬闸
    if passed:
        if total is not None and total < PASS_TOTAL:
            errors.append(f"硬闸：通过要求总分 ≥ {PASS_TOTAL}")
        env = scores.get("环境适配")
        if env is not None and env < PASS_ENV:
            errors.append(f"硬闸：通过要求环境适配 ≥ {PASS_ENV}")
    return errors


def resolve_quiz_score(quiz_link, quiz_score_manual):
    """确定最终印到证书上的测验分。有链接优先解析，否则用手动值。"""
    parsed = parse_quiz_score(quiz_link)
    if (quiz_link or "").strip() and parsed is not None:
        return parsed
    return quiz_score_manual
