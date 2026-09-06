import fs from "node:fs/promises";
import path from "node:path";

/**
 * Mosaïque de six publications formant une seule image sur la grille du profil.
 *
 * ─────────────────────────── LA GÉOMÉTRIE, QUI N'EST PAS ANODINE ───────────────────────
 *
 * La grille de profil Instagram n'est plus carrée depuis 2025 : chaque vignette y est
 * rognée en **3:4**, quelle que soit l'image envoyée. Une mosaïque dessinée en carrés
 * perdrait une bande sur les côtés de chaque tuile, et les raccords ne tomberaient jamais
 * juste — le défaut le plus visible qui soit sur une mosaïque.
 *
 * On publie donc en 4:5 (1080 × 1350), et la grille en montre le centre : 1012 × 1350.
 * L'image d'ensemble est composée dans cet espace-là — 3 colonnes de 1012 px — puis
 * chaque tuile est rendue avec 34 px de débord de chaque côté, rognés sur la grille mais
 * qui rendent la tuile correcte quand on la regarde seule dans le fil.
 *
 *   largeur du plan d'ensemble = 34 + 3 × 1012 + 34 = 3104
 *   hauteur                    = 2 × 1350           = 2700
 *   décalage de la tuile (r,c) = ( −c × 1012 , −r × 1350 )
 *
 * ─────────────────────────── CE QUI FAIT TENIR LA COMPOSITION ──────────────────────────
 *
 * Fond ivoire, encre sombre, or profond : la charte du site. La photo de course garde sa
 * lumière — elle est le sujet, pas une texture à assombrir.
 *
 * Quatre choses seulement font voir UNE image là où la grille en montre six :
 *   1. la photo traverse toute la rangée haute, et les cartes blanches ne remplissent
 *      jamais la largeur d'une colonne : la photo respire entre elles ;
 *   2. un fondu vers l'ivoire éteint la photo pile à la jointure des deux rangées ;
 *   3. une règle dorée court d'un bord à l'autre sur cette jointure ;
 *   4. le panneau sombre de la colonne du milieu ancre la rangée basse, qui sinon se
 *      lirait comme une page de texte blanche posée sous une photo — c'était le défaut
 *      de la version précédente.
 *
 * ─────────────────────────── CE QUE CHAQUE TUILE DOIT FAIRE SEULE ──────────────────────
 *
 * Dans le fil, personne ne voit jamais la mosaïque : on voit UNE tuile. Chacune porte
 * donc son adresse — `blackturf.fr` — et doit se tenir seule comme une publication.
 */

export const TUILE_L = 1080;
export const TUILE_H = 1350;
/** Largeur réellement visible d'une tuile sur la grille (rognage 3:4). */
export const VISIBLE_L = 1012;
export const DEBORD = (TUILE_L - VISIBLE_L) / 2; // 34
export const PLAN_L = DEBORD * 2 + VISIBLE_L * 3; // 3104
export const PLAN_H = TUILE_H * 2; // 2700

export const COULEURS = {
  ivoire: "#F5F2EA",
  blanc: "#FFFFFF",
  encre: "#15181D",
  encreDouce: "#5E6673",
  encreTenue: "#8C94A1",
  /** Or profond : le doré clair du site est illisible sur fond blanc. */
  or: "#9C6B12",
  orVif: "#E0A63C",
  ligne: "#E4DED2",
  /** Sur la rangée sombre : l'ivoire pur brûle, il faut le tenir d'un cran. */
  surSombre: "#E8E4DA",
  surSombreDoux: "#9AA2AE",
  surSombreTenu: "#868E9A",
  ligneSombre: "#2B3138",
} as const;

/**
 * Photos de course, tournantes.
 *
 * Ce sont des PHOTOS, pas des images fabriquées : une marque qui vend de la rigueur ne
 * s'illustre pas avec un cheval qui n'existe pas. Les cinq premières sont celles du
 * site ; les vingt-sept autres viennent de Pexels (licence Pexels : usage commercial libre,
 * sans attribution obligatoire, modification autorisée), et la provenance de chaque
 * fichier est journalisée dans `public/img/course/SOURCES.txt` — une image dont on ne
 * sait plus d'où elle vient est une image qu'on ne peut plus défendre.
 *
 * Moitié galop, moitié attelé : le PMU français trotte plus qu'il ne galope, et
 * illustrer trente-deux publications avec des pur-sang lancés au galop décrirait un
 * programme qui n'est pas celui du site.
 *
 * TROIS PHOTOS EN PORTRAIT ONT ÉTÉ RETIRÉES (galop-duo, galop-soleil, galop-poussiere,
 * rapports 0,67 à 0,80). Une source verticale posée dans une bande large ne peut pas
 * être recadrée sans perdre son sujet : sur la story, les deux chevaux de galop-duo
 * sortaient décapités. Toute photo ajoutée ici doit être en PAYSAGE.
 */
