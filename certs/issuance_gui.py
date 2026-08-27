# -*- coding: utf-8 -*-
"""
FDE 中级证书签发工具（Streamlit 图形界面）
────────────────────────────────────────────────────────────────
启动（仓库根目录，Streamlit ≥1.40）：
    streamlit run certs/issuance_gui.py

本文件只是「界面层」，所有校验/台账/评语逻辑都在 certs/issuance_core.py，
签发核心（编号/hash/双注册表/HTML/在线核验链接）复用 certs/generator.py。
流程：填表 → 硬闸校验 → 自动写 capstone 台账（generator 硬校验依据）
      → generator.issue() 签发 → 展示 HTML 路径 + 在线核验链接。
"""
from datetime import date
from pathlib import Path
import sys

import streamlit as st

# 确保无论从哪个目录 `streamlit run certs/issuance_gui.py`，都能找到同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))
import issuance_core as core   # noqa: E402  纯逻辑（校验/台账/评语）
import generator as certgen    # noqa: E402  签发核心（编号/hash/注册表/HTML）

st.set_page_config(page_title="FDE 中级证书签发", page_icon="🎓", layout="wide")
st.title("🎓 FDE 中级证书签发工具")
st.caption("适用：49.9 FDE 中级专项学习微信群 / 49.9 私人订制 学员 · "
           "签发即写双注册表，push 后在线可核验")

if "result" not in st.session_state:
    st.session_state.result = None

# ── 一、基本信息 ──
st.subheader("一、基本信息")
c1, c2, c3 = st.columns(3)
with c1:
    name = st.text_input("姓名（必填）", key="name",
                         help="证书上显示的持证人实名，须与 capstone 提交人对应")
with c2:
    quiz_link = st.text_input("中级测验成绩链接（非必填）", key="quiz_link",
                              help="成绩卡 result.html 链接，填了自动解析 score")
with c3:
    cs_link = st.text_input("Capstone 项目 GitHub 链接（非必填）", key="cs_link",
                            help="仅作溯源，存入台账与注册表，不上证书")

parsed = core.parse_quiz_score(quiz_link)
c4, c5, c6 = st.columns(3)
quiz_score_manual = None
with c4:
    if quiz_link.strip() and parsed is not None:
        st.metric("中级测验成绩（自动解析）", f"{parsed} / 100")
    else:
        quiz_score_manual = st.number_input(
            "中级测验成绩（0–100）", min_value=0, max_value=100,
            value=None, step=1, key="quiz_manual")
        st.caption("未填成绩链接时此框必填；填了链接自动解析，此框留空即可")
with c5:
    review_date = st.date_input("评审日期（必填）", value=date.today(), key="rdate")
with c6:
    passed = (st.radio(
        "结论（必填）",
        options=["✅ 通过", "❌ 不通过"],
        index=0,
        horizontal=True,
        key="conclusion") == "✅ 通过")

# ── 二、五维度评分 ──
st.subheader("二、五维度评分（必填，按 capstone/grading.md 锚点取分）")
dcols = st.columns(5)
scores = {}
for i, (label, mx) in enumerate(core.DIMS):
    with dcols[i]:
        scores[label] = st.number_input(
            f"{label}（0–{mx}）", min_value=0, max_value=mx,
            value=None, step=1, key=f"dim_{i}")
total = st.number_input("总分 / 100（五维自动求和，可手动修正）",
                        min_value=0, max_value=100, value=None, step=1, key="total")
if all(v is not None for v in scores.values()) and total is not None:
    dim_sum = sum(scores.values())
    if dim_sum != total:
        st.warning(f"五维之和为 **{dim_sum}**，与你填的总分 {total} 不一致，请核对"
                   f"（总分 = 功能+效果+性能+异常+适配）")

