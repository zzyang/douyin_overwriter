#!/usr/bin/env python3
"""
抖音视频文案提取与总结

功能：
1) 解析抖音短链接
2) 下载视频音频
3) 调用语音模型进行转写
4) 调用 DeepSeek 进行文案总结
5) 输出 Markdown
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
from html import unescape
from pathlib import Path
from typing import Any, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests


class PipelineError(RuntimeError):
    """业务错误。"""


def resolve_douyin_short_url(url: str, timeout: int = 15) -> Tuple[str, str]:
    """
    解析抖音短链接，返回 (最终链接, 视频ID(若提取不到则为空字符串))
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(url, allow_redirects=True, headers=headers, timeout=timeout)
    resp.raise_for_status()
    final_url = resp.url

    patterns = [
        r"/video/(\d+)",
        r"modal_id=(\d+)",
        r"aweme_id=(\d+)",
    ]
    video_id = ""
    for pattern in patterns:
        match = re.search(pattern, final_url)
        if match:
            video_id = match.group(1)
            break
    return final_url, video_id


def download_audio_with_yt_dlp(
    video_url: str,
    output_dir: Path,
    cookies_file: str = "",
    cookies_from_browser: str = "",
) -> Path:
    """
    使用 yt-dlp 提取音频并返回音频文件路径。
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    output_tpl = str(output_dir / "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-x",
        "--audio-format",
        "mp3",
        "-o",
        output_tpl,
        video_url,
    ]
    if cookies_file:
        cmd.extend(["--cookies", cookies_file])
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise PipelineError("未找到 yt-dlp，请先安装：pip install yt-dlp") from exc
    except subprocess.CalledProcessError as exc:
        # Douyin 常见风控会导致 yt-dlp 失败，尝试 iesdouyin 页面兜底提取。
        fallback_audio = try_download_audio_from_ies(video_url, output_dir)
        if fallback_audio is not None:
            return fallback_audio
        raise PipelineError(f"下载音频失败：{exc}") from exc

    audio_files = sorted(output_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not audio_files:
        raise PipelineError("yt-dlp 执行成功，但未找到输出 mp3 文件。")
    return audio_files[0]


def _extract_video_id_from_url(url: str) -> str:
    for pattern in (r"/video/(\d+)", r"modal_id=(\d+)", r"aweme_id=(\d+)"):
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return ""


def _extract_json_from_last_script(html: str) -> dict:
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I)
    for content in reversed(scripts):
        candidate = content.strip()
        if not candidate or not candidate.startswith("{"):
            continue
        try:
            return json.loads(unescape(candidate))
        except json.JSONDecodeError:
            continue
    return {}


def _extract_assigned_json(html: str, var_name: str) -> dict:
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.S | re.I)
    marker = f"{var_name} = "
    for script in scripts:
        if marker not in script:
            continue
        raw = script.split(marker, 1)[1].strip()
        if raw.endswith(";"):
            raw = raw[:-1].strip()
        try:
            return json.loads(unescape(raw))
        except json.JSONDecodeError:
            continue
    return {}


def try_download_audio_from_ies(video_url: str, output_dir: Path) -> Path | None:
    video_id = _extract_video_id_from_url(video_url)
    if not video_id:
        return None

    share_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        )
    }
    resp = requests.get(share_url, headers=headers, timeout=20)
    resp.raise_for_status()
    html = resp.text
    router_data = _extract_assigned_json(html, "window._ROUTER_DATA")
    if router_data:
        page_data = router_data.get("loaderData", {}).get("video_(id)/page", {})
        video_info_res = page_data.get("videoInfoRes", {})
    else:
        data = _extract_json_from_last_script(html)
        if not data:
            return None
        page_props = data.get("props", {}).get("pageProps", {})
        video_info_res = page_props.get("videoInfoRes", {})
    filter_list = video_info_res.get("filter_list") or []
    if filter_list:
        reason = filter_list[0].get("notice") or "视频不可访问"
        detail = filter_list[0].get("detail_msg") or ""
        raise PipelineError(f"视频不可访问：{reason} {detail}".strip())

    item_list = video_info_res.get("item_list") or []
    if not item_list:
        return None

    url_list = (
        item_list[0]
        .get("video", {})
        .get("play_addr", {})
        .get("url_list", [])
    )
    if not url_list:
        return None

    media_url = _prefer_low_bandwidth_url(url_list[0])
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_mp4 = output_dir / f"{video_id}.mp4"
    out_mp3 = output_dir / f"{video_id}.mp3"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.iesdouyin.com/",
    }
    last_exc: Exception | None = None
    for _ in range(3):
        try:
            with requests.get(media_url, stream=True, timeout=60, headers=headers) as r:
                r.raise_for_status()
                with temp_mp4.open("wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
            break
        except requests.RequestException as exc:
            last_exc = exc
            if temp_mp4.exists():
                temp_mp4.unlink()
    else:
        raise PipelineError(f"兜底下载视频失败：{last_exc}")

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(temp_mp4), "-vn", "-acodec", "libmp3lame", str(out_mp3)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        # 没有 ffmpeg 时，直接使用 mp4 给转写接口。
        return temp_mp4
    except subprocess.CalledProcessError as exc:
        raise PipelineError(f"ffmpeg 提取音频失败：{exc}") from exc
    finally:
        if temp_mp4.exists() and out_mp3.exists():
            temp_mp4.unlink()

    if not out_mp3.exists():
        return None
    return out_mp3


def get_media_url_from_ies(video_url: str) -> str:
    """从 iesdouyin 分享页提取可公开访问的视频地址。"""
    video_id = _extract_video_id_from_url(video_url)
    if not video_id:
        raise PipelineError("无法从链接中提取视频ID，无法调用千问ASR。")

    share_url = f"https://www.iesdouyin.com/share/video/{video_id}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        )
    }
    resp = requests.get(share_url, headers=headers, timeout=20)
    resp.raise_for_status()

    router_data = _extract_assigned_json(resp.text, "window._ROUTER_DATA")
    page_data = router_data.get("loaderData", {}).get("video_(id)/page", {})
    video_info_res = page_data.get("videoInfoRes", {})
    if not video_info_res:
        raise PipelineError("无法从 iesdouyin 页面提取视频元数据。")

    filter_list = video_info_res.get("filter_list") or []
    if filter_list:
        reason = filter_list[0].get("notice") or "视频不可访问"
        detail = filter_list[0].get("detail_msg") or ""
        raise PipelineError(f"视频不可访问：{reason} {detail}".strip())

    item_list = video_info_res.get("item_list") or []
    if not item_list:
        raise PipelineError("未找到视频内容，可能已下架或权限受限。")
    url_list = item_list[0].get("video", {}).get("play_addr", {}).get("url_list", [])
    if not url_list:
        raise PipelineError("未提取到可用播放地址。")
    return _prefer_low_bandwidth_url(url_list[0])


def _extract_transcript_text(payload: Any) -> str:
    """兼容多种返回结构，尽量提取纯文本转写结果。"""
    if isinstance(payload, dict):
        transcripts = payload.get("transcripts")
        if isinstance(transcripts, list):
            texts = []
            for row in transcripts:
                if isinstance(row, dict):
                    text = row.get("text")
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
            if texts:
                return "\n".join(texts)

        sentences = payload.get("sentences")
        if isinstance(sentences, list):
            texts = []
            for row in sentences:
                if isinstance(row, dict):
                    text = row.get("text") or row.get("sentence")
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
            if texts:
                return "\n".join(texts)

    result: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in {"text", "sentence", "transcript"} and isinstance(v, str) and v.strip():
                    result.append(v.strip())
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    if not result:
        return ""
    deduped: list[str] = []
    prev = None
    for text in result:
        if text != prev:
            deduped.append(text)
        prev = text
    return "\n".join(deduped)


def transcribe_with_qwen_filetrans(
    file_url: str,
    api_key: str,
    base_url: str = "https://dashscope.aliyuncs.com/api/v1",
    model: str = "qwen3-asr-flash-filetrans",
    timeout: int = 120,
    poll_interval: int = 2,
    max_wait_seconds: int = 600,
) -> str:
    submit_url = base_url.rstrip("/") + "/services/audio/asr/transcription"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": model,
        "input": {"file_url": file_url},
        "parameters": {
            "enable_itn": False,
        },
    }

    submit_resp = requests.post(submit_url, headers=headers, json=payload, timeout=timeout)
    if submit_resp.status_code >= 400:
        raise PipelineError(f"千问ASR任务提交失败：HTTP {submit_resp.status_code} - {submit_resp.text[:500]}")
    task_id = submit_resp.json().get("output", {}).get("task_id")
    if not task_id:
        raise PipelineError(f"千问ASR任务返回异常：{submit_resp.text[:500]}")

    query_url = base_url.rstrip("/") + f"/tasks/{task_id}"
    start = time.time()
    final_output = None
    while True:
        if time.time() - start > max_wait_seconds:
            raise PipelineError(f"千问ASR任务超时（>{max_wait_seconds}秒）。task_id={task_id}")
        query_resp = requests.get(query_url, headers=headers, timeout=timeout)
        if query_resp.status_code >= 400:
            raise PipelineError(f"千问ASR任务查询失败：HTTP {query_resp.status_code} - {query_resp.text[:500]}")
        body = query_resp.json()
        output = body.get("output", {})
        status = (output.get("task_status") or "").upper()
        if status in {"SUCCEEDED", "FAILED", "UNKNOWN"}:
            final_output = output
            break
        time.sleep(poll_interval)

    if not final_output:
        raise PipelineError("千问ASR任务结果为空。")
    if (final_output.get("task_status") or "").upper() != "SUCCEEDED":
        raise PipelineError(f"千问ASR任务失败：{json.dumps(final_output, ensure_ascii=False)[:500]}")

    transcription_url = ""
    # 兼容 1) output.result.transcription_url 2) output.results[*].transcription_url
    result_block = final_output.get("result") or {}
    if isinstance(result_block, dict) and result_block.get("transcription_url"):
        transcription_url = result_block["transcription_url"]
    results = final_output.get("results") or []
    if not transcription_url:
        for row in results:
            if row.get("subtask_status") == "SUCCEEDED" and row.get("transcription_url"):
                transcription_url = row["transcription_url"]
                break
    if not transcription_url:
        raise PipelineError(f"千问ASR无可用转写URL：{json.dumps(final_output, ensure_ascii=False)[:500]}")

    result_resp = requests.get(transcription_url, timeout=timeout)
    if result_resp.status_code >= 400:
        raise PipelineError(f"下载千问转写结果失败：HTTP {result_resp.status_code}")
    result_json = result_resp.json()
    text = _extract_transcript_text(result_json).strip()
    if not text:
        raise PipelineError(f"千问转写结果为空：{json.dumps(result_json, ensure_ascii=False)[:500]}")
    return text


def _prefer_low_bandwidth_url(url: str) -> str:
    """把 play URL 的 ratio 尽量降到 360p，减小下载与中转体积。"""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "ratio" in query:
        query["ratio"] = "360p"
        return urlunparse(parsed._replace(query=urlencode(query)))
    return url


def upload_file_to_dashscope(
    local_path: Path,
    api_key: str,
    base_url: str = "https://dashscope.aliyuncs.com/api/v1",
    timeout: int = 600,
) -> str:
    """
    上传文件到 DashScope 文件服务并返回文件 URL。
    """
    api = base_url.rstrip("/") + "/files"
    headers = {"Authorization": f"Bearer {api_key}"}
    last_exc: Exception | None = None
    resp = None
    for _ in range(3):
        try:
            with local_path.open("rb") as f:
                files = {"file": (local_path.name, f, "application/octet-stream")}
                data = {"purpose": "file-transcription"}
                resp = requests.post(api, headers=headers, files=files, data=data, timeout=timeout)
            break
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(2)
    if resp is None:
        raise PipelineError(f"上传临时文件失败：{last_exc}")
    if resp.status_code >= 400:
        raise PipelineError(f"上传 DashScope 文件失败：HTTP {resp.status_code} - {resp.text[:300]}")
    body = resp.json()
    uploaded_files = body.get("data", {}).get("uploaded_files") or []
    if not uploaded_files:
        raise PipelineError(f"上传 DashScope 文件返回异常：{json.dumps(body, ensure_ascii=False)[:300]}")
    file_id = uploaded_files[0].get("file_id")
    if not file_id:
        raise PipelineError(f"上传 DashScope 文件缺少 file_id：{json.dumps(body, ensure_ascii=False)[:300]}")

    detail_url = base_url.rstrip("/") + f"/files/{file_id}"
    detail_resp = requests.get(detail_url, headers=headers, timeout=timeout)
    if detail_resp.status_code >= 400:
        raise PipelineError(f"查询 DashScope 文件失败：HTTP {detail_resp.status_code} - {detail_resp.text[:300]}")
    file_url = detail_resp.json().get("data", {}).get("url", "")
    if not file_url:
        raise PipelineError(f"DashScope 文件详情缺少 url：{detail_resp.text[:300]}")
    return file_url


def transcribe_audio_openai_compatible(
    audio_path: Path,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 120,
) -> str:
    """
    调用 OpenAI 兼容语音转写接口，默认 endpoint: /audio/transcriptions
    """
    endpoint = base_url.rstrip("/") + "/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
    with audio_path.open("rb") as f:
        files = {
            "file": (audio_path.name, f, content_type),
        }
        data = {
            "model": model,
            "response_format": "json",
        }
        resp = requests.post(endpoint, headers=headers, files=files, data=data, timeout=timeout)
    if resp.status_code >= 400:
        raise PipelineError(f"语音转写失败：HTTP {resp.status_code} - {resp.text[:500]}")
    payload = resp.json()
    text = payload.get("text", "").strip()
    if not text:
        raise PipelineError(f"语音转写返回为空：{json.dumps(payload, ensure_ascii=False)[:500]}")
    return text


def summarize_with_deepseek(
    transcript: str,
    api_key: str,
    model: str = "deepseek-chat",
    system_prompt: str = "",
    base_url: str = "https://api.deepseek.com/v1",
    timeout: int = 120,
) -> str:
    endpoint = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    prompt = system_prompt.strip() or (
        "你是短视频文案分析助手。请基于转写文本输出：\n"
        "1. 一句话核心总结\n"
        "2. 3-5 条关键观点\n"
        "3. 可复用的文案结构模板\n"
        "4. 适合做标题的 5 个候选标题\n"
        "请使用简体中文，表达清晰，避免冗余。"
    )
    body = {
        "model": model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
    }
    resp = requests.post(endpoint, headers=headers, json=body, timeout=timeout)
    if resp.status_code >= 400:
        raise PipelineError(f"DeepSeek 总结失败：HTTP {resp.status_code} - {resp.text[:500]}")
    payload = resp.json()
    try:
        return payload["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError(f"DeepSeek 返回格式异常：{json.dumps(payload, ensure_ascii=False)[:500]}") from exc


def build_markdown(
    source_url: str,
    resolved_url: str,
    video_id: str,
    transcript: str,
    summary: str,
) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    video_id_text = video_id if video_id else "未解析到"
    return (
        f"# 抖音视频文案提取与总结\n\n"
        f"- 生成时间: {now}\n"
        f"- 原始链接: {source_url}\n"
        f"- 解析链接: {resolved_url}\n"
        f"- 视频ID: {video_id_text}\n\n"
        f"## 文案转写\n\n"
        f"{transcript}\n\n"
        f"## DeepSeek 总结\n\n"
        f"{summary}\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抖音视频文案提取总结工具")
    parser.add_argument("url", help="抖音短链接或视频分享链接")
    parser.add_argument(
        "-o",
        "--output",
        default="douyin_summary.md",
        help="Markdown 输出文件路径（默认: douyin_summary.md）",
    )
    parser.add_argument(
        "--workdir",
        default=".cache_douyin_audio",
        help="临时音频目录（默认: .cache_douyin_audio）",
    )
    parser.add_argument(
        "--asr-base-url",
        default=os.getenv("ASR_BASE_URL", "https://api.openai.com/v1"),
        help="语音接口 base url，默认读取 ASR_BASE_URL 或 https://api.openai.com/v1",
    )
    parser.add_argument(
        "--asr-model",
        default=os.getenv("ASR_MODEL", "whisper-1"),
        help="语音模型名，默认读取 ASR_MODEL 或 whisper-1",
    )
    parser.add_argument(
        "--asr-provider",
        choices=["openai", "qwen"],
        default=os.getenv("ASR_PROVIDER", "openai"),
        help="语音服务提供方，openai 或 qwen（默认 openai）",
    )
    parser.add_argument(
        "--asr-api-key",
        default=os.getenv("ASR_API_KEY", ""),
        help="语音接口 API Key，默认读取 ASR_API_KEY",
    )
    parser.add_argument(
        "--qwen-base-url",
        default=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"),
        help="千问ASR DashScope base url，默认 https://dashscope.aliyuncs.com/api/v1",
    )
    parser.add_argument(
        "--qwen-model",
        default=os.getenv("QWEN_MODEL", "qwen3-asr-flash-filetrans"),
        help="千问ASR模型，默认 qwen3-asr-flash-filetrans",
    )
    parser.add_argument(
        "--deepseek-api-key",
        default=os.getenv("DEEPSEEK_API_KEY", ""),
        help="DeepSeek API Key，默认读取 DEEPSEEK_API_KEY",
    )
    parser.add_argument(
        "--deepseek-model",
        default=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        help="DeepSeek 模型，默认 deepseek-chat",
    )
    parser.add_argument(
        "--deepseek-prompt",
        default=os.getenv("DEEPSEEK_PROMPT", ""),
        help="DeepSeek system prompt，可通过参数或 DEEPSEEK_PROMPT 覆盖默认总结提示词",
    )
    parser.add_argument(
        "--cookies",
        default=os.getenv("DOUYIN_COOKIES_FILE", ""),
        help="yt-dlp cookies 文件路径，默认读取 DOUYIN_COOKIES_FILE",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=os.getenv("DOUYIN_COOKIES_FROM_BROWSER", ""),
        help="从浏览器读取 cookies，如: chrome/safari/firefox",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.asr_api_key:
        print("错误: 缺少 ASR API Key，请设置 --asr-api-key 或环境变量 ASR_API_KEY", file=sys.stderr)
        return 2
    if not args.deepseek_api_key:
        print(
            "错误: 缺少 DeepSeek API Key，请设置 --deepseek-api-key 或环境变量 DEEPSEEK_API_KEY",
            file=sys.stderr,
        )
        return 2

    try:
        resolved_url, video_id = resolve_douyin_short_url(args.url)
        print(f"[1/4] 解析链接完成: {resolved_url}")

        if args.asr_provider == "qwen":
            media_url = get_media_url_from_ies(resolved_url)
            print("[2/4] 已提取播放地址，调用千问ASR中...")
            try:
                transcript = transcribe_with_qwen_filetrans(
                    file_url=media_url,
                    api_key=args.asr_api_key,
                    base_url=args.qwen_base_url,
                    model=args.qwen_model,
                )
            except PipelineError as exc:
                if "FILE_DOWNLOAD_FAILED" not in str(exc):
                    raise
                print("[2/4] 千问无法下载原始链接，尝试上传中转文件后重试...")
                local_media = try_download_audio_from_ies(resolved_url, Path(args.workdir))
                if not local_media:
                    raise PipelineError("中转重试失败：本地下载视频失败。") from exc
                relay_url = upload_file_to_dashscope(
                    local_media,
                    api_key=args.asr_api_key,
                    base_url=args.qwen_base_url,
                )
                transcript = transcribe_with_qwen_filetrans(
                    file_url=relay_url,
                    api_key=args.asr_api_key,
                    base_url=args.qwen_base_url,
                    model=args.qwen_model,
                )
        else:
            audio_path = download_audio_with_yt_dlp(
                resolved_url,
                Path(args.workdir),
                cookies_file=args.cookies,
                cookies_from_browser=args.cookies_from_browser,
            )
            print(f"[2/4] 音频下载完成: {audio_path}")
            transcript = transcribe_audio_openai_compatible(
                audio_path=audio_path,
                api_key=args.asr_api_key,
                base_url=args.asr_base_url,
                model=args.asr_model,
            )
        print(f"[3/4] 语音转写完成，字数: {len(transcript)}")

        summary = summarize_with_deepseek(
            transcript=transcript,
            api_key=args.deepseek_api_key,
            model=args.deepseek_model,
            system_prompt=args.deepseek_prompt,
        )
        print("[4/4] DeepSeek 总结完成")

        markdown = build_markdown(
            source_url=args.url,
            resolved_url=resolved_url,
            video_id=video_id,
            transcript=transcript,
            summary=summary,
        )

        output_path = Path(args.output)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"输出完成: {output_path.resolve()}")
        return 0
    except requests.RequestException as exc:
        print(f"网络请求失败: {exc}", file=sys.stderr)
        return 1
    except PipelineError as exc:
        print(f"处理失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
