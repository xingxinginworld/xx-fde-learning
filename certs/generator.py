# -*- coding: utf-8 -*-
"""
FDE 结营证书生成器
────────────────────────────────────────────────────────
用法：
  # 签发一张基础证书（99 题 ≥80 分）
  python certs/generator.py --name "张三" --tier basic --score 88

  # 签发中级证书（99 题 + capstone 通过）
  python certs/generator.py --name "李四" --tier intermediate --score 92 --capstone

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

TIER_META = {
    "basic":        {"prefix": "B", "name": "结营基础证书",
                     "exam": "99 题知识测验（成绩 ≥ 80 分）"},
    "intermediate": {"prefix": "I", "name": "结营中级证书",
                     "exam": "99 题知识测验 + 结营测验项目（capstone）"},
}


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


def make_hash(id_, name, d, score, capstone):
    raw = f"{id_}|{name}|{d}|{score}|{capstone}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def issue(name, tier, score, capstone_pass=False, emit_html=False):
    if tier not in TIER_META:
        raise SystemExit(f"未知等级: {tier}，可选 {list(TIER_META)}")
    meta = TIER_META[tier]
    year = date.today().year
    d = date.today().isoformat()

    records = load(REGISTRY)
    serial = next_serial(records, tier, year)
    cid = f"FDE-{meta['prefix']}-{year}-{serial:05d}"
    h = make_hash(cid, name, d, score, capstone_pass)

    rec = {
        "id": cid, "tier": tier, "tier_name": meta["name"],
        "name": name, "date": d, "year": year, "serial": serial,
        "quiz_score": score, "capstone_pass": bool(capstone_pass),
        "hash": h,
    }
    records.append(rec)
    save(REGISTRY, records)

    # 公开注册表（含姓名，供在线核验；不含本地隐私字段）
    pub = load(PUBLIC)
    pub.append({
        "id": cid, "tier": tier, "tier_name": meta["name"], "name": name,
        "date": d, "quiz_score": score, "capstone_pass": bool(capstone_pass),
        "hash": h,
    })
    save(PUBLIC, pub)

    verify_url = "https://xingxinginworld.github.io/xx-fde-learning/certs/verify.html"
    print(f"✅ 已签发：{cid}")
    print(f"   姓名：{name} | 等级：{meta['name']} | 成绩：{score} | 日期：{d}")
    print(f"   防伪 HASH：{h}")
    print(f"   在线核验：{verify_url}?id={cid}")

    if emit_html:
        os.makedirs(ISSUES, exist_ok=True)
        with open(TEMPLATE, "r", encoding="utf-8") as f:
            tpl = f.read()
        html = (tpl
                .replace("{{NAME}}", name)
                .replace("{{TIER_NAME}}", meta["name"])
                .replace("{{TIER_EXAM_DESC}}", meta["exam"])
                .replace("{{ID}}", cid)
                .replace("{{SCORE}}", str(score))
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
    ap.add_argument("--score", type=int, help="99 题测验成绩")
    ap.add_argument("--capstone", action="store_true", help="中级证书：capstone 已通过")
    ap.add_argument("--emit-html", action="store_true", help="额外导出可打印 HTML 证书")
    ap.add_argument("--demo", action="store_true", help="生成演示证书验证闭环")
    args = ap.parse_args()

    if args.demo:
        issue("演示学员", "basic", 86, emit_html=True)
        issue("演示学员·进阶", "intermediate", 91, capstone_pass=True, emit_html=True)
        return

    if not (args.name and args.tier and args.score is not None):
        ap.error("请至少提供 --name --tier --score（或使用 --demo）")
    issue(args.name, args.tier, args.score,
          capstone_pass=args.capstone, emit_html=args.emit_html)


if __name__ == "__main__":
    main()
