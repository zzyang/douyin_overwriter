# 抖音视频文案提取与总结

本项目用于：
- 解析抖音短链接
- 调用千问 ASR 做语音转写
- 调用 DeepSeek 对转写文案做总结
- 输出 Markdown 报告

## 文件说明

- `douyin_copywriter.py`: 主程序
- `run_douyin_summary.zsh`: 一键运行脚本（推荐）
- `requirements.txt`: Python 依赖

## 快速开始

### 1) 安装依赖

```bash
cd /Users/andy/Documents/Playground
pip3 install -r requirements.txt
```

### 2) 编辑运行脚本

打开并编辑：

`/Users/andy/Documents/Playground/run_douyin_summary.zsh`

重点修改这些变量：

- `DOUYIN_URL`: 抖音短链接
- `ASR_API_KEY`: 千问 Key
- `DEEPSEEK_API_KEY`: DeepSeek Key
- `DEEPSEEK_PROMPT`: 给 DeepSeek 的总结提示词（可自由改）
- `OUTPUT_MD`: 输出 Markdown 文件路径

### 3) 执行

```bash
chmod +x /Users/andy/Documents/Playground/run_douyin_summary.zsh
/Users/andy/Documents/Playground/run_douyin_summary.zsh
```

## 手动命令方式（可选）

```bash
python3 -u /Users/andy/Documents/Playground/douyin_copywriter.py "https://v.douyin.com/xxxxxx/" \
  --asr-provider qwen \
  --asr-api-key "YOUR_QWEN_API_KEY" \
  --deepseek-api-key "YOUR_DEEPSEEK_API_KEY" \
  --deepseek-prompt "你自定义的总结提示词" \
  -o /Users/andy/Documents/Playground/douyin_summary_output.md
```

## 说明

- 当千问无法直接下载抖音源地址时，程序会自动尝试中转上传后重试转写。
- `--deepseek-prompt` 为空时，会使用程序内置默认总结模板。