const PHOTOS = [
  "showcase.webp", // peloton en pleine course
  "duel.webp", // duel à l'arrivée
  "hero-1600.webp", // départ, portes numérotées
  "value.jpg", // piste au soleil couchant
  "cta.jpg", // arrivée devant le public
  "course/galop-skyline.jpg",
  "course/attele-sable.jpg",
  "course/galop-foule.jpg",
  "course/attele-action.jpg",
  "course/galop-stalles.jpg",
  "course/attele-soleil.jpg",
  "course/galop-musselburgh.jpg",
  "course/attele-sulky.jpg",
  "course/attele-normandie.jpg",
  "course/galop-lutte.jpg",
  "course/attele-herbe.jpg",
  "course/attele-tribunes.jpg",
  "course/galop-piste-claire.jpg",
  "course/attele-piste.jpg",
  "course/galop-vitesse.jpg",
  "course/attele-driver.jpg",
  "course/galop-mouvement.jpg",
  "course/attele-peloton.jpg",
  "course/galop-face-a-face.jpg",
  "course/attele-couleurs.jpg",
  "course/galop-trois.jpg",
  "course/attele-foulee.jpg",
  "course/attele-groupe.jpg",
  "course/galop-shakopee.jpg",
  "course/attele-duel.jpg",
  "course/galop-noir-et-blanc.jpg",
  "course/attele-noir-et-blanc.jpg",
] as const;

/**
 * La photo du jour — une par jour, sans répétition avant un tour complet du fonds.
 *
 * L'index suit le NOMBRE DE JOURS écoulés depuis l'époque, pas le quantième du mois.
 * Avec le quantième, le 1er et le 31 tombaient sur la même image et le cycle se calait
 * sur la longueur du mois : sur un fonds de 32 photos, février n'en aurait montré que
 * 28 et jamais les quatre dernières. Le compte de jours avance de un chaque jour et
 * ignore les mois, donc les 32 photos passent toutes, dans l'ordre, puis recommencent.
 *
 * Déterministe et sans état : deux rendus du même jour donnent la même image, et le
 * visuel d'hier reste reproductible — indispensable quand une publication est mise en
 * cause après coup.
 */
export function photoDuJour(jour: string): string {
  const jours = Math.floor(Date.parse(`${jour}T00:00:00Z`) / 86_400_000);
  if (!Number.isFinite(jours)) return PHOTOS[0];
  return PHOTOS[((jours % PHOTOS.length) + PHOTOS.length) % PHOTOS.length];
}

/**
 * La photo de la MOSAÏQUE — la même pendant tout un cycle de six semaines.
 *
 * ELLE NE PEUT PAS TOURNER, et ce n'est pas un choix esthétique. La photo traverse
 * toute la rangée haute du plan d'ensemble : les tuiles (0,0), (0,1) et (0,2) en
 * montrent trois fenêtres qui doivent se raccorder au pixel. Or ces trois tuiles sont
 * publiées à trois dimanches d'écart. Avec la rotation quotidienne, chacune porterait
 * une photo différente et la mosaïque ne tomberait jamais juste — le défaut le plus
 * visible qui soit, et impossible à corriger une fois les six publiées.
 *
 * L'index suit donc le NUMÉRO DE CYCLE, pas la date : toutes les semaines d'un même
 * cycle donnent la même image, et le cycle suivant en prend une autre.
 */
/**
 * Fonds DÉDIÉ à la mosaïque, en haute résolution.
 *
 * L'image d'ensemble fait 3104 × 2700 et la photo la couvre entièrement. Le fonds
 * quotidien est en 1800 px de large : l'y étirer revient à un agrandissement de 1,7×,
 * et le flou se voit sur une image qui reste six semaines en tête du profil. Ces
 * huit-là font 3400 px. Huit suffisent : un cycle dure six semaines.
 *
 * Toutes en PAYSAGE, comme le fonds quotidien — même raison, la même règle.
 */
const PHOTOS_MOSAIQUE = [
  "mosaique/galop-foule.jpg",
  "mosaique/attele-sable.jpg",
  "mosaique/galop-stalles.jpg",
  "mosaique/attele-tribunes.jpg",
  "mosaique/galop-piste-claire.jpg",
  "mosaique/attele-peloton.jpg",
  "mosaique/galop-shakopee.jpg",
  "mosaique/attele-groupe.jpg",
] as const;

export function photoDuCycle(cycle: number): string {
  const i = Math.trunc(cycle);
  return PHOTOS_MOSAIQUE[((i % PHOTOS_MOSAIQUE.length) + PHOTOS_MOSAIQUE.length) % PHOTOS_MOSAIQUE.length];
}

