from PIL import Image
import sys, os

SRC = "/home/user/blackturf/frontend/public/img/disciplines"
H       = 200      # hauteur de toile commune -> meme ratio px/affichage pour les quatre
SOL     = 176      # ligne de sol partagee dans la toile
MARGE_X = 15

# Multiplicateur par image : la boite englobante ne mesure pas le CHEVAL.
# L'attele traine un sulky (boite large), l'obstacle porte une haie (boite haute),
# le monte a un cavalier redresse. Sans correction, leurs chevaux sont plus petits.
def build(mult):
    out = {}
    for n, m in mult.items():
        src = "attele-repare.png" if n == "attele" else f"{SRC}/{n}-v2.png"
        im = Image.open(src).convert("RGBA")
        im = im.crop(im.getbbox())
        h = round(SOL * 0.80 * m)
        im = im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)
        W = im.width + 2 * MARGE_X
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.alpha_composite(im, (MARGE_X, SOL - im.height))
        out[n] = canvas
    return out

if __name__ == "__main__":
    mult = dict(plat=float(sys.argv[1]), attele=float(sys.argv[2]),
                monte=float(sys.argv[3]), obstacle=float(sys.argv[4]))
    imgs = build(mult)
    for n, c in imgs.items():
        c.save(f"disc-{n}.png", "PNG", optimize=True)
    # planche de controle, a la taille d'affichage x8
    ech = 8 * 40 / H
    strip = Image.new("RGBA", (round(sum(c.width for c in imgs.values()) * ech) + 3 * 40, round(H * ech)), (255, 251, 240, 255))
    x = 0
    for n in ["plat", "attele", "monte", "obstacle"]:
        c = imgs[n].resize((round(imgs[n].width * ech), round(H * ech)), Image.LANCZOS)
        strip.alpha_composite(c, (x, 0)); x += c.width + 40
    strip.convert("RGB").save("_strip.png")
    print({n: f"{c.width}x{c.height}" for n, c in imgs.items()})
