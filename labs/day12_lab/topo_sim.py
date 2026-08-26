# -*- coding: utf-8 -*-
"""
topo_sim.py —— 政企网络拓扑「连通性 + 出域」模拟器
===================================================

这是 Day12（政企网络地形入门）的实战化学习工具。

【它解决什么问题？】
Day12 教你看懂政企 5 层网络、判断 AI 系统该放哪一层。
但"看懂"不等于"做对决策"。这个模拟器让你把一个真实 AI 系统
（这里复用我们做过的 rag_demo：招标文件 RAG 问答）的组件"摆放"到
不同网络层，然后：
  1) 检查摆放是否合规（生产数据有没有落到可出网的区域）；
  2) 模拟一次完整调用链，逐跳判断：通 / 需白名单 / 不可达；
  3) 一旦发现"生产数据流向互联网"，立即标红【出域红线】。

【怎么跑？】
    python topo_sim.py                  # 跑默认场景里的 good / bad 两套方案
    python topo_sim.py --placement good # 只跑合规方案
    python topo_sim.py --scenario 你自己的.json

【依赖】
    纯 Python 标准库（json / os / sys / argparse），无需安装任何包。

【红线说明】
    全程使用"某单位"脱敏，不对应任何真实机构。
"""

import argparse
import json
import os
import sys

# 场景文件默认和本脚本放在同一目录
DEFAULT_SCENARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "场景_某单位5层拓扑.json")


# ----------------------------------------------------------------------------
# 1) 加载场景
# ----------------------------------------------------------------------------
def load_scenario(path):
    """读取 JSON 场景文件，返回 dict。文件不存在时给出清晰报错。"""
    if not os.path.exists(path):
        print(f"[错误] 找不到场景文件：{path}")
        print("        请确认 场景_某单位5层拓扑.json 与本脚本在同一目录。")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------
# 2) 防火墙规则查询（支持 * 通配）
# ----------------------------------------------------------------------------
def get_rule(rules, src, dst):
    """
    查两个网段之间的访问策略。政企网络默认"拒绝一切"，只有显式放行的才通。
    匹配优先级：精确(src,dst) > (*,dst) > (src,*) > (*,*) > 默认拒绝。
    返回 'open'（直接通） / 'whitelist'（需白名单才通） / 'deny'（不通）。
    """
    for r in rules:
        if r["src"] == src and r["dst"] == dst:
            return r["mode"]
    for r in rules:
        if r["src"] == "*" and r["dst"] == dst:
            return r["mode"]
    for r in rules:
        if r["src"] == src and r["dst"] == "*":
            return r["mode"]
    for r in rules:
        if r["src"] == "*" and r["dst"] == "*":
            return r["mode"]
    return "deny"  # 没写规则 = 默认拒绝（政企铁律）


# ----------------------------------------------------------------------------
# 3) 放置合规检查
# ----------------------------------------------------------------------------
def check_placement(segments, assets):
    """
    逐一检查每个资产摆得对不对。返回发现项列表，每项是一个 (级别, 文字) 元组。
    级别：'ERROR'（违规）/ 'WARN'（需注意）/ 'OK'（合规）。
    """
    findings = []
    for a in assets:
        seg = segments[a["segment"]]
        # 规则 A：带生产数据的资产不能放在"可出网"的区域（互联网 / DMZ）
        if a["carries_prod_data"] and seg["egress"]:
            findings.append(("ERROR",
                f"【出域红线】{a['name']} 携带生产数据，却放在可出网的"
                f"「{seg['name']}」，数据会出域！"))
        # 规则 B：公网 LLM（外部 API）必须在互联网侧
        elif a["type"] == "external_llm" and a["segment"] != "internet":
            findings.append(("WARN",
                f"{a['name']} 是公网 LLM，但没放在「互联网」侧，调用会不通。"))
        # 规则 C：私有化 LLM 收口在生产网 / 隔离区，是合规做法
        elif a["type"] == "private_llm" and a["segment"] in ("prod", "isolated"):
            findings.append(("OK",
                f"{a['name']} 私有化部署在「{seg['name']}」，生产数据不出网，合规收口。"))
        # 规则 D：带生产数据的资产落在生产网 / 隔离区，属于"数据收口"
        elif a["carries_prod_data"] and a["segment"] in ("prod", "isolated"):
            findings.append(("OK",
                f"{a['name']} 含生产数据，收口在「{seg['name']}」，未出域。"))
    if not findings:
        findings.append(("OK", "未检测到明显摆放问题。"))
    return findings


