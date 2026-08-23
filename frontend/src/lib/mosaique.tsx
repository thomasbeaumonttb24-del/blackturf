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
 * ─────────────────────────── POURQUOI CETTE VERSION EST CLAIRE ─────────────────────────
 *
 * Une première version posait le texte en blanc sur une photo très assombrie. Elle avait
 * deux torts : la photo de course n'était plus lisible alors qu'elle est le sujet, et
 * l'ensemble jurait avec le site, qui est blanc et or. La composition est donc claire —
 * fond ivoire, encre sombre, or profond — et la photo garde sa lumière.
 *
 * La continuité de l'image tient à trois choses : la photo traverse toute la rangée
 * haute, un dégradé la fond dans l'ivoire de la rangée basse, et le bandeau légal court
 * d'un bord à l'autre. Les cartes blanches ne remplissent jamais toute la largeur d'une
 * colonne : la photo respire entre elles, et c'est ce qui fait voir une seule image.
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
 * En cas d'échec on renvoie null : la composition se contente alors de son fond ivoire.
 * Un visuel sans photo reste publiable, un visuel qui plante non.
 */
export async function photoEnDataUri(fichier: string): Promise<string | null> {
  try {
    const chemin = path.join(process.cwd(), "public", "img", fichier);
    const brut = await fs.readFile(chemin);
    const { default: sharp } = await import("sharp");
    const jpeg = await sharp(brut)
      .resize(1800, 900, { fit: "cover", position: "attention" })
      .modulate({ brightness: 1.18, saturation: 1.02 })
      .jpeg({ quality: 82 })
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

function Eyebrow({ children, sur = "clair" }: { children: string; sur?: "clair" | "or" }) {
  return (
    <span
      style={{
        fontFamily: "Inter",
        fontSize: 24,
        fontWeight: 600,
        letterSpacing: 3.4,
        color: sur === "or" ? COULEURS.or : COULEURS.encreTenue,
      }}
    >
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
      <div style={{ display: "flex", alignItems: "center", marginBottom: 18 }}>
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
        <span style={{ fontFamily: "Inter", fontSize: 28, color: COULEURS.encre, marginLeft: 18 }}>
          {p.hippodrome} · {p.code}
        </span>
      </div>

      <span style={{ fontFamily: "Inter", fontSize: vedette ? 31 : 26, color: COULEURS.encreDouce }}>
        {euro(p.mise)} € misés
      </span>
      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: vedette ? 132 : 84,
          lineHeight: 1,
          color: vedette ? COULEURS.or : COULEURS.encre,
          letterSpacing: -5,
          marginTop: 10,
        }}
      >
        {euro(p.retour)} €
      </span>
      <span style={{ fontFamily: "Inter", fontSize: 24, color: COULEURS.encreDouce, marginTop: 12 }}>
        rendus par le plan
      </span>
    </div>
  );
}

function Atout({ titre, texte }: { titre: string; texte: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", marginBottom: 56 }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
        <div style={{ display: "flex", width: 11, height: 11, borderRadius: 6, background: COULEURS.orVif }} />
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
          marginLeft: 27,
        }}
      >
        {texte}
      </span>
    </div>
  );
}

