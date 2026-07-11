"""企业微信机器人推送（Webhook）。

WeCom markdown 消息限制：单条 ≤ 4096 字节，支持 # 标题、>**加粗**、[文字](链接) 等有限语法。
未配置 webhook 时仅打印消息内容，方便本地调试。
"""
import json
import os
from xml.sax.saxutils import escape

from .utils import BASE_DIR, get_logger

logger = get_logger()


def build_wecom_content(cfg: dict, grouped: dict, date_str: str) -> str:
    max_n = cfg["document"].get("max_items_per_category", 20)
    lines = [f"# 拾光 · 每日摘要 · {date_str}", ""]
    for cat, items in grouped.items():
        lines.append(f"## {cat}（{len(items)}）")
        for it in items[:max_n]:
            title = it.get("title", "")
            summary = it.get("summary", "")
            url = it.get("url", "")
            line = f"> **{title}**｜{summary}"
            if url:
                line += f" [查看]({url})"
            lines.append(line)
        lines.append("")
    return "\n".join(lines)


def push_wecom(webhook: str, content: str, mention_all: bool = False) -> dict:
    if not webhook:
        logger.info("未配置企业微信 Webhook，仅打印消息：\n%s", content)
        return {"printed": True}

    import requests

    msg = ("<@all>\n" + content) if mention_all else content
    payload = {"msgtype": "markdown", "markdown": {"content": msg}}
    try:
        r = requests.post(webhook, json=payload, timeout=10)
        logger.info("企业微信返回：%s", r.text)
        return r.json()
    except Exception as e:
        logger.exception("企业微信推送失败：%s", e)
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# 邮件推送（QQ 邮箱 SMTP）
# ---------------------------------------------------------------------------
def build_email_content(cfg: dict, grouped: dict, date_str: str) -> str:
    """构建 HTML 邮件正文（分类卡片 + 标题/摘要/链接）。"""
    max_n = cfg["document"].get("max_items_per_category", 20)
    css_card = "margin:0 0 12px;padding:10px 14px;border:1px solid #eee;border-radius:8px;"
    css_title = "color:#1a1a1a;text-decoration:none;font-size:15px;"
    css_sum = "color:#555;font-size:13px;margin-top:4px;line-height:1.5;"
    parts = [f'<h1 style="font-size:20px;">拾光 · 每日摘要 · {date_str}</h1>']
    for cat, items in grouped.items():
        parts.append(f'<h2 style="font-size:16px;margin:18px 0 8px;">{escape(cat)}（{len(items)}）</h2>')
        for it in items[:max_n]:
            title = escape(it.get("title", ""))
            summary = escape(it.get("summary", "")).replace("\n", "<br/>")
            url = it.get("url", "")
            if url:
                title_html = f'<a href="{escape(url)}" style="{css_title}">{title}</a>'
            else:
                title_html = f'<span style="{css_title}">{title}</span>'
            parts.append(
                f'<div style="{css_card}">{title_html}<div style="{css_sum}">{summary}</div></div>'
            )
    return "\n".join(parts)


def push_email(notify_cfg: dict, html_body: str, files: dict, date_str: str) -> dict:
    """通过 SMTP 发送邮件（HTML 正文 + PDF/MD 附件）；未配置账号时仅打印预览。"""
    sender = (notify_cfg.get("sender") or "").strip()
    password = (notify_cfg.get("password") or "").strip()
    receiver = (notify_cfg.get("receiver") or sender).strip()

    if not (sender and password and receiver):
        logger.info("未配置邮件发送信息（sender/password/receiver），仅打印 HTML 预览（前600字）：\n%s", html_body[:600])
        return {"printed": True}

    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
    from email.mime.application import MIMEApplication
    from email.header import Header
    import smtplib

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = receiver
    msg["Subject"] = Header(f"拾光 · {date_str}", "utf-8")
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    for path in (files or {}).values():
        if isinstance(path, str) and os.path.exists(path):
            with open(path, "rb") as fp:
                part = MIMEApplication(fp.read(), Name=os.path.basename(path))
            part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
            msg.attach(part)

    host = notify_cfg.get("smtp_host", "smtp.qq.com")
    port = int(notify_cfg.get("smtp_port", 465))
    use_ssl = bool(notify_cfg.get("smtp_ssl", True))
    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=15) as s:
                s.login(sender, password)
                s.sendmail(sender, receiver, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.starttls()
                s.login(sender, password)
                s.sendmail(sender, receiver, msg.as_string())
        logger.info("邮件已发送至 %s", receiver)
        return {"sent": True}
    except Exception as e:
        logger.exception("邮件发送失败：%s", e)
        return {"error": str(e)}