/**
 * Charge une photo du dossier public et la renvoie en data URI JPEG, au format voulu.
 *
 * Deux raisons de passer par une conversion :
 * - Satori ne sait pas décoder le WebP, et la moitié des photos du site le sont ;
 * - la photo doit couvrir une bande très large ; recadrée par `sharp` avec détection du
 *   sujet, les chevaux restent dans le cadre au lieu d'être coupés.
 *
 * Elle est éclaircie, pas assombrie : dans cette composition c'est le texte qui se pose
 * sur des cartes blanches, la photo n'a donc pas à disparaître pour rester lisible.
 *
 * LES DIMENSIONS SONT UN PARAMÈTRE, et pas par confort. Le recadrage avec détection du
 * sujet se fait ICI, aux dimensions demandées ; si l'appelant affiche ensuite l'image
 * dans un cadre d'un autre rapport, le navigateur la recoupe une SECONDE fois, sans
 * détection cette fois — et un cheval cadré au centre par `sharp` ressort coupé au bord.
 * Chaque visuel demande donc exactement le format dans lequel il pose la photo :
 * 1800 × 900 pour le bandeau de la mosaïque, 1080 × 620 pour la story verticale.
 *
 * `ancrage` (0 = haut, 1 = bas) REMPLACE la détection du sujet quand il est fourni, et
 * c'est ce qui rend le cheval entier. La détection de `sharp` centre le sujet dans la
 * fenêtre : elle coupe donc autant en bas qu'en haut, et ce qu'elle coupe en bas, ce
 * sont les jambes — le cheval sortait posé sur un moignon. Sur une photo de course, ce
 * qu'on peut perdre sans rien perdre est le ciel : la story ancre à 0,82. Vérifié sur
 * les six rapports les plus serrés du fonds (1,25 à 1,72), cheval entier des sabots
 * aux oreilles sur les six.
 *
 * En cas d'échec on renvoie null : la composition se contente alors de son fond ivoire.
 * Un visuel sans photo reste publiable, un visuel qui plante non.
 */
export async function photoEnDataUri(
  fichier: string,
  { largeur = 1800, hauteur = 900, luminosite = 1.18, ancrage }:
    { largeur?: number; hauteur?: number; luminosite?: number; ancrage?: number } = {},
): Promise<string | null> {
  try {
    const chemin = path.join(process.cwd(), "public", "img", fichier);
    const brut = await fs.readFile(chemin);
    const { default: sharp } = await import("sharp");
    const source = sharp(brut);

    let cadre;
    if (ancrage === undefined) {
      cadre = source.resize(largeur, hauteur, { fit: "cover", position: "attention" });
    } else {
      // Mise à la largeur voulue, puis fenêtre découpée à la hauteur `ancrage`. On ne
      // laisse pas `sharp` choisir : sa détection du sujet centre le cheval dans la
      // fenêtre, donc elle coupe autant en bas qu'en haut — et ce qu'elle coupe en
      // bas, ce sont les JAMBES. Or sur une photo de course, ce qu'on peut perdre
      // sans rien perdre, c'est le ciel.
      const meta = await source.metadata();
      const h = Math.round((largeur * (meta.height ?? 1)) / (meta.width ?? 1));
      const fenetre = Math.min(hauteur, h);
      const top = Math.max(0, Math.round((h - fenetre) * Math.min(1, Math.max(0, ancrage))));
      cadre = source
        .resize(largeur, h)
        .extract({ left: 0, top, width: largeur, height: fenetre });
    }

    const jpeg = await cadre
      .modulate({ brightness: luminosite, saturation: 1.02 })
      .jpeg({ quality: 82 })
      .toBuffer();
    return `data:image/jpeg;base64,${jpeg.toString("base64")}`;
  } catch {
    return null;
  }
}

/**
 * Une image du dossier public, telle quelle, en data URI PNG.
 *
 * Distincte de `photoEnDataUri` : ici on ne recadre RIEN et on garde la transparence
 * (le cheval du logo se pose sur l'ivoire, un aplat blanc derrière lui ferait une
 * vignette). Le fichier source fait 493 × 310 : on ne l'agrandit jamais au-delà, sinon
 * le contour bave — c'est la seule chose qu'on remarque sur un logo.
 */
export async function imageEnDataUri(
  fichier: string,
  { largeur = 400 } = {},
): Promise<string | null> {
  try {
    const chemin = path.join(process.cwd(), "public", "img", fichier);
    const brut = await fs.readFile(chemin);
    const { default: sharp } = await import("sharp");
    const png = await sharp(brut)
      .resize(largeur, null, { fit: "inside", withoutEnlargement: true })
      .png()
      .toBuffer();
    return `data:image/png;base64,${png.toString("base64")}`;
  } catch {
    return null;
  }
}

export interface PlanJour {
  hippodrome: string;
  code: string;
  mise: number;
  retour: number;
}

/**
 * Le bilan d'UNE SEMAINE — l'unité de la mosaïque.
 *
 * Chaque tuile est publiée un dimanche différent et porte les chiffres de SA semaine.
 * La mosaïque terminée est donc une chronique de six semaines, chacune datée sur sa
 * tuile : sans cette date, six blocs de chiffres côte à côte seraient illisibles.
 */
export interface SemaineMosaique {
  /** « du 30 août au 5 septembre » — porté par chaque tuile. */
  periode: string;
  nbCourses: number;
  nbHippodromes: number;
  nbPlans: number;
  nbPlansGagnants: number;
  totalRetour: number;
  pctTop3: number | null;
  nbTop3: number;
  nbAnalysees: number;
  hasardTop3: number | null;
  pctTop1: number | null;
  nbPartants: number;
  meilleur: {
    hippodrome: string; code: string; mise: number; retour: number; net: number;
    typePari: string | null;
  } | null;
  meilleureJournee: {
    jourLong: string; nbCourses: number; nbTop3: number; pctTop3: number;
  } | null;
}