/** Carte blanche posée sur la photo. */
function Carte({
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
        padding: "56px 58px",
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
export function PlanEnsemble({ d }: { d: DonneesMosaique }) {
  const col = (c: number) => DEBORD + c * VISIBLE_L;
  const MARGE = 76;
  const utile = VISIBLE_L - MARGE * 2;
  const bas = TUILE_H;
  const BANDEAU = PLAN_H - 168;

  // Les cartes laissent volontairement de la photo visible autour d'elles : sans cette
  // respiration, la rangée haute se lirait comme trois vignettes séparées.
  const CARTE_X = 56;
  const CARTE_L = VISIBLE_L - CARTE_X * 2;
  const CARTE_Y = 168;
  const CARTE_H = 1000;

  const [p1, p2, p3] = d.plans;

  return (
    <div
      style={{
        display: "flex",
        position: "relative",
        width: PLAN_L,
        height: PLAN_H,
        background: COULEURS.ivoire,
      }}
    >
      {/* ── La photo de course occupe toute la rangée haute, en pleine lumière ── */}
      {d.photo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={d.photo}
          alt=""
          width={PLAN_L}
          height={TUILE_H}
          style={{ position: "absolute", left: 0, top: 0, objectFit: "cover" }}
        />
      )}
      {/* Fondu vers l'ivoire : sans lui, la photo se couperait net à la jointure des deux
          rangées et la mosaïque se lirait en deux morceaux. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: PLAN_L,
          height: TUILE_H,
          display: "flex",
          background:
            "linear-gradient(180deg, rgba(245,242,234,0.10) 0%, rgba(245,242,234,0.00) 32%, rgba(245,242,234,0.30) 72%, rgba(245,242,234,0.88) 92%, #F5F2EA 100%)",
        }}
      />
      {/* Rangée basse : ivoire plein, c'est là que se lit l'argumentaire. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: bas,
          width: PLAN_L,
          height: TUILE_H,
          display: "flex",
          background: COULEURS.ivoire,
        }}
      />
      {/* Règle dorée à cheval sur les deux rangées : le raccord qui prouve à l'œil que
          les six vignettes n'en font qu'une. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: bas - 2,
          width: PLAN_L,
          height: 4,
          display: "flex",
          background:
            "linear-gradient(90deg, rgba(224,166,60,0) 0%, #E0A63C 20%, #C8901F 50%, #E0A63C 80%, rgba(224,166,60,0) 100%)",
        }}
      />

      {/* ═══════════ (0,0) — identité, date, volume ═══════════ */}
      <Carte x={col(0) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <div style={{ display: "flex", alignItems: "center" }}>
          <div style={{ display: "flex", width: 14, height: 46, background: COULEURS.orVif }} />
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 46,
              color: COULEURS.encre,
              marginLeft: 18,
              letterSpacing: -1,
            }}
          >
            BlackTurf
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", marginTop: 78 }}>
          <Eyebrow sur="or">RÉSULTATS PMU</Eyebrow>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 76,
              lineHeight: 1.06,
              color: COULEURS.encre,
              marginTop: 20,
              letterSpacing: -2.5,
            }}
          >
            {d.jourLong}
          </span>
        </div>

        <div style={{ display: "flex", width: 120, height: 4, background: COULEURS.orVif, marginTop: 62 }} />

        <div style={{ display: "flex", flexDirection: "column", marginTop: 62 }}>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 176,
              lineHeight: 0.92,
              color: COULEURS.encre,
              letterSpacing: -8,
            }}
          >
            {d.nbCourses}
          </span>
          <span style={{ fontFamily: "Inter", fontSize: 31, color: COULEURS.encreDouce, marginTop: 14 }}>
            courses analysées, {d.nbReunions} réunions
          </span>
        </div>

        <span
          style={{
            fontFamily: "Inter",
            fontSize: 25,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 62,
          }}
        >
          Arrivées et rapports officiels, course par course, en accès libre.
        </span>
      </Carte>

      {/* ═══════════ (0,1) — le meilleur plan du jour ═══════════ */}
      <Carte x={col(1) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow sur="or">LE MEILLEUR PLAN DU JOUR</Eyebrow>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 92 }}>
          {p1 ? <LignePlan p={p1} rang={1} /> : null}
        </div>
        <div style={{ display: "flex", width: 72, height: 3, background: COULEURS.ligne, marginTop: 96 }} />
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 25,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 30,
          }}
        >
          Plan calculé avant le départ, réglé aux rapports officiels du PMU.
        </span>
      </Carte>

      {/* ═══════════ (0,2) — les deux suivants ═══════════ */}
      <Carte x={col(2) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow sur="or">LES DEUX SUIVANTS</Eyebrow>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 66 }}>
          {p2 ? <LignePlan p={p2} rang={2} /> : null}
        </div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 62 }}>
          {p3 ? <LignePlan p={p3} rang={3} /> : null}
        </div>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 25,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 62,
          }}
        >
          Trois plans parmi les {d.nbCourses} courses du jour.
        </span>
      </Carte>

      {/* ═══════════ (1,0) — ce que fait le site ═══════════ */}
      <div
        style={{ position: "absolute", left: col(0) + MARGE, top: bas + 120, width: utile, display: "flex" }}
      >
        <Eyebrow sur="or">CE QUE FAIT BLACKTURF</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(0) + MARGE,
          top: bas + 250,
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
        <Atout
          titre="Un assistant qui répond"
          texte="Une question sur une course, un partant, un type de pari : la réponse s'appuie sur vos données."
        />
      </div>

      {/* ═══════════ (1,1) — l'argument que personne d'autre ne tient ═══════════ */}
      <div
        style={{ position: "absolute", left: col(1) + MARGE, top: bas + 120, width: utile, display: "flex" }}
      >
        <Eyebrow sur="or">CE QU&apos;ON NE VOUS DIRA PAS AILLEURS</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 246,
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
            fontSize: 72,
            lineHeight: 1.14,
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
        style={{ position: "absolute", left: col(2) + MARGE, top: bas + 120, width: utile, display: "flex" }}
      >
        <Eyebrow sur="or">ESSAYER</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 240,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 96,
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
          top: bas + 556,
          width: utile,
          display: "flex",
          flexDirection: "column",
          padding: "42px 46px",
          borderRadius: 22,
          background: COULEURS.encre,
        }}
      >
        <span style={{ fontFamily: "Inter", fontSize: 25, color: COULEURS.encreTenue }}>Tout est sur</span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 68,
            color: COULEURS.orVif,
            marginTop: 8,
            letterSpacing: -2,
          }}
        >
          blackturf.fr
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 792,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {[
          ["Découverte", "0 €", "programme, cotes, arrivées"],
          ["Standard", "12 €/mois", "prédictions et plan de mise"],
          ["Expert", "19 €/mois", "paris de valeur en temps réel"],
        ].map(([nom, prix, quoi]) => (
          <div
            key={nom}
            style={{
              display: "flex",
              flexDirection: "column",
              paddingTop: 19,
              paddingBottom: 19,
              borderTop: `1px solid ${COULEURS.ligne}`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
              <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 32, color: COULEURS.encre }}>
                {nom}
              </span>
              <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 32, color: COULEURS.or }}>
                {prix}
              </span>
            </div>
            <span style={{ fontFamily: "Inter", fontSize: 24, color: COULEURS.encreDouce, marginTop: 4 }}>
              {quoi}
            </span>
          </div>
        ))}
      </div>

      {/* ═══════════ Bandeau légal continu, sur les trois colonnes ═══════════
          Il traverse les trois vignettes basses, ce qui renforce l'effet « une seule
          image », et referme la composition. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: BANDEAU,
          width: PLAN_L,
          height: 1,
          display: "flex",
          background: COULEURS.ligne,
        }}
      />
      <div style={{ position: "absolute", left: col(0) + MARGE, top: BANDEAU + 46, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 23, lineHeight: 1.45, color: COULEURS.encreTenue }}>
          Jouer comporte des risques : endettement, isolement, dépendance.
        </span>
      </div>
      <div style={{ position: "absolute", left: col(1) + MARGE, top: BANDEAU + 46, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 23, lineHeight: 1.45, color: COULEURS.encreTenue }}>
          09 74 75 13 13 — appel non surtaxé. Interdit aux mineurs.
        </span>
      </div>
      <div style={{ position: "absolute", left: col(2) + MARGE, top: BANDEAU + 46, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 23, lineHeight: 1.45, color: COULEURS.encreTenue }}>
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
