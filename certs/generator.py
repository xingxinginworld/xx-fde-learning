# -*- coding: utf-8 -*-
"""
FDE 结营证书生成器
────────────────────────────────────────────────────────
用法：
  # 签发一张基础证书（99 题 ≥80 分）
  python certs/generator.py --name "张三" --tier basic --score 88

  # 签发中级证书（100 题中级测验 + capstone 通过，需台账有通过记录）
  python certs/generator.py --name "李四" --tier intermediate --score 92 --capstone
  # 如台账分数与 --capstone-score 不一致，以台账为准（除非显式传 --capstone-score）

  # 同时导出一张可打印的 HTML 证书
  python certs/generator.py --name "张三" --tier basic --score 88 --emit-html

  # 生成一张演示证书，验证「生成→注册→查询」闭环
  python certs/generator.py --demo

说明：
  - 编号格式 FDE-{B|I}-YYYY-NNNNN（每年从 00001 起，按等级各自计数）
  - 完整注册表 certs/registry.json（含姓名）仅本地，不入库（见 .gitignore）
  - 公开注册表 certs/registry.public.json（供 verify.html 在线核验）会同步写入并提交
"""
import argparse
import hashlib
import json
import os
from datetime import date

BASE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(BASE, "registry.json")
PUBLIC   = os.path.join(BASE, "registry.public.json")
TEMPLATE = os.path.join(BASE, "template.html")
ISSUES   = os.path.join(BASE, "issues")
# Capstone 评分台账（群主本地维护，不入库；签发中级证前必须在此有通过记录）
CAPSTONE_RESULTS = os.path.join(os.path.dirname(BASE), "capstone", "results.json")

TIER_META = {
    "basic":        {"prefix": "B", "name": "结营基础证书",
                     "exam": "99 题知识测验（成绩 ≥ 80 分）",
                     "sub": "Certificate of Completion · AI 交付工程师成长计划",
                     "tier_class": "cert-basic"},
    "intermediate": {"prefix": "I", "name": "结营中级证书",
                     "exam": "100 题中级知识测验 + 结营项目（capstone，≥70 分）",
                     "sub": "Intermediate Certificate · AI 交付工程师进阶认证",
                     "tier_class": "cert-inter"},
}

# 中级证书专属视觉元素（深蓝暗金）；基础证书注入空值，不渲染
INTER_WATERMARK = '<div class="watermark">FDE&nbsp;PRO</div>'
INTER_MEDAL = ('<div class="medal"><div class="ribbons">'
               '<div class="ribbon"></div>'
               '<div class="badge2">★</div>'
               '<div class="ribbon"></div>'
               '</div></div>')


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_serial(records, tier, year):
    """同等级、同年份下的最大序号 +1；首张则从 1 开始。"""
    max_n = 0
    for r in records:
        if r.get("tier") == tier and r.get("year") == year:
            max_n = max(max_n, r.get("serial", 0))
    return max_n + 1


def find_capstone_pass(name):
    """在 capstone 台账中查该学员最近一次『通过』记录，无则返回 None。"""
    results = load(CAPSTONE_RESULTS)
    passed = [r for r in results
              if r.get("name") == name and r.get("pass") is True]
    if not passed:
        return None
    return max(passed, key=lambda r: r.get("submit_date", ""))


