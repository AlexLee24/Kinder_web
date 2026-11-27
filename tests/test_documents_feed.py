"""Lab Info › Docs as an EAU-style feed: metadata per document, drafts for admins only, save / pin / delete."""
import json

import pytest

from app.blueprints.private_area import documents, helpers


@pytest.fixture
def tdir(tmp_path, monkeypatch):
    for mod in (documents, helpers):
        monkeypatch.setattr(mod, 'tutorials_dir', str(tmp_path))
    monkeypatch.setattr(helpers, 'tutorials_env_path', str(tmp_path / '.env'))
    (tmp_path / 'old_note.md').write_text('# Old note\n\nFirst paragraph **bold**.\n', encoding='utf-8')
    return tmp_path


def test_info_falls_back_to_heading_and_first_paragraph(tdir):
    d = documents.document_info('old_note.md', {})
    assert d['title'] == 'Old note' and d['excerpt'] == 'First paragraph bold.'
    assert d['category'] == 'guide' and not d['draft'] and d['minutes'] == 1


def test_save_creates_lists_and_hides_drafts(client_factory, tdir):
    admin = client_factory('admin')
    r = admin.post('/api/documents/save', json={'title': 'Observing at Lulin', 'summary': 'S', 'category': 'observing',
                                                'content': '## A\ntext', 'draft': True, 'cover': 'javascript:x'})
    assert r.status_code == 200
    name = r.get_json()['filename']
    assert name == 'observing_at_lulin.md'
    meta = json.loads((tdir / 'metadata.json').read_text())
    assert meta['docs'][name]['cover'] == '' and meta['docs'][name]['draft'] is True
    assert b'Observing at Lulin' not in client_factory('member').get('/documents').data
    assert client_factory('member').get(f'/documents/{name}').status_code == 404
    assert b'Observing at Lulin' in admin.get('/documents?drafts=1').data
    admin.post('/api/documents/save', json={'filename': name, 'title': 'Observing at Lulin', 'content': 'x',
                                           'category': 'observing', 'pinned': True})
    page = client_factory('member').get('/documents').data.decode()
    assert page.index('Observing at Lulin') < page.index('Old note')      # pinned first


def test_chinese_title_gets_a_safe_filename(client_factory, tdir):
    r = client_factory('admin').post('/api/documents/save', json={'title': '望遠鏡操作', 'content': 'x'})
    assert r.get_json()['filename'].startswith('doc_')


def test_only_admins_write(client_factory, tdir):
    member = client_factory('member')
    assert member.post('/api/documents/save', json={'title': 'x'}).status_code == 403
    assert member.post('/api/documents/old_note.md/delete').status_code == 403
    assert member.get('/documents/new').status_code == 403


def test_delete_moves_to_trash(client_factory, tdir):
    assert client_factory('admin').post('/api/documents/old_note.md/delete').status_code == 200
    assert not (tdir / 'old_note.md').exists()
    assert any(p.name.endswith('_old_note.md') for p in (tdir / '.trash').iterdir())
