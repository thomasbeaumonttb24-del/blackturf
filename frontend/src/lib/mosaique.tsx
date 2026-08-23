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
 * ─────────────────────────── UNE SEULE PHOTO, DÉCOUPÉE EN SIX ──────────────────────────
 *
 * La photo de course couvre le plan ENTIER : c'est elle qui fait la mosaïque. Sans elle,
 * six vignettes sombres côte à côte ne se lisent pas comme une image unique. Elle est
 * assombrie et voilée de dégradés là où le texte se pose, sans quoi rien ne serait
 * lisible sur un peloton en pleine lumière.
 *
 * ─────────────────────────── CHAQUE TUILE DOIT TENIR SEULE ─────────────────────────────
 *
 * Une mosaïque ne se lit qu'à une seule adresse : la grille du profil. Dans le fil, un
 * abonné ne voit qu'une tuile isolée. Chaque tuile porte donc son propre bloc de contenu
 * complet, tandis que la photo, la règle dorée et le bandeau légal courent d'une tuile à
 * l'autre pour que l'ensemble se recompose sur le profil.
 */

export const TUILE_L = 1080;
export const TUILE_H = 1350;
/** Largeur réellement visible d'une tuile sur la grille (rognage 3:4). */
export const VISIBLE_L = 1012;
export const DEBORD = (TUILE_L - VISIBLE_L) / 2; // 34
export const PLAN_L = DEBORD * 2 + VISIBLE_L * 3; // 3104
export const PLAN_H = TUILE_H * 2; // 2700

export const COULEURS = {
  fond: "#08090C",
  fondClair: "#141821",
  encre: "#F7F6F1",
  encreDouce: "#A7AEBA",
  or: "#E0A63C",
  orVif: "#F5C766",
  ligne: "#2A3140",
} as const;

/**
 * Photos de course, tournantes.
 *
 * Ce sont les photos du site, pas des images fabriquées : une marque qui vend de la
 * rigueur ne s'illustre pas avec un cheval qui n'existe pas. Le choix suit le quantième,
 * donc change à chaque série — publier la même image tous les jours lasserait en trois
 * jours.
 */
const PHOTOS = [
  "showcase.webp", // peloton en pleine course
  "duel.webp", // duel à l'arrivée
  "hero-1600.webp", // départ, portes numérotées
  "value.jpg", // piste au soleil couchant
  "cta.jpg", // arrivée devant le public
] as const;

export function photoDuJour(jour: string): string {
  const n = Number(jour.slice(8, 10)) || 1;
  return PHOTOS[n % PHOTOS.length];
}

/**
 * Charge une photo du dossier public et la renvoie en data URI JPEG, au format du plan.
 *
 * Deux raisons de passer par une conversion :
 * - Satori ne sait pas décoder le WebP, et la moitié des photos du site le sont ;
 * - la photo doit couvrir un plan très large (3104 × 2700) ; recadrée par `sharp` avec
 *   détection du sujet, les chevaux restent au centre au lieu d'être coupés.
 *
 * En cas d'échec on renvoie null : la composition se contente alors de son fond sombre.
 * Un visuel sans photo reste publiable, un visuel qui plante non.
 */
export async function photoEnDataUri(fichier: string): Promise<string | null> {
  try {
    const chemin = path.join(process.cwd(), "public", "img", fichier);
    const brut = await fs.readFile(chemin);
    const { default: sharp } = await import("sharp");
    const jpeg = await sharp(brut)
      .resize(1800, 1566, { fit: "cover", position: "attention" })
      .modulate({ brightness: 1.22, saturation: 0.86 })
      .jpeg({ quality: 78 })
      .toBuffer();
    return `data:image/jpeg;base64,${jpeg.toString("base64")}`;
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

export interface DonneesMosaique {
  jourLong: string;
  jourCourt: string;
  nbCourses: number;
  nbReunions: number;
  plans: PlanJour[];
  photo: string | null;
}

const euro = (n: number) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/* ────────────────────────────── Fragments de composition ────────────────────────────── */

function Marque({ taille = 46 }: { taille?: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center" }}>
      <div style={{ display: "flex", width: taille / 3.2, height: taille, background: COULEURS.or }} />
      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: taille,
          color: COULEURS.encre,
          marginLeft: taille / 2.6,
          letterSpacing: -1,
        }}
      >
        BlackTurf
      </span>
    </div>
  );
}

function Eyebrow({ children }: { children: string }) {
  return (
    <span style={{ fontFamily: "Inter", fontSize: 25, color: COULEURS.or, letterSpacing: 3.5 }}>
      {children}
    </span>
  );
}

