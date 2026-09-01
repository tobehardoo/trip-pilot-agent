from datetime import UTC, datetime

import pytest

from trip_agent.acquisition import GuangzhouGovernmentArticleExtractor


def _html(
    body: str,
    *,
    title: str | None = "岭南文化漫步",
    published_at: str | None = "2026-02-12 15:40:59",
    source: str | None = "广州文旅",
    container: str = '<div id="zoomcon" class="content_article">{body}</div>',
) -> bytes:
    metadata = []
    if title is not None:
        metadata.append(f'<meta name="ArticleTitle" content="{title}">')
    if published_at is not None:
        metadata.append(f'<meta name="PubDate" content="{published_at}">')
    if source is not None:
        metadata.append(f'<meta name="ContentSource" content="{source}">')
    return (
        "<!doctype html><html><head>"
        + "".join(metadata)
        + "</head><body><nav>首页 政务 服务</nav>"
        + container.format(body=body)
        + "<footer>广州市人民政府 版权所有</footer></body></html>"
    ).encode()


def _long_paragraph(subject: str = "岭南建筑") -> str:
    return (
        f"{subject}串联起街巷、园林与传统工艺，适合以步行方式观察城市空间。"
        "资料同时介绍历史沿革、保护范围与文化价值，为行程主题选择提供稳定背景。"
    )


