import { COULEURS } from "./mosaique";

/**
 * Les plans d'un Reel — images verticales 1080 × 1920, assemblées ensuite en vidéo.
 *
 * ─────────────────────────── POURQUOI DES PLANS FIXES ──────────────────────────────────
 *
 * Satori compose des images, pas des vidéos. Un Reel est donc fabriqué en deux temps :
 * ces plans sont rendus ici un par un, puis un assembleur les enchaîne avec un mouvement
 * de caméra et des fondus. Chaque plan doit donc se tenir SEUL, à l'arrêt sur image.
 *
 * ─────────────────────────── CE QUE LE FORMAT IMPOSE ───────────────────────────────────
 *
 * 1. LA PREMIÈRE SECONDE DÉCIDE DE TOUT. Le plan 0 ne présente rien : il pose une
 *    question qui concerne le spectateur. Un logo en ouverture fait défiler.
 * 2. ON REGARDE SANS LE SON. La grande majorité des Reels sont vus en silence, et
 *    l'API ne permet pas d'attacher un son tendance : tout doit passer par le texte.
 *    D'où des plans à UNE idée, en très gros — pas des paragraphes.
 * 3. LE TÉLÉPHONE MASQUE LES BORDS. L'interface d'Instagram couvre le bas de l'écran
 *    (légende, boutons) et un peu le haut. Rien d'important ne descend sous 1560 ni ne
 *    monte au-dessus de 220 : c'est la zone sûre.
 */

export const REEL_L = 1080;
export const REEL_H = 1920;

/** Marge latérale. La zone sûre verticale est portée par le conteneur centré. */
const MARGE = 88;
const utile = REEL_L - MARGE * 2;

export interface DonneesReel {
  precisionTop3: number | null;
  hasardTop3: number | null;
  coursesMesurees: number;
  photo: string | null;
}

