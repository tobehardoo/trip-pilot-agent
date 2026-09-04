"""按平台实现的链接解析器子模块。"""

from . import bilibili, douyin, kuaishou, weibo, xhs, zhihu

__all__ = ["xhs", "douyin", "weibo", "zhihu", "kuaishou", "bilibili"]