from PIL import Image
import sys, os

# Sources : silhouettes fournies par l'utilisateur, detourees du fond blanc
# (src-*.png, alpha issu de la luminance, antialiasing du bord conserve).
H       = 200      # hauteur de toile commune -> meme ratio px/affichage pour les quatre
SOL     = 178      # ligne de sol partagee dans la toile
MARGE_X = 14

def build(mult):
    out = {}
    for n, m in mult.items():
        im = Image.open(f"src-{n}.png").convert("RGBA")
        im = im.crop(im.getbbox())
        h = round(SOL * 0.80 * m)
        im = im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)
        canvas = Image.new("RGBA", (im.width + 2 * MARGE_X, H), (0, 0, 0, 0))
        canvas.alpha_composite(im, (MARGE_X, SOL - im.height))
        out[n] = canvas
    return out

if __name__ == "__main__":
    mult = dict(plat=float(sys.argv[1]), attele=float(sys.argv[2]),
                monte=float(sys.argv[3]), obstacle=float(sys.argv[4]))
    imgs = build(mult)
    for n, c in imgs.items():
        c.save(f"disc-{n}.png", "PNG", optimize=True)
    ech = 8 * 42 / H                                   # planche de controle a x8 la taille imprimee
    strip = Image.new("RGBA", (round(sum(c.width for c in imgs.values()) * ech) + 3 * 40,
                               round(H * ech)), (255, 251, 240, 255))
    x = 0
    for n in ["plat", "attele", "monte", "obstacle"]:
        c = imgs[n].resize((round(imgs[n].width * ech), round(H * ech)), Image.LANCZOS)
        strip.alpha_composite(c, (x, 0)); x += c.width + 40
    strip.convert("RGB").save("_strip.png")
    print({n: f"{c.width}x{c.height}  {os.path.getsize(f'disc-{n}.png')//1024}KB" for n, c in imgs.items()})
