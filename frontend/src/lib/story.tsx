import { COULEURS } from "@/lib/mosaique";
import { MENTION_LEGALE } from "@/lib/visuels";

/**
 * Story du soir — 1080 × 1920, la performance de la journée.
 *
 * ─────────────────────────── CE QU'ELLE DIT, ET DANS QUEL ORDRE ───────────────────────────
 *
 * Le chiffre de tête est la QUALITÉ DE CLASSEMENT, pas un gain : la part des courses
 * où le gagnant réel figurait dans le Top 3 prédit. C'est le seul chiffre que le site
 * puisse défendre sur la durée, et il est publié avec les deux choses sans lesquelles
 * il ne veut rien dire : son dénominateur (« 38 courses sur 51 ») et le repère du
 * hasard, CALCULÉ sur le champ réel de chaque course. « 74,5 % » seul ne dit pas au
 * lecteur ce qu'il bat.
 *
 * Viennent ensuite l'argent : le meilleur plan du jour, puis le TOTAL rendu par tous
 * les plans.
 *
 * ─────────────────────────── LE VOCABULAIRE, QUI N'EST PAS DÉCORATIF ───────────────────────────
 *
 * Ces montants sont ceux de PLANS calculés et réglés aux rapports officiels du PMU,
 * pas d'argent encaissé par quiconque. « Misé » et « rendu » sont exacts ; « gagné »,
 * « nos gains » ou « bénéfice » ne le seraient pas.
 *
 * La mise TOTALE de la journée n'est pas affichée (arbitrage produit du 2026-09-05).
 * Le garde-fou est le dénominateur : le nombre de plans gagnants sort toujours avec le
 * nombre total de plans calculés, sans quoi « 21 plans gagnants » se lirait comme si
 * tous les plans avaient gagné.
 *
 * LE PROFIL N'EST JAMAIS AFFICHÉ. Le plus gros gain d'une journée vient presque
 * toujours du profil le plus risqué : le nommer reviendrait à mettre ce profil en
 * avant à chaque publication.
 *
 * ─────────────────────────── LA GÉOMÉTRIE ───────────────────────────
 *
 * L'interface d'Instagram recouvre ~250 px en haut et ~250 px en bas d'une story. La
 * photo occupe le haut (elle peut être partiellement masquée, c'est du décor) et TOUT
 * le texte, mention légale comprise, tient au-dessus de y = 1700.
 */

export const STORY_L = 1080;
export const STORY_H = 1920;

/**
 * Bande photo. 620 px pour 1080 de large, soit 1,74:1 — le fonds est en 1,25 à 1,72,
 * donc on ne rogne presque rien, et ce qu'on rogne part du HAUT (voir `ancrage`).
 * En dessous, le cheval perd ses jambes ; au-dessus, le texte ne tient plus.
 */
export const PHOTO_H = 620;
const MARGE = 64;
const UTILE = STORY_L - MARGE * 2;

/** Vert du gain : celui de `lib/visuels` est calé pour un fond sombre, illisible ici. */
const VERT = "#177A4C";

export interface MeilleurPlan {
  hippodrome: string;
  code: string;
  mise: number;
  retour: number;
  net: number;
  typePari: string | null;
}

export interface DonneesStory {
  jourLong: string;
  /** Qualité de classement du jour. `null` = pas encore mesurable : on se tait. */
  pctTop3: number | null;
  nbTop3: number;
  nbAnalysees: number;
  hasardTop3: number | null;
  pctTop1: number | null;
  nbTop1: number;
  nbPartants: number;
  nbHippodromes: number;
  meilleur: MeilleurPlan | null;
  totalRetour: number;
  nbPlans: number;
  nbPlansGagnants: number;
  photo: string | null;
  horse: string | null;
}

/**
 * Montants : les centimes ne s'affichent que s'il y en a. Même règle que la mosaïque.
 *
 * L'espace des milliers est REMPLACÉ par une espace ordinaire. `Intl` produit une
 * espace fine insécable (U+202F) que les fontes embarquées ne portent pas : Satori la
 * rend à chasse nulle et « 1 040,30 € » sortait « 1040,30 € ». Sur un visuel dont le
 * seul contenu est un nombre, quatre chiffres collés se lisent mal.
 */
const euro = (n: number) =>
  n
    .toLocaleString("fr-FR", {
      minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
      maximumFractionDigits: 2,
    })
    .replace(/[  ]/g, " ");

/** Pourcentages à la française : virgule décimale, jamais de point. */
const pct = (n: number) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** Surtitre doré encadré de deux filets — le motif qui rythme toute la page. */
function Surtitre({ children, largeur = UTILE }: { children: string; largeur?: number }) {
  return (
    <div style={{ display: "flex", alignItems: "center", width: largeur }}>
      <div style={{ display: "flex", flex: 1, height: 1, background: COULEURS.ligne }} />
      <span
        style={{
          fontFamily: "Inter",
          fontWeight: 600,
          fontSize: 23,
          letterSpacing: 4,
          color: COULEURS.or,
          margin: "0 22px",
        }}
      >
        {children}
      </span>
      <div style={{ display: "flex", flex: 1, height: 1, background: COULEURS.ligne }} />
    </div>
  );
}

