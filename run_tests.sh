#!/usr/bin/env bash
# 一键复跑：接口用例 + 工作台表单用例 + 浏览器 UI 用例（UI 用例会自动拉起服务）。
set -euo pipefail
cd "$(dirname "$0")"

PY=${PY:-python3}

echo "==> 1/2 接口与表单用例"
"$PY" -m pytest tests -q --ignore=tests/ui

echo
echo "==> 2/2 浏览器 UI 用例（截图写入 docs/screenshots/）"
# 若本机已有可用浏览器可直跑；否则先 python -m playwright install chromium
# 需要复用已在运行的浏览器（含登录态）时：PW_CDP=http://127.0.0.1:9222 ./run_tests.sh
"$PY" -m pytest tests/ui -q

echo
echo "全部用例通过。截图见 docs/screenshots/，明细见 docs/运行报告.md"
