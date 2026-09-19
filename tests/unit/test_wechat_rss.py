from src.knowledge.wechat_rss import WechatArticle, _write_article, parse_feed


def test_long_wechat_article_urls_keep_query_identity() -> None:
    payload = """<rss version="2.0"><channel>
      <item>
        <title>一</title>
        <link>https://mp.weixin.qq.com/s?__biz=abc&amp;mid=1&amp;idx=1&amp;sn=one&amp;scene=58</link>
        <pubDate>Thu, 10 Sep 2026 08:02:39 +0000</pubDate>
      </item>
      <item>
        <title>二</title>
        <link>https://mp.weixin.qq.com/s?__biz=abc&amp;mid=2&amp;idx=1&amp;sn=two&amp;scene=58</link>
        <pubDate>Wed, 09 Sep 2026 08:02:39 +0000</pubDate>
      </item>
    </channel></rss>
    """

    articles = parse_feed(payload)

    assert len(articles) == 2
    assert {article.title for article in articles} == {"一", "二"}
    assert len({article.article_id for article in articles}) == 2


def test_metadata_sync_does_not_erase_enriched_content(tmp_path) -> None:
    enriched = WechatArticle(
        article_id="a" * 24,
        title="文章",
        url="https://mp.weixin.qq.com/s/article",
        published_at="2026-09-10T00:00:00+00:00",
        summary="正文摘要足够长",
        content_html="<p>正文</p>",
    )
    metadata_only = WechatArticle(
        article_id=enriched.article_id,
        title=enriched.title,
        url=enriched.url,
        published_at=enriched.published_at,
        summary=enriched.title,
    )

    _write_article(enriched, tmp_path)
    _write_article(metadata_only, tmp_path)

    document = (tmp_path / ("a" * 24 + ".yaml")).read_text(encoding="utf-8")
    assert "正文摘要足够长" in document
    assert "<p>正文</p>" in document
