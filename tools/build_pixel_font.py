"""Rebuild the Chinese pixel-font subset served to the mini program.

    pip install fonttools brotli
    npm pack @vp-tw/cjk-web-fonts-fusion-pixel-font && tar xzf vp-tw-cjk-web-fonts-fusion-pixel-font-*.tgz
    python tools/build_pixel_font.py package/dist/12px/proportional/zh_hans

Merges the per-Unicode-block woff2 subsets, then keeps every character used in the
project (mini program, backend, knowledge base) plus the 3,755 GB2312 level-1 hanzi.
"""
from __future__ import annotations

import glob
import sys
import tempfile
from pathlib import Path

from fontTools import subset
from fontTools.merge import Merger
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "backend/app/static/fonts"


def project_chars() -> str:
    chars: set[str] = set()
    for pattern in ("miniprogram/**/*.*", "backend/app/**/*.py", "llm_wiki/**/*.md"):
        for f in ROOT.glob(pattern):
            try:
                chars |= set(f.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, IsADirectoryError):
                pass
    for hi in range(0xB0, 0xD8):  # GB2312 level-1
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                pass
    chars |= {chr(c) for c in range(0x20, 0x7F)}
    chars |= set("，。、；：？！“”‘’（）《》【】…—·￥¥％＋－×÷＝～→←↑↓★☆●○■□▲△◆◇✓✔✕✗♥°℃")
    return "".join(sorted(c for c in chars if c.isprintable()))


def main(src_dir: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for i, f in enumerate(sorted(glob.glob(f"{src_dir}/*.woff2"))):
            t = TTFont(f)
            t.flavor = None
            p = f"{tmp}/part{i:03d}.ttf"
            t.save(p)
            parts.append(p)
        merged = f"{tmp}/merged.ttf"
        Merger().merge(parts).save(merged)
        text = project_chars()
        for flavor in ("woff2", "woff"):
            opts = subset.Options()
            opts.flavor = flavor
            opts.layout_features = ["*"]
            opts.name_IDs = ["*"]
            font = subset.load_font(merged, opts)
            s = subset.Subsetter(opts)
            s.populate(text=text)
            s.subset(font)
            out = OUT / f"fusion-pixel-12px-sc.{flavor}"
            subset.save_font(font, str(out), opts)
            print(out, out.stat().st_size, "bytes,", len(text), "chars")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "package/dist/12px/proportional/zh_hans")
