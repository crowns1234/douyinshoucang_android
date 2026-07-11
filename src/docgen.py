"""生成每日摘要文档（Markdown + PDF）。"""
import os
import time

from .utils import BASE_DIR, get_logger
from xml.sax.saxutils import escape

logger = get_logger()


def render_markdown(grouped: dict, date_str: str) -> str:
    lines = [f"# 拾光 · 每日摘要 · {date_str}", ""]
    for cat, items in grouped.items():
        lines.append(f"## {cat}（{len(items)}）")
        for it in items:
            summary = it.get("summary", "")
            if summary:
                summary_lines = "\n    ".join(summary.split("\n"))
                lines.append(f"- **{it.get('title', '')}**\n    {summary_lines}")
            else:
                lines.append(f"- **{it.get('title', '')}**")
            lines.append(f"  - 作者：{it.get('author', '')} ｜ [链接]({it.get('url', '')})")
        lines.append("")
    return "\n".join(lines)


def render_pdf(grouped: dict, date_str: str, out_path: str):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # 注册中文字体，解决 PDF 默认字体（Helvetica/Times）不包含中文 → 乱码
    _cn_font = None
    for _cand in (
        "C:/Windows/Fonts/msyh.ttc",      # 微软雅黑
        "C:/Windows/Fonts/msyhbd.ttc",    # 微软雅黑粗体
        "C:/Windows/Fonts/simsun.ttc",    # 宋体
    ):
        if os.path.exists(_cand):
            try:
                pdfmetrics.registerFont(TTFont("CNFont", _cand))
                _cn_font = "CNFont"
                break
            except Exception:
                continue
    if not _cn_font:
        # fallback: reportlab 内置 CJK 字体（跨平台兜底）
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        _cn_font = "STSong-Light"

    doc = SimpleDocTemplate(out_path, pagesize=A4, title=f"拾光 · {date_str}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontSize=18, fontName=_cn_font)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=13, spaceBefore=10, fontName=_cn_font)
    body = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10, leading=14, fontName=_cn_font)

    story = [Paragraph(f"抖音收藏每日摘要 · {date_str}", h1), Spacer(1, 6)]
    for cat, items in grouped.items():
        story.append(Paragraph(escape(f"{cat}（{len(items)}）"), h2))
        for it in items:
            title = escape(it.get("title", ""))
            summary = escape(it.get("summary", "")).replace("\n", "<br/>")
            author = escape(it.get("author", ""))
            url = escape(it.get("url", ""))
            story.append(
                Paragraph(
                    f"<b>{title}</b><br/>{summary}<br/>作者：{author} ｜ <a href='{url}'>链接</a>",
                    body,
                )
            )
            story.append(Spacer(1, 4))
    doc.build(story)


def generate(cfg: dict, grouped: dict, date_str: str) -> dict:
    fmts = cfg["document"]["format"]
    out_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(out_dir, exist_ok=True)
    results = {}

    if "markdown" in fmts:
        md = render_markdown(grouped, date_str)
        p = os.path.join(out_dir, f"digest_{date_str}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(md)
        results["markdown"] = p

    if "pdf" in fmts:
        p = os.path.join(out_dir, f"digest_{date_str}.pdf")
        render_pdf(grouped, date_str, p)
        results["pdf"] = p

    # 旧文档清理
    keep = cfg["document"].get("keep_days", 30)
    _clean_old(out_dir, keep)
    return results


def _clean_old(out_dir: str, keep_days: int):
    now = time.time()
    for fn in os.listdir(out_dir):
        fp = os.path.join(out_dir, fn)
        if os.path.isfile(fp) and now - os.path.getmtime(fp) > keep_days * 86400:
            try:
                os.remove(fp)
            except OSError:
                pass
