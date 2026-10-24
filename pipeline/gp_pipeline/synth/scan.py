"""Degrade a text-layer PDF into an image-only "scan" (SPEC §4.1).

pdftoppm at ``dpi`` (grayscale) -> rotate ``rotation`` degrees (white fill) -> scanner-style paper
whitening (pixels lighter than ``paper`` become pure white, as flatbed drivers do) -> JPEG at
``quality`` (progressive, optimized) -> PDF. The JPEG bytes are embedded unchanged (DCTDecode
pass-through via reportlab), so the quality setting is exactly what lands in the file. The output
has no text layer: extraction must go through OCR. Deterministic for fixed inputs.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image
from reportlab import rl_config
from reportlab.pdfgen import canvas

PDFTOPPM = shutil.which("pdftoppm") or "/opt/homebrew/bin/pdftoppm"

DEFAULT = {"dpi": 150, "rotation": 0.7, "quality": 60}
NOISE = {"dpi": 100, "rotation": 2.0, "quality": 35}


def rasterize(pdf: Path, dpi: int) -> list[Image.Image]:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([PDFTOPPM, "-r", str(dpi), "-gray", "-png", str(pdf), f"{td}/pg"], check=True)
        pages = sorted(Path(td).glob("pg*.png"))
        return [Image.open(p).copy() for p in pages]


def degrade(pdf: Path, out: Path, dpi: int = 150, rotation: float = 0.7, quality: int = 60,
            paper: int = 215) -> Path:
    rl_config.useA85 = 0  # embed the JPEG bytes as-is (ASCII85 would add 25%)
    c = canvas.Canvas(str(out), invariant=1)
    td = tempfile.TemporaryDirectory()
    for i, im in enumerate(rasterize(pdf, dpi)):
        im = im.convert("L").rotate(-rotation, resample=Image.BICUBIC, expand=False, fillcolor=255)
        im = im.point(lambda v: 255 if v > paper else v)
        jpg = Path(td.name) / f"p{i}.jpg"
        im.save(jpg, "JPEG", quality=quality, optimize=True, progressive=True)
        w_pt, h_pt = im.width * 72 / dpi, im.height * 72 / dpi
        c.setPageSize((w_pt, h_pt))
        c.drawImage(str(jpg), 0, 0, w_pt, h_pt)  # a JPEG path is embedded with DCTDecode, no re-encode
        c.showPage()
    c.save()
    td.cleanup()
    return out
