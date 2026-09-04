"""平台标识与统一解析结果模型。"""

from __future__ import annotations

from dataclasses import dataclass, field

# 统一的中文平台展示名（用于报错/展示）。
PLATFORM_LABELS: dict[str, str] = {
    "xhs": "小红书",
    "douyin": "抖音",
    "weibo": "微博",
    "zhihu": "知乎",
    "kuaishou": "快手",
    "shipinhao": "视频号",
    "bilibili": "B站",
    "bili_article": "B站专栏",
    # 已知但暂不支持正文提取的平台（用于明确报错）
    "acfun": "acfun",
    "allcpp": "allcpp",
    "instagram": "Instagram",
    "iwara": "Iwara",
    "ncm": "网易云音乐",
    "nga": "NGA",
    "pixiv": "Pixiv",
    "qzone": "QQ空间",
    "tiktok": "TikTok",
    "twitter": "Twitter",
    "youtube": "YouTube",
}


@dataclass(frozen=True, slots=True)
class ParsedLink:
    """一次成功解析的正文结果（供知识库/情报导入使用）。"""

    platform: str
    title: str
    desc: str
    author: str = ""
    url: str = ""
    # 解析过程的附加说明（如是否回退、数据完整度），不落到正文。
    notes: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """用于入库的正文：标题与描述拼装，标题不重复。"""
        parts: list[str] = []
        if self.title and not self.desc.startswith(self.title):
            parts.append(self.title)
        if self.desc:
            parts.append(self.desc)
        return "\n".join(parts).strip()

    @property
    def platform_label(self) -> str:
        return PLATFORM_LABELS.get(self.platform, self.platform)