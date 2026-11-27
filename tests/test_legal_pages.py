"""/privacy and /terms: public, English or 繁體中文, linked from the login page."""
import pytest


@pytest.mark.parametrize('path', ['/privacy', '/terms'])
def test_public_in_both_languages(client, path):
    en = client.get(f'{path}?lang=en')
    zh = client.get(f'{path}?lang=zh')
    assert en.status_code == zh.status_code == 200
    assert b'Last updated' in en.data and '最後更新'.encode() in zh.data
    assert b'kinder [at] astro.ncu.edu.tw' in en.data


def test_language_follows_the_browser(client):
    assert '隱私權政策'.encode() in client.get('/privacy', headers={'Accept-Language': 'zh-TW,zh;q=0.9'}).data
    assert b'Privacy Policy' in client.get('/privacy', headers={'Accept-Language': 'en-US'}).data


def test_facts_fill_the_text(client, monkeypatch):
    from app.blueprints.basic import legal
    page = client.get('/privacy?lang=en').data
    assert b'kept for 3 days' in page and b'within 3 days' in page and b'legal-tbd' not in page
    assert b'legal-tbd' not in client.get('/terms?lang=zh').data
    monkeypatch.setitem(legal.FACTS, 'log_days', None)
    assert b'legal-tbd' in client.get('/privacy?lang=en').data


def test_login_links_to_both(client):
    page = client.get('/login').data
    assert b'href="/terms"' in page and b'href="/privacy"' in page
