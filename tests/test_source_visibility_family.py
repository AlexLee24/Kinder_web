"""Default source visibility: a rule covers every source whose name holds it as a whole word (LOT → LOT_(w/o_TS),
LOT(AUTO), LOT(AUTO, w/o TS)); an exact rule wins, else the longest."""
import contextlib

import pytest

from app.db import auth


@pytest.mark.parametrize('source, covered', [
    ('LOT', True), ('LOT_(w/o_TS)', True), ('LOT(AUTO)', True), ('LOT(AUTO, w/o TS)', True), ('Lulin LOT', True),
    ('SLOT', False), ('LOTUS', False), ('SLT(AUTO)', False), ('', False), ('LOT(TNS)', False),
])
def test_rule_covers_whole_words(source, covered):
    assert auth.rule_covers('LOT', source) is covered


def test_the_exact_rule_then_the_longest_decides():
    rules = ['SLT', 'SLT(AUTO)', 'ZTF(alerce)']
    assert auth.matching_rule('SLT_(w/o_TS)', rules) == 'SLT'
    assert auth.matching_rule('SLT(AUTO, w/o TS)', rules) == 'SLT'
    assert auth.matching_rule('SLT(AUTO)', rules) == 'SLT(AUTO)'
    assert auth.matching_rule('ZTF(TNS)', rules) is None
    assert auth.matching_rule('LOT', rules) is None


class _Cur:
    def __init__(self, tables):
        self.tables, self.rows = tables, []

    def execute(self, sql, args=None):
        if 'object_source_permissions' in sql:
            self.rows = []
        elif 'default_permissions' in sql:
            self.rows = self.tables['defaults']
        elif 'auth.groups' in sql:
            self.rows = [{'name': 'GREAT_Lab', 'group_id': 1}]
        elif 'auth.users' in sql:
            roles = self.tables.get('roles', {}).get(args[0].lower())
            self.rows = [] if roles is None else [{'roles': roles}]

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Conn:
    def __init__(self, tables):
        self.tables = tables

    def cursor(self, cursor_factory=None):
        return _Cur(self.tables)


def test_every_lot_label_shares_the_lot_rule(monkeypatch):
    tables = {'defaults': [{'source': 'LOT', 'permissions_set': 'groups', 'groups': [1]},
                           {'source': 'ZTF(alerce)', 'permissions_set': 'public', 'groups': []}],
              'roles': {'a@b': 1, 'c@d': 1}}
    monkeypatch.setattr(auth, 'get_db_connection', lambda: contextlib.nullcontext(_Conn(tables)))
    srcs = ['LOT', 'LOT_(w/o_TS)', 'LOT(AUTO)', 'LOT(AUTO, w/o TS)', 'ZTF(alerce)']
    member = auth.filter_by_source_permissions('X', 'phot', srcs, user_email='a@b', user_groups=['GREAT_Lab'])
    assert member == srcs
    other = auth.filter_by_source_permissions('X', 'phot', srcs, user_email='c@d', user_groups=['Students'])
    assert other == ['ZTF(alerce)']                     # no LOT label slips through under its own name
    anon = auth.filter_by_source_permissions('X', 'phot', srcs)
    assert anon == ['ZTF(alerce)']


def test_tns_reports_keep_their_public_default(monkeypatch):
    """'ATLAS' (GREAT_Lab only) must not hide ATLAS(TNS), which is public by the system default."""
    tables = {'defaults': [{'source': 'ATLAS', 'permissions_set': 'groups', 'groups': [1]}]}
    monkeypatch.setattr(auth, 'get_db_connection', lambda: contextlib.nullcontext(_Conn(tables)))
    srcs = ['ATLAS', 'ATLAS(TNS)', 'ATLAS (TNS)']
    assert auth.filter_by_source_permissions('X', 'phot', srcs) == ['ATLAS(TNS)', 'ATLAS (TNS)']


@pytest.mark.parametrize('source, public', [
    ('ZTF (TNS)', True), ('(TNS)', True), ('ZTF(alerce)', True), ('LSST(alerce)', True), ('ALeRCE (TNS)', True),
    ('ZTF', False), ('ZTF(lasair)', False), ('ATLAS', False), ('SLT', False),
])
def test_tns_and_alerce_are_public_data(source, public):
    assert auth.is_public_data_source(source) is public
    assert auth._system_default_for_source(source) == ('public' if public else 'login')


def test_a_family_rule_does_not_cover_alerce():
    assert auth.rule_covers('ZTF', 'ZTF(lasair)')
    assert not auth.rule_covers('ZTF', 'ZTF(alerce)')
    assert not auth.rule_covers('LSST', 'LSST(alerce)')
    assert auth.rule_covers('ZTF(alerce)', 'ZTF(alerce)')


def test_without_a_rule_only_signed_in_users_see_a_source(monkeypatch):
    """No rule: TNS / ALeRCE for everyone; the rest for user accounts (roles >= 1), not guests or visitors."""
    tables = {'defaults': [], 'roles': {'user@x': 1, 'guest@x': 0, 'admin@x': 50}}
    monkeypatch.setattr(auth, 'get_db_connection', lambda: contextlib.nullcontext(_Conn(tables)))
    srcs = ['ZTF (TNS)', 'ZTF(alerce)', 'LSST(alerce)', 'ZTF(lasair)', 'PS', 'Unknown']
    public = ['ZTF (TNS)', 'ZTF(alerce)', 'LSST(alerce)']
    assert auth.filter_by_source_permissions('X', 'phot', srcs) == public
    assert auth.filter_by_source_permissions('X', 'phot', srcs, user_email='guest@x') == public
    assert auth.filter_by_source_permissions('X', 'phot', srcs, user_email='nobody@x') == public   # no account row
    assert auth.filter_by_source_permissions('X', 'phot', srcs, user_email='USER@x') == srcs
    assert auth.filter_by_source_permissions('X', 'phot', srcs, user_email='admin@x') == srcs
    assert auth.filter_by_source_permissions('X', 'phot', srcs, user_email='guest@x', user_roles=1) == srcs


def test_login_rules_and_overrides_also_exclude_guests(monkeypatch):
    tables = {'defaults': [{'source': 'PS', 'permissions_set': 'login', 'groups': []}], 'roles': {'g@x': 0, 'u@x': 1}}
    monkeypatch.setattr(auth, 'get_db_connection', lambda: contextlib.nullcontext(_Conn(tables)))
    assert auth.filter_by_source_permissions('X', 'phot', ['PS'], user_email='g@x') == []
    assert auth.filter_by_source_permissions('X', 'phot', ['PS'], user_email='u@x') == ['PS']
