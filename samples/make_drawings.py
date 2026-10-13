"""Draws sample "kid crayon drawings" for Little Makers Market demos.

Original art made procedurally (no third-party images), so it is safe to use
in the public repo and the demo video. Run: python make_drawings.py
"""
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 1024
OUT = Path(__file__).resolve().parent / "drawings"

PURPLE = (128, 70, 190)
GOLD = (240, 190, 30)
ORANGE = (250, 130, 30)
RED = (225, 45, 45)
GREEN = (60, 170, 70)
DARKGREEN = (35, 120, 50)
BLUE = (50, 120, 230)
SKY = (110, 185, 240)
PINK = (245, 130, 180)
YELLOW = (250, 215, 40)
BROWN = (130, 85, 45)
BLACK = (35, 35, 40)
GREY = (150, 150, 160)
WHITE = (255, 255, 255)


class Paper:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        np_rng = np.random.default_rng(seed)
        base = np.full((SIZE, SIZE, 3), (250, 248, 240), np.float32)
        base += np_rng.normal(0, 3, (SIZE, SIZE, 1))
        self.img = Image.fromarray(base.clip(0, 255).astype(np.uint8), "RGB")
        # crayon grain: wax skips over the paper tooth
        self.grain = Image.fromarray((np_rng.random((SIZE, SIZE)) > 0.28).astype(np.uint8) * 255, "L")
        self.grain = self.grain.filter(ImageFilter.GaussianBlur(0.6))

    # ---- geometry helpers -------------------------------------------------
    def wobble(self, pts, amount=6.0, step=6.0):
        """Resample a polyline densely and add slow hand wobble."""
        dense = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(2, int(math.hypot(x1 - x0, y1 - y0) / step))
            for i in range(n):
                t = i / n
                dense.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        dense.append(pts[-1])
        ph1, ph2 = self.rng.random() * 6.28, self.rng.random() * 6.28
        f1, f2 = self.rng.uniform(0.03, 0.06), self.rng.uniform(0.08, 0.15)
        return [(x + amount * math.sin(i * f1 + ph1), y + amount * math.cos(i * f2 + ph2))
                for i, (x, y) in enumerate(dense)]

    def ellipse(self, cx, cy, rx, ry, rot=0.0, n=60):
        pts = []
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            x, y = rx * math.cos(a), ry * math.sin(a)
            pts.append((cx + x * math.cos(rot) - y * math.sin(rot), cy + x * math.sin(rot) + y * math.cos(rot)))
        # kids rarely close a circle perfectly
        over = self.rng.randint(2, 6)
        return pts + pts[1:over]

    # ---- drawing ------------------------------------------------------------
    def _apply(self, layer_alpha, color):
        alpha = ImageChops.multiply(layer_alpha, self.grain)
        solid = Image.new("RGB", (SIZE, SIZE), color)
        self.img = Image.composite(solid, self.img, alpha)

    def line(self, pts, color=BLACK, width=7, passes=3, wobble=5.0):
        layer = Image.new("L", (SIZE, SIZE), 0)
        d = ImageDraw.Draw(layer)
        for _ in range(passes):
            jit = [(x + self.rng.uniform(-1.5, 1.5), y + self.rng.uniform(-1.5, 1.5)) for x, y in self.wobble(pts, wobble)]
            d.line(jit, fill=int(255 * 0.75), width=width, joint="curve")
        self._apply(layer, color)

    def fill(self, outline_pts, color, spacing=11, angle=None, width=9):
        """Scribble-fill a closed shape with zigzag strokes that overshoot a little."""
        mask = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(mask).polygon(self.wobble(outline_pts, 4), fill=255)
        mask = mask.filter(ImageFilter.MaxFilter(9))  # overshoot the outline
        xs = [p[0] for p in outline_pts]
        ys = [p[1] for p in outline_pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        r = max(max(xs) - min(xs), max(ys) - min(ys)) * 0.75 + 20
        ang = angle if angle is not None else self.rng.uniform(-0.9, 0.9)
        ca, sa = math.cos(ang), math.sin(ang)
        zig = []
        t, flip = -r, 1
        while t < r:
            zig.append((cx + t * ca - flip * r * sa, cy + t * sa + flip * r * ca))
            t += spacing
            flip = -flip
        layer = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(layer).line(self.wobble(zig, 3, 8), fill=200, width=width)
        layer = ImageChops.multiply(layer, mask)
        self._apply(layer, color)

    def shape(self, pts, fill_color, line_color=BLACK, width=7):
        if fill_color:
            self.fill(pts, fill_color)
        self.line(pts, line_color, width)

    def dot(self, x, y, r, color=BLACK):
        self.fill(self.ellipse(x, y, r, r, n=20), color, spacing=4, width=6)

    # ---- scenery kids always add ---------------------------------------------
    def grass(self, y=900):
        pts = []
        x = -10
        while x < SIZE + 20:
            pts += [(x, y + self.rng.uniform(-8, 8)), (x + 9, y - self.rng.uniform(25, 45))]
            x += 18
        self.line(pts, GREEN, width=6, passes=2, wobble=2)
        self.fill([(0, y), (SIZE, y), (SIZE, SIZE), (0, SIZE)], GREEN, spacing=16, angle=0.2)

    def sun(self, cx=110, cy=110, r=60):
        self.shape(self.ellipse(cx, cy, r, r), YELLOW, ORANGE, 6)
        for i in range(10):
            a = i * math.pi / 5 + self.rng.uniform(-0.1, 0.1)
            self.line([(cx + (r + 12) * math.cos(a), cy + (r + 12) * math.sin(a)),
                       (cx + (r + 50) * math.cos(a), cy + (r + 50) * math.sin(a))], ORANGE, 6, 2, 2)

    def smile(self, cx, cy, w, h=None):
        h = h or w * 0.5
        pts = [(cx - w / 2 + w * i / 12, cy + h * math.sin(math.pi * i / 12)) for i in range(13)]
        self.line(pts, BLACK, 6, 2, 1.5)

    def save(self, name):
        OUT.mkdir(exist_ok=True)
        self.img.save(OUT / f"{name}.png")
        print("saved", name)


def purple_dragon():
    p = Paper(1)
    p.sun()
    p.grass()
    # wings
    p.shape([(470, 420), (400, 230), (560, 380)], SKY)
    p.shape([(560, 400), (650, 220), (640, 420)], SKY)
    # tail
    p.shape([(700, 600), (880, 560), (930, 470), (900, 600), (720, 680)], PURPLE)
    # body + head
    p.shape(p.ellipse(560, 600, 190, 140), PURPLE)
    p.shape(p.ellipse(340, 400, 120, 100), PURPLE)
    # three legs (the kid insisted)
    for x in (460, 570, 680):
        p.line([(x, 720), (x - 5, 870)], BLACK, 9)
        p.line([(x - 5, 870), (x + 35, 872)], BLACK, 9)
    # crown
    p.shape([(260, 320), (275, 230), (310, 290), (340, 215), (370, 290), (405, 235), (415, 320)], GOLD, ORANGE, 6)
    # face
    p.dot(300, 380, 14)
    p.dot(380, 380, 14)
    p.smile(340, 440, 110, 40)
    # fire
    p.shape([(220, 430), (120, 380), (150, 430), (80, 450), (150, 470), (110, 520), (225, 470)], ORANGE, RED, 6)
    p.save("purple-dragon")


def rainbow_cat():
    p = Paper(2)
    p.grass()
    colors = [RED, ORANGE, YELLOW, GREEN, BLUE, PURPLE]
    body = p.ellipse(520, 650, 200, 170)
    p.line(body, BLACK, 7)
    for i, c in enumerate(colors):
        y0 = 490 + i * 55
        band = [(320, y0), (720, y0), (720, y0 + 55), (320, y0 + 55)]
        clip = [pt for pt in body if y0 - 10 <= pt[1] <= y0 + 65]
        if clip:
            p.fill(band if not clip else [(min(x for x, _ in clip), y0), (max(x for x, _ in clip), y0),
                                          (max(x for x, _ in clip), y0 + 55), (min(x for x, _ in clip), y0 + 55)], c, angle=0.0)
    p.line(body, BLACK, 7)
    p.shape([(700, 700), (820, 640), (900, 520), (880, 500), (800, 610), (700, 650)], ORANGE)
    head = p.ellipse(500, 360, 150, 130)
    p.shape(head, ORANGE)
    p.shape([(380, 290), (370, 160), (460, 250)], ORANGE)
    p.shape([(540, 250), (630, 160), (620, 290)], ORANGE)
    p.dot(450, 340, 16)
    p.dot(560, 340, 16)
    p.shape([(490, 390), (515, 390), (502, 405)], PINK)
    p.smile(502, 420, 70, 25)
    for dy in (-15, 10):
        p.line([(400, 400 + dy), (300, 390 + dy * 2)], BLACK, 4, 2, 1)
        p.line([(600, 400 + dy), (700, 390 + dy * 2)], BLACK, 4, 2, 1)
    p.save("rainbow-cat")


def robot_friend():
    p = Paper(3)
    p.sun(900, 120, 55)
    p.grass(920)
    p.shape([(330, 430), (690, 430), (690, 760), (330, 760), (330, 430)], GREY)
    p.shape([(380, 200), (640, 200), (640, 410), (380, 410), (380, 200)], GREY)
    p.line([(510, 200), (510, 120)], BLACK, 7)
    p.dot(510, 110, 22, RED)
    p.shape(p.ellipse(450, 290, 42, 42), WHITE)
    p.shape(p.ellipse(570, 290, 42, 42), WHITE)
    p.dot(455, 295, 16, BLUE)
    p.dot(565, 295, 16, BLUE)
    p.smile(510, 350, 120, 25)
    p.line([(330, 520), (200, 450), (160, 380)], BLACK, 9)
    p.line([(690, 520), (820, 590)], BLACK, 9)
    p.shape(p.ellipse(840, 600, 30, 30), RED)
    for x in (420, 600):
        p.line([(x, 760), (x, 900)], BLACK, 10)
    p.shape([(440, 520), (580, 520), (580, 640), (440, 640), (440, 520)], YELLOW)
    p.shape(p.ellipse(510, 580, 30, 30), RED)
    p.save("robot-friend")


def happy_dinosaur():
    p = Paper(4)
    p.sun()
    p.grass()
    for i, x in enumerate(range(380, 760, 70)):
        p.shape([(x, 520 - (i % 2) * 10), (x + 35, 420), (x + 70, 520)], ORANGE)
    p.shape([(700, 640), (900, 720), (950, 760), (720, 740)], GREEN)
    p.shape(p.ellipse(560, 640, 220, 140), GREEN)
    p.shape([(380, 560), (330, 380), (260, 300), (180, 320), (190, 380), (290, 420), (340, 600)], GREEN)
    p.dot(230, 335, 12)
    p.smile(210, 365, 50, 15)
    for x, y in ((480, 600), (600, 580), (680, 660), (520, 700)):
        p.dot(x, y, 22, ORANGE)
    for x in (430, 520, 620, 700):
        p.line([(x, 760), (x, 880)], DARKGREEN, 14)
    p.save("happy-dinosaur")


def silly_monster():
    p = Paper(5)
    p.grass()
    blob = [(300, 800), (240, 600), (260, 420), (360, 280), (520, 250), (680, 300),
            (770, 450), (780, 650), (720, 800), (600, 760), (500, 820), (400, 770), (300, 800)]
    p.shape(blob, BLUE)
    for x in (360, 470, 580, 690):
        p.line([(x, 300 - (x % 3) * 10), (x - 30, 170)], BLUE, 8)
    p.shape(p.ellipse(510, 430, 100, 85), WHITE)
    p.dot(520, 440, 38, GREEN)
    p.dot(525, 445, 16)
    mouth = [(340, 600), (680, 600), (640, 700), (380, 700), (340, 600)]
    p.shape(mouth, RED)
    for i in range(7):
        x = 370 + i * 45
        p.shape([(x, 602), (x + 20, 645), (x + 40, 602)], WHITE, BLACK, 4)
    p.line([(250, 600), (130, 520)], BLACK, 9)
    p.line([(770, 600), (890, 500)], BLACK, 9)
    p.save("silly-monster")


def space_rocket():
    p = Paper(6)
    # night sky scribble
    p.fill([(0, 0), (SIZE, 0), (SIZE, SIZE), (0, SIZE)], (40, 40, 110), spacing=14, angle=0.4)
    for _ in range(14):
        x, y = p.rng.uniform(60, 960), p.rng.uniform(60, 960)
        if abs(x - 512) < 200:
            continue
        p.line([(x - 18, y), (x + 18, y)], YELLOW, 6, 2, 1)
        p.line([(x, y - 18), (x, y + 18)], YELLOW, 6, 2, 1)
    body = [(512, 130), (620, 330), (620, 700), (404, 700), (404, 330), (512, 130)]
    p.shape(body, RED, WHITE)
    p.shape([(404, 560), (300, 720), (404, 690)], YELLOW, WHITE)
    p.shape([(620, 560), (724, 720), (620, 690)], YELLOW, WHITE)
    p.shape(p.ellipse(512, 420, 70, 70), SKY, WHITE)
    p.dot(490, 410, 10)
    p.dot(535, 410, 10)
    p.smile(512, 440, 50, 18)
    p.shape([(430, 710), (470, 880), (512, 780), (555, 900), (594, 710)], ORANGE, YELLOW)
    p.save("space-rocket")


def sun_turtle():
    p = Paper(7)
    p.fill([(0, 600), (SIZE, 600), (SIZE, SIZE), (0, SIZE)], SKY, spacing=18, angle=0.1)
    shell = [(260, 620)] + [(512 + 260 * math.cos(a), 620 - 230 * math.sin(a))
                            for a in np.linspace(math.pi, 0, 30)] + [(260, 620)]
    p.shape(shell, DARKGREEN)
    p.shape(p.ellipse(512, 480, 85, 85), YELLOW, ORANGE)
    for i in range(8):
        a = i * math.pi / 4
        p.line([(512 + 100 * math.cos(a), 480 + 100 * math.sin(a)),
                (512 + 140 * math.cos(a), 480 + 140 * math.sin(a))], ORANGE, 6, 2, 1)
    p.shape(p.ellipse(840, 560, 85, 70), GREEN)
    p.dot(865, 540, 12)
    p.smile(850, 585, 60, 18)
    for x in (320, 640):
        p.shape(p.ellipse(x, 660, 55, 40), GREEN)
    p.shape([(260, 600), (170, 640), (260, 630)], GREEN)
    p.save("sun-turtle")


if __name__ == "__main__":
    for fn in (purple_dragon, rainbow_cat, robot_friend, happy_dinosaur, silly_monster, space_rocket, sun_turtle):
        fn()
