"""Génère les visuels statiques des e-mails (frontend/public/img/email/).

Les clients mail ignorent les dégradés radiaux, les ombres et les masques CSS que
la fiche course utilise pour ses médailles, son en-tête et ses silhouettes de
discipline : on les « cuit » ici en images, servies depuis blackturf.fr. Le rendu
est alors identique partout (Gmail, Outlook, Apple Mail), y compris sans CSS.

Relancer après une modification de la charte :
    python3 scripts/generer_visuels_email.py   (Pillow requis)
"""
from pathlib import Path

from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RACINE = Path(__file__).resolve().parents[1] / "frontend" / "public" / "img"
SORTIE = RACINE / "email"
POLICE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Mêmes teintes que PODIUM dans frontend/src/components/courses/classement.tsx.
PODIUM = {
    1: [(0.0, "#FFF7D6"), (0.32, "#FCD34D"), (0.72, "#D97706"), (1.0, "#92400E")],
    2: [(0.0, "#FFFFFF"), (0.34, "#E2E8F0"), (0.74, "#94A3B8"), (1.0, "#475569")],
    3: [(0.0, "#FFEAD5"), (0.34, "#FDBA74"), (0.76, "#C2410C"), (1.0, "#7C2D12")],
}
# Mêmes couleurs que DISCIPLINE_MASK dans CourseClient.tsx.
DISCIPLINES = {"plat": "#B45309", "attele": "#0E7C66", "monte": "#2A5BD7", "obstacle": "#86198F"}


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _interp(stops, t):
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            k = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            a, b = _rgb(c0), _rgb(c1)
            return tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))
    return _rgb(stops[-1][1])


def medaille(rang: int, taille: int = 132) -> None:
    """Pièce de podium en relief : dégradé radial éclairé en haut à gauche, liseré,
    anneau intérieur embouti, chiffre ombré, ombre portée douce."""
    s = taille * 4  # sur-échantillonnage pour des bords lisses
    marge = int(s * 0.10)
    d = s - 2 * marge
    fond = Image.new("RGBA", (s, s), (0, 0, 0, 0))

    ombre = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(ombre).ellipse((marge, marge + s * 0.05, marge + d, marge + d + s * 0.05), fill=(0, 0, 0, 110))
    fond.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(s * 0.035)))

    piece = Image.new("RGBA", (d, d))
    px = piece.load()
    cx, cy, rmax = d * 0.32, d * 0.28, d * 0.95
    for y in range(d):
        for x in range(d):
            t = min(1.0, ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / rmax)
            px[x, y] = (*_interp(PODIUM[rang], t), 255)
    masque = Image.new("L", (d, d), 0)
    ImageDraw.Draw(masque).ellipse((0, 0, d - 1, d - 1), fill=255)
    piece.putalpha(masque)

    dp = ImageDraw.Draw(piece)
    fonce = _rgb(PODIUM[rang][-1][1])
    dp.ellipse((2, 2, d - 3, d - 3), outline=(*fonce, 200), width=int(d * 0.025))
    e = int(d * 0.13)
    dp.ellipse((e, e, d - e, d - e), outline=(255, 255, 255, 110), width=int(d * 0.018))
    dp.ellipse((e + d * 0.02, e + d * 0.02, d - e + d * 0.02, d - e + d * 0.02), outline=(*fonce, 90), width=int(d * 0.014))

    # Reflet spéculaire en haut à gauche.
    reflet = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    ImageDraw.Draw(reflet).ellipse((d * 0.16, d * 0.08, d * 0.62, d * 0.40), fill=(255, 255, 255, 95))
    reflet = reflet.filter(ImageFilter.GaussianBlur(d * 0.05))
    piece.alpha_composite(Image.composite(reflet, Image.new("RGBA", (d, d), (0, 0, 0, 0)), masque))

    police = ImageFont.truetype(POLICE, int(d * 0.50))
    txt = str(rang)
    bb = dp.textbbox((0, 0), txt, font=police)
    tx, ty = (d - (bb[2] - bb[0])) / 2 - bb[0], (d - (bb[3] - bb[1])) / 2 - bb[1]
    dp.text((tx, ty + d * 0.025), txt, font=police, fill=(*fonce, 170))
    dp.text((tx, ty), txt, font=police, fill=(255, 255, 255, 255))

    fond.alpha_composite(piece, (marge, marge))
    fond.resize((taille, taille), Image.LANCZOS).save(SORTIE / f"medaille-{rang}.png", optimize=True)


