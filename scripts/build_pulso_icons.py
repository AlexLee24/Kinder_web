"""Build app/blueprints/basic/static/js/kinder_icons.js from a PulsoIcon-Package checkout (ISC, CityPulso).

    python scripts/build_pulso_icons.py /path/to/PulsoIcon-Package

Copies the data of the icons Kinder uses (packages/core/src/icons/<key>.ts) and PulsoIcon's motion
recipes (packages/core/src/recipes.ts) into one plain script, with a small player on the Web Animations
API in place of PulsoIcon's Motion-based one. Icons rest as ordinary line icons and play their motion
when the button / link they sit in is hovered or focused; nothing moves under prefers-reduced-motion.

The page's existing inline SVG icons are recognised by their first shapes (SIGNATURES) and swapped,
so templates and scripts keep drawing the icons they always did.
"""
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / 'app' / 'blueprints' / 'basic' / 'static' / 'js' / 'kinder_icons.js'

# first shape (and the second when needed) of an icon already on the pages -> PulsoIcon key
SIGNATURES = {
    'path:m15 6-6 6 6 6': 'chevron-left', 'path:m15 18-6-6 6-6': 'chevron-left',
    'path:m9 6 6 6-6 6': 'chevron-right', 'path:m9 18 6-6-6-6': 'chevron-right',
    'polyline:18 15 12 9 6 15': 'chevron-up',
    'path:m12 4-8 4 8 4 8-4-8-4': 'layers',
    'path:M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7z': 'shield-check',
    'path:M10 14 21 3': 'send',
    'rect:4,5,16,16': 'calendar', 'rect:3,4,18,18': 'calendar',
    'path:M13 3v7h6l-8 11v-7H5z': 'zap', 'polygon:13 2 3 14 12 14 11 22 21 10 12 10 13 2': 'zap',
    'circle:9,7,4': 'users',
    'path:M3 21h18': 'building',
    'path:M10 5a2 2 0 1 1 4 0 7 7 0 0 1 4 6v3a4 4 0 0 0 2 3H4a4 4 0 0 0 2-3v-3a7 7 0 0 1 4-6': 'bell',
    'circle:12,8,4': 'user',
    'path:M12 3a12 12 0 0 0 8.5 3A12 12 0 0 1 12 21 12 12 0 0 1 3.5 6 12 12 0 0 0 12 3': 'shield',
    'path:M14 8V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2-2v-2': 'log-out',
    'path:M5 12H3l9-9 9 9h-2': 'house',
    'path:M21 12h-8a1 1 0 1 0-1 1v8a9 9 0 0 0 9-9': 'chart-pie',
    'path:M4 19h16': 'chart-line',
    'circle:12,12,1': 'target',
    'circle:12,12,9||path:M12 7v5l3 3': 'clock', 'circle:12,12,10||polyline:12 6 12 12 16 14': 'clock',
    'circle:12,12,9||path:M12 8h.01': 'info',
    'circle:12,12,9||path:M3.6 9h16.8M3.6 15h16.8': 'globe',
    'path:M7 10h3V7L6.5 3.5a6 6 0 0 1 8 8l6 6a2 2 0 0 1-3 3l-6-6a6 6 0 0 1-8-8z': 'wrench',
    'rect:4,4,6,6': 'layout-grid',
    'path:M6 21l6-5 6 5': 'telescope',
    'path:M3 20h18||path:m4 16 5-6 4 3 7-8': 'chart-line',
    'path:M3 20h18||path:M3 16h3l1.5-3 1.5 5 2-12 2 9 1.5-4 1.5 5H21': 'activity',
    'rect:3,3,7,9': 'layout-dashboard',
    'path:M12 6H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6': 'square-arrow-out-up-right',
    'path:M9 3h6': 'flask-conical',
    'path:m3 20 6.5-11 4 6.5 2.5-4L21 20z': 'mountain',
    'path:M12 3v12': 'download',
    'rect:5,8,14,11': 'bot',
    'path:M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z': 'moon',
    'path:M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z': 'cloud',
    'path:M18 6 6 18M6 6l12 12': 'x',
    'polyline:20 6 9 17 4 12': 'check',
    'polyline:16 18 22 12 16 6': 'code',
    'path:M15 3h6v6||path:M9 21H3v-6': 'maximize-2',
    'path:M15 3h6v6||path:M10 14 21 3': 'external-link',
    'rect:9,9,13,13': 'copy',
    'line:22,2,11,13': 'send',
    'polyline:3 6 5 6 21 6': 'trash',
    'polyline:22 12 18 12 15 21 9 3 6 12 2 12': 'activity',
    'path:M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z': 'eye',
    'path:M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0': 'eye',
    'line:12,5,12,19': 'plus',
    'path:M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7': 'square-pen',
    'path:m17 2 4 4-4 4': 'repeat',
    'polyline:23 4 23 10 17 10': 'refresh-cw',
    'path:M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83': 'loader',
    'circle:5,12,1': 'ellipsis',
    'rect:3,4,18,16': 'list',
    'rect:3,4,18,4': 'archive',
    'path:M14 3v4a1 1 0 0 0 1 1h4': 'file-text',
    'circle:8,15,4': 'key',
    'path:M12 5h3.5a5 5 0 0 1 0 10H10l-4.015 4.227a2.3 2.3 0 0 1-3.923-2.035l1.634-8.173A5 5 0 0 1 8.6 5z': 'gamepad',
    'path:M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4': 'log-in',
    'path:M12 21a9 9 0 0 1 0-18c4.97 0 9 3.582 9 8 0 1.06-.474 2.078-1.318 2.828S17.693 15 16.5 15H14a2 2 0 0 0-1 3.75A1.3 1.3 0 0 1 12 21': 'palette',
    'path:M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 0 0-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 0 0-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 0 0-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 0 0-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 0 0 1.066-2.573c-.94-1.543.826-3.31 2.37-2.37 1 .608 2.296.07 2.572-1.065z': 'settings',
}

