// Admin › Permissions (/admin/permissions): actions (level + extra groups / people, saved on change),
// checking one account, extra groups per private page, default source visibility (Save all).
// Data: <script id="permData"> from admin/permissions.py.
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    if (!$('apmPage')) return;
    let D = {};
    try { D = JSON.parse($('permData').textContent) || {}; } catch (e) { /* empty */ }
    const PEOPLE = new Map((D.people || []).map((p) => [p.email.toLowerCase(), p]));
    const GROUPS = D.groups || [];
    const LEVELS = D.levels || [];
    const SHORT = { login: 'Signed in', user: 'Users', great_lab: 'GREAT Lab', admin: 'Admins' };

    function toast(msg, type) {
        document.querySelectorAll('.notification').forEach((n) => n.remove());
        const n = document.createElement('div');
        n.className = 'notification notification-' + (type || 'info');
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(() => n.remove(), 3200);
    }
    async function call(url, method, body) {
        const r = await fetch(url, { method: method || 'GET', credentials: 'same-origin',
            headers: body ? { 'Content-Type': 'application/json', Accept: 'application/json' } : { Accept: 'application/json' },
            body: body ? JSON.stringify(body) : undefined });
        let d = {};
        try { d = await r.json(); } catch (e) { /* not JSON */ }
        if (!r.ok || d.success === false) throw new Error(d.error || ('HTTP ' + r.status));
        return d;
    }
    const personName = (email) => { const p = PEOPLE.get(String(email).toLowerCase()); return p ? p.name : email; };
    const chip = (text, attrs, title) => `<span class="perm-tag"${title ? ` title="${esc(title)}"` : ''}>${esc(text)}<button type="button" class="kw-chip-x" ${attrs} aria-label="Remove ${esc(text)}">&times;</button></span>`;

    // ── Actions ──────────────────────────────────────────────────────────────
    const actions = D.actions || [];
    const openWho = new Set();

    function sameRule(a, b) {
        return a.level === b.level && !a.groups.length && !a.users.length && !b.groups.length && !b.users.length;
    }

    function renderAction(a) {
        const r = a.rule;
        const isDefault = sameRule(r, { level: a.default, groups: [], users: [] });
        const seg = LEVELS.map((l) => `<button type="button" class="kw-seg-item${r.level === l.key ? ' is-on' : ''}" data-level="${l.key}" aria-pressed="${r.level === l.key}" title="${esc(l.label)}">${esc(SHORT[l.key] || l.label)}</button>`).join('');
        const groupChips = r.groups.map((g) => chip(g, `data-rm-group="${esc(g)}"`)).join('');
        const userChips = r.users.map((u) => chip(personName(u), `data-rm-user="${esc(u)}"`, u)).join('');
        const groupOpts = GROUPS.filter((g) => !r.groups.includes(g)).map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
        const who = a.who || [];
        const whoList = openWho.has(a.key)
            ? `<ul class="apm-who-list">${who.map((e) => { const p = PEOPLE.get(e.toLowerCase()); return `<li>${esc(p ? p.name : e)} <small>${esc(p ? p.role : '')}</small></li>`; }).join('')}</ul>` : '';
        return `
        <article class="apm-action" data-action="${a.key}">
            <header class="apm-action-head">
                <div><span class="apm-area">${esc(a.area)}</span><h3>${esc(a.label)}</h3><p>${esc(a.desc)}</p></div>
                ${isDefault ? '<span class="apm-default">Default</span>' : `<button type="button" class="kw-btn kw-btn-sm kw-btn-ghost" data-reset>Reset to default</button>`}
            </header>
            <div class="apm-level-row"><div class="kw-seg apm-levels" role="group" aria-label="Who may ${esc(a.label.toLowerCase())}">${seg}</div>
                <small class="apm-level-note">${esc((LEVELS.find((l) => l.key === r.level) || {}).label || '')}${r.level === 'admin' ? '' : ' and admins'}</small></div>
            <div class="apm-extra">
                <div class="apm-extra-row"><span class="apm-extra-label">Also these groups</span>
                    <div class="perm-groups">${groupChips || '<span class="cell-muted">none</span>'}
                        ${groupOpts ? `<select class="kw-select kw-select-sm" data-add-group aria-label="Add a group"><option value="">+ group</option>${groupOpts}</select>` : ''}</div></div>
                <div class="apm-extra-row"><span class="apm-extra-label">Also these people</span>
                    <div class="perm-groups">${userChips || '<span class="cell-muted">none</span>'}
                        <form class="apm-add-user" data-add-user><input class="kw-input kw-input-sm" list="apmPeopleList" placeholder="+ name or email" aria-label="Add a person"><button type="submit" class="kw-btn kw-btn-sm">Add</button></form></div></div>
            </div>
            <footer class="apm-who"><button type="button" class="apm-who-btn" data-who aria-expanded="${openWho.has(a.key)}"><b>${who.length}</b> ${who.length === 1 ? 'person' : 'people'} can do this ${openWho.has(a.key) ? '▴' : '▾'}</button>${whoList}</footer>
        </article>`;
    }

    function renderActions() {
        $('apmActions').innerHTML = actions.map(renderAction).join('');
    }

    async function saveAction(a, next, reset) {
        const card = document.querySelector(`.apm-action[data-action="${a.key}"]`);
        if (card) card.classList.add('is-saving');
        try {
            const d = await call('/admin/permissions/action', 'POST', reset ? { action: a.key, reset: true } : Object.assign({ action: a.key }, next));
            a.rule = d.rule;
            a.who = d.who;
            toast(`${a.label}: saved · ${d.who.length} can do it`, 'success');
        } catch (e) {
            toast(`${a.label}: ${e.message}`, 'error');
        }
        renderActions();
    }

    $('apmActions').addEventListener('click', (ev) => {
        const card = ev.target.closest('.apm-action');
        if (!card) return;
        const a = actions.find((x) => x.key === card.dataset.action);
        const r = a.rule;
        const lv = ev.target.closest('[data-level]');
        if (lv && lv.dataset.level !== r.level) {
            saveAction(a, { level: lv.dataset.level, groups: r.groups, users: r.users });
            return;
        }
        const rg = ev.target.closest('[data-rm-group]');
        if (rg) { saveAction(a, { level: r.level, groups: r.groups.filter((g) => g !== rg.dataset.rmGroup), users: r.users }); return; }
        const ru = ev.target.closest('[data-rm-user]');
        if (ru) { saveAction(a, { level: r.level, groups: r.groups, users: r.users.filter((u) => u !== ru.dataset.rmUser) }); return; }
        if (ev.target.closest('[data-reset]')) {
            if (confirm(`Reset "${a.label}" to its default?`)) saveAction(a, null, true);
            return;
        }
        if (ev.target.closest('[data-who]')) {
            if (openWho.has(a.key)) openWho.delete(a.key); else openWho.add(a.key);
            renderActions();
        }
    });
    $('apmActions').addEventListener('change', (ev) => {
        const sel = ev.target.closest('[data-add-group]');
        if (!sel || !sel.value) return;
        const a = actions.find((x) => x.key === sel.closest('.apm-action').dataset.action);
        saveAction(a, { level: a.rule.level, groups: a.rule.groups.concat(sel.value), users: a.rule.users });
    });
    $('apmActions').addEventListener('submit', (ev) => {
        const form = ev.target.closest('[data-add-user]');
        if (!form) return;
        ev.preventDefault();
        const raw = form.querySelector('input').value.trim().toLowerCase();
        if (!raw) return;
        const match = PEOPLE.get(raw) || [...PEOPLE.values()].find((p) => p.name.toLowerCase() === raw || String(p.shown).toLowerCase() === raw);
        if (!match) { toast('No account called ' + raw, 'error'); return; }
        const a = actions.find((x) => x.key === form.closest('.apm-action').dataset.action);
        const email = match.email.toLowerCase();
        if (a.rule.users.includes(email)) { toast(match.name + ' is already on the list', 'info'); return; }
        saveAction(a, { level: a.rule.level, groups: a.rule.groups, users: a.rule.users.concat(email) });
    });

    // ── Check someone ────────────────────────────────────────────────────────
    async function check() {
        const raw = $('apmCheckInput').value.trim().toLowerCase();
        if (!raw) return;
        const p = PEOPLE.get(raw) || [...PEOPLE.values()].find((x) => x.name.toLowerCase() === raw || String(x.shown).toLowerCase() === raw);
        const out = $('apmCheckOut');
        if (!p) { out.innerHTML = `<p class="kw-empty">No account called ${esc(raw)}.</p>`; return; }
        out.innerHTML = '<p class="kw-muted">Checking…</p>';
        try {
            const d = await call('/admin/permissions/check?email=' + encodeURIComponent(p.email));
            const row = (x) => `<li class="${x.allowed ? 'is-yes' : 'is-no'}"><span class="apm-mark" aria-label="${x.allowed ? 'Allowed' : 'Not allowed'}">${x.allowed ? '✓' : '✕'}</span><span>${esc(x.label)}</span><small>${esc(x.why)}</small></li>`;
            out.innerHTML = `
                <div class="apm-check-who"><b>${esc(d.person.name)}</b> <span class="kw-muted">${esc(d.person.shown)}</span>
                    <span class="apm-role">${esc(d.is_admin ? 'admin' : d.person.role)}</span>
                    ${d.person.groups.length ? d.person.groups.map((g) => `<span class="perm-tag">${esc(g)}</span>`).join('') : '<span class="cell-muted">no groups</span>'}</div>
                <div class="apm-check-cols">
                    <div><h4>Actions</h4><ul class="apm-check-list">${d.actions.map(row).join('')}</ul></div>
                    <div><h4>Private pages</h4><ul class="apm-check-list">${d.pages.map(row).join('')}</ul></div>
                </div>`;
        } catch (e) {
            out.innerHTML = `<p class="kw-empty">${esc(e.message)}</p>`;
        }
    }
    $('apmCheckBtn').addEventListener('click', check);
    $('apmCheckInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); check(); } });
    $('apmCheckInput').addEventListener('change', check);

    // ── Private pages ────────────────────────────────────────────────────────
    let pagePerms = {}, pageLevels = {}, levelLabels = {};
    async function loadPages() {
        try {
            const d = await call('/api/admin/private_area/page_perms');
            pagePerms = d.perms || {};
            pageLevels = d.levels || {};
            levelLabels = d.level_labels || {member: 'GREAT Lab members', admin: 'Admins only'};
            renderPages();
        } catch (e) {
            $('apmPages').innerHTML = `<div class="kw-empty">Could not load: ${esc(e.message)}</div>`;
        }
    }
    function renderPages() {
        const choices = GROUPS.filter((g) => g !== 'GREAT_Lab');
        $('apmPages').innerHTML = (D.pages || []).map((pg) => {
            const extra = (pagePerms[pg.key] || []).filter((g) => g !== 'GREAT_Lab');
            const opts = choices.filter((g) => !extra.includes(g)).map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
            const lvl = pageLevels[pg.key] || 'member';
            const lvlOpts = Object.entries(levelLabels).map(([k, v]) => `<option value="${esc(k)}"${k === lvl ? ' selected' : ''}>${esc(v)}</option>`).join('');
            const base = lvl === 'admin'
                ? '<span class="perm-tag perm-locked" title="Only admins, plus the groups added here">Admins</span>'
                : '<span class="perm-tag perm-locked" title="Always has access">GREAT_Lab</span>';
            return `<div class="pperm-card" data-page="${esc(pg.key)}">
                <div class="pperm-title">${esc(pg.label)}</div>
                <select class="kw-select kw-select-sm" data-page-level aria-label="Who can open ${esc(pg.label)}">${lvlOpts}</select>
                <div class="pperm-tags">${base}${extra.map((g) => chip(g, `data-rm-page-group="${esc(g)}"`)).join('')}</div>
                ${opts ? `<div class="pperm-add"><select class="kw-select kw-select-sm" data-add-page-group aria-label="Add a group"><option value="">Add a group…</option>${opts}</select></div>` : ''}
            </div>`;
        }).join('');
    }
    $('apmPages').addEventListener('change', async (ev) => {
        const lv = ev.target.closest('[data-page-level]');
        if (lv) {
            const page = lv.closest('[data-page]').dataset.page;
            try {
                await call('/api/admin/private_area/page_level', 'POST', { page, level: lv.value });
                pageLevels[page] = lv.value;
                toast(`${page.replace(/_/g, ' ')}: ${levelLabels[lv.value]}`, 'success');
            } catch (e) { toast(e.message, 'error'); }
            renderPages();
            return;
        }
        const sel = ev.target.closest('[data-add-page-group]');
        if (!sel || !sel.value) return;
        const page = sel.closest('[data-page]').dataset.page;
        try {
            await call('/api/admin/private_area/page_perms', 'POST', { page, group_name: sel.value });
            pagePerms[page] = (pagePerms[page] || []).concat(sel.value);
            toast(`${sel.value} can now open ${page.replace(/_/g, ' ')}`, 'success');
        } catch (e) { toast(e.message, 'error'); }
        renderPages();
    });
    $('apmPages').addEventListener('click', async (ev) => {
        const rm = ev.target.closest('[data-rm-page-group]');
        if (!rm) return;
        const page = rm.closest('[data-page]').dataset.page;
        const g = rm.dataset.rmPageGroup;
        if (!confirm(`Remove ${g}'s access to ${page.replace(/_/g, ' ')}?`)) return;
        try {
            await call('/api/admin/private_area/page_perms', 'DELETE', { page, group_name: g });
            pagePerms[page] = (pagePerms[page] || []).filter((x) => x !== g);
            toast(`Removed ${g}`, 'success');
        } catch (e) { toast(e.message, 'error'); }
        renderPages();
    });

    // ── Source visibility ────────────────────────────────────────────────────
    let sources = [];      // {source_name, is_public, allowed_groups (null | [])}
    let allSources = [];
    let dirty = false;
    const visOf = (p) => p._vis || (p.is_public ? 'public' : p.allowed_groups === null ? 'logged_in' : p.allowed_groups.length ? 'groups' : 'blocked');
    const VIS = [['public', 'Everyone'], ['logged_in', 'Anyone signed in'], ['groups', 'Specific groups'], ['blocked', 'Nobody']];

    function setDirty(v) {
        dirty = v;
        $('apmSourcesSave').disabled = !v;
        $('apmSourcesStatus').textContent = v ? 'Unsaved changes' : '';
    }
    async function loadSources() {
        try {
            const [p, s] = await Promise.all([call('/admin/default-source-permissions'), call('/admin/sources/all')]);
            sources = p.permissions || [];
            allSources = s.sources || [];
            renderSources();
        } catch (e) {
            $('apmSourcesStatus').textContent = 'Could not load: ' + e.message;
        }
    }
    function renderSources() {
        const have = new Set(sources.map((p) => p.source_name));
        $('apmSourceAdd').innerHTML = '<option value="">Add a source…</option>' +
            allSources.filter((s) => !have.has(s)).map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
        $('apmSourcesEmpty').hidden = sources.length > 0;
        $('apmSourcesBody').innerHTML = sources.map((p, i) => {
            const v = visOf(p);
            const groups = (p.allowed_groups || []).map((g) => chip(g, `data-rm-src-group="${esc(g)}"`)).join('');
            const opts = GROUPS.filter((g) => !(p.allowed_groups || []).includes(g)).map((g) => `<option value="${esc(g)}">${esc(g)}</option>`).join('');
            return `<tr data-i="${i}">
                <td><span class="source-name">${esc(p.source_name)}</span></td>
                <td><select class="kw-select kw-select-sm perm-vis perm-vis-${v}" data-vis aria-label="Visibility">${VIS.map(([k, l]) => `<option value="${k}"${k === v ? ' selected' : ''}>${l}</option>`).join('')}</select></td>
                <td><div class="perm-groups">${v === 'groups' ? groups + (opts ? `<select class="kw-select kw-select-sm" data-add-src-group aria-label="Add a group"><option value="">+ group</option>${opts}</select>` : '') : '<span class="cell-muted">—</span>'}</div></td>
                <td class="td-right"><button type="button" class="kw-icon-btn is-danger" data-rm-src title="Remove rule" aria-label="Remove rule">&times;</button></td>
            </tr>`;
        }).join('');
    }
    $('apmSourceAdd').addEventListener('change', (ev) => {
        if (!ev.target.value) return;
        sources.push({ source_name: ev.target.value, is_public: false, allowed_groups: null });
        setDirty(true);
        renderSources();
    });
    $('apmSourcesBody').addEventListener('change', (ev) => {
        const tr = ev.target.closest('tr');
        if (!tr) return;
        const p = sources[+tr.dataset.i];
        if (ev.target.matches('[data-vis]')) {
            const v = ev.target.value;
            delete p._vis;
            if (v === 'public') { p.is_public = true; p.allowed_groups = null; }
            else if (v === 'logged_in') { p.is_public = false; p.allowed_groups = null; }
            else if (v === 'blocked') { p.is_public = false; p.allowed_groups = []; }
            else { p.is_public = false; if (!Array.isArray(p.allowed_groups)) p.allowed_groups = []; p._vis = 'groups'; }
        } else if (ev.target.matches('[data-add-src-group]') && ev.target.value) {
            p.allowed_groups = (p.allowed_groups || []).concat(ev.target.value);
            delete p._vis;
        } else return;
        setDirty(true);
        renderSources();
    });
    $('apmSourcesBody').addEventListener('click', (ev) => {
        const tr = ev.target.closest('tr');
        if (!tr) return;
        const p = sources[+tr.dataset.i];
        const rg = ev.target.closest('[data-rm-src-group]');
        if (rg) {
            p.allowed_groups = (p.allowed_groups || []).filter((g) => g !== rg.dataset.rmSrcGroup);
            if (!p.allowed_groups.length) p._vis = 'groups';
        } else if (ev.target.closest('[data-rm-src]')) {
            sources.splice(+tr.dataset.i, 1);
        } else return;
        setDirty(true);
        renderSources();
    });
    $('apmSourcesSave').addEventListener('click', async () => {
        const half = sources.find((p) => p._vis === 'groups' && !(p.allowed_groups || []).length);
        if (half && !confirm(`${half.source_name} is set to "Specific groups" with no group: nobody will see it. Save anyway?`)) return;
        $('apmSourcesSave').disabled = true;
        $('apmSourcesStatus').textContent = 'Saving…';
        try {
            await call('/admin/default-source-permissions', 'POST', { permissions: sources.map(({ _vis, ...p }) => p) });
            setDirty(false);
            $('apmSourcesStatus').textContent = 'Saved';
            toast('Source visibility saved', 'success');
        } catch (e) {
            setDirty(true);
            toast('Save failed: ' + e.message, 'error');
        }
    });
    window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });

    renderActions();
    loadPages();
    loadSources();
})();
