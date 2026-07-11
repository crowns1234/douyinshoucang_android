"""视频转写：把视频内容变成文字。

支持四种 provider：
- mock：读取 samples/{video_id}.txt，用于演示，不依赖任何模型/下载。
- local：下载视频后用本地 Whisper 转写（需先装 ffmpeg 与 openai-whisper）。
- api：下载视频后调用 OpenAI 兼容 Whisper API 转写。
- baidu：用 ffmpeg 从抖音直链抽 16k 单声道 PCM，按 60s 切片调百度语音识别
         server_api（免费额度，需百度智能云 API Key / Secret Key）。

baidu 模式不落盘视频，直接 ffmpeg 边抽边转写，最省空间。
"""
import os
import sys
import base64
import subprocess
import urllib.request
import urllib.error
import json
import hashlib

from .utils import BASE_DIR, get_logger, DEFAULT_UA

logger = get_logger()

# 百度短语音 REST 接口：单段 ≤60s、≤3MB（raw pcm）。我们统一切成 16k/16bit/mono pcm，
# 每 60s = 16000*2*60 = 1,920,000 字节，远小于 3MB 上限。
CHUNK_SECONDS = 55  # 留点余量
CHUNK_BYTES = 16000 * 2 * CHUNK_SECONDS
REFERER = "https://www.douyin.com/"

# 百度要求 cuid 为特定格式的字符串（建议 32 位 hex，如设备标识 md5），普通单词会被拒（3300）。
CUID = hashlib.md5("douyin_digest_client".encode("utf-8")).hexdigest()


def _find_ffmpeg(cfg: dict) -> str:
    p = (cfg.get("transcription") or {}).get("ffmpeg_path")
    if p and os.path.exists(p):
        return p
    cand = os.path.join(BASE_DIR, "tools", "ffmpeg.exe")
    if os.path.exists(cand):
        return cand
    return "ffmpeg"  # 退回 PATH


def _download_direct_simple(url: str, save_dir: str, video_id: str) -> str:
    """纯 urllib 下载（带 Referer），不依赖 yt-dlp。"""
    os.makedirs(save_dir, exist_ok=True)
    out = os.path.join(save_dir, f"{video_id}.mp4")
    req = urllib.request.Request(url, headers={
        "User-Agent": DEFAULT_UA,
        "Referer": REFERER,
    })
    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
        while True:
            buf = r.read(1024 * 1024)
            if not buf:
                break
            f.write(buf)
    return out


def _extract_pcm(ffmpeg: str, url: str, max_seconds: int = 0) -> bytes:
    """用 ffmpeg 从直链抽 16k/16bit/mono 的 PCM 原始字节（不落盘）。

    max_seconds>0 时加 `-t` 限制，ffmpeg 只拉取前 N 秒，省下载时间/流量。
    """
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-headers", f"Referer: {REFERER}\r\nUser-Agent: Mozilla/5.0",
        "-i", url,
    ]
    if max_seconds and max_seconds > 0:
        cmd += ["-t", str(max_seconds)]
    cmd += ["-ar", "16000", "-ac", "1", "-f", "s16le", "-"]
    logger.info("ffmpeg 抽取音频中...")
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 抽取音频失败: " + proc.stderr.decode("utf-8", "ignore")[:300])
    return proc.stdout


def _get_baidu_token(api_key: str, secret_key: str) -> str:
    url = (
        "https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials"
        f"&client_id={api_key}&client_secret={secret_key}"
    )
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    if "access_token" not in data:
        raise RuntimeError("获取百度 access_token 失败：" + str(data))
    return data["access_token"]