export interface DonneesMosaique {
  jourLong: string;
  jourCourt: string;
  semaine: SemaineMosaique;
  nbCourses: number;
  /** Nombre de PLANS publiés (courses × profils), pas de courses : la tuile qui
   *  porte les montants annonçait « les 66 plans du jour » en comptant les courses,
   *  alors que chaque course en produit un par profil. */
  nbPlans: number;
  nbReunions: number;
  plans: PlanJour[];
  photo: string | null;
  /** Le cheval du logo, en data URI. Recomposer le lockup en code plutôt que de
   *  tirer le PNG de 160 × 87 : à cette taille il baverait. */
  horse: string | null;
}

/**
 * Montants : les centimes ne s'affichent que s'il y en a.
 *
 * « 883,00 € » posé en 146 px traîne deux zéros qui ne disent rien et cassent la force du
 * nombre. « 883 € » frappe ; « 478,80 € » garde ses centimes parce qu'ils existent.
 */
const euro = (n: number) =>
  n.toLocaleString("fr-FR", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });

/** Pourcentages à la française : virgule décimale, jamais de point. */
const pourcent = (n: number) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/* ────────────────────────────── Fragments de composition ────────────────────────────── */

export function Eyebrow({ children, ton = "or" }: { children: string; ton?: "or" | "tenu" | "sombre" }) {
  const couleur =
    ton === "or" ? COULEURS.or : ton === "sombre" ? COULEURS.orVif : COULEURS.encreTenue;
  return (
    <span
      style={{
        fontFamily: "Inter",
        fontSize: 24,
        fontWeight: 600,
        letterSpacing: 3.4,
        color: couleur,
      }}
    >
      {children}
    </span>
  );
}

/**
 * La date de la journée présentée.
 *
 * Elle était posée en surtitre à 24 px, à la taille d'une étiquette : sur une vignette
 * de fil vue au pouce, elle disparaissait, et une publication de résultats dont on ne
 * lit pas le jour ne prouve plus rien — c'est même la première chose qu'on lui
 * reproche. Elle passe donc en Grotesk 46, sur une barre dorée qui la détache du reste
 * de la carte : elle se lit avant le titre, ce qui est l'ordre juste.
 */
export function DateDuJour({
  jour,
  ton = "clair",
  taille = "grand",
}: {
  jour: string;
  ton?: "clair" | "sombre";
  taille?: "grand" | "moyen";
}) {
  const px = taille === "grand" ? 46 : 34;
  return (
    <div style={{ display: "flex", alignItems: "center" }}>
      <div
        style={{
          display: "flex",
          width: taille === "grand" ? 8 : 6,
          height: px + 6,
          borderRadius: 4,
          background: COULEURS.orVif,
        }}
      />
      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: px,
          letterSpacing: -0.4,
          color: ton === "sombre" ? COULEURS.orVif : COULEURS.or,
          marginLeft: taille === "grand" ? 20 : 15,
        }}
      >
        {jour}
      </span>
    </div>
  );
}

/**
 * L'adresse du site, au pied de chaque tuile.
 *
 * Dans le fil, une tuile est vue seule : sans cette ligne, cinq publications sur six ne
 * disent nulle part où aller.
 */
export function Adresse({ ton = "clair" }: { ton?: "clair" | "sombre" }) {
  return (
    <div style={{ display: "flex", alignItems: "center" }}>
      <div style={{ display: "flex", width: 22, height: 3, background: COULEURS.orVif }} />
      <span
        style={{
          fontFamily: "Inter",
          fontWeight: 600,
          fontSize: 25,
          letterSpacing: 0.6,
          color: ton === "sombre" ? COULEURS.orVif : COULEURS.or,
          marginLeft: 14,
        }}
      >
        blackturf.fr
      </span>
    </div>
  );
}

/**
 * Un plan de la journée : ce qui a été misé, ce que le plan a rendu.
 *
 * Le vocabulaire n'est pas décoratif. Ces montants sont ceux d'un PLAN calculé et réglé
 * aux rapports réels du PMU — pas d'argent encaissé par quiconque. « Misé » et « rendu »
 * sont exacts ; « gain » ou « bénéfice » ne le seraient pas. Aucun multiplicateur n'est
 * affiché non plus : un « ×88 » sur un plan choisi parmi 46 se lirait comme une promesse.
 */
