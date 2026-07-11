"""可复用的流水线。

供 CLI（run.py）与 UI（app.py）共用。与原来 run.py 的区别是：
每完成一个阶段都会调用 on_progress(stage, pct, message)，便于 UI 实时显示进度。

业务逻辑（src/collector/transcriber/summarizer/docgen/notifier）完全复用，此处不改。
"""
import os

from .config import load_config
from .utils import BASE_DIR, get_logger, today_str
from .collector import collect
from .transcriber import transcribe
from .summarizer import summarize
from .docgen import generate
from . import notifier

logger = get_logger()


def run_pipeline(
    cfg: dict = None,
    date_str: str = None,
    use_demo: bool = False,
    no_push: bool = False,
    on_progress=None,
) -> dict:
    """跑完整条流水线，返回结果字典。

    参数：
      cfg        配置 dict（不传则自动 load_config）
      date_str   指定日期 YYYY-MM-DD（默认今天）
      use_demo   使用演示数据，不依赖真实账号
      no_push    只生成本地文档，不推送
      on_progress 进度回调，签名 on_progress(stage:str, pct:float, message:str)

    返回：
      {
        "items": [...], "grouped": {...},
        "files": {"markdown": path, "pdf": path},
        "pushed": bool, "empty": bool
      }
    """
    cfg = cfg or load_config()
    emit = on_progress or (lambda stage, pct, msg: None)
    date_str = date_str or today_str()

    # 1) 采集
    emit("collect", 0.05, "开始采集收藏列表…")
    items = collect(cfg, use_demo=use_demo)
    if not items:
        emit("collect", 0.20, "未采集到任何视频，流程结束")
        return {"items": [], "grouped": {}, "files": {}, "pushed": False, "empty": True}
    emit("collect", 0.20, f"采集到 {len(items)} 条视频")

    # 2) 转写（逐条，进度随条数推进）
    emit("transcribe", 0.25, "开始转写视频内容…")
    transcript_dir = os.path.join(BASE_DIR, "transcripts")
    download_dir = os.path.join(BASE_DIR, "downloads")
    os.makedirs(transcript_dir, exist_ok=True)
    total = len(items)
    for i, v in enumerate(items):
        vid = v.get("id") or v.get("title") or "unknown"
        try:
            text = transcribe(cfg, v, download_dir)
        except Exception as e:
            logger.exception("转写失败 %s: %s", vid, e)
            text = ""
        raw_title = (v.get("title") or "").strip()
        safe_title = "".join(c if c.isalnum() or c in " _-." else "_" for c in raw_title)[:40]
        fname = f"{safe_title}_{vid}.txt" if safe_title else f"{vid}.txt"
        with open(os.path.join(transcript_dir, fname), "w", encoding="utf-8") as f:
            f.write(text)
        v["transcript"] = text
        title = (v.get("title") or "")[:20]
        emit(
            "transcribe",
            0.25 + 0.35 * (i + 1) / total,
            f"已转写 {i + 1}/{total}：{title}",
        )

    # 3) 摘要 + 分类
    emit("summarize", 0.65, "生成摘要与分类…")
    grouped = summarize(cfg, items)

    # 4) 生成文档
    emit("generate", 0.80, "生成 Markdown / PDF…")
    files = generate(cfg, grouped, date_str)

    # 5) 推送
    emit("notify", 0.90, "推送结果…")
    pushed = _notify(cfg, grouped, date_str, files, no_push)

    emit("done", 1.0, "完成 ✅")
    return {
        "items": items,
        "grouped": grouped,
        "files": files,
        "pushed": pushed,
        "empty": False,
    }


def _notify(cfg: dict, grouped: dict, date_str: str, files: dict, no_push: bool) -> bool:
    method = cfg["notify"].get("method", "wecom")
    if method == "email":
        html = notifier.build_email_content(cfg, grouped, date_str)
        if no_push:
            logger.info("（no_push）邮件 HTML 预览长度：%d", len(html))
            return False
        res = notifier.push_email(cfg["notify"], html, files, date_str)
        return bool(res.get("sent"))
    else:
        content = notifier.build_wecom_content(cfg, grouped, date_str)
        if no_push:
            logger.info("（no_push）企业微信消息内容：\n%s", content)
            return False
        res = notifier.push_wecom(
            cfg["notify"]["webhook"],
            content,
            cfg["notify"].get("mention_all", False),
        )
        return bool(
            res.get("printed") or res.get("errcode") == 0 or "error" not in res
        )