def make_hash(id_, name, d, score, capstone):
    raw = f"{id_}|{name}|{d}|{score}|{capstone}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def issue(name, tier, score, capstone_pass=False, capstone_score=None,
          emit_html=False, skip_check=False):
    if tier not in TIER_META:
        raise SystemExit(f"未知等级: {tier}，可选 {list(TIER_META)}")
    meta = TIER_META[tier]
    year = date.today().year
    d = date.today().isoformat()

    # ── 中级证书硬校验：台账必须有通过记录（堵住裸 --capstone 发证漏洞）──
    if tier == "intermediate":
        if not capstone_pass:
            raise SystemExit("中级证书必须带 --capstone（测验通过不等于 capstone 通过）")
        rec_cs = find_capstone_pass(name) if not skip_check else None
        if not skip_check and rec_cs is None:
            raise SystemExit(
                f"❌ 拒绝签发：capstone/results.json 台账中找不到「{name}」的通过记录。\n"
                f"   请先按 capstone/grading.md 评分并写入台账，再重新签发。\n"
                f"   （紧急情况可加 --skip-check 跳过，但不建议）")
        ledger_total = rec_cs.get("total") if rec_cs else None
        if capstone_score is not None and ledger_total is not None \
                and capstone_score != ledger_total:
            raise SystemExit(
                f"❌ --capstone-score {capstone_score} 与台账分数 {ledger_total} 不一致，以台账为准或核对台账")
        capstone_score = ledger_total if ledger_total is not None else capstone_score

    records = load(REGISTRY)
    serial = next_serial(records, tier, year)
    cid = f"FDE-{meta['prefix']}-{year}-{serial:05d}"
    h = make_hash(cid, name, d, score, capstone_pass)

    rec = {
        "id": cid, "tier": tier, "tier_name": meta["name"],
        "name": name, "date": d, "year": year, "serial": serial,
        "quiz_score": score, "capstone_pass": bool(capstone_pass),
        "capstone_score": capstone_score,
        "hash": h,
    }
    records.append(rec)
    save(REGISTRY, records)

    # 公开注册表（含姓名，供在线核验；不含本地隐私字段）
    pub = load(PUBLIC)
    pub.append({
        "id": cid, "tier": tier, "tier_name": meta["name"], "name": name,
        "date": d, "quiz_score": score, "capstone_pass": bool(capstone_pass),
        "capstone_score": capstone_score,
        "hash": h,
    })
    save(PUBLIC, pub)

    verify_url = "https://xingxinginworld.github.io/xx-fde-learning/certs/verify.html"
    print(f"✅ 已签发：{cid}")
    print(f"   姓名：{name} | 等级：{meta['name']} | 成绩：{score} | 日期：{d}")
    if tier == "intermediate":
        cs = f"{capstone_score}/100" if capstone_score is not None else "已通过"
        print(f"   结营项目（capstone）：{cs}")
    print(f"   防伪 HASH：{h}")
    print(f"   在线核验：{verify_url}?id={cid}")

    if emit_html:
        os.makedirs(ISSUES, exist_ok=True)
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            tpl = f.read()
        is_inter = (tier == "intermediate")
        cs_html = f"{capstone_score} / 100" if (is_inter and capstone_score is not None) else "—"
        html = (tpl
                .replace("{{TIER_CLASS}}", meta["tier_class"])
                .replace("{{WATERMARK}}", INTER_WATERMARK if is_inter else "")
                .replace("{{MEDAL}}", INTER_MEDAL if is_inter else "")
                .replace("{{SUB_TITLE}}", meta["sub"])
                .replace("{{NAME}}", name)
                .replace("{{TIER_NAME}}", meta["name"])
                .replace("{{TIER_EXAM_DESC}}", meta["exam"])
                .replace("{{ID}}", cid)
                .replace("{{SCORE}}", str(score))
                .replace("{{CAPSTONE_SCORE}}", cs_html)
                .replace("{{DATE}}", d)
                .replace("{{HASH}}", h)
                .replace("{{VERIFY_URL}}", verify_url))
        out = os.path.join(ISSUES, f"{cid}.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"   证书 HTML 已导出：{out}")

    return rec


def main():
    ap = argparse.ArgumentParser(description="FDE 结营证书生成器")
    ap.add_argument("--name", help="持证人姓名")
    ap.add_argument("--tier", choices=list(TIER_META), help="证书等级")
    ap.add_argument("--score", type=int, help="测验成绩（基础 99 题 / 中级 100 题）")
    ap.add_argument("--capstone", action="store_true", help="中级证书：capstone 已通过（会校验 capstone/results.json 台账）")
    ap.add_argument("--capstone-score", type=int, help="capstone 总分（缺省取台账值；与台账不一致会报错）")
    ap.add_argument("--emit-html", action="store_true", help="额外导出可打印 HTML 证书")
    ap.add_argument("--demo", action="store_true", help="生成演示证书验证闭环（不写真实台账校验）")
    args = ap.parse_args()

    if args.demo:
        issue("演示学员", "basic", 86, emit_html=True)
        issue("演示学员·进阶", "intermediate", 91,
              capstone_pass=True, capstone_score=86, emit_html=True, skip_check=True)
        return

    if not (args.name and args.tier and args.score is not None):
        ap.error("请至少提供 --name --tier --score（或使用 --demo）")
    issue(args.name, args.tier, args.score,
          capstone_pass=args.capstone, capstone_score=args.capstone_score,
          emit_html=args.emit_html)


if __name__ == "__main__":
    main()
