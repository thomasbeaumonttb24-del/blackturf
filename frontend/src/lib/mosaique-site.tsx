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
  photo: string | null;
}

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

      {/* ═══════════ (0,0) — la marque et ce qu'elle fait ═══════════
          Publiée en DERNIER, donc en tête du profil et en tête du fil : c'est elle qui doit
          expliquer BlackTurf à quelqu'un qui n'en a jamais entendu parler. */}
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
          <Eyebrow>PRONOSTICS PMU CALCULÉS</Eyebrow>
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
          <div style={{ display: "flex", width: 400 }}>
            <Chiffre valeur={nb(d.coursesEnBase)} legende="courses en base" taille={72} />
          </div>
          <div style={{ display: "flex" }}>
            <Chiffre valeur={nb(d.partantsAnalyses)} legende="partants analysés" taille={72} />
          </div>
        </div>

        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 46,
          }}
        >
          Programme, cotes et rapports officiels en accès libre.
        </span>
      </Carte>

      {/* ═══════════ (0,1) — LE chiffre ═══════════
          Le seul chiffre que personne d'autre n'affiche : le dénominateur. Un site de
          pronostics montre ses coups gagnants ; celui-ci montre d'abord combien de courses
          il a réglées, gagnantes ou non. C'est ce qui rend le reste crédible. */}
      <Carte x={col(1) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow>LA PREUVE, PAS LA PROMESSE</Eyebrow>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 96 }}>
          <Chiffre
            valeur={nb(d.coursesReglees)}
            legende="courses réglées aux rapports officiels du PMU"
          />
        </div>
        <div style={{ display: "flex", width: 72, height: 3, background: COULEURS.ligne, marginTop: 88 }} />
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 27,
            lineHeight: 1.5,
            color: COULEURS.encre,
            marginTop: 36,
          }}
        >
          Chaque pronostic est figé AVANT le départ, puis réglé à l&apos;arrivée. Aucune
          reconstruction après coup.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 28,
          }}
        >
          {nb(d.journeesPubliees)} journées publiées, gagnantes comme perdantes.
        </span>
        <div style={{ display: "flex", marginTop: 52 }}>
          <Adresse />
        </div>
      </Carte>

      {/* ═══════════ (0,2) — comment c'est calculé ═══════════ */}
      <Carte x={col(2) + CARTE_X} y={CARTE_Y} l={CARTE_L} h={CARTE_H}>
        <Eyebrow>COMMENT C&apos;EST CALCULÉ</Eyebrow>
        <div style={{ display: "flex", flexDirection: "column", marginTop: 96 }}>
          <Chiffre valeur="80" legende="critères par cheval, à chaque course" />
        </div>
        <div style={{ display: "flex", width: 72, height: 3, background: COULEURS.ligne, marginTop: 88 }} />
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 27,
            lineHeight: 1.5,
            color: COULEURS.encre,
            marginTop: 36,
          }}
        >
          Une probabilité calculée pour chaque partant, publiée avant le départ. Pas un avis :
          un calcul.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 26,
            lineHeight: 1.5,
            color: COULEURS.encreDouce,
            marginTop: 28,
          }}
        >
          Et les cotes du PMU et des principaux opérateurs, côte à côte.
        </span>
        <div style={{ display: "flex", marginTop: 52 }}>
          <Adresse />
        </div>
      </Carte>

      {/* ═══════════ (1,0) — ce que fait le site ═══════════ */}
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
        {/* Le chiffre « 80 critères » porte déjà la tuile (0,2) : le répéter ici le
            banaliserait, et sur la grille les deux se lisent côte à côte. */}
        <Atout
          titre="Il lit le programme pour vous"
          texte="Toutes les courses de la carte, tous les partants, dépouillés avant le départ."
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

      {/* ═══════════ (1,1) — nommer l'adversaire, puis vendre contre lui ═══════════
          Première version : trois paragraphes qui expliquaient pourquoi on ne peut PAS
          gagner. C'était vrai, et ça ne vendait rien — un mur de texte qui prévient au
          lieu de proposer.
          Celle-ci garde exactement la même honnêteté mais renverse le mouvement : le
          prélèvement devient l'ADVERSAIRE, la barre le rend visible en une seconde, et
          la suite dit ce qu'on peut faire contre lui — et où aller le vérifier. */}
      <div
        style={{ position: "absolute", left: col(1) + MARGE, top: bas + 108, width: utile, display: "flex" }}
      >
        <Eyebrow ton="sombre">VOTRE VRAI ADVERSAIRE</Eyebrow>
      </div>
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 196,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 76,
            lineHeight: 1.1,
            color: COULEURS.surSombre,
            letterSpacing: -2.5,
          }}
        >
          Ce n&apos;est pas le favori.
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 76,
            lineHeight: 1.1,
            color: COULEURS.orVif,
            letterSpacing: -2.5,
          }}
        >
          C&apos;est le prélèvement.
        </span>
      </div>

      {/* La barre : 20 % d'un trait valent trois phrases. Les largeurs sont en pixels et
          non en pourcentages — Satori calcule mal les pourcentages dans un flex absolu. */}
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 396,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Inter",
            fontWeight: 600,
            fontSize: 23,
            letterSpacing: 2.6,
            color: COULEURS.surSombreDoux,
          }}
        >
          SUR 100&#160;€ JOUÉS AU PMU
        </span>
        <div style={{ display: "flex", marginTop: 20 }}>
          <div
            style={{
              display: "flex",
              width: Math.round(utile * 0.8),
              height: 28,
              background: COULEURS.orVif,
              borderTopLeftRadius: 14,
              borderBottomLeftRadius: 14,
            }}
          />
          <div
            style={{
              display: "flex",
              width: utile - Math.round(utile * 0.8),
              height: 28,
              background: "#3A424C",
              borderTopRightRadius: 14,
              borderBottomRightRadius: 14,
            }}
          />
        </div>
        {/* Chaque libellé prend la couleur de SON segment. Sans ça, l'or désignait les
            80 € dans la barre et les 20 € dans le libellé, et l'œil ne savait plus ce que
            la couleur voulait dire. */}
        <div style={{ display: "flex", justifyContent: "space-between", width: utile, marginTop: 16 }}>
          <span style={{ fontFamily: "Inter", fontWeight: 600, fontSize: 25, color: COULEURS.orVif }}>
            80&#160;€ redistribués
          </span>
          <span style={{ fontFamily: "Inter", fontSize: 25, color: "#A8B0BA" }}>
            20&#160;€ prélevés
          </span>
        </div>
      </div>

      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 560,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 29,
            lineHeight: 1.55,
            color: COULEURS.surSombreDoux,
          }}
        >
          Aucun pronostiqueur n&apos;efface ces 20&#8239;%. Qui vous promet le contraire vous
          ment, ou ne sait pas compter.
        </span>
        <span
          style={{
            fontFamily: "Inter",
            fontSize: 30,
            lineHeight: 1.55,
            color: COULEURS.surSombre,
            marginTop: 34,
          }}
        >
          Ce qui se joue, c&apos;est le reste : repérer les chevaux dont la cote est plus
          haute que leur vraie chance. BlackTurf le calcule sur chaque partant, avant le
          départ.
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 878,
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
            fontSize: 42,
            lineHeight: 1.24,
            color: COULEURS.orVif,
            letterSpacing: -1,
            marginTop: 30,
          }}
        >
          Le seul service de pronostics qui publie aussi ses pertes.
        </span>
      </div>

      {/* L'adresse seule ne demandait rien. Ici elle porte une action et une raison d'y
          aller — c'est le seul endroit de la mosaïque où on invite à VÉRIFIER. */}
      <div
        style={{
          position: "absolute",
          left: col(1) + MARGE,
          top: bas + 1072,
          width: utile,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <span style={{ fontFamily: "Inter", fontSize: 25, color: COULEURS.surSombreDoux }}>
          Le bilan complet, pertes comprises :
        </span>
        <div style={{ display: "flex", alignItems: "center", marginTop: 8 }}>
          <div style={{ display: "flex", width: 22, height: 3, background: COULEURS.orVif }} />
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 34,
              letterSpacing: -0.8,
              color: COULEURS.orVif,
              marginLeft: 14,
            }}
          >
            blackturf.fr/track-record
          </span>
        </div>
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