# ── 三、评语 ──
st.subheader("三、评语（必填，自动从 10 条池随机抽取，可换一条）")
pool = core.load_comments()["pass" if passed else "fail"]
cur_key = "pass" if passed else "fail"
if "comment" not in st.session_state or st.session_state.get("comment_key") != cur_key:
    st.session_state.comment_key = cur_key
    st.session_state.comment = core.pick_comment(passed)
cc1, cc2 = st.columns([1, 4])
with cc1:
    st.write("")
    if st.button("🎲 换一条", key="reroll"):
        others = [c for c in pool if c != st.session_state.comment]
        st.session_state.comment = (others[len(others) // 2]
                                    if len(others) > 1 else pool[0])
        st.rerun()
with cc2:
    st.text_area("评语", value=st.session_state.comment, height=76, key="comment_ta")

# ── 校验 ──
errors = core.validate(name, scores, total, passed, quiz_link, quiz_score_manual)
for e in errors:
    st.error(f"⚠️ {e}")

# 台账已有通过记录提示
if name.strip():
    existing = core.find_latest_entry(name.strip())
    if existing and existing.get("pass") is True and total is not None \
            and existing.get("total") != total:
        st.info(f"ℹ️ 台账中「{name.strip()}」已有通过记录（{existing.get('total')} 分，"
                f"{existing.get('submit_date')}）。本次将新增一条，签发时以最新记录为准。")

# ── 签发 ──
st.divider()
can_submit = not errors
if st.button("🚀 签发", type="primary", disabled=not can_submit):
    rdate = review_date.isoformat()
    quiz_score = core.resolve_quiz_score(quiz_link, quiz_score_manual)
    comment = st.session_state.comment
    if passed:
        # 1) 先写台账（generator 中级硬校验的依据：台账必须有该姓名通过记录）
        core.append_ledger(core.make_entry(
            name.strip(), scores, total, True, comment, rdate,
            quiz_link.strip(), cs_link.strip()))
        # 2) 复用签发核心（编号/hash/双注册表/HTML/核验链接）
        #    注：测验链接/capstone 链接只留档在本地台账（make_entry 已写入），
        #    不写入公开注册表，也不上证书——公开链路保持与 generator.py 原版一致。
        try:
            rec = certgen.issue(
                name=name.strip(), tier="intermediate", score=int(quiz_score),
                capstone_pass=True, emit_html=True)
        except SystemExit as se:
            st.error(f"❌ 签发被拒绝：{se}")
            st.session_state.result = "error"
        else:
            # 3) 回写 cert_id 到刚追加的台账条目
            led = core.load_ledger()
            led[-1]["cert_id"] = rec["id"]
            core.save_ledger(led)
            verify = f"{core.VERIFY_BASE}?id={rec['id']}"
            html_path = certgen.ISSUES + f"/{rec['id']}.html"
            st.session_state.result = {
                "passed": True, "cid": rec["id"],
                "html": html_path, "verify": verify}
    else:
        core.append_ledger(core.make_entry(
            name.strip(), scores, total, False, comment, rdate,
            quiz_link.strip(), cs_link.strip()))
        st.session_state.result = {"passed": False}

# ── 结果 ──
res = st.session_state.result
if isinstance(res, dict) and res.get("passed"):
    st.success("✅ **证书已生成**")
    st.write("证书存储的 HTML 路径为：")
    st.code(res["html"], language="text")
    st.write(
        "**注意：需要 `git push` 后给出如下链接，即可在线验证**  \n\n"
        f"在线核验链接：**{res['verify']}**  \n\n"
        f"证书编号：{res['cid']}（已写入 registry.json + registry.public.json）")
elif isinstance(res, dict) and not res.get("passed"):
    st.info("💪 **再接再厉，证书在等着你。**")
    st.caption(f"已写入一条不通过台账留痕（{name.strip()}，总分 {total}），"
               f"整改后可重新评审签发。")

st.caption("说明：`certs/issues/` 与 `capstone/results.json` 已在 .gitignore（本地存档不入库）；"
           "只有 `certs/registry.public.json` 需要随证书 push 到仓库，在线核验才会生效。")
