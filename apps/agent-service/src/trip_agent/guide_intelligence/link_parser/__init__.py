"""跨平台分享链接解析器（抓标题/正文，供知识库与情报导入复用）。

仅依赖 httpx + 标准库；技巧移植自 astrbot_plugin_parser（MIT）。
"""

from .errors import LinkParseError
from .models import ParsedLink
from .service import looks_supported, parse_link

__all__ = ["LinkParseError", "ParsedLink", "parse_link", "looks_supported"]