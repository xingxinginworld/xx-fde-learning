@echo off
REM 一键启动脚本（Windows，使用本地 .venv 虚拟环境）
if not exist .venv (
  echo ==^> 创建虚拟环境并安装依赖
  py -3.13 -m venv .venv
  .venv\Scripts\pip.exe install -r requirements.txt
)

if not exist index\vecs.faiss (
  echo ==^> 首次运行，构建向量索引（请先确保 data\ 下已放入招标文件 PDF）
  .venv\Scripts\python.exe build_index.py
)

echo ==^> 启动 Demo：http://localhost:8501
.venv\Scripts\streamlit.exe run app.py