const pct = (n: number) => `${n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;
const nb = (n: number) => n.toLocaleString("fr-FR").replace(/[  ]/g, " ");

/** Le cadre commun : fond encre, marque en haut, mention légale en bas. */
function Plan({
  children,
  photo,
  legal = true,
}: {
  children: React.ReactNode;
  photo?: string | null;
  legal?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        position: "relative",
        width: REEL_L,
        height: REEL_H,
        background: COULEURS.encre,
      }}
    >
      {/* Deux expressions SÉPARÉES, jamais un fragment : Satori ignore les fragments
          React enfants d'un flex — les éléments se superposent, sans la moindre erreur. */}
      {photo ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={photo}
          alt=""
          width={REEL_L}
          height={REEL_H}
          style={{ position: "absolute", left: 0, top: 0, objectFit: "cover" }}
        />
      ) : null}
      {/* La photo doit rester lisible SOUS le texte : un voile dégradé, pas un
          assombrissement uniforme qui l'éteindrait complètement. */}
      {photo ? (
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: REEL_L,
            height: REEL_H,
            display: "flex",
            background:
              "linear-gradient(180deg, rgba(21,24,29,0.72) 0%, rgba(21,24,29,0.45) 35%, rgba(21,24,29,0.82) 72%, #15181D 100%)",
          }}
        />
      ) : null}

      <div
        style={{
          position: "absolute",
          left: MARGE,
          top: 132,
          display: "flex",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", width: 12, height: 40, background: COULEURS.orVif }} />
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 40,
            color: COULEURS.surSombre,
            marginLeft: 16,
            letterSpacing: -0.8,
          }}
        >
          BlackTurf
        </span>
      </div>

      {/* Le contenu est CENTRÉ dans la zone sûre, jamais posé en haut.
          Première version : chaque plan commençait à une hauteur fixe, et les deux tiers
          bas de l'image restaient vides — sur un téléphone tenu à la main, le regard est
          au milieu de l'écran, pas sous la marque. Centrer règle aussi le fait que les
          plans n'ont pas la même quantité de texte : ils restent alignés entre eux. */}
      <div
        style={{
          position: "absolute",
          left: MARGE,
          top: 300,
          width: utile,
          height: 1260,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        {children}
      </div>

      {legal ? (
        <div style={{ position: "absolute", left: MARGE, top: 1700, width: utile, display: "flex" }}>
          <span style={{ fontFamily: "Inter", fontSize: 24, lineHeight: 1.4, color: "#868E9A" }}>
            Jouer comporte des risques : endettement, isolement, dépendance.
            09&#160;74&#160;75&#160;13&#160;13. Interdit aux mineurs.
          </span>
        </div>
      ) : null}
    </div>
  );
}

const titre = (taille: number, couleur: string) =>
  ({
    fontFamily: "Grotesk",
    fontWeight: 700 as const,
    fontSize: taille,
    lineHeight: 1.06,
    color: couleur,
    letterSpacing: -3,
  });

/** Les plans, dans l'ordre. Chacun porte UNE idée. */
export function PlanReel({ n, d }: { n: number; d: DonneesReel }) {
  // ── 0 · l'accroche. Elle ne présente rien, elle interpelle. ──
  if (n === 0) {
    return (
      <Plan photo={d.photo} legal={false}>
        <div
          style={{ width: utile, display: "flex", flexDirection: "column" }}
        >
          <span style={titre(112, COULEURS.surSombre)}>Vous pariez</span>
          <span style={titre(112, COULEURS.surSombre)}>au feeling ?</span>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 40,
              lineHeight: 1.4,
              color: COULEURS.orVif,
              marginTop: 44,
            }}
          >
            Il y a une autre façon de lire une course.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 1 · le chiffre, seul, en très gros. ──
  if (n === 1) {
    return (
      <Plan>
        <div
          style={{ width: utile, display: "flex", flexDirection: "column" }}
        >
          <span
            style={{
              fontFamily: "Inter",
              fontWeight: 600,
              fontSize: 30,
              letterSpacing: 3.4,
              color: COULEURS.orVif,
            }}
          >
            SUR LES COURSES MESURÉES
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 250,
              lineHeight: 1,
              color: COULEURS.surSombre,
              letterSpacing: -12,
              marginTop: 40,
            }}
          >
            {d.precisionTop3 !== null ? pct(d.precisionTop3) : "—"}
          </span>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 44,
              lineHeight: 1.35,
              color: COULEURS.surSombre,
              marginTop: 44,
            }}
          >
            du temps, le gagnant est dans notre top 3.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 2 · le témoin. Sans lui, le chiffre d'avant ne prouve rien. ──
  if (n === 2) {
    return (
      <Plan>
        <div
          style={{ width: utile, display: "flex", flexDirection: "column" }}
        >
          <span
            style={{
              fontFamily: "Inter",
              fontWeight: 600,
              fontSize: 30,
              letterSpacing: 3.4,
              color: COULEURS.surSombreDoux,
            }}
          >
            SUR EXACTEMENT LES MÊMES COURSES
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 250,
              lineHeight: 1,
              color: COULEURS.surSombreDoux,
              letterSpacing: -12,
              marginTop: 40,
            }}
          >
            {d.hasardTop3 !== null ? pct(d.hasardTop3) : "—"}
          </span>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 44,
              lineHeight: 1.35,
              color: COULEURS.surSombreDoux,
              marginTop: 44,
            }}
          >
            c&apos;est ce que ferait le hasard.
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 52,
              lineHeight: 1.2,
              color: COULEURS.orVif,
              letterSpacing: -1.5,
              marginTop: 60,
            }}
          >
            Deux fois mieux que le hasard.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 3 · d'où ça vient. ──
  if (n === 3) {
    return (
      <Plan>
        <div
          style={{ width: utile, display: "flex", flexDirection: "column" }}
        >
          <span style={titre(104, COULEURS.surSombre)}>80+ critères</span>
          <span style={titre(104, COULEURS.orVif)}>par cheval.</span>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 70 }}>
            {[
              "Contrecoup après un gros effort",
              "Biais de corde de l’hippodrome",
              "Déferrage, œillères, pénétromètre",
              "Argent professionnel sur la cote",
            ].map((l) => (
              <div key={l} style={{ display: "flex", alignItems: "center", marginBottom: 34 }}>
                <div
                  style={{ display: "flex", width: 14, height: 14, borderRadius: 7, background: COULEURS.orVif }}
                />
                <span
                  style={{ fontFamily: "Inter", fontSize: 38, color: COULEURS.surSombre, marginLeft: 22 }}
                >
                  {l}
                </span>
              </div>
            ))}
          </div>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 34,
              lineHeight: 1.4,
              color: COULEURS.surSombreDoux,
              marginTop: 30,
            }}
          >
            Recalibré chaque nuit sur les arrivées réelles.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 4 · l'honnêteté. C'est elle qui rend le reste croyable. ──
  if (n === 4) {
    return (
      <Plan>
        <div
          style={{ width: utile, display: "flex", flexDirection: "column" }}
        >
          <span style={titre(92, COULEURS.surSombre)}>Et les jours</span>
          <span style={titre(92, COULEURS.surSombre)}>où on se trompe ?</span>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 42,
              lineHeight: 1.4,
              color: COULEURS.surSombreDoux,
              marginTop: 56,
            }}
          >
            Ils sont publiés aussi.
          </span>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 36,
              lineHeight: 1.45,
              color: COULEURS.surSombreDoux,
              marginTop: 32,
            }}
          >
            {d.coursesMesurees
              ? `${nb(d.coursesMesurees)} courses réglées aux rapports officiels du PMU, pronostic enregistré avant le départ.`
              : "Chaque pronostic est réglé aux rapports officiels, enregistré avant le départ."}
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 50,
              lineHeight: 1.22,
              color: COULEURS.orVif,
              letterSpacing: -1.4,
              marginTop: 56,
            }}
          >
            Le seul service de pronostics qui publie aussi ses pertes.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 5 · l'adresse, en plein écran doré. ──
  return (
    <Plan legal={false}>
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: REEL_L,
          height: REEL_H,
          display: "flex",
          background: COULEURS.orVif,
        }}
      />
      <div
        style={{ width: utile, display: "flex", flexDirection: "column" }}
      >
        <span style={{ fontFamily: "Inter", fontWeight: 600, fontSize: 36, color: "#4A3504" }}>
          Le programme du jour est déjà en ligne
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 104,
            lineHeight: 1.05,
            color: "#1B1405",
            letterSpacing: -3,
            marginTop: 20,
          }}
        >
          blackturf.fr
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 40,
            lineHeight: 1.4,
            color: "#4A3504",
            marginTop: 44,
          }}
        >
          7 jours offerts. Le programme, les cotes et les rapports restent gratuits.
        </span>
      </div>
      <div style={{ position: "absolute", left: MARGE, top: 1700, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 24, lineHeight: 1.4, color: "#4A3504" }}>
          Jouer comporte des risques : endettement, isolement, dépendance.
          09&#160;74&#160;75&#160;13&#160;13. Interdit aux mineurs.
        </span>
      </div>
    </Plan>
  );
}

/** Nombre de plans — l'assembleur en a besoin pour savoir combien en demander. */
export const NB_PLANS = 6;