def banniere(source: str, nom: str, focale_y: float = 0.5) -> None:
    """Photo 1200×520 fondue vers l'encre de l'en-tête : le texte HTML posé en
    dessous prolonge l'image sans rupture."""
    im = Image.open(RACINE / "course" / source).convert("RGB")
    l, h = 1200, 520
    ratio = max(l / im.width, h / im.height)
    im = im.resize((round(im.width * ratio), round(im.height * ratio)), Image.LANCZOS)
    y0 = round((im.height - h) * focale_y)
    x0 = (im.width - l) // 2
    im = im.crop((x0, y0, x0 + l, y0 + h)).convert("RGBA")

    encre = _rgb("#14110C")
    voile = Image.new("RGBA", (l, h))
    vp = voile.load()
    for y in range(h):
        bas = max(0.0, (y / h - 0.35) / 0.65) ** 1.6       # fondu vers le bas
        for x in range(l):
            vignette = (abs(x / l - 0.5) * 2) ** 2.2 * 0.45  # bords assombris
            a = min(1.0, 0.18 + bas * 0.95 + vignette)
            vp[x, y] = (*encre, round(a * 255))
    im.alpha_composite(voile)
    im.convert("RGB").save(SORTIE / f"hero-{nom}.jpg", quality=80, optimize=True, progressive=True)


def logo() -> None:
    im = Image.open(RACINE / "logo-blackturf.png").convert("RGBA")
    fond = Image.new("RGBA", im.size, (255, 255, 255, 255))
    diff = Image.eval(Image.alpha_composite(fond, im).convert("L"), lambda v: 255 if v < 235 else 0)
    im = im.crop(diff.getbbox())
    im = im.resize((360, round(im.height * 360 / im.width)), Image.LANCZOS)
    # Fond blanc opaque + palette : 15 Ko au lieu de 140, rendu identique sur le
    # bandeau blanc qui le porte.
    fond = Image.new("RGB", im.size, (255, 255, 255))
    fond.paste(im, mask=im.getchannel("A"))
    fond.quantize(colors=96, method=Image.MEDIANCUT).save(SORTIE / "logo-blackturf.png", optimize=True)


def disciplines() -> None:
    """Silhouettes de discipline teintées, comme le masque CSS de la fiche course."""
    for nom, couleur in DISCIPLINES.items():
        src = Image.open(RACINE / "disciplines" / f"{nom}-v9.png").convert("RGBA")
        alpha = src.getchannel("A")
        teinte = Image.new("RGBA", src.size, (*_rgb(couleur), 255))
        teinte.putalpha(alpha)
        teinte = teinte.crop(alpha.getbbox())
        teinte.thumbnail((96, 64), Image.LANCZOS)
        teinte.save(SORTIE / f"disc-{nom}.png", optimize=True)


def tuile_ia(taille: int = 88) -> None:
    """Tuile or en relief qui porte l'en-tête « classement de l'algorithme »
    (IconeTuile côté site)."""
    s = taille * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ombre = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(ombre).rounded_rectangle((s * .08, s * .12, s * .92, s * .96), s * .24, fill=(146, 64, 14, 90))
    im.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(s * .04)))
    corps = Image.new("RGBA", (s, s))
    cp = corps.load()
    for y in range(s):
        t = y / s
        c = _interp([(0, "#FFF4D1"), (0.5, "#FCD34D"), (1, "#D97706")], t)
        for x in range(s):
            cp[x, y] = (*c, 255)
    masque = Image.new("L", (s, s), 0)
    ImageDraw.Draw(masque).rounded_rectangle((s * .08, s * .06, s * .92, s * .90), s * .24, fill=255)
    im.alpha_composite(Image.composite(corps, Image.new("RGBA", (s, s), (0, 0, 0, 0)), masque))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((s * .08, s * .06, s * .92, s * .90), s * .24, outline=(255, 255, 255, 150), width=int(s * .02))
    police = ImageFont.truetype(POLICE, int(s * .34))
    bb = d.textbbox((0, 0), "IA", font=police)
    tx, ty = (s - (bb[2] - bb[0])) / 2 - bb[0], (s * .96 - (bb[3] - bb[1])) / 2 - bb[1]
    d.text((tx, ty + s * .02), "IA", font=police, fill=(146, 64, 14, 140))
    d.text((tx, ty), "IA", font=police, fill=(255, 255, 255, 255))
    im.resize((taille, taille), Image.LANCZOS).save(SORTIE / "tuile-ia.png", optimize=True)