# ----------------------------------------------------------------------------
# 4) 调用链逐跳追踪
# ----------------------------------------------------------------------------
def trace_flow(segments, rules, assets_by_name, chain):
    """
    按调用链顺序，逐跳判断可达性，并检测"生产数据是否流向互联网"。
    返回每一跳的结果列表。
    """
    hops = []
    for i in range(len(chain) - 1):
        a = assets_by_name[chain[i]]
        b = assets_by_name[chain[i + 1]]
        sa, sb = a["segment"], b["segment"]

        # 同一网段内通信，永远可达
        if sa == sb:
            mode = "open"
        else:
            mode = get_rule(rules, sa, sb)

        hop = {
            "src": a["name"], "dst": b["name"],
            "sa": segments[sa]["name"], "sb": segments[sb]["name"],
            "mode": mode,
            "exfil": False,
        }

        # 出域检测：源资产带生产数据（或源网段本身存生产数据），且目标网段可出网
        src_carries = a["carries_prod_data"] or segments[sa]["holds_prod_data"]
        if src_carries and segments[sb]["egress"]:
            hop["exfil"] = True

        hops.append(hop)
    return hops


# ----------------------------------------------------------------------------
# 5) 跑一套方案，打印报告
# ----------------------------------------------------------------------------
def run_placement(name, placement, segments, rules):
    print("=" * 70)
    print(f"方案：{name}")
    print(f"说明：{placement['desc']}")
    print("=" * 70)

    assets = placement["assets"]
    assets_by_name = {a["name"]: a for a in assets}

    # --- 5.1 摆放合规检查 ---
    print("\n[1] 摆放合规检查")
    findings = check_placement(segments, assets)
    has_error = False
    for level, text in findings:
        tag = {"ERROR": "[违规]", "WARN": "[注意]", "OK": "[合规]"}.get(level, "[?]")
        print(f"  {tag} {text}")
        if level == "ERROR":
            has_error = True

    # --- 5.2 调用链追踪 ---
    print("\n[2] 调用链逐跳追踪")
    chain = placement["call_chain"]
    print("  链路：" + " → ".join(chain))
    hops = trace_flow(segments, rules, assets_by_name, chain)
    has_deny = False
    has_exfil = False
    for h in hops:
        if h["mode"] == "open":
            mark = "[通]"
        elif h["mode"] == "whitelist":
            mark = "[需白名单]"
        else:
            mark = "[不可达]"
            has_deny = True
        line = f"  {mark} {h['src']}({h['sa']}) → {h['dst']}({h['sb']})"
        if h["exfil"]:
            line += "  <<< 出域红线：生产数据流向可出网区域！"
            has_exfil = True
        print(line)

    # --- 5.3 结论 ---
    print("\n[3] 结论")
    if has_exfil or has_error:
        print("  ✗ 不合规：存在出域红线或违规摆放，上线前必须整改。")
    elif has_deny:
        print("  △ 链路中存在不可达跳，需补白名单 / 调整摆放后才能通。")
    else:
        print("  ✓ 合规：数据未出域，调用链全部可达（白名单跳需提前申请）。")
    print()
    return not (has_exfil or has_error)


# ----------------------------------------------------------------------------
# 6) 主入口
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="政企网络拓扑连通性+出域模拟器")
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO, help="场景 JSON 路径")
    parser.add_argument("--placement", default="all",
                        choices=["all", "good", "bad"], help="只跑指定方案")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    segments = scenario["segments"]
    rules = scenario["rules"]
    placements = scenario["placements"]

    print("#" * 70)
    print(f"# {scenario['name']}")
    if scenario.get("note"):
        print(f"# {scenario['note']}")
    print("#" * 70)

    # 打印拓扑速览
    print("\n[网络层速览]")
    for key, seg in sorted(segments.items(), key=lambda x: x[1]["layer"]):
        flags = []
        if seg["egress"]:
            flags.append("可出网")
        if seg["holds_prod_data"]:
            flags.append("存生产数据")
        print(f"  L{seg['layer']} {seg['name']}：{', '.join(flags) if flags else '普通'}")

    # 跑方案
    targets = (["good", "bad"] if args.placement == "all" else [args.placement])
    results = {}
    for t in targets:
        if t not in placements:
            print(f"[跳过] 场景中没有 '{t}' 方案")
            continue
        ok = run_placement(t, placements[t], segments, rules)
        results[t] = ok

    # 总览
    print("=" * 70)
    print("总览：")
    for t, ok in results.items():
        print(f"  {t:6s} → {'合规' if ok else '不合规'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
