#!/usr/bin/env zsh
set -euo pipefail

# ===== 配置区（按需修改）=====
DOUYIN_URL="https://v.douyin.com/xxxx/"
ASR_PROVIDER="qwen"
ASR_API_KEY="YOUR_QWEN_API_KEY"
DEEPSEEK_API_KEY="YOUR_DEEPSEEK_API_KEY"
OUTPUT_MD="/dir/douyin_summary_output.md"
DEEPSEEK_PROMPT=$'你是短视频文案分析助手。\n请基于转写文本输出：\n1. 一句话核心总结\n2. 3-5条关键观点\n3. 可复用的文案结构模板\n4. 5个标题建议\n请使用简体中文，表达清晰。'

# Python 脚本路径（默认当前目录）
PYTHON_SCRIPT="/dir/douyin_copywriter.py"

# ===== 运行前检查 =====
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
  echo "错误: 未找到 Python 脚本: $PYTHON_SCRIPT"
  echo "请确认 douyin_copywriter.py 在该路径下。"
  exit 1
fi

if [[ "$ASR_API_KEY" == "YOUR_QWEN_API_KEY" || "$DEEPSEEK_API_KEY" == "YOUR_DEEPSEEK_API_KEY" ]]; then
  echo "错误: 请先在脚本里填入 ASR_API_KEY 和 DEEPSEEK_API_KEY"
  exit 1
fi

# ===== 环境变量配置 =====
export ASR_PROVIDER
export ASR_API_KEY
export DEEPSEEK_API_KEY
export QWEN_BASE_URL="https://dashscope.aliyuncs.com/api/v1"
export QWEN_MODEL="qwen3-asr-flash-filetrans"
export DEEPSEEK_MODEL="deepseek-chat"
export DEEPSEEK_PROMPT

# ===== 执行 =====
python3 -u "$PYTHON_SCRIPT" "$DOUYIN_URL" \
  --asr-provider "$ASR_PROVIDER" \
  --asr-api-key "$ASR_API_KEY" \
  --deepseek-api-key "$DEEPSEEK_API_KEY" \
  --deepseek-prompt "$DEEPSEEK_PROMPT" \
  -o "$OUTPUT_MD"

echo "完成: $OUTPUT_MD"
