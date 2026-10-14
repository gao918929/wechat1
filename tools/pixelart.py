"""Pixel-art pipeline: text grids → crisp SVG icons / sprite sheets for the mini program.

Sources live in ``art/pixel/*.txt``. One file per asset::

    # name: tomato            (output file name, defaults to the file stem)
    # kind: icon | sprite     (sprites are animated sheets: frames laid out left→right)
    # variants: off           (optional: also emit <name>-off.svg in greyscale, for inactive states)
    ................
    ......GG........
    ...
    ---                       (frame separator, sprites only)
    ................

Every character is one art pixel, coloured from the shared PALETTE below ('.' = transparent).
All frames of an asset must have the same width/height.

    python tools/pixelart.py                 # build every asset into miniprogram/assets/px/
    python tools/pixelart.py --sheet out.png # also render a labelled contact sheet for review
    python tools/pixelart.py --check         # validate only (unknown colours, ragged rows)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "art/pixel"
OUT = ROOT / "miniprogram/assets/px"

# One shared, limited palette keeps every icon and sprite in the same visual family.
PALETTE = {
    "K": "#2b2340",  # ink (outlines)
    "k": "#4a3f6b",  # soft ink
    "W": "#ffffff",  # white highlight
    "w": "#fffaf0",  # paper
    "q": "#e2d3b1",  # paper shade
    "g": "#4cb963",  # leaf green
    "G": "#2e7d46",  # dark green
    "l": "#a6e88a",  # light green
    "r": "#e8553e",  # tomato red
    "R": "#a8322a",  # dark red
    "p": "#ffb3a1",  # pink / blush
    "o": "#f59a2c",  # carrot orange
    "O": "#b8641b",  # dark orange
    "y": "#f8d24b",  # butter yellow
    "Y": "#c79a1e",  # dark yellow
    "b": "#4fa8e0",  # sky blue
    "B": "#2d6fa8",  # dark blue
    "c": "#b5e1ff",  # ice blue
    "v": "#8e6ad8",  # grape purple
    "V": "#5b3fa0",  # dark purple
    "m": "#f27ba6",  # pink
    "n": "#9b6a3c",  # brown
    "N": "#5e3d22",  # dark brown
    "s": "#ffd2a8",  # skin
    "e": "#c9c3d6",  # light grey
    "E": "#8a8199",  # grey
}
TRANSPARENT = "."


def grey(hex_color: str) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    v = round(0.299 * r + 0.587 * g + 0.114 * b)
    v = round(150 + (v / 255) * 90)  # compress into a soft grey ramp
    return f"#{v:02x}{v:02x}{v:02x}"


def parse(path: Path) -> dict:
    meta = {"name": path.stem, "kind": "icon", "variants": ""}
    frames: list[list[str]] = [[]]
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.startswith("#"):
            if ":" in line:
                k, v = line[1:].split(":", 1)
                meta[k.strip()] = v.strip()
            continue
        if not line:
            continue
        if line.strip() == "---":
            frames.append([])
            continue
        frames[-1].append(line)
    frames = [f for f in frames if f]
    if not frames:
        raise ValueError(f"{path.name}: no pixel rows")
    h, w = len(frames[0]), len(frames[0][0])
    for i, f in enumerate(frames):
        if len(f) != h or any(len(row) != w for row in f):
            raise ValueError(f"{path.name}: frame {i} is not {w}x{h} (rows must all be the same length)")
        for row in f:
            bad = {c for c in row if c != TRANSPARENT and c not in PALETTE}
            if bad:
                raise ValueError(f"{path.name}: unknown colour code(s) {sorted(bad)}")
    meta.update(frames=frames, w=w, h=h)
    return meta


def to_svg(asset: dict, recolor=None) -> str:
    w, h, frames = asset["w"], asset["h"], asset["frames"]
    rects = []
    for fi, frame in enumerate(frames):
        ox = fi * w
        for y, row in enumerate(frame):
            x = 0
            while x < w:  # merge horizontal runs of one colour into a single rect
                c = row[x]
                if c == TRANSPARENT:
                    x += 1
                    continue
                run = 1
                while x + run < w and row[x + run] == c:
                    run += 1
                color = PALETTE[c] if recolor is None else recolor(PALETTE[c])
                rects.append(f'<rect x="{ox + x}" y="{y}" width="{run}" height="1" fill="{color}"/>')
                x += run
    total_w = w * len(frames)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w * 4}" height="{h * 4}" '
            f'viewBox="0 0 {total_w} {h}" shape-rendering="crispEdges">' + "".join(rects) + "</svg>\n")


def contact_sheet(assets: list[dict], out: Path, scale: int = 6) -> None:
    from PIL import Image, ImageDraw

    cell_w = max(a["w"] * len(a["frames"]) for a in assets) * scale + 24
    cell_h = max(a["h"] for a in assets) * scale + 40
    cols = max(1, min(6, 1800 // cell_w))
    rows = (len(assets) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell_w, rows * cell_h), "#f6efdd")
    d = ImageDraw.Draw(img)
    for i, a in enumerate(assets):
        x0, y0 = (i % cols) * cell_w + 12, (i // cols) * cell_h + 8
        for fi, frame in enumerate(a["frames"]):
            for y, row in enumerate(frame):
                for x, c in enumerate(row):
                    if c != TRANSPARENT:
                        px = x0 + (fi * a["w"] + x) * scale
                        d.rectangle([px, y0 + y * scale, px + scale - 1, y0 + (y + 1) * scale - 1], fill=PALETTE[c])
        d.text((x0, y0 + a["h"] * scale + 6), f'{a["name"]} ({a["w"]}x{a["h"]}x{len(a["frames"])})', fill="#2b2340")
    img.save(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", help="write a labelled PNG contact sheet")
    ap.add_argument("--check", action="store_true", help="validate sources only")
    ap.add_argument("names", nargs="*", help="only these assets (file stems)")
    args = ap.parse_args()
    files = sorted(SRC.glob("*.txt"))
    if args.names:
        files = [f for f in files if f.stem in set(args.names)]
    assets, errors = [], []
    for f in files:
        try:
            assets.append(parse(f))
        except ValueError as exc:
            errors.append(str(exc))
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    if errors or args.check:
        print(f"{len(assets)} ok, {len(errors)} errors")
        return 1 if errors else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for a in assets:
        (OUT / f'{a["name"]}.svg').write_text(to_svg(a), encoding="utf-8")
        if "off" in a.get("variants", ""):
            (OUT / f'{a["name"]}-off.svg').write_text(to_svg(a, grey), encoding="utf-8")
    if args.sheet:
        contact_sheet(assets, Path(args.sheet))
    print(f"built {len(assets)} assets into {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