def _asr_chunk_baidu(token: str, pcm: bytes) -> str:
    """对一段 ≤60s 的 pcm 调百度 server_api，返回识别文本。"""
    speech = base64.b64encode(pcm).decode("ascii")
    body = {
        "format": "pcm",
        "rate": 16000,
        "channel": 1,
        "cuid": CUID,
        "token": token,
        "dev_pid": 1537,  # 普通话(中文)
        "speech": speech,
        "len": len(pcm),
    }
    req = urllib.request.Request(
        "https://vop.baidu.com/server_api",  # 注意：dev_pid 必须放 body，放进 URL query 会触发「url param cuid error」
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("err_no") != 0:
                raise RuntimeError(f"百度识别错误 {data.get('err_no')}: {data.get('err_msg')}")
            # 百度 result 可能是列表（多句）或字符串，统一拼成字符串
            res = data.get("result", "")
            if isinstance(res, list):
                res = "".join(res)
            return res
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == 2:
                raise
            logger.warning("百度识别请求重试(%d): %s", attempt + 1, e)


def _transcribe_baidu(cfg: dict, video: dict) -> str:
    tcfg = cfg["transcription"]
    api_key = tcfg.get("baidu_api_key")
    secret_key = tcfg.get("baidu_secret_key")
    if not api_key or not secret_key:
        raise RuntimeError(
            "未配置百度语音识别密钥。请在 config.yaml 的 transcription 下填写 "
            "baidu_api_key 与 baidu_secret_key（百度智能云→语音技术→创建应用获得）。"
        )
    play_url = video.get("play_url") or video.get("url")
    if not play_url:
        raise RuntimeError("缺少视频直链 play_url，无法转写。")

    # 时长封顶：日报只需抓住要点，避免长视频爆免费额度/耗时。默认前 3 分钟。
    max_seconds = int(tcfg.get("max_seconds", 180) or 180)
    capped = max_seconds and max_seconds > 0

    ffmpeg = _find_ffmpeg(cfg)
    pcm = _extract_pcm(ffmpeg, play_url, max_seconds if capped else 0)
    logger.info("音频抽取完成，共 %.1f 秒", len(pcm) / 32000.0)
    if not pcm:
        return "（音频抽取为空，可能视频无音轨或直链失效）"

    # 安全兜底：即便 ffmpeg 未遵守 -t，也按 cap_bytes 截断
    cap_bytes = max_seconds * 32000
    if capped and len(pcm) > cap_bytes:
        pcm = pcm[:cap_bytes]
        logger.info("视频较长，仅转写前 %d 秒（%d 段）", max_seconds, (len(pcm) + CHUNK_BYTES - 1) // CHUNK_BYTES)

    token = _get_baidu_token(api_key, secret_key)
    parts = []
    for i in range(0, len(pcm), CHUNK_BYTES):
        chunk = pcm[i:i + CHUNK_BYTES]
        if len(chunk) < 16000 * 2:  # 末尾不足 1 秒，丢弃
            break
        parts.append(_asr_chunk_baidu(token, chunk))
    text = "".join(parts).strip()
    if not text:
        return "（百度未返回识别结果）"
    if capped:
        text += f"\n（注：视频较长，仅转写了前 {max_seconds} 秒语音）"
    return text


def _transcribe_local(path: str, model: str, language: str) -> str:
    import whisper

    m = whisper.load_model(model)
    return m.transcribe(path, language=language)["text"]


def _transcribe_api(path: str, api_key: str, language: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(
            model="whisper-1", file=f, language=language
        )
    return resp.text


def _transcribe_mock(video_id: str) -> str:
    sample = os.path.join(BASE_DIR, "samples", f"{video_id}.txt")
    if os.path.exists(sample):
        return open(sample, encoding="utf-8").read()
    return "（演示模式：此处为视频转写文本占位。配置本地 Whisper 或 API 后可获得真实内容。）"


def transcribe(cfg: dict, video: dict, save_dir: str) -> str:
    provider = cfg["transcription"]["provider"]
    vid = video.get("id") or video.get("title") or "unknown"

    if provider == "mock":
        return _transcribe_mock(vid)

    if provider == "baidu":
        return _transcribe_baidu(cfg, video)

    # local / api：先下载视频再转写
    path = _download_direct_simple(video.get("url", ""), save_dir, vid)
    if provider == "local":
        text = _transcribe_local(
            path, cfg["transcription"]["model"], cfg["transcription"]["language"]
        )
    elif provider == "api":
        text = _transcribe_api(
            path, cfg["transcription"]["api_key"], cfg["transcription"]["language"]
        )
    else:
        text = ""

    keep = cfg["transcription"].get("keep_videos_days", 0)
    if not keep:
        try:
            os.remove(path)
        except OSError:
            pass
    return text
