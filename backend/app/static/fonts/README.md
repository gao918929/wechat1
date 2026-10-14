# Pixel fonts

Loaded by the mini program at runtime via `wx.loadFontFace` (kept out of the 2 MB package).

| File | Font | License |
|---|---|---|
| `fusion-pixel-12px-sc.woff(2)` | [Fusion Pixel Font](https://github.com/TakWolf/fusion-pixel-font) 12px proportional, Simplified Chinese — merged from the per-block webfont subsets of `@vp-tw/cjk-web-fonts-fusion-pixel-font` and subset to the project's characters + the 3,755 GB2312 level-1 hanzi | SIL OFL 1.1 (`OFL-FusionPixel.txt`) |
| `press-start-2p.woff(2)` | [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P) (Latin), via `@fontsource/press-start-2p` | SIL OFL 1.1 (`OFL-PressStart2P.txt`) |

Regenerate the Chinese subset with `tools/build_pixel_font.py` after adding UI text that uses rare characters.