function LignePlan({ p, rang }: { p: PlanJour; rang: number }) {
  const vedette = rang === 1;
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: vedette ? 34 : 22 }}>
        <span
          style={{
            display: "flex",
            width: 42,
            height: 42,
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 9,
            background: vedette ? COULEURS.orVif : COULEURS.ivoire,
            color: vedette ? "#1B1405" : COULEURS.encreDouce,
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 23,
          }}
        >
          {rang}
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: vedette ? 34 : 30,
            color: COULEURS.encre,
            marginLeft: 18,
            letterSpacing: -0.6,
          }}
        >
          {p.hippodrome} · {p.code}
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "baseline" }}>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: vedette ? 46 : 38,
            color: COULEURS.encre,
            letterSpacing: -1.4,
          }}
        >
          {euro(p.mise)} €
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: vedette ? 27 : 24,
            color: COULEURS.encreDouce,
            marginLeft: 12,
          }}
        >
          misés
        </span>
      </div>

      <div style={{ display: "flex", alignItems: "center", marginTop: vedette ? 24 : 18 }}>
        <div style={{ display: "flex", width: vedette ? 54 : 40, height: 3, background: COULEURS.orVif }} />
        <span
          style={{
            fontFamily: "Inter",
            fontWeight: 600,
            fontSize: vedette ? 24 : 21,
            letterSpacing: 2.6,
            color: COULEURS.or,
            marginLeft: 14,
          }}
        >
          LE PLAN A RENDU
        </span>
      </div>

      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: vedette ? 168 : 94,
          lineHeight: 1,
          color: vedette ? COULEURS.or : COULEURS.encre,
          letterSpacing: -6,
          marginTop: vedette ? 16 : 12,
        }}
      >
        {euro(p.retour)} €
      </span>
    </div>
  );
}

export function Atout({ titre, texte }: { titre: string; texte: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", marginBottom: 40 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <div style={{ display: "flex", width: 11, height: 11, borderRadius: 6, background: COULEURS.orVif }} />
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 36,
            color: COULEURS.surSombre,
            marginLeft: 16,
            letterSpacing: -0.6,
          }}
        >
          {titre}
        </span>
      </div>
      <span
        style={{
          fontFamily: "Inter",
          fontSize: 26,
          lineHeight: 1.45,
          color: COULEURS.surSombreDoux,
          marginLeft: 27,
        }}
      >
        {texte}
      </span>
    </div>
  );
}

/** Carte blanche posée sur la photo. */
export function Carte({
  x,
  y,
  l,
  h,
  children,
}: {
  x: number;
  y: number;
  l: number;
  h: number;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        width: l,
        height: h,
        display: "flex",
        flexDirection: "column",
        background: COULEURS.blanc,
        borderRadius: 26,
        padding: "54px 58px",
        border: `1px solid ${COULEURS.ligne}`,
      }}
    >
      {children}
    </div>
  );
}

/**
 * Le plan d'ensemble, à l'échelle réelle. Chaque tuile en montre une fenêtre.
 *
 * TOUTES LES POSITIONS SONT ABSOLUES, exprimées dans l'espace du plan : c'est la seule
 * façon d'obtenir des raccords exacts. Un bloc posé « au fil du texte » se décalerait
 * d'une tuile à l'autre, et la mosaïque ne tomberait plus juste.
 */
/**
 * Une carte de bilan hebdomadaire — le contenu d'UNE tuile, et d'une seule semaine.
 *
 * Les six cartes sont identiques dans leur structure et différentes dans leurs
 * chiffres : chacune est publiée un dimanche différent et parle de SA semaine. C'est
 * ce qui rend l'image finale lisible — six blocs de même forme, six périodes datées —
 * là où six mises en page différentes auraient donné un patchwork.
 *
 * `ton` : clair sur la photo (rangée haute), sombre sur l'encre (rangée basse). Deux
 * registres pour un seul dessin ; c'est la CONTINUITÉ du fond, pas l'uniformité des
 * cartes, qui fait voir une seule image.
 */
/** Vert du gain. Assez profond pour tenir sur blanc, assez clair pour tenir sur encre. */
/** Vert du gain, calé pour un fond clair — le même que la story. */
const VERT_GAIN = "#177A4C";

/** Les six tuiles, dans l'ORDRE DE PUBLICATION (à l'envers de l'ordre de lecture). */
const ORDRE_TUILES = ["1-2", "1-1", "1-0", "0-2", "0-1", "0-0"] as const;

/** Surtitre doré encadré de deux filets — le motif qui rythme la carte. */
function Surtitre({ children }: { children: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", width: "100%" }}>
      <div style={{ display: "flex", flex: 1, height: 1, background: "rgba(224,166,60,0.34)" }} />
      <span
        style={{
          fontFamily: "Inter", fontWeight: 600, fontSize: 21, letterSpacing: 3.2,
          color: COULEURS.orVif, margin: "0 18px",
        }}
      >
        {children}
      </span>
      <div style={{ display: "flex", flex: 1, height: 1, background: "rgba(224,166,60,0.34)" }} />
    </div>
  );
}

/** Une colonne du bandeau de volume : un nombre, deux lignes de légende. */
function Chiffre({ valeur, unite, legende }: { valeur: string; unite?: string; legende: string[] }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", width: 258 }}>
      <div style={{ display: "flex", alignItems: "baseline" }}>
        <span
          style={{
            fontFamily: "Grotesk", fontWeight: 700, fontSize: 46,
            color: COULEURS.encre, letterSpacing: -1.6,
          }}
        >
          {valeur}
        </span>
        {unite ? (
          <span
            style={{
              fontFamily: "Grotesk", fontWeight: 700, fontSize: 24,
              color: COULEURS.or, marginLeft: 4,
            }}
          >
            {unite}
          </span>
        ) : null}
      </div>
      {legende.map((l, i) => (
        <span
          key={i}
          style={{
            fontFamily: "Inter", fontSize: 20, lineHeight: 1.3,
            color: COULEURS.encreDouce, marginTop: i === 0 ? 6 : 0,
          }}
        >
          {l}
        </span>
      ))}
    </div>
  );
}

