from pathlib import Path

from app.site_rules import default_site_rule_registry


def write_archive(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "archive.html"
    path.write_text(body, encoding="utf-8")
    return path


def test_wechat_verification_page_requires_manual_action(tmp_path: Path) -> None:
    path = write_archive(
        tmp_path,
        """
        <html><head><title>Weixin Official Accounts Platform</title></head><body>
        <h2>环境异常</h2>
        <p>当前环境异常，完成验证后即可继续访问。</p>
        <a id="js_verify">去验证</a>
        <iframe id="tcaptcha_iframe_dy"></iframe>
        </body></html>
        """,
    )

    result = default_site_rule_registry().inspect(
        "https://mp.weixin.qq.com/s/example",
        path,
    )

    assert result is not None
    assert result.error is None
    assert [action.code for action in result.manual_actions] == [
        "wechat_article_verification"
    ]
    assert result.manual_actions[0].resume == "retry_page"


def test_wechat_article_platform_title_is_not_enough(tmp_path: Path) -> None:
    path = write_archive(
        tmp_path,
        """
        <html><head><title>Weixin Official Accounts Platform</title></head><body>
        <article id="js_article"><h1>正常文章</h1><p>文章正文</p></article>
        </body></html>
        """,
    )

    result = default_site_rule_registry().inspect(
        "https://mp.weixin.qq.com/s/example",
        path,
    )

    assert result is None


def test_wechat_verification_text_does_not_affect_other_sites(tmp_path: Path) -> None:
    path = write_archive(
        tmp_path,
        "<h2>环境异常</h2><p>完成验证后即可继续访问</p><a id='js_verify'>去验证</a>",
    )

    result = default_site_rule_registry().inspect("https://example.com/article", path)

    assert result is None


def test_wechat_unavailable_page_is_terminal_error(tmp_path: Path) -> None:
    path = write_archive(tmp_path, "<html><body>此内容暂时无法查看</body></html>")

    result = default_site_rule_registry().inspect(
        "https://mp.weixin.qq.com/s/example",
        path,
    )

    assert result is not None
    assert result.manual_actions == ()
    assert result.error == "微信文章内容暂时无法查看。"


def test_wechat_rule_ignores_signals_after_inspection_limit(tmp_path: Path) -> None:
    path = write_archive(
        tmp_path,
        ("x" * (2 * 1024 * 1024))
        + "<h2>环境异常</h2><p>完成验证后即可继续访问</p><a id='js_verify'>去验证</a>",
    )

    result = default_site_rule_registry().inspect(
        "https://mp.weixin.qq.com/s/example",
        path,
    )

    assert result is None


def test_normal_wechat_article_is_not_rewritten(tmp_path: Path) -> None:
    path = write_archive(
        tmp_path,
        """
        <html><head><title>微信文章</title></head><body>
        <main class="rich_media_area_primary"><div class="rich_media_area_primary_inner">
        <h1 class="rich_media_title">标题</h1>
        <div id="js_content" class="rich_media_content">
        <img class="js_img_placeholder wx_img_placeholder other"
             data-src="https://mmbiz.qpic.cn/example/640?wx_fmt=png"
             src="data:image/svg+xml,placeholder">
        </div></div></main></body></html>
        """,
    )
    original = path.read_text(encoding="utf-8")

    default_site_rule_registry().prepare_archive(
        "https://mp.weixin.qq.com/s/example",
        path,
    )

    assert path.read_text(encoding="utf-8") == original


def test_wechat_preparation_does_not_change_other_sites(tmp_path: Path) -> None:
    path = write_archive(
        tmp_path,
        '<html><body><div id="js_content">unchanged</div></body></html>',
    )
    original = path.read_text(encoding="utf-8")

    default_site_rule_registry().prepare_archive("https://example.com/article", path)

    assert path.read_text(encoding="utf-8") == original
