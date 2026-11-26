// ── player (Web Animations API; PulsoIcon's own uses Motion) ── appended by scripts/build_pulso_icons.py
const NS = 'http://www.w3.org/2000/svg';
const TRIGGER = 'button, a, label, summary, [role="button"], [role="menuitem"], [role="tab"], [role="link"], [onclick], [data-icon-trigger]';
const TRANSFORMS = ['x', 'y', 'rotate', 'scale', 'scaleX', 'scaleY', 'skewY'];
const EASE = { easeInOut: 'cubic-bezier(0.42, 0, 0.58, 1)', easeOut: 'cubic-bezier(0, 0, 0.58, 1)' };
const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const ease = e => Array.isArray(e) ? `cubic-bezier(${e.join(',')})` : (EASE[e] || 'ease-in-out');
const attrName = n => n.replace(/[A-Z]/g, c => '-' + c.toLowerCase());

function motionOf(m) {
    return RECIPES[m.r]({ d: m.d || 0, x: m.x || 0, y: m.y || 0, a: m.a || 0 });
}

// one icon as an <svg> element, the shapes that move carrying their motion
function render(key, from) {
    const data = I[key];
    const svg = document.createElementNS(NS, 'svg');
    const own = from || {};
    const set = (el, k, v) => el.setAttribute(k, v);
    [['xmlns', NS], ['viewBox', '0 0 24 24'], ['fill', 'none'], ['stroke', 'currentColor'], ['stroke-width', own.strokeWidth || '2'],
     ['stroke-linecap', 'round'], ['stroke-linejoin', 'round'], ['aria-hidden', 'true'], ['focusable', 'false']].forEach(([k, v]) => set(svg, k, v));
    svg.setAttribute('class', ('kicon kicon-' + key + ' ' + (own.className || '')).trim());
    if (own.width) set(svg, 'width', own.width);
    if (own.height) set(svg, 'height', own.height);
    if (own.style) set(svg, 'style', own.style);
    svg.style.overflow = 'visible';
    const moving = [];
    for (const [tag, attrs, m] of data.nodes) {
        let el = document.createElementNS(NS, tag);
        for (const [k, v] of Object.entries(attrs)) if (k !== 'transform' || !m) set(el, attrName(k), v);
        let node = el;
        if (m) {
            const motion = motionOf(m);
            const o = m.o || [12, 12];
            if (motion.normal.pathLength !== undefined) {
                set(el, 'pathLength', '1');
                set(el, 'stroke-dasharray', `${motion.normal.pathLength} 1`);
                set(el, 'stroke-dashoffset', `${-(motion.normal.pathOffset || 0) || 0}`);
            }
            el.style.transformBox = 'view-box';
            el.style.transformOrigin = `${o[0]}px ${o[1]}px`;
            moving.push([el, motion.animate]);
            if (attrs.transform) { node = document.createElementNS(NS, 'g'); set(node, 'transform', attrs.transform); node.appendChild(el); }
        }
        svg.appendChild(node);
    }
    if (data.svg) {
        const motion = motionOf(data.svg);
        const o = data.svg.o || [12, 12];
        svg.style.transformOrigin = `${o[0] / 24 * 100}% ${o[1] / 24 * 100}%`;
        moving.push([svg, motion.animate, true]);
    }
    svg._kmoving = moving;
    return svg;
}

