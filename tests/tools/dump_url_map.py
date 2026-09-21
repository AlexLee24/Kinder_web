"""Dump the Flask URL map for before/after comparisons of a refactor.

    .venv/bin/python tests/tools/dump_url_map.py /tmp/url_map

Writes ``<prefix>_sorted.txt`` (rule, methods, endpoint), ``<prefix>_order.txt``
(registration order — matters when two blueprints register the same rule),
``<prefix>_blueprints.txt`` and ``<prefix>_views.txt`` (endpoint -> view function).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault('DETECT_IN_WEB', '1')


def main(prefix):
    from app import create_app
    app = create_app(start_jobs=False)

    def methods(r):
        return ','.join(sorted(m for m in r.methods if m not in ('HEAD', 'OPTIONS')))

    rules = sorted(app.url_map.iter_rules(), key=lambda r: (r.rule, r.endpoint))
    with open(prefix + '_sorted.txt', 'w') as f:
        for r in rules:
            f.write(f"{r.rule:70s} {methods(r):20s} {r.endpoint}\n")
    with open(prefix + '_order.txt', 'w') as f:
        for r in app.url_map.iter_rules():
            f.write(f"{r.rule}\t{methods(r)}\t{r.endpoint}\n")
    with open(prefix + '_blueprints.txt', 'w') as f:
        for name, bp in app.blueprints.items():
            f.write(f"{name}\ttemplate_folder={bp.template_folder}\tstatic_folder={bp.static_folder}\turl_prefix={bp.url_prefix}\n")
    with open(prefix + '_views.txt', 'w') as f:
        for ep, fn in sorted(app.view_functions.items()):
            f.write(f"{ep}\t{fn.__module__}.{fn.__name__}\n")
    print(f"rules={len(rules)} blueprints={len(app.blueprints)} -> {prefix}_*")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'url_map')
    os._exit(0)  # don't wait for background threads
