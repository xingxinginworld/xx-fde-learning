#!/bin/bash
# 一键启动脚本（Linux / Mac，使用本地 .venv 虚拟环境）
set -e

if [ ! -d .venv ]; then
  echo "==> 创建虚拟环境并安装依赖"
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

if [ ! -f index/vecs.faiss ]; then
  echo "==> 首次运行，构建向量索引（请先确保 data/ 下已放入招标文件 PDF）"
  .venv/bin/python build_index.py
fi

echo "==> 启动 Demo：http://localhost:8501"
.venv/bin/streamlit run app.py