/**
 * Un plan de la journée : ce qui a été misé, ce que le plan a rendu.
 *
 * Le vocabulaire n'est pas décoratif. Ces montants sont ceux d'un PLAN calculé et réglé
 * aux rapports réels du PMU — pas d'argent encaissé par quiconque. « Misé » et « rendu »
 * sont exacts ; « gain » ou « bénéfice » ne le seraient pas.
 */
function LignePlan({ p, rang }: { p: PlanJour; rang: number }) {
  const vedette = rang === 1;
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 16 }}>
        <span
          style={{
            display: "flex",
            width: 42,
            height: 42,
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 9,
            background: vedette ? COULEURS.or : "rgba(255,255,255,0.10)",
            color: vedette ? "#1B1405" : COULEURS.encreDouce,
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 23,
          }}
        >
          {rang}
        </span>
        <span style={{ fontFamily: "Inter", fontSize: 28, color: COULEURS.encre, marginLeft: 18 }}>
          {p.hippodrome} · {p.code}
        </span>
      </div>

      <span style={{ fontFamily: "Inter", fontSize: vedette ? 32 : 27, color: COULEURS.encreDouce }}>
        {euro(p.mise)} € misés
      </span>
      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: vedette ? 138 : 88,
          lineHeight: 1,
          color: vedette ? COULEURS.orVif : COULEURS.encre,
          letterSpacing: -5,
          marginTop: 10,
        }}
      >
        {euro(p.retour)} €
      </span>
      <span style={{ fontFamily: "Inter", fontSize: 25, color: COULEURS.encreDouce, marginTop: 12 }}>
        rendus par le plan
      </span>
    </div>
  );
}

function Atout({ titre, texte }: { titre: string; texte: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", marginBottom: 42 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <div style={{ display: "flex", width: 10, height: 10, borderRadius: 5, background: COULEURS.or }} />
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 35,
            color: COULEURS.encre,
            marginLeft: 16,
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
          color: COULEURS.encreDouce,
          marginLeft: 26,
        }}
      >
        {texte}
      </span>
    </div>
  );
}

/**
 * Le plan d'ensemble, à l'échelle réelle. Chaque tuile en montre une fenêtre.
 *
 * TOUTES LES POSITIONS SONT ABSOLUES, exprimées dans l'espace du plan : c'est la seule
 * façon d'obtenir des raccords exacts. Un bloc posé « au fil du texte » se décalerait
 * d'une tuile à l'autre.
 *
 * Le rythme vertical est calé pour qu'aucune vignette ne soit à moitié vide : un premier
 * rendu laissait un tiers de vide sous chaque bloc, ce qui saute aux yeux sur une grille
 * où les six vignettes se touchent.
 */