const asList = v => Array.isArray(v) ? v : [v];
function sample(list, n) {                // a keyframe list stretched to n entries
    if (list.length === n) return list;
    return Array.from({ length: n }, (_, i) => list[Math.round(i * (list.length - 1) / Math.max(1, n - 1))]);
}
function keyframes(values, unit) {
    const props = Object.keys(values);
    const n = Math.max(...props.map(p => asList(values[p]).length));
    const v = {};
    props.forEach(p => { v[p] = sample(asList(values[p]), n); });
    return Array.from({ length: n }, (_, i) => {
        const f = {};
        const t = TRANSFORMS.filter(p => p in v);
        if (t.length) {
            const g = p => v[p] ? v[p][i] : (p.startsWith('scale') ? 1 : 0);
            f.transform = `translate(${g('x') * unit}px, ${g('y') * unit}px) rotate(${g('rotate')}deg) scale(${g('scale')}) `
                + `scaleX(${g('scaleX')}) scaleY(${g('scaleY')}) skewY(${g('skewY')}deg)`;
        }
        if (v.opacity) f.opacity = v.opacity[i];
        if (v.pathLength) f.strokeDasharray = `${v.pathLength[i]} 1`;
        if (v.pathOffset) f.strokeDashoffset = `${-v.pathOffset[i]}`;
        return f;
    });
}
function run(el, values, t, unit) {
    if (!Object.keys(values).length) return null;
    const frames = keyframes(values, unit);
    if (t.times && t.times.length === frames.length) frames.forEach((f, i) => { f.offset = t.times[i]; });
    return el.animate(frames, { duration: (t.duration || 0.5) * 1000, delay: (t.delay || 0) * 1000, easing: ease(t.ease || 'easeInOut'), fill: 'none' });
}
function play(svg) {
    if (svg._kplaying || reduced()) return;
    const anims = [];
    const unit = svg.getBoundingClientRect().width / 24 || 1;
    for (const [el, state, isRoot] of svg._kmoving) {
        const { transition = {}, ...values } = state;
        const { opacity: ot, ...timing } = transition;
        if (ot && values.opacity !== undefined) {
            const { opacity, ...rest } = values;
            anims.push(run(el, rest, timing, isRoot ? unit : 1), run(el, { opacity }, ot, 1));
        } else {
            anims.push(run(el, values, timing, isRoot ? unit : 1));
        }
    }
    const live = anims.filter(Boolean);
    if (!live.length) return;
    svg._kplaying = true;
    Promise.all(live.map(a => a.finished.catch(() => {}))).then(() => { svg._kplaying = false; });
}

// the shapes an inline icon starts with, as SIGNATURES keys them
function shapeSig(e) {
    if (!e) return '';
    const t = e.tagName.toLowerCase();
    const a = n => e.getAttribute(n) || '';
    const v = { path: () => a('d'), polyline: () => a('points'), polygon: () => a('points'),
        line: () => [a('x1'), a('y1'), a('x2'), a('y2')].join(','), rect: () => [a('x'), a('y'), a('width'), a('height')].join(','),
        circle: () => [a('cx'), a('cy'), a('r')].join(',') }[t];
    return v ? t + ':' + v().replace(/\s+/g, ' ').trim() : '';
}
function keyFor(svg) {
    const a = shapeSig(svg.children[0]);
    return SIGNATURES[a + '||' + shapeSig(svg.children[1])] || SIGNATURES[a] || null;
}

const bound = new WeakSet();
function bind(svg) {
    const host = svg.parentElement && svg.parentElement.closest(TRIGGER) || svg;
    if (bound.has(host)) { (host._kicons || (host._kicons = [])).push(svg); return; }
    bound.add(host);
    host._kicons = [svg];
    const go = () => host._kicons.forEach(s => s.isConnected && play(s));
    host.addEventListener('pointerenter', go);
    host.addEventListener('focusin', go);
}

function upgrade(root) {
    (root || document).querySelectorAll('svg:not(.kicon)').forEach(old => {
        if (old.closest('.js-plotly-plot, .pa-vis-svg, [data-no-kicon]') || old.classList.contains('pa-vis-svg')) return;
        const key = keyFor(old);
        if (!key || !I[key]) return;
        const svg = render(key, { width: old.getAttribute('width'), height: old.getAttribute('height'), className: old.getAttribute('class'),
            style: old.getAttribute('style'), strokeWidth: old.getAttribute('stroke-width') });
        old.replaceWith(svg);
        bind(svg);
    });
}

let pending = false;
function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; upgrade(document); });
}
function start() {
    upgrade(document);
    new MutationObserver(muts => { if (muts.some(m => m.addedNodes.length)) schedule(); })
        .observe(document.body, { childList: true, subtree: true });
}
window.KinderIcons = { render, upgrade, play };
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
