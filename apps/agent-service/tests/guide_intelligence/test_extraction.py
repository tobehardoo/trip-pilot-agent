from datetime import UTC, datetime, timedelta

from trip_agent.guide_intelligence.extraction import GenericGuideExtractor


def test_extracts_readable_article_and_typed_fresh_facts() -> None:
    fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    html = """
    <html>
      <head><title>广州周末攻略</title></head>
      <body>
        <nav>首页 登录 下载 App</nav>
        <article>
          <h1>广州周末攻略</h1>
          <p>陈家祠值得预留两小时，建筑细节非常漂亮。</p>
          <p>午饭推荐去荔银肠粉，人均 35 元，早上排队约 20 分钟。</p>
          <p>从公园前乘地铁 1 号线到陈家祠站，建议提前预约门票。</p>
          <script>window.secret = "ignore me"</script>
        </article>
      </body>
    </html>
    """.encode()

    result = GenericGuideExtractor().extract(
        content=html,
        content_type="text/html; charset=utf-8",
        fetched_at=fetched_at,
    )

    assert result.title == "广州周末攻略"
    assert "首页 登录" not in result.content
    assert "window.secret" not in result.content
    assert {fact.category for fact in result.facts} >= {
        "ATTRACTION",
        "DINING",
        "TRANSPORT",
        "COST",
        "QUEUE",
        "RESERVATION",
    }
    dynamic = next(fact for fact in result.facts if fact.category == "QUEUE")
    assert dynamic.observed_at == fetched_at
    assert dynamic.expires_at == fetched_at + timedelta(days=7)
    assert dynamic.evidence in result.content


def test_deduplicates_sentences_and_allows_an_article_without_supported_facts() -> None:
    fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    html = """
    <html><head><meta property="og:title" content="旅行随笔"></head>
    <body><main>
      <p>今天的风很舒服。</p>
      <p>今天的风很舒服。</p>
    </main></body></html>
    """.encode()

    result = GenericGuideExtractor().extract(
        content=html,
        content_type="text/html",
        fetched_at=fetched_at,
    )

    assert result.title == "旅行随笔"
    assert result.content == "今天的风很舒服。"
    assert result.facts == ()


def test_caps_article_and_fact_expansion() -> None:
    fetched_at = datetime(2026, 7, 23, 8, 0, tzinfo=UTC)
    paragraphs = "".join(
        f"<p>Attraction tip {index}: take the metro and reserve a ticket "
        f"{'x' * 1_200}</p>"
        for index in range(700)
    )
    html = f"<html><body><article>{paragraphs}</article></body></html>".encode()

    result = GenericGuideExtractor().extract(
        content=html,
        content_type="text/html",
        fetched_at=fetched_at,
    )

    assert len(result.content) <= 100_000
    assert result.content.count("\n") < 500
    assert len(result.facts) <= 100
    assert all(len(fact.statement) <= 1_000 for fact in result.facts)
    assert all(len(fact.evidence) <= 1_000 for fact in result.facts)