export function PlanEnsemble({ d }: { d: DonneesMosaique }) {
  const col = (c: number) => DEBORD + c * VISIBLE_L;
  const MARGE = 76;
  const utile = VISIBLE_L - MARGE * 2;
  const bas = TUILE_H;
  const BANDEAU = PLAN_H - 190;

  const [p1, p2, p3] = d.plans;

  return (
    <div
      style={{
        display: "flex",
        position: "relative",
        width: PLAN_L,
        height: PLAN_H,
        background: COULEURS.fond,
      }}
    >
      {/* ── La photo de course, sur le plan ENTIER : c'est elle, la mosaïque ── */}
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
      {/* ── LES VOILES ────────────────────────────────────────────────────────────────
          Un seul dégradé du haut vers le bas noyait la photo : on ne distinguait plus
          les chevaux, alors qu'ils sont le sujet. Le voile suit donc le TEXTE — dense en
          haut de chaque rangée, où se posent les blocs, et levé en bas, où la photo
          respire. Ce qui paraissait vide devient de l'image. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: PLAN_L,
          height: TUILE_H,
          display: "flex",
          background:
            "linear-gradient(180deg, rgba(8,9,12,0.90) 0%, rgba(8,9,12,0.84) 46%, rgba(8,9,12,0.52) 76%, rgba(8,9,12,0.30) 100%)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: bas,
          width: PLAN_L,
          height: TUILE_H,
          display: "flex",
          background:
            "linear-gradient(180deg, rgba(8,9,12,0.93) 0%, rgba(8,9,12,0.88) 52%, rgba(8,9,12,0.55) 78%, rgba(8,9,12,0.28) 100%)",
        }}
      />
      {/* Renfort latéral gauche : la première colonne porte le plus de texte. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: VISIBLE_L + DEBORD,
          height: PLAN_H,
          display: "flex",
          background:
            "linear-gradient(90deg, rgba(8,9,12,0.82) 0%, rgba(8,9,12,0.40) 74%, rgba(8,9,12,0) 100%)",
        }}
      />

      {/* Règle dorée à cheval sur les deux rangées : le raccord qui prouve à l'œil que
          les six vignettes n'en font qu'une. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: bas - 3,
          width: PLAN_L,
          height: 6,
          display: "flex",
          background:
            "linear-gradient(90deg, rgba(224,166,60,0) 0%, #E0A63C 20%, #F5C766 50%, #E0A63C 80%, rgba(224,166,60,0) 100%)",
        }}
      />

      {/* ═══════════ (0,0) — identité, date, volume ═══════════ */}
      <div style={{ position: "absolute", left: col(0) + MARGE, top: 118, display: "flex" }}>
        <Marque />
      </div>
      <div
        style={{
          position: "absolute",
          left: col(0) + MARGE,
          top: 300,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Eyebrow>RÉSULTATS PMU</Eyebrow>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 80,
            lineHeight: 1.06,
            color: COULEURS.encre,
            marginTop: 22,
            letterSpacing: -2.5,
          }}
        >
          {d.jourLong}
        </span>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(0) + MARGE,
          top: 624,
          display: "flex",
          width: 128,
          height: 4,
          background: COULEURS.or,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: col(0) + MARGE,
          top: 704,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 190,
            lineHeight: 0.94,
            color: COULEURS.encre,
            letterSpacing: -8,
          }}
        >
          {d.nbCourses}
        </span>
        <span style={{ fontFamily: "Inter", fontSize: 32, color: COULEURS.encreDouce, marginTop: 12 }}>
          courses analysées, {d.nbReunions} réunions
        </span>
      </div>
      <div style={{ position: "absolute", left: col(0) + MARGE, top: 1096, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 26, lineHeight: 1.5, color: COULEURS.encreDouce }}>
          Arrivées et rapports officiels, course par course, en accès libre.
        </span>
      </div>

      {/* ═══════════ (0,1) — le meilleur plan du jour ═══════════ */}
      <div style={{ position: "absolute", left: col(1) + MARGE, top: 118, width: utile, display: "flex" }}>
        <Eyebrow>LE MEILLEUR PLAN DU JOUR</Eyebrow>
      </div>
      {p1 && (
        <div
          style={{
            position: "absolute",
            left: col(1) + MARGE,
            top: 262,
            width: utile,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <LignePlan p={p1} rang={1} />
        </div>
      )}
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: 1046,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", width: 72, height: 3, background: COULEURS.ligne }} />
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 25,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 26,
          }}
        >
          Plan calculé avant le départ, réglé aux rapports officiels du PMU.
        </span>
      </div>

      {/* ═══════════ (0,2) — les deux suivants ═══════════ */}
      <div style={{ position: "absolute", left: col(2) + MARGE, top: 118, width: utile, display: "flex" }}>
        <Eyebrow>LES DEUX SUIVANTS</Eyebrow>
      </div>
      {p2 && (
        <div
          style={{
            position: "absolute",
            left: col(2) + MARGE,
            top: 262,
            width: utile,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <LignePlan p={p2} rang={2} />
        </div>
      )}
      {p3 && (
        <div
          style={{
            position: "absolute",
            left: col(2) + MARGE,
            top: 706,
            width: utile,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <LignePlan p={p3} rang={3} />
        </div>
      )}
      <div style={{ position: "absolute", left: col(2) + MARGE, top: 1160, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 25, lineHeight: 1.5, color: COULEURS.encreDouce }}>
          Trois plans parmi les {d.nbCourses} courses du jour.
        </span>
      </div>

      {/* ═══════════ (1,0) — ce que fait le site ═══════════ */}
      <div
        style={{ position: "absolute", left: col(0) + MARGE, top: bas + 128, width: utile, display: "flex" }}
      >
        <Eyebrow>CE QUE FAIT BLACKTURF</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(0) + MARGE,
          top: bas + 258,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Atout
          titre="Le programme, analysé"
          texte="80 critères par cheval, une probabilité calculée pour chaque partant, avant le départ."
        />
        <Atout
          titre="Un plan sur votre budget"
          texte="Vous entrez votre mise, le plan de jeu se calcule dessus. Pas de ticket type."
        />
        <Atout
          titre="Les cotes comparées"
          texte="PMU et principaux opérateurs côte à côte, pour repérer où la cote décroche."
        />
        <Atout
          titre="Le bilan, publié"
          texte="Chaque pronostic est noté aux rapports réels du PMU. Les jours rouges aussi."
        />
      </div>

      {/* ═══════════ (1,1) — l'argument que personne d'autre ne tient ═══════════ */}
      <div
        style={{ position: "absolute", left: col(1) + MARGE, top: bas + 128, width: utile, display: "flex" }}
      >
        <Eyebrow>CE QU&apos;ON NE VOUS DIRA PAS AILLEURS</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 256,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Espace fine insécable entre le nombre et le signe : « 20 % » se coupait en fin
            de ligne, le pourcentage se retrouvant seul sur la ligne suivante. */}
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 74,
            lineHeight: 1.13,
            color: COULEURS.encre,
            letterSpacing: -2,
          }}
        >
          Le PMU prélève environ 20&#8239;% des enjeux.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 28,
            lineHeight: 1.55,
            color: COULEURS.encreDouce,
            marginTop: 54,
          }}
        >
          Personne ne peut promettre un gain régulier là-dessus. Ce qui se mesure, c&apos;est
          l&apos;écart entre la probabilité réelle d&apos;un cheval et celle qu&apos;implique sa
          cote.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 28,
            lineHeight: 1.55,
            color: COULEURS.encre,
            marginTop: 42,
          }}
        >
          C&apos;est ce que BlackTurf calcule, course par course — et ce qu&apos;il publie
          ensuite, résultat en main.
        </span>
      </div>

      {/* ═══════════ (1,2) — la conversion ═══════════ */}
      <div
        style={{ position: "absolute", left: col(2) + MARGE, top: bas + 128, width: utile, display: "flex" }}
      >
        <Eyebrow>ESSAYER</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 250,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 98,
            lineHeight: 1.04,
            color: COULEURS.encre,
            letterSpacing: -3,
          }}
        >
          7 jours offerts
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 28,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 30,
          }}
        >
          Programme et rapports en accès libre. Prédictions, paris de valeur et plan de mise
          à partir de 12&#8239;€/mois.
        </span>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 640,
          width: utile,
          display: "flex",
          flexDirection: "column",
          padding: "40px 44px",
          borderRadius: 20,
          background: COULEURS.or,
        }}
      >
        <span style={{ fontFamily: "Inter", fontSize: 25, color: "#3A2A08" }}>Tout est sur</span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 68,
            color: "#1B1405",
            marginTop: 6,
            letterSpacing: -2,
          }}
        >
          blackturf.fr
        </span>
      </div>

      {/* ═══════════ Bandeau légal continu, sur les trois colonnes ═══════════
          Il remplit le bas des trois vignettes basses — vides au premier rendu — et
          renforce l'effet « une seule image » puisqu'il les traverse. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: BANDEAU - 34,
          width: PLAN_L,
          height: PLAN_H - BANDEAU + 34,
          display: "flex",
          background: "rgba(8,9,12,0.88)",
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: BANDEAU,
          width: PLAN_L,
          height: 2,
          display: "flex",
          background: COULEURS.ligne,
        }}
      />
      <div style={{ position: "absolute", left: col(0) + MARGE, top: BANDEAU + 44, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 24, lineHeight: 1.45, color: COULEURS.encreDouce }}>
          Jouer comporte des risques : endettement, isolement, dépendance.
        </span>
      </div>
      <div style={{ position: "absolute", left: col(1) + MARGE, top: BANDEAU + 44, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 24, lineHeight: 1.45, color: COULEURS.encreDouce }}>
          09 74 75 13 13 — appel non surtaxé. Interdit aux mineurs.
        </span>
      </div>
      <div style={{ position: "absolute", left: col(2) + MARGE, top: BANDEAU + 44, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 24, lineHeight: 1.45, color: COULEURS.encreDouce }}>
          BlackTurf est un outil d&apos;aide à la décision, pas une garantie de gain.
        </span>
      </div>
    </div>
  );
}

/** Enveloppe d'une tuile : une fenêtre 1080 × 1350 ouverte sur le plan d'ensemble. */
export function Tuile({ d, rangee, colonne }: { d: DonneesMosaique; rangee: number; colonne: number }) {
  return (
    <div
      style={{
        display: "flex",
        position: "relative",
        width: TUILE_L,
        height: TUILE_H,
        overflow: "hidden",
        background: COULEURS.fond,
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