def dessiner_casaque(corps: str, manches: str, motif: Optional[str] = None, taille: int = 96) -> Image.Image:
    """Casaque (maillot de jockey) vue de face, en relief léger. Sert de repli
    quand le PMU ne fournit pas d'image pour un partant."""
    s = taille * 4
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    k = s / 100
    tronc = [(30, 18), (42, 12), (58, 12), (70, 18), (72, 90), (28, 90)]
    manche_g = [(30, 18), (8, 44), (18, 54), (30, 38)]
    manche_d = [(70, 18), (92, 44), (82, 54), (70, 38)]
    pts = lambda l: [(x * k, y * k) for x, y in l]
    ombre = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    od = ImageDraw.Draw(ombre)
    for poly in (tronc, manche_g, manche_d):
        od.polygon([(x, y + 3 * k) for x, y in pts(poly)], fill=(0, 0, 0, 80))
    im.alpha_composite(ombre.filter(ImageFilter.GaussianBlur(2.5 * k)))
    d = ImageDraw.Draw(im)
    d.polygon(pts(manche_g), fill=_rgb(manches), outline=(0, 0, 0), width=int(1.2 * k))
    d.polygon(pts(manche_d), fill=_rgb(manches), outline=(0, 0, 0), width=int(1.2 * k))
    d.polygon(pts(tronc), fill=_rgb(corps), outline=(0, 0, 0), width=int(1.2 * k))
    if motif:
        d.rectangle((44 * k, 13 * k, 56 * k, 89 * k), fill=_rgb(motif))
    d.pieslice((40 * k, 4 * k, 60 * k, 20 * k), 0, 180, fill=(255, 255, 255), outline=(0, 0, 0), width=int(k))
    # Reflet sur l'épaule gauche.
    reflet = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(reflet).ellipse((30 * k, 18 * k, 52 * k, 50 * k), fill=(255, 255, 255, 60))
    im.alpha_composite(reflet.filter(ImageFilter.GaussianBlur(4 * k)))
    return im.resize((taille, taille), Image.LANCZOS)


def cheval_or() -> None:
    """Silhouette du logo en or pour le pied de mail, sur fond sombre : les
    zones noires deviennent or, les reflets blancs or clair."""
    im = Image.open(RACINE / "logo-horse.png").convert("RGBA")
    px = im.load()
    fonce, clair = _rgb("#C99A3C"), _rgb("#F3E3B5")
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if a:
                t = (r + g + b) / 765
                px[x, y] = (*(round(fonce[i] + (clair[i] - fonce[i]) * t) for i in range(3)), a)
    im.thumbnail((160, 160), Image.LANCZOS)
    im.save(SORTIE / "cheval-or.png", optimize=True)


if __name__ == "__main__":
    SORTIE.mkdir(parents=True, exist_ok=True)
    for r in (1, 2, 3):
        medaille(r)
    banniere("galop-lutte.jpg", "galop", focale_y=0.62)
    banniere("attele-action.jpg", "trot", focale_y=0.55)
    logo()
    disciplines()
    tuile_ia()
    cheval_or()
    dessiner_casaque("#E7E5E4", "#D6D3D1").save(SORTIE / "casaque-neutre.png", optimize=True)
    print("Visuels écrits dans", SORTIE)