/** Une colonne du bandeau de chiffres. */
function Chiffre({
  valeur,
  unite,
  legende,
}: {
  valeur: string;
  unite?: string;
  legende: string[];
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: 300,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline" }}>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 50,
            color: COULEURS.encre,
            letterSpacing: -2,
          }}
        >
          {valeur}
        </span>
        {unite ? (
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 28,
              color: COULEURS.or,
              marginLeft: 6,
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
            fontFamily: "Inter",
            fontSize: 23,
            lineHeight: 1.3,
            color: COULEURS.encreDouce,
            marginTop: i === 0 ? 8 : 0,
          }}
        >
          {l}
        </span>
      ))}
    </div>
  );
}

export function Story({ d }: { d: DonneesStory }) {
  const m = d.meilleur;
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: STORY_L,
        height: STORY_H,
        background: COULEURS.ivoire,
      }}
    >
      {/* Filet doré en tête : il ferme le haut de l'image quand la story est vue en
          plein écran, sinon la photo semble déborder de l'écran. */}
      <div
        style={{
          display: "flex",
          width: STORY_L,
          height: 6,
          background: "linear-gradient(90deg, #C8901F 0%, #E0A63C 50%, #C8901F 100%)",
        }}
      />

      <div style={{ display: "flex", width: STORY_L, height: PHOTO_H }}>
        {d.photo ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={d.photo} alt="" width={STORY_L} height={PHOTO_H} style={{ objectFit: "cover" }} />
        ) : null}
      </div>

      <div
        style={{
          display: "flex",
          width: STORY_L,
          height: 6,
          background: "linear-gradient(90deg, #C8901F 0%, #E0A63C 50%, #C8901F 100%)",
        }}
      />

      {/* ══════════ La marque ══════════ */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 104,
          height: 104,
          borderRadius: 52,
          border: `3px solid ${COULEURS.or}`,
          marginTop: 28,
        }}
      >
        {d.horse ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={d.horse} alt="" width={80} height={50} />
        ) : null}
      </div>
      <div style={{ display: "flex", alignItems: "baseline", marginTop: 10 }}>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 27,
            letterSpacing: 2,
            color: COULEURS.encre,
          }}
        >
          BLACK
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 27,
            letterSpacing: 2,
            color: COULEURS.or,
          }}
        >
          TURF
        </span>
      </div>

      {/* ══════════ Le jour ══════════
          Il était en surtitre à 23 px, à la taille d'une étiquette. Une publication de
          résultats dont on ne lit pas le jour ne prouve rien — c'est même la première
          chose qu'on lui reproche. Il prend donc la taille d'un titre. */}
      <div style={{ display: "flex", marginTop: 20 }}>
        <Surtitre>PERFORMANCE DU JOUR</Surtitre>
      </div>
      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: 48,
          letterSpacing: -1.4,
          color: COULEURS.encre,
          marginTop: 10,
        }}
      >
        {d.jourLong}
      </span>

      {/* ══════════ La qualité de classement ══════════ */}
      {d.pctTop3 !== null ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 18 }}>
          <div style={{ display: "flex", alignItems: "baseline" }}>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 106,
                lineHeight: 1,
                color: COULEURS.encre,
                letterSpacing: -6,
              }}
            >
              {pct(d.pctTop3)}
            </span>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 46,
                color: COULEURS.or,
                marginLeft: 6,
              }}
            >
              %
            </span>
          </div>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 37,
              lineHeight: 1.2,
              color: COULEURS.encre,
              letterSpacing: -1,
              marginTop: 6,
            }}
          >
            des courses où le gagnant
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 37,
              lineHeight: 1.2,
              color: COULEURS.encre,
              letterSpacing: -1,
            }}
          >
            était dans notre Top 3
          </span>
          {/* Dénominateur ET repère du hasard, toujours : un pourcentage sans eux ne se
              vérifie pas et ne dit pas ce qu'il bat. */}
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 25,
              color: COULEURS.encreDouce,
              marginTop: 12,
            }}
          >
            {d.nbTop3} courses sur {d.nbAnalysees} analysées
            {d.hasardTop3 !== null
              ? ` · un tirage au sort en trouverait ${pct(d.hasardTop3)} %`
              : ""}
          </span>
        </div>
      ) : null}

      {/* ══════════ Le volume de la journée ══════════ */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: UTILE,
          marginTop: 22,
        }}
      >
        <Chiffre
          valeur={d.pctTop1 !== null ? pct(d.pctTop1) : "—"}
          unite={d.pctTop1 !== null ? "%" : undefined}
          legende={["notre favori a gagné", `${d.nbTop1} courses sur ${d.nbAnalysees}`]}
        />
        <div style={{ display: "flex", width: 1, height: 86, background: COULEURS.ligne }} />
        <Chiffre
          valeur={d.nbPartants.toLocaleString("fr-FR")}
          legende={["partants analysés", "dans la journée"]}
        />
        <div style={{ display: "flex", width: 1, height: 86, background: COULEURS.ligne }} />
        <Chiffre
          valeur={String(d.nbHippodromes)}
          legende={["hippodromes", "couverts"]}
        />
      </div>

      {/* ══════════ Le meilleur plan ══════════ */}
      {m ? (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 22 }}>
          <Surtitre largeur={640}>MEILLEUR GAIN DE LA JOURNÉE</Surtitre>
          <div style={{ display: "flex", alignItems: "baseline", marginTop: 14 }}>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 42,
                color: COULEURS.encreTenue,
                letterSpacing: -1.4,
              }}
            >
              {euro(m.mise)} €
            </span>
            <span style={{ fontFamily: "Inter", fontSize: 40, color: COULEURS.or, margin: "0 20px" }}>
              →
            </span>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 64,
                color: VERT,
                letterSpacing: -3,
              }}
            >
              {euro(m.retour)} €
            </span>
          </div>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 26,
              color: COULEURS.encreDouce,
              marginTop: 10,
            }}
          >
            {[m.typePari, m.hippodrome, `${euro(m.net)} € net`].filter(Boolean).join(" · ")}
          </span>
        </div>
      ) : null}

      {/* ══════════ Le total de la journée ══════════
          Une seule ligne : c'est un chiffre de contexte, pas le sujet de la story. Le
          nombre de plans gagnants ne sort JAMAIS sans le nombre total calculé. */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          width: UTILE,
          marginTop: 18,
          paddingTop: 16,
          borderTop: `1px solid ${COULEURS.ligne}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline" }}>
          <span style={{ fontFamily: "Inter", fontSize: 27, color: COULEURS.encreDouce }}>
            Total rendu par les plans du jour
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 42,
              color: COULEURS.or,
              letterSpacing: -1.6,
              marginLeft: 18,
            }}
          >
            {euro(d.totalRetour)} €
          </span>
        </div>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 24,
            color: COULEURS.encreTenue,
            marginTop: 6,
          }}
        >
          {d.nbPlansGagnants} plans gagnants sur les {d.nbPlans} calculés
        </span>
      </div>

      {/* ══════════ Où aller ══════════ */}
      <div style={{ display: "flex", alignItems: "baseline", marginTop: 16 }}>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 34,
            color: COULEURS.encre,
            letterSpacing: -1,
          }}
        >
          Ne pariez plus&nbsp;
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 34,
            color: COULEURS.or,
            letterSpacing: -1,
          }}
        >
          au hasard.
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "16px 38px",
          borderRadius: 46,
          background: COULEURS.encre,
          marginTop: 14,
        }}
      >
        {/* Adresse RACINE, sans chemin. Une story se regarde, elle ne se clique pas :
            un lecteur qui doit retaper « blackturf.fr/track-record » de mémoire ne
            tape rien du tout. */}
        <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 33, color: COULEURS.surSombre }}>
          black
        </span>
        <span style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 33, color: COULEURS.orVif }}>
          turf.fr
        </span>
      </div>

      {/* POURQUOI CETTE LIGNE, ET PAS UN BOUTON.
          L'API de publication de contenu de Meta publie le MÉDIA, et rien d'autre :
          aucun sticker n'y est exposé — ni lien, ni sondage, ni mention. Une story
          publiée automatiquement sort donc forcément sans bouton cliquable, et c'est
          une limite de l'API, pas un oubli. Les outils qui savent poser le sticker
          passent par l'API privée d'Instagram, hors conditions d'utilisation : pas sur
          un compte de marque.
          Le chemin qui reste est celui de tout le monde — le lien de profil, déjà
          renseigné sur `blackturf.fr` — encore faut-il le DIRE, sinon l'adresse écrite
          dans la pastille ne se retape pas. */}
      <div style={{ display: "flex", alignItems: "center", marginTop: 12 }}>
        <span style={{ fontFamily: "Inter", fontSize: 25, color: COULEURS.or }}>↑</span>
        <span
          style={{
            fontFamily: "Inter",
            fontWeight: 600,
            fontSize: 25,
            color: COULEURS.encreDouce,
            marginLeft: 10,
          }}
        >
          Lien direct dans la bio
        </span>
      </div>

      {/* La mention de jeu responsable est portée par l'IMAGE, pas seulement par la
          légende : une image circule hors de sa légende, et c'est l'image qu'on
          retrouve republiée. Elle reste au-dessus de la zone que l'interface
          d'Instagram recouvre. */}
      <span
        style={{
          display: "flex",
          width: UTILE - 60,
          textAlign: "center",
          fontFamily: "Inter",
          fontSize: 17,
          lineHeight: 1.4,
          color: COULEURS.encreTenue,
          marginTop: 14,
        }}
      >
        Les résultats passés ne préjugent pas des résultats futurs. {MENTION_LEGALE}
      </span>
    </div>
  );
}