# TypeScript annotations in recipes.ts, removed to leave plain JavaScript
_TS = [(r'const back: Transition', 'const back'),
       (r'\(p: RecipeParams, duration: number, extra: Transition = \{\}\): Transition =>', '(p, duration, extra = {}) =>'),
       (r'export const RECIPES: Record<RecipeName, Recipe> =', 'const RECIPES =')]


def recipes_js(src):
    text = (src / 'packages/core/src/recipes.ts').read_text()
    body = text[text.index('const back'):text.index('export const RECIPE_NAMES')]
    for a, b in _TS:
        body, n = re.subn(a, b, body)
        if not n:
            raise SystemExit(f'recipes.ts changed: {a!r} not found')
    return body


def icon_js(src, key):
    text = (src / f'packages/core/src/icons/{key}.ts').read_text()
    text = re.sub(r'^import .*\n', '', text, flags=re.M)
    text, n = re.subn(r'export const \w+ = icon\("[^"]*", "([^"]+)", \{', lambda m: f'I[{json.dumps(m.group(1))}] = ({{', text)
    if n != 1:
        raise SystemExit(f'{key}.ts: unexpected shape')
    return text.strip()


def main():
    src = Path(sys.argv[1]).expanduser()
    license_head = (src / 'LICENSE').read_text().split('---')[0].strip()
    keys = sorted(set(SIGNATURES.values()))
    icons = '\n'.join(icon_js(src, k) for k in keys)
    runtime = (Path(__file__).resolve().parent / 'kinder_icons_runtime.js').read_text()
    OUT.write_text(
        '/* Kinder icons: PulsoIcon line icons and motions (generated by scripts/build_pulso_icons.py, do not edit).\n'
        + '\n'.join(' * ' + line if line else ' *' for line in license_head.splitlines())
        + '\n * Some icon shapes come from Lucide (ISC), Tabler Icons (MIT) and Iconoir (MIT). */\n'
        + '(function () {\n"use strict";\nconst I = {};\n' + icons + '\n' + recipes_js(src)
        + '\nconst SIGNATURES = ' + json.dumps(SIGNATURES, indent=0) + ';\n' + runtime + '\n})();\n')
    print(f'{OUT}: {len(keys)} icons')


if __name__ == '__main__':
    main()
