import {
  TUILE_L,
  TUILE_H,
  VISIBLE_L,
  DEBORD,
  PLAN_L,
  PLAN_H,
  COULEURS,
  Eyebrow,
  Adresse,
  Atout,
  Carte,
} from "./mosaique";

/**
 * Mosaïque « présentation du service » — six publications, une seule image.
 *
 * ─────────────────────────── POURQUOI UNE SECONDE MOSAÏQUE ─────────────────────────────
 *
 * La première (`mosaique.tsx`) raconte UNE journée : les meilleurs plans du jour. Elle ne
 * vaut donc que le soir même, et elle ne dit pas ce qu'est BlackTurf à quelqu'un qui
 * arrive sur le profil.
 *
 * Celle-ci ne dépend d'aucune journée. Elle porte les chiffres de fond du service et
 * l'argumentaire : c'est la vitrine, celle qu'on installe en premier et qui reste vraie
 * six mois plus tard. Les deux partagent la géométrie, la charte et les fragments de
 * composition — un seul endroit où le design existe.
 *
 * ─────────────────────────── CE QUI EST INTERDIT ICI ───────────────────────────────────
 *
 * Aucun chiffre de RÉUSSITE. Le nombre de paris gagnés rapporté au nombre de courses
 * réglées se lit comme un taux de rentabilité, alors que le ROI mesuré est négatif :
 * l'API ne l'expose donc pas à ce visuel, et il n'a rien à faire ici. Les chiffres
 * montrés sont des chiffres de MÉTHODE et de VOLUME — vérifiables, et qu'aucun
 * concurrent ne peut afficher sans montrer les siens.
 *
 * La géométrie est celle de l'autre mosaïque, et pour les mêmes raisons : la grille de
 * profil rogne chaque vignette en 3:4, on publie en 4:5 et on ne compose que sur les
 * 1012 px centraux. Voir `mosaique.tsx` pour le détail.
 */

export interface DonneesSite {
  coursesEnBase: number;
  partantsAnalyses: number;
  coursesReglees: number;
  journeesPubliees: number;
  /** Taux mesurés, en pourcents. `null` = indisponible : le bloc n'est pas rendu. */
  precisionTop3: number | null;
  hasardTop3: number | null;
  favoriPlace: number | null;
  favoriGagnant: number | null;
  coursesMesurees: number;
  photo: string | null;
}

