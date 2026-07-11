"""安卓版定时任务入口 —— 纯 HTTP 采集，不依赖 Playwright / Chrome。
供 Tasker / Termux cron 等外部调度器调用。
"""
import os, sys

# 确保能找到 src 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.collector_http import collect_http
from src.config import load_config
from src.pipeline import run_pipeline


def main():
    cfg = load_config()
    # 强制 HTTP 采集
    cfg["collection"]["provider"] = "http"

    items = collect_http(cfg)
    if not items:
        print("今日无新增收藏")
        return

    result = run_pipeline(cfg)
    n = len(result.get("items") or [])
    pushed = result.get("pushed", False)
    files = result.get("files") or {}
    md = files.get("markdown", "无")
    print(f"完成：{n} 条 | 推送: {'已发送' if pushed else '未发送'} | 日报: {md}")


if __name__ == "__main__":
    main()
