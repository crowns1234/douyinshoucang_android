"""LLM 摘要与分类。

- mock：基于关键词做简单摘要与分类，无需任何 API，用于演示。
- openai：调用 OpenAI 兼容接口，输出结构化 JSON（summary + category）。

最终返回按分类分组的数据：{category: [item, ...]}。
"""
import json

from .utils import get_logger

logger = get_logger()

# mock 模式下的简单分类关键词
CATEGORY_KEYWORDS = {
    "美食": ["美食", "吃", "菜", "料理", "餐厅", "烘焙", "早餐", "做饭"],
    "科技": ["科技", "手机", "AI", "代码", "电脑", "数码", "软件", "修复", "工具"],
    "搞笑": ["搞笑", "笑", "段子", "喜剧", "打工人"],
    "生活": ["生活", "日常", "vlog", "旅行", "穿搭"],
    "知识": ["知识", "科普", "学习", "教程", "历史", "心理"],
}


# mock 分类优先级：先匹配更具体的类别，避免“吃饭”误判为“美食”
_PRIORITY = ["搞笑", "科技", "美食", "生活", "知识"]


def _classify_mock(text: str, categories: list) -> str:
    for cat in _PRIORITY:
        if cat in categories and any(k in text for k in CATEGORY_KEYWORDS.get(cat, [])):
            return cat
    for cat in categories:
        if cat not in _PRIORITY and any(k in text for k in CATEGORY_KEYWORDS.get(cat, [])):
            return cat
    return "其他"


def _summarize_mock(video: dict, categories: list):
    # 标题由文档/消息单独展示，这里只给“内容摘要”，避免重复
    transcript = (video.get("transcript") or "").strip().replace("\n", " ")
    snippet = transcript[:60] + ("…" if len(transcript) > 60 else "")
    summary = snippet or (video.get("desc") or video.get("title") or "")
    text = video.get("title", "") + video.get("desc", "") + transcript
    cat = _classify_mock(text, categories)
    return summary, cat


def _summarize_openai(video: dict, cfg: dict, categories: list):
    from openai import OpenAI

    client = OpenAI(
        api_key=cfg["summary"]["api_key"], base_url=cfg["summary"].get("base_url")
    )
    category_instruction = (
        f"从以下候选分类中选择一个最合适的：{categories}"
        if categories else
        "自行判断一个最合适的分类标签（用简洁的中文词，如'科技科普''美食探店''生活技巧'等）"
    )
    prompt = (
        "请仔细阅读以下抖音收藏视频的标题、描述和语音转写内容，完成两项任务：\n"
        f"1. {category_instruction}。\n"
        "2. 对视频内容做详细总结。\n\n"
        "总结要求：\n"
        "- 分条列出，用编号（1. 2. 3. …）区分每个要点\n"
        "- 每条要具体，包含视频中提到的关键信息、方法、观点或操作步骤\n"
        "- 不要只复述标题，要从转写内容中提取实质性信息\n"
        "- 如果转写较长，提取最重要的 3-8 条要点即可\n"
        "- 每条 1-2 句话，保留原意，不要过度概括\n\n"
        f"标题：{video.get('title', '')}\n"
        f"描述：{video.get('desc', '')}\n"
        f"视频转写：{video.get('transcript', '')}\n\n"
        '只返回 JSON，格式：{"summary": "1. 要点一\\n2. 要点二\\n...", "category": "分类"}'
    )
    resp = client.chat.completions.create(
        model=cfg["summary"]["model"],
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    data = json.loads(resp.choices[0].message.content)
    return data.get("summary", ""), data.get("category", "其他")


def summarize(cfg: dict, items: list) -> dict:
    categories = cfg["summary"]["categories"]
    provider = cfg["summary"]["provider"]
    grouped = {}
    for v in items:
        if provider == "mock":
            s, c = _summarize_mock(v, categories)
        else:
            s, c = _summarize_openai(v, cfg, categories)
        v = dict(v)
        v["summary"] = s
        v["category"] = c
        grouped.setdefault(c, []).append(v)
    return grouped
