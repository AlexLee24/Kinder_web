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

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, tables):
        self.tables = tables

    def cursor(self, cursor_factory=None):
        return _Cur(self.tables)


def test_every_lot_label_shares_the_lot_rule(monkeypatch):
    tables = {'defaults': [{'source': 'LOT', 'permissions_set': 'groups', 'groups': [1]},
                           {'source': 'ZTF(alerce)', 'permissions_set': 'public', 'groups': []}]}
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
