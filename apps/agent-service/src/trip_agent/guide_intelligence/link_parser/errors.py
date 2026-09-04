"""链接解析的稳定错误码与面向用户的提示。

所有失败都以结构化 ``LinkParseError`` 抛出，前端据此给出明确可操作的提示，
避免把裸异常或平台 HTML 堆给用户（需求：附报错提醒提醒部分不支持的类型）。
"""

from __future__ import annotations


class LinkParseError(Exception):
    """一次分享链接解析的失败，携带稳定 code 与中文用户提示。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    @classmethod
    def unsupported_platform(cls, platform_hint: str) -> LinkParseError:
        return cls(
            "UNSUPPORTED_PLATFORM",
            f"「{platform_hint}」平台链接暂不支持自动提取正文，"
            "请打开内容复制文字，改用「粘贴正文」导入。",
        )

    @classmethod
    def expired(cls) -> LinkParseError:
        return cls(
            "LINK_EXPIRED",
            "该分享链接无效或内容已删除，请确认链接有效后重试。",
        )

    @classmethod
    def needs_auth(cls) -> LinkParseError:
        return cls(
            "NEEDS_AUTH",
            "该内容需要登录或分享登录态才能查看，暂无法自动提取，请改用「粘贴正文」。",
        )

    @classmethod
    def media_only(cls) -> LinkParseError:
        return cls(
            "MEDIA_ONLY",
            "该链接为纯视频/图集，没有可用的文字正文，请复制简介文字改用「粘贴正文」。",
        )

    @classmethod
    def network(cls, detail: str = "") -> LinkParseError:
        return cls(
            "NETWORK_UNAVAILABLE",
            f"抓取链接失败（网络异常{'：' + detail if detail else ''}），"
            "请稍后重试或改用「粘贴正文」。",
        )

    @classmethod
    def parse_failed(cls, detail: str = "") -> LinkParseError:
        return cls(
            "PARSE_FAILED",
            f"未能从该链接解析出可用正文{'（' + detail + '）' if detail else ''}，"
            "请改用「粘贴正文」导入。",
        )