def test_extractor_reads_official_metadata_and_filters_page_noise() -> None:
    content = _html(
        "<script>window.bad = true</script>"
        "<p><strong>街区概览</strong></p>"
        f"<p>{_long_paragraph()}</p>"
        f"<p>{_long_paragraph()}</p>"
        "<div class=share>分享到</div>"
        "<p>相关附件</p><p>不应进入正文的附件说明</p>"
    )

    result = GuangzhouGovernmentArticleExtractor().extract(
        content=content,
        content_type="text/html; charset=utf-8",
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "EXTRACTED"
    assert result.article.title == "岭南文化漫步"
    assert result.article.published_at == datetime(2026, 2, 12, 7, 40, 59, tzinfo=UTC)
    assert result.article.content_source == "广州文旅"
    assert result.article.content.count(_long_paragraph()) == 1
    assert "街区概览" in result.article.content
    assert "首页" not in result.article.content
    assert "window.bad" not in result.article.content
    assert "分享到" not in result.article.content
    assert "附件说明" not in result.article.content
    assert result.article.parser_version == "gz-government-bs4-v1"
    assert result.issues == ()


def test_extractor_supports_content_article_and_date_only_metadata() -> None:
    content = _html(
        f"<p>{_long_paragraph('民间工艺')}</p>",
        published_at="2024-04-25",
        container='<section class="content_article">{body}</section>',
    )

    result = GuangzhouGovernmentArticleExtractor().extract(
        content=content,
        content_type="application/xhtml+xml",
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "EXTRACTED"
    assert result.article.published_at == datetime(2024, 4, 24, 16, tzinfo=UTC)
    assert "民间工艺" in result.article.content


def test_extractor_keeps_missing_publication_time_as_a_warning() -> None:
    result = GuangzhouGovernmentArticleExtractor().extract(
        content=_html(f"<p>{_long_paragraph()}</p>", published_at=None),
        content_type="text/html",
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "EXTRACTED"
    assert result.article.published_at is None
    assert [issue.code for issue in result.issues] == ["PUBLISHED_AT_MISSING"]
    assert result.issues[0].severity == "WARNING"


@pytest.mark.parametrize(
    "dynamic_fact",
    [
        "门票免费，具体政策以现场公告为准。",
        "开馆时间为每日九时，每周一闭馆。",
        "参观需要提前实名预约购票。",
        "可乘坐地铁一号线到达。",
        "附近设有多条公交车站。",
        "交通方式可能根据现场管制调整。",
    ],
)
def test_extractor_marks_common_dynamic_facts_without_rejecting_the_article(
    dynamic_fact: str,
) -> None:
    result = GuangzhouGovernmentArticleExtractor().extract(
        content=_html(f"<p>{_long_paragraph()}</p><p>{dynamic_fact}</p>"),
        content_type="text/html",
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "EXTRACTED"
    assert [issue.code for issue in result.issues] == ["DYNAMIC_FACTS_PRESENT"]
    assert result.issues[0].severity == "WARNING"


@pytest.mark.parametrize(
    ("content", "content_type", "expected_code"),
    [
        (
            _html(f"<p>{_long_paragraph()}</p>"),
            "application/pdf",
            "UNSUPPORTED_CONTENT_TYPE",
        ),
        (
            _html(f"<p>{_long_paragraph()}</p>"),
            "text/html; charset=not-a-real-codec",
            "UNSUPPORTED_CONTENT_ENCODING",
        ),
        (
            b"<html><head><meta name='ArticleTitle' content='missing'></head><body></body></html>",
            "text/html",
            "ARTICLE_CONTAINER_MISSING",
        ),
        (
            _html("<p>内容过短。</p>"),
            "text/html",
            "CONTENT_TOO_SHORT",
        ),
        (
            _html(f"<p>{_long_paragraph()}</p>", title=None),
            "text/html",
            "TITLE_MISSING",
        ),
        (
            _html(f"<p>{_long_paragraph()}</p>", published_at="2027-01-01"),
            "text/html",
            "PUBLISHED_AT_IN_FUTURE",
        ),
    ],
)
def test_extractor_rejects_invalid_candidates(
    content: bytes,
    content_type: str,
    expected_code: str,
) -> None:
    result = GuangzhouGovernmentArticleExtractor().extract(
        content=content,
        content_type=content_type,
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "REJECTED"
    assert expected_code in [issue.code for issue in result.issues]
    assert all(issue.severity == "ERROR" for issue in result.issues)


@pytest.mark.parametrize("meta_charset", ["", '<meta charset="utf-8">'])
def test_extractor_uses_http_declared_encoding_over_html_metadata(
    meta_charset: str,
) -> None:
    document = (
        f"<html><head>{meta_charset}"
        '<meta name="ArticleTitle" content="西关旧城">'
        '<meta name="PubDate" content="2026-02-12T15:40:00+08:00">'
        '</head><body><main><p>'
        + _long_paragraph("西关街巷")
        + "</p></main></body></html>"
    ).encode("gb18030")

    result = GuangzhouGovernmentArticleExtractor().extract(
        content=document,
        content_type="text/html; charset=gb18030",
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "EXTRACTED"
    assert result.article.title == "西关旧城"
    assert result.article.published_at == datetime(2026, 2, 12, 7, 40, tzinfo=UTC)
    assert "西关街巷" in result.article.content


def test_extractor_truncates_attachment_tail_in_generic_container_fallback() -> None:
    body = (
        f"<div>{_long_paragraph()}</div>"
        "<span>相关附件</span><span>附件下载和相关新闻不属于正文。</span>"
    )
    result = GuangzhouGovernmentArticleExtractor().extract(
        content=_html(body, container="<main>{body}</main>"),
        content_type="text/html",
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "EXTRACTED"
    assert "岭南建筑" in result.article.content
    assert "附件下载" not in result.article.content


def test_extractor_preserves_tail_words_used_inside_legitimate_prose() -> None:
    body = (
        f"<p>{_long_paragraph()}本次展览的相关内容包括岭南木雕与陶塑。</p>"
        "<p>后续段落继续说明展陈历史与公共教育价值。</p>"
    )
    result = GuangzhouGovernmentArticleExtractor().extract(
        content=_html(body),
        content_type="text/html",
        fetched_at=datetime(2026, 2, 13, tzinfo=UTC),
    )

    assert result.status == "EXTRACTED"
    assert "相关内容包括岭南木雕" in result.article.content
    assert "后续段落继续说明" in result.article.content
