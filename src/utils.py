"""通用工具：路径、日志、日期、文件名安全化。"""
import os
import re
import sys
import logging
from datetime import datetime, date

def _resolve_base_dir() -> str:
    """项目根目录。

    开发模式：指向 src 的上一级（含 config.yaml）。
    PyInstaller --onefile 打包后：从 exe 所在目录逐级向上查找含
    config.yaml 的项目根（用户数据目录），找不到再回退到解压目录。
    """
    here = os.path.dirname(os.path.abspath(__file__))            # <root>/src (打包后为 _MEI/src)
    if getattr(sys, "frozen", False):
        # 从 exe 所在目录向上逐级查找，定位用户的数据根目录
        start = os.path.dirname(os.path.abspath(sys.argv[0]))
        cur = start
        while True:
            if os.path.exists(os.path.join(cur, "config.yaml")):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:  # 已到盘符根
                break
            cur = parent
        # exe 被单独复制、附近无 config.yaml：回退到解压目录
        return getattr(sys, "_MEIPASS", here)
    # 开发模式
    root = os.path.dirname(here)
    return root if os.path.exists(os.path.join(root, "config.yaml")) else here


# 项目根目录
BASE_DIR = _resolve_base_dir()
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# 统一 UA：所有浏览器/下载请求共用，避免多处重复且不一致
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.7827.55 Safari/537.36"
)

# 运行时确保各目录存在（downloads 等会被 .gitignore 忽略，但运行时需要）
for _d in ["cookies", "downloads", "transcripts", "output", "data", "logs"]:
    os.makedirs(os.path.join(BASE_DIR, _d), exist_ok=True)


def today_str(fmt: str = "%Y-%m-%d") -> str:
    return datetime.now().strftime(fmt)


def safe_filename(s: str, maxlen: int = 40) -> str:
    """把任意字符串转成安全的文件名片段。"""
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    return (s[:maxlen].strip() or "untitled")


def get_logger(name: str = "douyin_digest"):
    os.makedirs(LOGS_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(
                os.path.join(LOGS_DIR, f"{date.today().isoformat()}.log"),
                encoding="utf-8",
            ),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(name)
