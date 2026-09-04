"""URL → 平台识别。

覆盖插件支持的分享形态（协议识), 识别结果分两类：
- ``EXTRACTABLE``：已实现正文提取的文本平台（小红书/抖音/微博/知乎/快手/视频号/B站）。
- ``KNOWN_UNSUPPORTED``：已知但暂不支持正文提取的平台（纯音视频/需登录），给明确报错。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 已实现正文提取的文本平台 → 提取器名
EXTRACTABLE: dict[str, str] = {
    "xhs": "xhs",
    "douyin": "douyin",
    "weibo": "weibo",
    "zhihu": "zhihu",
    "kuaishou": "kuaishou",
    "bilibili": "bilibili",
}

# 已知但暂不支持正文提取的平台（纯音视频 / 需登录 / 海外）
KNOWN_UNSUPPORTED: dict[str, str] = {
    "shipinhao": "微信视频号",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "twitter": "Twitter",
    "pixiv": "Pixiv",
    "iwara": "Iwara",
    "qzone": "QQ空间",
    "ncm": "网易云音乐",
    "acfun": "acfun",
    "allcpp": "allcpp",
    "nga": "NGA",
}


@dataclass(frozen=True, slots=True)
class Detection:
    platform: str
    extractor: str | None  # EXTRACTABLE 时为提取器名；否则 None
    label: str
    hint: str | None  # 对 KNOWN_UNSUPPORTED 给出追加说明

    @property
    def is_supported(self) -> bool:
        return self.extractor is not None


_DOMAIN_MAP: tuple[tuple[tuple[str, ...], str], ...] = (
    (("xiaohongshu.com", "xhslink.com", "xhslink.cn"), "xhs"),
    (("douyin.com", "iesdouyin.com", "v.douyin.com"), "douyin"),
    (("weibo.com", "m.weibo.cn", "weibo.cn", "m.weibo.com"), "weibo"),
    (("zhihu.com", "zhuanlan.zhihu.com"), "zhihu"),
    (("kuaishou.com", "chenzhongtech.com", "v.kuaishou.com"), "kuaishou"),
    (("weixin.qq.com", "channels.weixin.qq.com"), "shipinhao"),
    (("bilibili.com", "b23.tv"), "bilibili"),
    (("youtube.com", "youtu.be"), "youtube"),
    (("tiktok.com",), "tiktok"),
    (("instagram.com", "instagr.am"), "instagram"),
    (("twitter.com", "x.com", "t.co"), "twitter"),
    (("pixiv.net",), "pixiv"),
    (("iwara.tv",), "iwara"),
    (("qzone.qq.com",), "qzone"),
    (("music.163.com",), "ncm"),
    (("acfun.cn",), "acfun"),
    (("acg.heiyu.xyz",), "allcpp"),
    (("ngabbs.com",), "nga"),
)

_KUAISHOU_V = re.compile(r"v\.kuaishou\.com/", re.I)


def detect(url: str) -> Detection | None:
    lowered = (url or "").strip().lower()
    if not lowered:
        return None
    # 快手短链先于泛域名判断（v.kuaishou.com 与 kuaishou.com 同命中）
    if _KUAISHOU_V.search(lowered):
        return _build("kuaishou", url)
    for domains, platform in _DOMAIN_MAP:
        if any(domain in lowered for domain in domains):
            return _build(platform, url)
    return None


def _build(platform: str, url: str) -> Detection:
    if platform in EXTRACTABLE:
        return Detection(platform, EXTRACTABLE[platform], EXTRACTABLE[platform], None)
    if platform in KNOWN_UNSUPPORTED:
        hint = _unsupported_hint(platform)
        return Detection(platform, None, KNOWN_UNSUPPORTED[platform], hint)
    return Detection(platform, None, platform, None)


def _unsupported_hint(platform: str) -> str:
    if platform in {"youtube", "tiktok", "instagram", "twitter"}:
        return "该平台主要为视频/图集，且海外访问受限，暂不自动提取正文。"
    if platform == "qzone":
        return "QQ空间分享需登录态，暂不自动提取。"
    if platform in {"pixiv", "iwara", "ncm", "acfun", "allcpp", "nga"}:
        return "该链接为原创绘画/音频/社区内容，无旅行攻略正文，暂不支持。"
    return ""