/**
 * Une carte de bilan hebdomadaire — le contenu d'UNE tuile, et d'une seule semaine.
 *
 * Elle reprend, en 4:5, le dessin de la story quotidienne : logo, période, taux de
 * Top 3 en tête, bandeau de volume, l'argent, l'adresse et le renvoi vers la bio.
 * Une même marque ne doit pas parler deux langues visuelles selon le format.
 *
 * LA HIÉRARCHIE EST VOULUE : la période, puis la qualité de CLASSEMENT, puis
 * l'argent. Le chiffre de tête n'est pas un gain — c'est le seul que le site puisse
 * défendre dans la durée, et il n'est jamais publié sans son dénominateur ni sans le
 * repère du hasard : « 65,1 % » seul ne dit pas au lecteur ce qu'il bat.
 *
 * FOND SOMBRE TRANSLUCIDE sur les SIX cartes, et pas trois blanches puis trois
 * noires : la photo passe derrière toutes, ce qui est précisément ce qui fait voir
 * une seule image au lieu de six vignettes.
 */
function CarteSemaine({
  s, rang, total, horse,
}: {
  s: SemaineMosaique; rang: number; total: number; horse: string | null;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: "100%",
        height: "100%",
        // Verre sombre : la photo reste lisible derrière, le texte reste lisible devant.
        background: COULEURS.ivoire,
        borderRadius: 30,
        padding: "44px 48px",
        border: `1px solid ${COULEURS.ligne}`,
      }}
    >
      {/* ── La marque, et le rang dans la série ──────────────────────────── */}
      <div
        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}
      >
        <div style={{ display: "flex", alignItems: "center" }}>
          <div
            style={{
              display: "flex", alignItems: "center", justifyContent: "center",
              width: 62, height: 62, borderRadius: 31,
              border: `2px solid ${COULEURS.or}`,
            }}
          >
            {horse ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={horse} alt="" width={42} height={26} />
            ) : null}
          </div>
          <div style={{ display: "flex", alignItems: "baseline", marginLeft: 14 }}>
            <span
              style={{
                fontFamily: "Grotesk", fontWeight: 700, fontSize: 27,
                letterSpacing: 1.6, color: COULEURS.encre,
              }}
            >
              BLACK
            </span>
            <span
              style={{
                fontFamily: "Grotesk", fontWeight: 700, fontSize: 27,
                letterSpacing: 1.6, color: COULEURS.or,
              }}
            >
              TURF
            </span>
          </div>
        </div>
        <span
          style={{
            fontFamily: "Inter", fontWeight: 600, fontSize: 20, letterSpacing: 2.4,
            color: COULEURS.or,
          }}
        >
          SEMAINE {rang} / {total}
        </span>
      </div>

      {/* ── La période ──────────────────────────────────────────────────── */}
      <div style={{ display: "flex", marginTop: 24 }}>
        <Surtitre>PERFORMANCE DE LA SEMAINE</Surtitre>
      </div>
      <span
        style={{
          fontFamily: "Grotesk", fontWeight: 700, fontSize: 38,
          color: COULEURS.encre, letterSpacing: -1, marginTop: 12,
        }}
      >
        {s.periode}
      </span>

      {/* ── Le chiffre de tête ─────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "baseline", marginTop: 18 }}>
        <span
          style={{
            fontFamily: "Grotesk", fontWeight: 700, fontSize: 116, lineHeight: 1,
            color: COULEURS.encre, letterSpacing: -5,
          }}
        >
          {s.pctTop3 !== null ? pourcent(s.pctTop3) : "—"}
        </span>
        <span
          style={{
            fontFamily: "Grotesk", fontWeight: 700, fontSize: 48,
            color: COULEURS.or, marginLeft: 5,
          }}
        >
          %
        </span>
      </div>
      <span
        style={{
          fontFamily: "Grotesk", fontWeight: 700, fontSize: 33, lineHeight: 1.2,
          color: COULEURS.encre, letterSpacing: -0.8, marginTop: 6,
        }}
      >
        des courses où le gagnant
      </span>
      <span
        style={{
          fontFamily: "Grotesk", fontWeight: 700, fontSize: 33, lineHeight: 1.2,
          color: COULEURS.encre, letterSpacing: -0.8,
        }}
      >
        était dans notre Top 3
      </span>
      <span
        style={{
          fontFamily: "Inter", fontSize: 21, lineHeight: 1.4,
          color: COULEURS.encreDouce, marginTop: 12,
        }}
      >
        {s.nbTop3} sur {s.nbAnalysees} courses analysées
        {s.hasardTop3 !== null ? ` · le hasard : ${pourcent(s.hasardTop3)} %` : ""}
      </span>

      {/* ── Le volume de la semaine ─────────────────────────────────────── */}
      <div
        style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          width: "100%", marginTop: 22,
        }}
      >
        <Chiffre
          valeur={s.pctTop1 !== null ? pourcent(s.pctTop1) : "—"}
          unite={s.pctTop1 !== null ? "%" : undefined}
          legende={["notre favori a gagné"]}
        />
        <div style={{ display: "flex", width: 1, height: 62, background: COULEURS.ligne }} />
        <Chiffre valeur={s.nbPartants.toLocaleString("fr-FR").replace(/[  ]/g, " ")}
                 legende={["partants analysés"]} />
        <div style={{ display: "flex", width: 1, height: 62, background: COULEURS.ligne }} />
        <Chiffre valeur={String(s.nbHippodromes)} legende={["hippodromes couverts"]} />
      </div>

      <div
        style={{
          display: "flex", width: "100%", height: 1,
          background: COULEURS.ligne, marginTop: 22,
        }}
      />

      {/* ── L'argent : le meilleur gain, puis le total ──────────────────── */}
      <div style={{ display: "flex", marginTop: 20 }}>
        <Surtitre>MEILLEUR GAIN DE LA SEMAINE</Surtitre>
      </div>
      {s.meilleur ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 12 }}>
          <div style={{ display: "flex", alignItems: "baseline" }}>
            <span
              style={{
                fontFamily: "Grotesk", fontWeight: 700, fontSize: 40,
                color: COULEURS.encreTenue, letterSpacing: -1,
              }}
            >
              {euro(s.meilleur.mise)} €
            </span>
            <span style={{ fontFamily: "Inter", fontSize: 30, color: COULEURS.or, margin: "0 16px" }}>
              →
            </span>
            <span
              style={{
                fontFamily: "Grotesk", fontWeight: 700, fontSize: 62,
                color: VERT_GAIN, letterSpacing: -2.2,
              }}
            >
              {euro(s.meilleur.retour)} €
            </span>
          </div>
          <span
            style={{
              fontFamily: "Inter", fontSize: 21, color: COULEURS.encreDouce, marginTop: 6,
            }}
          >
            {[s.meilleur.typePari, s.meilleur.hippodrome, s.meilleur.code]
              .filter(Boolean)
              .join(" · ")}
          </span>
        </div>
      ) : (
        <span
          style={{ fontFamily: "Inter", fontSize: 21, color: COULEURS.encreDouce, marginTop: 12 }}
        >
          Aucun plan gagnant cette semaine.
        </span>
      )}

      {/* Le nombre de plans GAGNANTS ne sort jamais sans le nombre TOTAL calculé :
          sans dénominateur, la phrase se lirait comme si tous avaient gagné. */}
      <div style={{ display: "flex", alignItems: "baseline", marginTop: 18 }}>
        <span style={{ fontFamily: "Inter", fontSize: 22, color: COULEURS.encreDouce }}>
          Total rendu par les plans
        </span>
        <span
          style={{
            fontFamily: "Grotesk", fontWeight: 700, fontSize: 38,
            color: COULEURS.or, letterSpacing: -1.4, marginLeft: 14,
          }}
        >
          {euro(s.totalRetour)} €
        </span>
      </div>
      <span
        style={{ fontFamily: "Inter", fontSize: 20, color: COULEURS.encreTenue, marginTop: 4 }}
      >
        {s.nbPlansGagnants} plans gagnants sur les {s.nbPlans} calculés · {s.nbCourses} courses
      </span>

      {/* ── Où aller ───────────────────────────────────────────────────────
          L'API de Meta ne sait pas poser de sticker de lien : une publication
          automatique sort forcément sans bouton cliquable. Le seul chemin qui reste
          est le lien de profil — encore faut-il le DIRE, sinon l'adresse écrite dans
          la pastille ne se retape pas. */}
      <div
        style={{
          display: "flex", alignItems: "center", justifyContent: "center",
          padding: "16px 38px", borderRadius: 40, background: COULEURS.encre,
          marginTop: "auto",
        }}
      >
        <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 30, color: COULEURS.surSombre }}>
          black
        </span>
        <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 30, color: COULEURS.orVif }}>
          turf.fr
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", marginTop: 10 }}>
        <span style={{ fontFamily: "Inter", fontSize: 21, color: COULEURS.or }}>↑</span>
        <span
          style={{
            fontFamily: "Inter", fontWeight: 600, fontSize: 21,
            color: COULEURS.encreDouce, marginLeft: 8,
          }}
        >
          Lien direct dans la bio
        </span>
      </div>
    </div>
  );
}

