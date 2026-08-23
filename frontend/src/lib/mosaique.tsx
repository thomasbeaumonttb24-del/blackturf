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
  surSombreTenu: "#78808C",
  ligneSombre: "#2B3138",
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

/* ────────────────────────────── Fragments de composition ────────────────────────────── */

function Eyebrow({ children, ton = "or" }: { children: string; ton?: "or" | "tenu" | "sombre" }) {
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
 * L'adresse du site, au pied de chaque tuile.
 *
 * Dans le fil, une tuile est vue seule : sans cette ligne, cinq publications sur six ne
 * disent nulle part où aller.
 */
function Adresse({ ton = "clair" }: { ton?: "clair" | "sombre" }) {
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

function Atout({ titre, texte }: { titre: string; texte: string }) {
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
  const CARTE_Y = 150;
  const CARTE_H = 968;

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
      {/* ═══════════ Rangée basse : encre pleine, d'un bord à l'autre ═══════════
          Elle était ivoire, et se lisait comme une page de texte blanche posée sous une
          photo — deux images, pas une. En encre elle devient le socle de la composition :
          la photo claire au-dessus, la ligne dorée entre les deux, l'argumentaire dans le
          sombre.

          La bande couvre TOUTE la largeur du plan, débords compris. Un aplat qui
          s'arrêterait à la largeur visible d'une colonne serait invisible sur la grille,
          mais laisserait une bande claire de 34 px sur le côté de chaque tuile vue seule
          dans le fil — et une bande sombre parasite sur le bord de sa voisine. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: bas,
          width: PLAN_L,
          height: TUILE_H,
          display: "flex",
          background: COULEURS.encre,
        }}
      />

      {/* Règle dorée à cheval sur les deux rangées : le raccord qui prouve à l'œil que les
          six vignettes n'en font qu'une. Elle était en dégradé, s'éteignant sur les bords —
          invisible depuis que la rangée basse est en encre, où c'est justement le contraste
          qui la porte. Pleine, d'un bord à l'autre, elle traverse les trois tuiles. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: bas - 3,
          width: PLAN_L,
          height: 6,
          display: "flex",
          background: "linear-gradient(90deg, #C8901F 0%, #E0A63C 50%, #C8901F 100%)",
        }}
      />

      {/* ═══════════ (0,0) — la marque, ce qu'elle fait, le volume du jour ═══════════
          Publiée en DERNIER, donc en tête du profil et en tête du fil : c'est la tuile qui
          doit expliquer BlackTurf à quelqu'un qui n'en a jamais entendu parler. La date
          passe en surtitre, la promesse prend la place du titre. */}
      <Carte x={col(0) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <div
          style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}
        >
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
          <span style={{ fontFamily: "Inter", fontWeight: 600, fontSize: 25, color: COULEURS.or }}>
            blackturf.fr
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", marginTop: 72 }}>
          <Eyebrow>{d.jourLong.toUpperCase()}</Eyebrow>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 74,
              lineHeight: 1.08,
              color: COULEURS.encre,
              marginTop: 22,
              letterSpacing: -2.5,
            }}
          >
            Le programme du jour, passé au calcul.
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 74,
              lineHeight: 1.08,
              color: COULEURS.or,
              letterSpacing: -2.5,
            }}
          >
            Pas au feeling.
          </span>
        </div>

        <div style={{ display: "flex", width: 120, height: 4, background: COULEURS.orVif, marginTop: 52 }} />

        <div style={{ display: "flex", marginTop: 48 }}>
          <div style={{ display: "flex", flexDirection: "column", width: 380 }}>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 104,
                lineHeight: 1,
                color: COULEURS.encre,
                letterSpacing: -5,
              }}
            >
              {d.nbCourses}
            </span>
            <span style={{ fontFamily: "Inter", fontSize: 26, color: COULEURS.encreDouce, marginTop: 10 }}>
              courses analysées
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 104,
                lineHeight: 1,
                color: COULEURS.encre,
                letterSpacing: -5,
              }}
            >
              {d.nbReunions}
            </span>
            <span style={{ fontFamily: "Inter", fontSize: 26, color: COULEURS.encreDouce, marginTop: 10 }}>
              réunions PMU
            </span>
          </div>
        </div>

        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 52,
          }}
        >
          Arrivées et rapports officiels, course par course, en accès libre.
        </span>
      </Carte>

      {/* ═══════════ (0,1) — le meilleur plan du jour ═══════════
          La preuve. Misé, puis rendu, dans cet ordre, avec « le plan a rendu » écrit noir
          sur blanc : c'est ce qui distingue un plan réglé aux rapports d'une promesse. */}
      <Carte x={col(1) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow>LE MEILLEUR PLAN DU JOUR</Eyebrow>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 92 }}>
          {p1 ? <LignePlan p={p1} rang={1} /> : null}
        </div>
        <div style={{ display: "flex", width: 72, height: 3, background: COULEURS.ligne, marginTop: 104 }} />
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 34,
          }}
        >
          Calculé avant le départ, réglé aux rapports officiels du PMU. Les {d.nbCourses} plans
          du jour sont publiés — les perdants aussi.
        </span>
        <div style={{ display: "flex", marginTop: 54 }}>
          <Adresse />
        </div>
      </Carte>

      {/* ═══════════ (0,2) — les deux suivants ═══════════ */}
      <Carte x={col(2) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow>ET LES DEUX SUIVANTS</Eyebrow>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 44 }}>
          {p2 ? <LignePlan p={p2} rang={2} /> : null}
        </div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 44 }}>
          {p3 ? <LignePlan p={p3} rang={3} /> : null}
        </div>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 44,
          }}
        >
          Trois plans sur les {d.nbCourses} courses du jour. Le reste est en ligne, gagnants
          comme perdants.
        </span>
        <div style={{ display: "flex", marginTop: 30 }}>
          <Adresse />
        </div>
      </Carte>

      {/* ═══════════ (1,0) — ce que fait le site ═══════════
          Cinq lignes, verbe en tête : ce n'est pas une liste de fonctions, c'est la liste
          du travail que l'abonné ne fait plus lui-même. */}
      <div
        style={{ position: "absolute", left: col(0) + MARGE, top: bas + 112, width: utile, display: "flex" }}
      >
        <Eyebrow ton="sombre">CE QUE BLACKTURF FAIT, CHAQUE JOUR</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(0) + MARGE,
          top: bas + 224,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Atout
          titre="Il lit le programme pour vous"
          texte="80 critères par cheval, une probabilité calculée pour chaque partant, publiée avant le départ."
        />
        <Atout
          titre="Il calcule sur VOTRE mise"
          texte="Vous entrez votre budget, le plan de jeu se construit dessus. Aucun ticket type imposé."
        />
        <Atout
          titre="Il compare les cotes"
          texte="PMU et principaux opérateurs côte à côte : on voit où la cote décroche."
        />
        <Atout
          titre="Il publie son bilan"
          texte="Chaque plan est réglé aux rapports réels du PMU. Les journées rouges restent en ligne."
        />
        <Atout
          titre="Il répond à vos questions"
          texte="Une course, un partant, un type de pari : la réponse s'appuie sur vos données."
        />
      </div>
      <div style={{ position: "absolute", left: col(0) + MARGE, top: bas + 1092, display: "flex" }}>
        <Adresse ton="sombre" />
      </div>

      {/* ═══════════ (1,1) — l'argument que personne d'autre ne tient ═══════════
          Fond sombre : c'est la tuile qui doit être crue. Elle annonce le prélèvement avant
          de dire quoi que ce soit d'autre — c'est ce qui rend crédible tout le reste. */}
      <div
        style={{ position: "absolute", left: col(1) + MARGE, top: bas + 112, width: utile, display: "flex" }}
      >
        <Eyebrow ton="sombre">CE QU&apos;ON NE VOUS DIRA PAS AILLEURS</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 214,
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
            fontSize: 80,
            lineHeight: 1.1,
            color: COULEURS.surSombre,
            letterSpacing: -2.5,
          }}
        >
          Le PMU prélève environ
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 80,
            lineHeight: 1.1,
            color: COULEURS.orVif,
            letterSpacing: -2.5,
          }}
        >
          20&#8239;% des enjeux.
        </span>

        <div
          style={{ display: "flex", width: 96, height: 3, background: COULEURS.ligneSombre, marginTop: 50 }}
        />

        <span
          style={{
            fontFamily: "Inter",
            fontSize: 29,
            lineHeight: 1.55,
            color: COULEURS.surSombreDoux,
            marginTop: 44,
          }}
        >
          Personne ne peut promettre un gain régulier là-dessus. Qui vous le promet vous ment,
          ou ne sait pas compter.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 29,
            lineHeight: 1.55,
            color: COULEURS.surSombreDoux,
            marginTop: 32,
          }}
        >
          Ce qui se mesure, en revanche, c&apos;est l&apos;écart entre la probabilité réelle
          d&apos;un cheval et celle qu&apos;implique sa cote.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 29,
            lineHeight: 1.55,
            color: COULEURS.surSombre,
            marginTop: 32,
          }}
        >
          C&apos;est ce que BlackTurf calcule, course par course — et ce qu&apos;il publie
          ensuite, résultat en main.
        </span>
      </div>
      {/* La phrase qui doit rester en tête. C'est l'argument commercial du service, et le
          seul qu'un concurrent ne peut pas copier sans montrer ses propres chiffres. */}
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 896,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <div style={{ display: "flex", width: 96, height: 3, background: COULEURS.ligneSombre }} />
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 40,
            lineHeight: 1.25,
            color: COULEURS.orVif,
            letterSpacing: -1,
            marginTop: 32,
          }}
        >
          Le seul service de pronostics qui publie aussi ses pertes.
        </span>
      </div>
      <div style={{ position: "absolute", left: col(1) + MARGE, top: bas + 1092, display: "flex" }}>
        <Adresse ton="sombre" />
      </div>

      {/* ═══════════ (1,2) — la conversion ═══════════
          L'ordre compte : la promesse, puis le prix, puis l'adresse. Le bloc noir ferme la
          composition dans l'angle bas-droit : c'est le seul aplat doré de tout le plan, et
          il tombe sur le dernier bloc que l'œil rencontre. */}
      <div
        style={{ position: "absolute", left: col(2) + MARGE, top: bas + 112, width: utile, display: "flex" }}
      >
        <Eyebrow ton="sombre">COMMENCER</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 210,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 100,
            lineHeight: 1.04,
            color: COULEURS.surSombre,
            letterSpacing: -3.5,
          }}
        >
          7 jours offerts
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 28,
            lineHeight: 1.5,
            color: COULEURS.surSombreDoux,
            marginTop: 26,
          }}
        >
          Vous créez un compte, vous entrez votre budget : le plan du jour se calcule dessus.
          Résiliable à tout moment.
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 452,
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
              paddingTop: 22,
              paddingBottom: 22,
              borderTop: `1px solid ${COULEURS.ligneSombre}`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
              <span
                style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 34, color: COULEURS.surSombre }}
              >
                {nom}
              </span>
              <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 34, color: COULEURS.orVif }}>
                {prix}
              </span>
            </div>
            <span style={{ fontFamily: "Inter", fontSize: 25, color: COULEURS.surSombreDoux, marginTop: 4 }}>
              {quoi}
            </span>
          </div>
        ))}
      </div>

      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 872,
          width: utile,
          display: "flex",
          flexDirection: "column",
          padding: "40px 46px",
          borderRadius: 22,
          background: COULEURS.orVif,
        }}
      >
        <span style={{ fontFamily: "Inter", fontWeight: 600, fontSize: 25, color: "#5E4406" }}>
          Le programme du jour est déjà en ligne
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 70,
            color: "#1B1405",
            marginTop: 8,
            letterSpacing: -2,
          }}
        >
          blackturf.fr
        </span>
      </div>

      {/* ═══════════ Mention de jeu responsable, rangée HAUTE ═══════════
          Elle n'existait que dans la rangée basse : les trois tuiles du haut partaient donc
          sans mention alors qu'elles sont publiées séparément, et que dans le fil personne
          ne voit jamais les six ensemble. Chaque colonne porte la mention entière, à
          l'identique — un bandeau légal se répète, il ne se découpe pas. Elle se pose dans
          le fondu de la photo, où le fond est déjà presque ivoire. */}
      {[0, 1, 2].map((c) => (
        <div
          key={`legal-haut-${c}`}
          style={{
            position: "absolute",
            left: col(c) + MARGE,
            top: TUILE_H - 118,
            width: utile,
            display: "flex",
          }}
        >
          {/* Espaces insécables dans le numéro d'aide : il se coupait en fin de ligne, le
              dernier « 13 » se retrouvant seul sur la ligne suivante. */}
          <span style={{ fontFamily: "Inter", fontSize: 22, lineHeight: 1.45, color: COULEURS.encreDouce }}>
            Jouer comporte des risques : endettement, isolement, dépendance.
            09&#160;74&#160;75&#160;13&#160;13, appel non surtaxé. Interdit aux mineurs.
          </span>
        </div>
      ))}

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
          background: COULEURS.ligneSombre,
        }}
      />
      <div
        style={{ position: "absolute", left: col(0) + MARGE, top: BANDEAU + 46, width: utile, display: "flex" }}
      >
        <span style={{ fontFamily: "Inter", fontSize: 23, lineHeight: 1.45, color: COULEURS.surSombreTenu }}>
          Jouer comporte des risques : endettement, isolement, dépendance.
        </span>
      </div>
      <div
        style={{ position: "absolute", left: col(1) + MARGE, top: BANDEAU + 46, width: utile, display: "flex" }}
      >
        <span style={{ fontFamily: "Inter", fontSize: 23, lineHeight: 1.45, color: COULEURS.surSombreTenu }}>
          Pour être aidé : 09 74 75 13 13, appel non surtaxé. Interdit aux mineurs.
        </span>
      </div>
      <div
        style={{ position: "absolute", left: col(2) + MARGE, top: BANDEAU + 46, width: utile, display: "flex" }}
      >
        <span style={{ fontFamily: "Inter", fontSize: 23, lineHeight: 1.45, color: COULEURS.surSombreTenu }}>
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
