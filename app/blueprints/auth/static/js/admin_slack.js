// Admin › Slack (/admin/slack): pick a ready-made message (or blank) and a channel, edit, see it as Slack shows it,
// send; Reuse in the history. Data: <script id="asTemplates"> / <script id="asChannels"> (admin/slack.py).
(function () {
    'use strict';
    const $ = (id) => document.getElementById(id);
    const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    if (!$('asPage')) return;
    let TEMPLATES = [], CHANNELS = [];
    try { TEMPLATES = JSON.parse($('asTemplates').textContent) || []; } catch (e) { /* none */ }
    try { CHANNELS = JSON.parse($('asChannels').textContent) || []; } catch (e) { /* none */ }
    const form = $('asForm');
    const text = $('asText');
    // The emoji the ready-made messages use, plus a few common ones; others show as :name:.
    const EMOJI = { rotating_light: '🚨', bell: '🔔', calendar: '📅', telescope: '🔭', white_check_mark: '✅', warning: '⚠️',
        wave: '👋', star: '⭐', iphone: '📱', tada: '🎉', pray: '🙏', eyes: '👀', sunrise: '🌅', crescent_moon: '🌙', satellite: '🛰️' };

    function toast(msg, type) {
        const n = document.createElement('div');
        n.className = 'notification notification-' + (type || 'info');
        n.textContent = msg;
        document.body.appendChild(n);
        setTimeout(() => { n.style.animation = 'notificationSlideOut 0.25s forwards'; setTimeout(() => n.remove(), 260); }, 3400);
    }
    document.querySelectorAll('time[data-local]').forEach((t) => {
        const d = new Date(t.getAttribute('datetime'));
        if (!isNaN(d)) t.textContent = d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    });

    const radio = (name) => form.querySelector('input[name="' + name + '"]:checked');
    function channelLabel() {
        const v = radio('channel') ? radio('channel').value : '';
        if (v === 'custom') return ($('asCustom').value.trim().toUpperCase() || 'channel id');
        const c = CHANNELS.find((x) => x.key === v);
        return c ? c.label : 'channel';
    }

    // Slack mrkdwn → HTML, enough for a preview: links, *bold*, _italic_, ~strike~, `code`, :emoji:, line breaks.
    function mrkdwn(s) {
        const links = [];
        s = s.replace(/<((?:https?:\/\/|mailto:)[^|>\s]+)(?:\|([^>]+))?>/g, (m, url, label) => {
            links.push('<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(label || url) + '</a>');
            return '\u0000' + (links.length - 1) + '\u0000';
        });
        let h = esc(s)
            .replace(/`([^`\n]+)`/g, '<code>$1</code>')
            .replace(/(^|[\s(])\*([^*\n]+)\*(?=$|[\s).,!?:;])/gm, '$1<b>$2</b>')
            .replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,!?:;])/gm, '$1<i>$2</i>')
            .replace(/(^|[\s(])~([^~\n]+)~(?=$|[\s).,!?:;])/gm, '$1<s>$2</s>')
            .replace(/:([a-z0-9_+-]+):/g, (m, name) => EMOJI[name] || m)
            .replace(/\n/g, '<br>');
        return h.replace(/\u0000(\d+)\u0000/g, (m, i) => links[+i]);
    }

    function preview() {
        const v = text.value;
        $('asTextN').textContent = v.length + '/3000';
        $('asPBody').innerHTML = v.trim() ? mrkdwn(v) : '<span class="kw-muted">Your message</span>';
        $('asPCh').textContent = '# ' + channelLabel();
        $('asEst').textContent = v.trim() ? 'Posts to # ' + channelLabel() + ' as the Kinder bot' : '—';
    }

    function setChannel(key, id) {
        let input = form.querySelector('input[name="channel"][value="' + key + '"]');
        if (!input || input.disabled) {
            const known = CHANNELS.find((c) => c.id && c.id === id);
            input = known ? form.querySelector('input[name="channel"][value="' + known.key + '"]') : null;
        }
        if (!input && id) {
            input = form.querySelector('input[name="channel"][value="custom"]');
            $('asCustom').value = id;
        }
        if (input && !input.disabled) input.checked = true;
        $('asCustomWrap').hidden = !(radio('channel') && radio('channel').value === 'custom');
    }

    form.querySelectorAll('input[name="template"]').forEach((r) => r.addEventListener('change', () => {
        if (text.value.trim() && text.dataset.from !== 'template' && !confirm('Replace what you have written?')) {
            form.querySelector('input[name="template"][value="' + (text.dataset.tpl || '') + '"]').checked = true;
            return;
        }
        const t = TEMPLATES.find((x) => x.key === r.value);
        text.value = t ? t.text : '';
        text.dataset.from = t ? 'template' : '';
        text.dataset.tpl = r.value;
        if (t) setChannel(t.channel);
        preview();
        text.focus();
    }));
    form.querySelectorAll('input[name="channel"]').forEach((r) => r.addEventListener('change', () => { setChannel(r.value); preview(); }));
    $('asCustom').addEventListener('input', preview);
    text.addEventListener('input', () => { text.dataset.from = 'edited'; preview(); });
    preview();

    form.addEventListener('submit', (ev) => {
        ev.preventDefault();
        const v = text.value.trim();
        const ch = radio('channel') ? radio('channel').value : '';
        if (!v) { toast('Write a message', 'error'); text.focus(); return; }
        if (!ch) { toast('Choose a channel', 'error'); return; }
        if (!confirm('Post this to # ' + channelLabel() + ' in Slack? Everyone in the channel sees it.')) return;
        const btn = $('asSend');
        btn.disabled = true;
        fetch('/admin/slack/send', {
            method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify({ text: v, channel: ch, channel_id: $('asCustom').value, template: text.dataset.tpl || '' }),
        }).then((r) => r.json().catch(() => ({}))).then((d) => {
            if (!d.ok) { btn.disabled = false; toast(d.error || 'Could not send', 'error'); return; }
            toast('Posted to # ' + d.channel, 'success');
            setTimeout(() => location.reload(), 900);
        }).catch(() => { btn.disabled = false; toast('Could not send', 'error'); });
    });

    document.querySelectorAll('[data-reuse]').forEach((b) => b.addEventListener('click', () => {
        const x = JSON.parse(b.getAttribute('data-reuse'));
        text.value = x.text || '';
        text.dataset.from = 'edited';
        form.querySelector('input[name="template"][value=""]').checked = true;
        text.dataset.tpl = '';
        setChannel(x.channel, x.channel_id);
        preview();
        form.scrollIntoView({ behavior: 'smooth', block: 'start' });
        text.focus({ preventScroll: true });
    }));
})();