/**
 * Le plan d'ensemble : SIX BILANS DE SEMAINE qui forment une seule image.
 *
 * Chaque tuile est publiée un dimanche et porte les chiffres de sa semaine. Au bout
 * de six dimanches, la grille du profil montre l'image entière.
 *
 * CE QUI FAIT L'UNITÉ : une SEULE photo, sur toute la surface du plan — pas une
 * bande en haut et un aplat en bas. Les six cartes de verre sombre flottent dessus,
 * et c'est le paysage continu derrière elles qui recolle les six vignettes. Une
 * rangée noire aurait coupé l'image en deux, ce qui est exactement le défaut qu'une
 * mosaïque doit éviter.
 *
 * LA PHOTO EST FIXÉE PAR CYCLE (`photoDuCycle`) et non par jour : les tuiles sont
 * publiées à six dimanches d'écart et doivent montrer la même image, sinon les
 * raccords ne tombent jamais juste.
 */
export function PlanEnsemble({ d }: { d: DonneesMosaique }) {
  const col = (c: number) => DEBORD + c * VISIBLE_L;

  // Les cartes laissent de la photo visible autour d'elles : sans cette respiration,
  // la mosaïque se lirait comme six vignettes collées, pas comme une image.
  const CARTE_X = 52;
  const CARTE_L = VISIBLE_L - CARTE_X * 2;
  const CARTE_Y = 96;
  const CARTE_H = 1090;

  const s = d.semaine;

  return (
    <div
      style={{
        display: "flex",
        position: "relative",
        width: PLAN_L,
        height: PLAN_H,
        background: COULEURS.encre,
      }}
    >
      {d.photo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={d.photo}
          alt=""
          width={PLAN_L}
          height={PLAN_H}
          style={{ position: "absolute", left: 0, top: 0, objectFit: "cover" }}
        />
      )}
      {/* Voile sombre : la photo doit rester une photo, pas devenir une texture — mais
          sans lui, les cartes de verre n'auraient aucun contraste sur les parties
          claires du ciel ou de la piste. */}
      <div
        style={{
          position: "absolute", left: 0, top: 0, width: PLAN_L, height: PLAN_H,
          // Voile IVOIRE et non sombre : les cartes sont claires, un voile noir les
          // ferait flotter sur un trou. Il éclaircit la photo juste assez pour que le
          // blanc des cartes ne paraisse pas sale, sans la transformer en texture.
          display: "flex", background: "rgba(245,242,234,0.30)",
        }}
      />

      {/* ═══════════ Les six bilans ═══════════
          `rang` suit l'ORDRE DE PUBLICATION, pas l'ordre de lecture : Instagram empile
          de la plus récente à la plus ancienne, en haut à gauche. La première publiée
          (semaine 1) se retrouve donc en bas à droite. */}
      {ORDRE_TUILES.map((cle, i) => {
        const [r, c] = cle.split("-").map(Number);
        return (
          <div
            key={cle}
            style={{
              position: "absolute",
              left: col(c) + CARTE_X,
              top: r * TUILE_H + CARTE_Y,
              width: CARTE_L,
              height: CARTE_H,
              display: "flex",
            }}
          >
            <CarteSemaine s={s} rang={i + 1} total={ORDRE_TUILES.length} horse={d.horse} />
          </div>
        );
      })}

      {/* Fondu sombre au pied de chaque tuile : la mention légale se posait sur la
          photo nue et devenait illisible dès que le fond y était clair. Une mention
          de jeu responsable qu'on ne peut pas lire ne vaut pas mieux qu'une absente. */}
      {[0, 1].map((r) => (
        <div
          key={"voile-" + r}
          style={{
            position: "absolute", left: 0, top: r * TUILE_H + TUILE_H - 210,
            width: PLAN_L, height: 210, display: "flex",
            background: "linear-gradient(180deg, rgba(245,242,234,0) 0%, rgba(245,242,234,0.88) 55%, rgba(245,242,234,0.97) 100%)",
          }}
        />
      ))}

      {/* ═══════════ Mention légale, sur chaque tuile ═══════════
          Chaque tuile est publiée séparément : la mention se répète, elle ne se
          découpe pas. */}
      {[0, 1].map((r) =>
        [0, 1, 2].map((c) => (
          <div
            key={`legal-${r}-${c}`}
            style={{
              position: "absolute",
              left: col(c) + MARGE_LEGALE,
              top: r * TUILE_H + TUILE_H - 128,
              width: VISIBLE_L - MARGE_LEGALE * 2,
              display: "flex",
            }}
          >
            <span
              style={{
                fontFamily: "Inter", fontSize: 21, lineHeight: 1.4,
                color: COULEURS.encreTenue,
              }}
            >
              Les résultats passés ne préjugent pas des résultats futurs. Jouer comporte des
              risques : endettement, isolement, dépendance. 09 74 75 13 13. Interdit aux mineurs.
            </span>
          </div>
        )),
      )}
    </div>
  );
}

/** Marge des mentions légales : elles courent d'un bord à l'autre de la colonne
 *  visible, pas dans une carte. */
const MARGE_LEGALE = 72;
export function Tuile({ d, rangee, colonne }: { d: DonneesMosaique; rangee: number; colonne: number }) {
  return (
    <div
      style={{
        display: "flex",
        position: "relative",
        width: TUILE_L,
        height: TUILE_H,
        overflow: "hidden",
        background: COULEURS.ivoire,
      }}
    >
      <div
        style={{
          display: "flex",
          position: "absolute",
          left: -colonne * VISIBLE_L,
          top: -rangee * TUILE_H,
        }}
      >
        <PlanEnsemble d={d} />
      </div>
    </div>
  );
}
