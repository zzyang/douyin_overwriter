# 抖音视频文案提取总结

一个 Python 命令行工具，支持：
- 解析抖音短链接
- 下载并提取音频
- 调用语音模型转写成文字
- 调用 DeepSeek 总结文案
- 输出 Markdown 报告

说明：当 `yt-dlp` 因抖音风控失败时，程序会尝试使用 `iesdouyin` 页面数据做一次兜底下载；若视频已删除/权限不可见，会输出明确原因。

## 1. 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

还需要系统可用 `ffmpeg`（供 `yt-dlp` 音频提取时使用）。

## 2. 配置 API Key

```bash
export ASR_API_KEY="你的语音模型API_KEY"
export DEEPSEEK_API_KEY="你的DeepSeek_API_KEY"
```

可选配置：

```bash
export ASR_BASE_URL="https://api.openai.com/v1"
export ASR_MODEL="whisper-1"
export DEEPSEEK_MODEL="deepseek-chat"
```

若使用千问 ASR（DashScope）：

```bash
export ASR_PROVIDER="qwen"
export ASR_API_KEY="你的DashScope_API_KEY"
export QWEN_BASE_URL="https://dashscope.aliyuncs.com/api/v1"
export QWEN_MODEL="qwen3-asr-flash-filetrans"
```

## 3. 运行

```bash
python douyin_copywriter.py "https://v.douyin.com/xxxxxx/"

# 使用千问 ASR + DeepSeek 总结
python douyin_copywriter.py "https://v.douyin.com/xxxxxx/" \
  --asr-provider qwen \
  --asr-api-key "$ASR_API_KEY" \
  --deepseek-api-key "$DEEPSEEK_API_KEY" \
  -o result.md
```

指定输出路径：

```bash
python douyin_copywriter.py "https://v.douyin.com/xxxxxx/" -o result.md

# 需要登录态时（推荐）
python douyin_copywriter.py "https://v.douyin.com/xxxxxx/" \
  --cookies-from-browser chrome \
  -o result.md
```

## 4. 参数说明

- `url`: 抖音短链接或分享链接
- `-o, --output`: 输出 Markdown 文件路径（默认 `douyin_summary.md`）
- `--workdir`: 临时音频目录（默认 `.cache_douyin_audio`）
- `--asr-base-url`: 语音模型服务地址（OpenAI 兼容）
- `--asr-model`: 语音模型名
- `--asr-provider`: `openai` 或 `qwen`
- `--asr-api-key`: 语音模型 API Key
- `--qwen-base-url`: 千问 ASR DashScope 地址
- `--qwen-model`: 千问 ASR 模型（默认 `qwen3-asr-flash-filetrans`）
- `--deepseek-api-key`: DeepSeek API Key
- `--deepseek-model`: DeepSeek 模型名
- `--cookies`: cookies 文件路径（yt-dlp 格式）
- `--cookies-from-browser`: 直接从浏览器读取 cookies（如 `chrome` / `safari` / `firefox`）

## 5. 输出示例结构

生成文件包含：
- 原始链接、解析链接、视频ID
- 完整转写文本
- DeepSeek 总结（核心总结、观点、模板、标题建议）