/** « 60.2 » → « 60,2 % ». Les taux sont affichés à la décimale, comme sur le site. */
const pct = (n: number) => `${n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;

/**
 * Séparateur de milliers insécable.
 *
 * `toLocaleString("fr-FR")` sort une espace fine insécable (U+202F) que toutes les
 * polices ne portent pas — le nombre se coupait alors en deux au milieu. On la remplace
 * par l'espace insécable ordinaire, présente partout.
 */
const nb = (n: number) => n.toLocaleString("fr-FR").replace(/[  ]/g, " ");

/** Un grand nombre et sa légende, le motif porteur de cette mosaïque. */
function Chiffre({
  valeur,
  legende,
  taille = 172,
}: {
  valeur: string;
  legende: string;
  taille?: number;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: taille,
          lineHeight: 1,
          color: COULEURS.encre,
          letterSpacing: taille > 100 ? -6 : -3,
        }}
      >
        {valeur}
      </span>
      <span
        style={{
          fontFamily: "Inter",
          fontSize: 27,
          lineHeight: 1.4,
          color: COULEURS.encreDouce,
          marginTop: 14,
        }}
      >
        {legende}
      </span>
    </div>
  );
}

export function PlanSite({ d }: { d: DonneesSite }) {
  const col = (c: number) => DEBORD + c * VISIBLE_L;
  const MARGE = 76;
  const utile = VISIBLE_L - MARGE * 2;
  const bas = TUILE_H;
  const BANDEAU = PLAN_H - 168;

  const CARTE_X = 56;
  const CARTE_L = VISIBLE_L - CARTE_X * 2;
  const CARTE_Y = 150;
  const CARTE_H = 900;

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
      {/* Rangée basse en encre pleine, débords compris : un aplat qui s'arrêterait à la
          largeur visible d'une colonne laisserait une bande claire sur le côté de chaque
          tuile vue seule dans le fil, et une bande sombre parasite sur sa voisine. */}
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

      {/* ═══════════ (0,0) — la marque, la promesse, la phrase qui reste ═══════════
          Publiée en DERNIER, donc en tête du profil et en tête du fil : c'est elle qui doit
          expliquer BlackTurf à quelqu'un qui n'en a jamais entendu parler. La ligne dorée
          est celle du dépliant — c'est la formule la plus juste que la marque possède. */}
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

        <div style={{ display: "flex", flexDirection: "column", marginTop: 64 }}>
          <Eyebrow>PARIS HIPPIQUES PMU</Eyebrow>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 70,
              lineHeight: 1.08,
              color: COULEURS.encre,
              marginTop: 20,
              letterSpacing: -2.5,
            }}
          >
            Chaque course du PMU, analysée avant le départ.
          </span>
        </div>

        <div style={{ display: "flex", width: 120, height: 4, background: COULEURS.orVif, marginTop: 44 }} />

        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 38,
            lineHeight: 1.28,
            color: COULEURS.or,
            letterSpacing: -0.8,
            marginTop: 40,
          }}
        >
          Pendant qu&apos;ils jouent au feeling, vous jouez aux chiffres.
        </span>

        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 44,
          }}
        >
          {nb(d.coursesEnBase)} courses et {nb(d.partantsAnalyses)} partants en base. Programme,
          cotes et rapports officiels en accès libre.
        </span>
      </Carte>

      {/* ═══════════ (0,1) — LE chiffre, et son témoin ═══════════
          Un taux seul ne prouve rien : 60 % sur des champs de onze partants, est-ce beaucoup ?
          Le hasard sur EXACTEMENT les mêmes courses répond, et c'est la seule façon honnête
          de vendre une précision — sans jamais parler d'argent. */}
      <Carte x={col(1) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow>CE QUE ÇA DONNE, MESURÉ</Eyebrow>
        {d.precisionTop3 !== null ? (
          <div style={{ display: "flex", flexDirection: "column", marginTop: 72 }}>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 162,
                lineHeight: 1,
                color: COULEURS.encre,
                letterSpacing: -6,
              }}
            >
              {pct(d.precisionTop3)}
            </span>
            <span
              style={{
                fontFamily: "Inter",
                fontSize: 30,
                lineHeight: 1.4,
                color: COULEURS.encre,
                marginTop: 16,
              }}
            >
              des courses : le gagnant est dans notre top 3
            </span>
          </div>
        ) : null}

        {d.hasardTop3 !== null ? (
          <div style={{ display: "flex", alignItems: "center", marginTop: 44 }}>
            <div style={{ display: "flex", width: 40, height: 3, background: COULEURS.ligne }} />
            <span
              style={{
                fontFamily: "Inter",
                fontSize: 26,
                color: COULEURS.encreDouce,
                marginLeft: 14,
              }}
            >
              Le hasard, sur les mêmes courses : {pct(d.hasardTop3)}
            </span>
          </div>
        ) : null}

        <div style={{ display: "flex", marginTop: 62 }}>
          <div style={{ display: "flex", flexDirection: "column", width: 380 }}>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 66,
                lineHeight: 1,
                color: COULEURS.or,
                letterSpacing: -2,
              }}
            >
              {d.favoriPlace !== null ? pct(d.favoriPlace) : "—"}
            </span>
            <span style={{ fontFamily: "Inter", fontSize: 24, color: COULEURS.encreDouce, marginTop: 8 }}>
              notre favori dans les trois
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <span
              style={{
                fontFamily: "Grotesk",
                fontWeight: 700,
                fontSize: 66,
                lineHeight: 1,
                color: COULEURS.or,
                letterSpacing: -2,
              }}
            >
              {d.favoriGagnant !== null ? pct(d.favoriGagnant) : "—"}
            </span>
            <span style={{ fontFamily: "Inter", fontSize: 24, color: COULEURS.encreDouce, marginTop: 8 }}>
              notre favori gagnant
            </span>
          </div>
        </div>

        <span
          style={{
            fontFamily: "Inter",
            fontSize: 24,
            lineHeight: 1.45,
            color: COULEURS.encreDouce,
            marginTop: 52,
          }}
        >
          Mesuré sur {nb(d.coursesMesurees)} courses réglées aux rapports officiels du PMU.
        </span>
        <div style={{ display: "flex", marginTop: 38 }}>
          <Adresse />
        </div>
      </Carte>

      {/* ═══════════ (0,2) — l'algorithme, et ce qu'il fait la nuit ═══════════
          Les familles de critères sont celles du dépliant, et volontairement les moins
          attendues : « forme et cotes » n'impressionne personne, « contrecoup après un gros
          effort » et « coups de cote à 30 minutes » disent qu'on a vraiment regardé. */}
      <Carte x={col(2) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow>L&apos;ALGORITHME</Eyebrow>
        <div style={{ display: "flex", alignItems: "baseline", marginTop: 44 }}>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 132,
              lineHeight: 1,
              color: COULEURS.encre,
              letterSpacing: -6,
            }}
          >
            80+
          </span>
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 29,
              color: COULEURS.encreDouce,
              marginLeft: 20,
            }}
          >
            critères par cheval
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", marginTop: 40 }}>
          {[
            "Contrecoup, surmenage, descente de catégorie",
            "Biais de corde, déferrage, pénétromètre",
            "Père sur ce terrain, jockey × ce cheval",
            "Argent professionnel, coups de cote à 30 min",
          ].map((ligne) => (
            <div key={ligne} style={{ display: "flex", alignItems: "center", marginBottom: 22 }}>
              <div
                style={{ display: "flex", width: 9, height: 9, borderRadius: 5, background: COULEURS.orVif }}
              />
              <span
                style={{
                  fontFamily: "Inter",
                  fontSize: 26,
                  lineHeight: 1.35,
                  color: COULEURS.encre,
                  marginLeft: 16,
                }}
              >
                {ligne}
              </span>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", width: 72, height: 3, background: COULEURS.ligne, marginTop: 24 }} />
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 26,
          }}
        >
          Recalibré chaque nuit sur les arrivées réelles. Ce qui s&apos;est trompé hier corrige
          le pronostic d&apos;aujourd&apos;hui.
        </span>
        <div style={{ display: "flex", marginTop: 34 }}>
          <Adresse />
        </div>
      </Carte>
      {/* ═══════════ (1,0) — ce que fait le site ═══════════ */}
      <div
        style={{ position: "absolute", left: col(0) + MARGE, top: bas + 112, width: utile, display: "flex" }}
      >
        <Eyebrow ton="sombre">CE QUE VOUS OBTENEZ</Eyebrow>
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
        {/* Formulé en BÉNÉFICES, comme le dépliant : « ce que vous obtenez », pas « ce que
            le logiciel fait ». Et le chiffre « 80+ » porte déjà la tuile (0,2) — le répéter
            ici le banaliserait, alors que les deux se lisent côte à côte sur la grille. */}
        <Atout
          titre="Tout le programme, analysé"
          texte="Chaque partant classé, avec sa probabilité et sa cote juste, avant le départ."
        />
        {/* Le plan de mise a sa propre tuile juste à côté (1,1) : le décrire ici aussi
            ferait deux fois la même chose sur la même rangée de la grille. La place
            revient aux cotes comparées, qui n'étaient nulle part. */}
        <Atout
          titre="Les cotes comparées"
          texte="PMU et principaux opérateurs côte à côte, avec le mouvement : on voit où la cote décroche."
        />
        <Atout
          titre="Les paris de valeur"
          texte="Signalés seulement quand la cote paie plus que le risque réel du cheval."
        />
        <Atout
          titre="Votre capital suivi sans triche"
          texte="Réglé aux vrais rapports PMU. Les paris perdus sont affichés aussi."
        />
        <Atout
          titre="Alerté dès qu'un signal sort"
          texte="Notification et e-mail sur les courses que vous suivez."
        />
      </div>
      <div style={{ position: "absolute", left: col(0) + MARGE, top: bas + 1092, display: "flex" }}>
        <Adresse ton="sombre" />
      </div>

      {/* ═══════════ (1,1) — le plan de mise, la démonstration ═══════════
          Cette tuile portait le prélèvement du PMU. Retirée sur décision produit.

          Ce qui la remplace est ce que le produit fait de plus singulier : personne
          d'autre ne répartit une mise sur le budget du joueur. Un ticket type se recopie ;
          une répartition, non.

          CE QUI N'EST VOLONTAIREMENT PAS AFFICHÉ : les gains potentiels de chaque ticket.
          « 4 € » en face de « ~112 € » se lit comme un rendement attendu alors que c'est
          un rapport conditionnel. Les probabilités estimées, elles, sont montrées — ce
          sont les seules qui disent la vérité sur ce qu'on achète. */}
      <div
        style={{ position: "absolute", left: col(1) + MARGE, top: bas + 108, width: utile, display: "flex" }}
      >
        <Eyebrow ton="sombre">LE PLAN DE MISE</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 190,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 68,
            lineHeight: 1.1,
            color: COULEURS.surSombre,
            letterSpacing: -2.2,
          }}
        >
          Votre budget, réparti
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 68,
            lineHeight: 1.1,
            color: COULEURS.orVif,
            letterSpacing: -2.2,
          }}
        >
          pari par pari.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 29,
            lineHeight: 1.5,
            color: COULEURS.surSombreDoux,
            marginTop: 26,
          }}
        >
          Vous entrez un montant, le plan s&apos;écrit. Exemple pour 20&#160;€ :
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 462,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {[
          ["SÉCURITÉ · 40 %", "8 €", "Couplé Placé — 2 + 4", "probabilité estimée 41 %"],
          ["RENDEMENT · 40 %", "8 €", "Simple Gagnant — 4", "probabilité estimée 17 %"],
          ["GROS LOT · 20 %", "4 €", "Couplé Gagnant — 2 + 4", "probabilité estimée 9 %"],
        ].map(([part, mise, pari, proba]) => (
          <div
            key={part}
            style={{
              display: "flex",
              flexDirection: "column",
              paddingTop: 20,
              paddingBottom: 20,
              borderTop: `1px solid ${COULEURS.ligneSombre}`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
              <span
                style={{
                  fontFamily: "Inter",
                  fontWeight: 600,
                  fontSize: 22,
                  letterSpacing: 2.4,
                  color: COULEURS.orVif,
                }}
              >
                {part}
              </span>
              <span
                style={{
                  fontFamily: "Grotesk",
                  fontWeight: 700,
                  fontSize: 34,
                  color: COULEURS.surSombre,
                  letterSpacing: -1,
                }}
              >
                {mise}
              </span>
            </div>
            <span
              style={{
                fontFamily: "Inter",
                fontSize: 28,
                color: COULEURS.surSombre,
                marginTop: 10,
              }}
            >
              {pari}
            </span>
            <span
              style={{ fontFamily: "Inter", fontSize: 24, color: COULEURS.surSombreDoux, marginTop: 4 }}
            >
              {proba}
            </span>
          </div>
        ))}
      </div>

      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 978,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 25,
            lineHeight: 1.45,
            color: COULEURS.surSombreDoux,
          }}
        >
          Plan d&apos;exemple. La répartition s&apos;adapte à votre budget et à votre profil —
          prudent, modéré ou risqué.
        </span>
      </div>
      <div style={{ position: "absolute", left: col(1) + MARGE, top: bas + 1092, display: "flex" }}>
        <Adresse ton="sombre" />
      </div>

      {/* ═══════════ (1,2) — la conversion ═══════════ */}
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
        {/* Titre repris du dépliant. « 7 jours offerts » annonce une durée ; « moins cher
            qu'un ticket perdu » annonce un ordre de grandeur, et se retient. */}
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 76,
            lineHeight: 1.08,
            color: COULEURS.surSombre,
            letterSpacing: -2.6,
          }}
        >
          Moins cher qu&apos;un ticket perdu.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 28,
            lineHeight: 1.5,
            color: COULEURS.surSombreDoux,
            marginTop: 24,
          }}
        >
          Sept jours d&apos;essai gratuit, puis 12&nbsp;€/mois. Annulation en deux clics.
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          left: col(2) + MARGE,
          top: bas + 512,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Quotas réels, pas des formules commerciales : `MISE_PLAN_DAILY_LIMITS` vaut
            {"{"}free: 1, standard: 5{"}"} côté API, et l'expert n'y figure pas — donc
            illimité. Annoncer autre chose se verrait dès le premier essai. */}
        {[
          ["Découverte", "0 €", "1 plan de mise par jour, cotes et arrivées"],
          ["Standard", "12 €/mois", "5 plans par jour, suivi du capital, alertes"],
          ["Expert", "19 €/mois", "illimité, paris de valeur en temps réel"],
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
          top: bas + 892,
          width: utile,
          display: "flex",
          flexDirection: "column",
          padding: "40px 46px",
          borderRadius: 22,
          background: COULEURS.orVif,
        }}
      >
        <span style={{ fontFamily: "Inter", fontWeight: 600, fontSize: 25, color: "#4A3504" }}>
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
          Chaque tuile est publiée séparément : la mention se répète sur les trois colonnes,
          elle ne se découpe pas. */}
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
          <span style={{ fontFamily: "Inter", fontSize: 22, lineHeight: 1.45, color: COULEURS.encreDouce }}>
            Jouer comporte des risques : endettement, isolement, dépendance.
            09&#160;74&#160;75&#160;13&#160;13, appel non surtaxé. Interdit aux mineurs.
          </span>
        </div>
      ))}

      {/* ═══════════ Bandeau légal continu, rangée basse ═══════════ */}
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
export function TuileSite({ d, rangee, colonne }: { d: DonneesSite; rangee: number; colonne: number }) {
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
        <PlanSite d={d} />
      </div>
    </div>
  );
}
