#!/usr/bin/env python3
"""Build a local HTML contact sheet from e2e/screenshots/<target>/<viewport>/<page>.jpg.

usage: python3 scripts/contact-sheet.py <out.html>
Images are copied next to the HTML (<out>-files/...) and referenced relatively, so the sheet is a plain
local folder: open it in any browser, nothing is uploaded anywhere.
"""
import html, json, shutil, sys
from pathlib import Path

src = Path("e2e/screenshots")
out = Path(sys.argv[1]).expanduser()
assets = out.with_name(out.stem + "-files")
if assets.exists():
    shutil.rmtree(assets)
VPS = ["iphone", "android", "tablet", "desktop"]
VP_LABEL = {"iphone": "iPhone 390", "android": "Android 360", "tablet": "Tablet 768", "desktop": "Desktop 1440"}
TARGET_LABEL = {"mock": "Mock backend (MSW, in the browser)", "python": "Python stack (gp-python)", "go": "Go stack (gp-go)"}

targets = [t for t in ["python", "go", "mock"] if (src / t).is_dir()]
sections, count = [], 0
for t in targets:
    pages = sorted({p.stem for vp in VPS for p in (src / t / vp).glob("*.jpg")})
    rows = []
    for name in pages:
        cells = []
        for vp in VPS:
            f = src / t / vp / f"{name}.jpg"
            if not f.exists():
                cells.append('<td class="none">—</td>')
                continue
            dest = assets / t / vp / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dest)
            count += 1
            meta = {}
            mf = f.with_suffix(".jpg.json")
            if mf.exists():
                meta = json.loads(mf.read_text())
            rel = dest.relative_to(out.parent).as_posix()
            cells.append(f'<td><a href="{html.escape(rel)}" target="_blank" title="{html.escape(meta.get("url", ""))}"><img loading="lazy" src="{html.escape(rel)}" alt="{html.escape(name)} at {VP_LABEL[vp]}"></a></td>')
        label = name.split("-", 1)[-1].replace("-", " ")
        rows.append(f'<tr><th scope="row">{html.escape(label)}</th>{"".join(cells)}</tr>')
    sections.append(f'<section><h2>{html.escape(TARGET_LABEL.get(t, t))}</h2><div class="scroll"><table><thead><tr><th></th>{"".join(f"<th>{VP_LABEL[v]}</th>" for v in VPS)}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')

doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Groundplan screens</title><style>
:root{{color-scheme:light dark;--bg:#f3f4f6;--card:#fff;--ink:#1b2430;--mute:#59626f;--line:#e2e5e9}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1116;--card:#151a21;--ink:#e2e6eb;--mute:#9ba4af;--line:#262d36}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1500px;margin:0 auto;padding:24px 16px 64px}} h1{{font-size:22px;margin:0 0 4px}} p{{color:var(--mute);margin:0 0 20px}}
section{{background:var(--card);border-radius:10px;box-shadow:0 0 0 1px var(--line);padding:16px;margin:0 0 24px}} h2{{font-size:16px;margin:0 0 12px}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse}} th{{font-weight:600;text-align:left;padding:6px 10px;color:var(--mute);font-size:12px;white-space:nowrap;vertical-align:top}}
td{{padding:6px 10px;vertical-align:top}} img{{display:block;width:180px;max-height:420px;object-fit:cover;object-position:top;border-radius:6px;box-shadow:0 0 0 1px var(--line)}}
td.none{{color:var(--mute)}} tbody th{{text-transform:capitalize;font-size:13px;color:var(--ink);min-width:140px}}
</style></head><body><main><h1>Groundplan: every screen, every viewport</h1>
<p>{count} full-page screenshots taken by the Playwright suite. Click any image for the full page. Local file, not published.</p>
{"".join(sections)}</main></body></html>"""
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(doc)
print(f"{out} ({count} images in {assets})")
