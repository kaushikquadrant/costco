"""Draw the status badges used on the dashboard's "Queries in this run" table (Day 6).

30 PNGs: 10 letters (B A F G R T I C S E) x 3 states (pass ✓ green, fail ✗ red, na – grey).
Shape and mark carry the meaning as well as colour (colour-blind safe).
Usage: python eval-adk/dashboard/make_badges.py   -> eval-adk/dashboard/badges/<L>_<state>.png
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "badges"
W, H, SCALE = 64, 30, 4                      # final size in px; drawn 4x larger, then reduced for smooth edges
STATES = {"pass": ("#1D9E75", "✓"), "fail": ("#D9483B", "✗"), "na": ("#9A9890", "–")}
LETTERS = "BAFGRTICSE"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def badge(letter: str, color: str, mark: str) -> Image.Image:
    w, h = W * SCALE, H * SCALE
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=color)
    font = ImageFont.truetype(FONT, int(h * 0.58))
    text = f"{letter} {mark}"
    box = d.textbbox((0, 0), text, font=font)
    d.text(((w - (box[2] - box[0])) / 2 - box[0], (h - (box[3] - box[1])) / 2 - box[1]), text, font=font, fill="white")
    return img.resize((W, H), Image.LANCZOS)


OUT.mkdir(parents=True, exist_ok=True)
for letter in LETTERS:
    for state, (color, mark) in STATES.items():
        badge(letter, color, mark).save(OUT / f"{letter}_{state}.png")

# Contact sheet to check the look in one image.
sheet = Image.new("RGBA", (len(LETTERS) * (W + 8) + 8, 3 * (H + 8) + 8), "white")
for i, letter in enumerate(LETTERS):
    for j, state in enumerate(STATES):
        sheet.paste(Image.open(OUT / f"{letter}_{state}.png"), (8 + i * (W + 8), 8 + j * (H + 8)), Image.open(OUT / f"{letter}_{state}.png"))
sheet.save(OUT.parent / "badges_preview.png")
print(f"{len(list(OUT.glob('*.png')))} badges in {OUT}")
