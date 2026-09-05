import { Adresse, COULEURS, DateDuJour, Eyebrow } from "@/lib/mosaique";
import { MENTION_LEGALE } from "@/lib/visuels";

/**
 * Story du soir — 1080 × 1920, le bilan de la journée.
 *
 * ─────────────────────────── LA GÉOMÉTRIE ───────────────────────────
 *
 * Une story Instagram est recouverte par l'interface de l'application : environ 250 px
 * en haut (avatar, barre de progression) et 250 px en bas (champ « Envoyer un message »,
 * boutons). Tout ce qui compte tient donc entre y = 250 et y = 1670, et le bas de
 * l'image est volontairement vide — un chiffre posé à 1800 px serait masqué par le
 * clavier chez la moitié des lecteurs.
 *
 * ─────────────────────────── LE VOCABULAIRE, QUI N'EST PAS DÉCORATIF ───────────────────────────
 *
 * Le montant affiché est ce que les plans ont RENDU, réglé aux rapports officiels du
 * PMU. Ce n'est ni un bénéfice, ni de l'argent encaissé par qui que ce soit : la mise
 * n'est pas affichée sur ce visuel (choix produit tranché le 2026-09-05), donc le
 * chiffre ne peut pas être présenté comme un gain net. « Rendu par les plans » est
 * exact ; « gagné », « nos gains » ou « bénéfice » seraient faux.
 *
 * Le NOMBRE DE PLANS DU JOUR est affiché à côté du nombre de plans gagnants, et ce
 * n'est pas un détail : sans lui, « 29 plans gagnants » se lirait comme si tous les
 * plans avaient gagné. Avec « sur les 153 du jour », le lecteur voit la proportion
 * réelle sans qu'aucune mise ne soit publiée.
 */

export const STORY_L = 1080;
export const STORY_H = 1920;

/** Hauteur de la bande photo, fondue vers l'ivoire sur son dernier tiers. */
export const PHOTO_H = 860;
/** La carte blanche chevauche la photo : c'est ce chevauchement qui tient la page. */
const CARTE_X = 60;
const CARTE_Y = 530;
const CARTE_L = STORY_L - CARTE_X * 2;
const CARTE_H = 820;
const BANDE_Y = CARTE_Y + CARTE_H; // 1350
/**
 * Le socle en encre commence à 1350 et non plus à 1430 : la mention légale se posait
 * sinon à 1690, c'est-à-dire SOUS le champ « Envoyer un message » d'Instagram. Une
 * mention de jeu responsable masquée par l'interface ne vaut pas mieux qu'une mention
 * absente — c'est même exactement ce que les plateformes sanctionnent.
 */
const BANDE_CONTENU_Y = BANDE_Y + 44;

export interface PlanStory {
  hippodrome: string;
  code: string;
  retour: number;
}

export interface DonneesStory {
  jourLong: string;
  nbPlans: number;
  nbPlansGagnants: number;
  totalRetour: number;
  plans: PlanStory[];
  photo: string | null;
}

/** Montants : les centimes ne s'affichent que s'il y en a. Même règle que la mosaïque. */
const euro = (n: number) =>
  n.toLocaleString("fr-FR", {
    minimumFractionDigits: Number.isInteger(n) ? 0 : 2,
    maximumFractionDigits: 2,
  });

/** Une ligne de podium : la course, puis ce que son plan a rendu. */
function LigneCourte({ p, rang }: { p: PlanStory; rang: number }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        width: "100%",
        marginTop: 18,
      }}
    >
      <div style={{ display: "flex", alignItems: "center" }}>
        <span
          style={{
            display: "flex",
            width: 38,
            height: 38,
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 8,
            background: rang === 1 ? COULEURS.orVif : COULEURS.ivoire,
            color: rang === 1 ? "#1B1405" : COULEURS.encreDouce,
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 21,
          }}
        >
          {rang}
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 30,
            color: COULEURS.encre,
            marginLeft: 16,
            letterSpacing: -0.6,
          }}
        >
          {p.hippodrome} · {p.code}
        </span>
      </div>
      <span
        style={{
          fontFamily: "Grotesk",
          fontWeight: 700,
          fontSize: 36,
          color: COULEURS.or,
          letterSpacing: -1,
        }}
      >
        {euro(p.retour)} €
      </span>
    </div>
  );
}

export function Story({ d }: { d: DonneesStory }) {
  const podium = d.plans.slice(0, 3);
  return (
    <div
      style={{
        display: "flex",
        position: "relative",
        width: STORY_L,
        height: STORY_H,
        background: COULEURS.ivoire,
      }}
    >
      {d.photo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={d.photo}
          alt=""
          width={STORY_L}
          height={PHOTO_H}
          style={{ position: "absolute", left: 0, top: 0, objectFit: "cover" }}
        />
      )}
      {/* Fondu : la photo doit s'éteindre AVANT la carte, sinon le blanc se découpe
          dessus comme un autocollant. */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: STORY_L,
          height: PHOTO_H,
          display: "flex",
          background:
            "linear-gradient(180deg, rgba(245,242,234,0.06) 0%, rgba(245,242,234,0.00) 40%, rgba(245,242,234,0.42) 76%, rgba(245,242,234,0.92) 94%, #F5F2EA 100%)",
        }}
      />

      {/* La marque, posée dans le haut de la photo — sous la zone masquée par
          l'interface d'Instagram, jamais dedans. */}
      <div
        style={{
          position: "absolute",
          left: CARTE_X,
          top: 268,
          display: "flex",
          alignItems: "center",
          padding: "18px 30px",
          borderRadius: 18,
          background: "rgba(21,24,29,0.72)",
        }}
      >
        <div style={{ display: "flex", width: 10, height: 40, background: COULEURS.orVif }} />
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 40,
            color: COULEURS.surSombre,
            marginLeft: 16,
            letterSpacing: -1,
          }}
        >
          BlackTurf
        </span>
      </div>

      {/* ══════════ La carte : la date, le montant rendu, le podium ══════════ */}
      <div
        style={{
          position: "absolute",
          left: CARTE_X,
          top: CARTE_Y,
          width: CARTE_L,
          height: CARTE_H,
          display: "flex",
          flexDirection: "column",
          background: COULEURS.blanc,
          borderRadius: 30,
          padding: "50px 56px",
          border: `1px solid ${COULEURS.ligne}`,
        }}
      >
        <DateDuJour jour={d.jourLong} />

        <div style={{ display: "flex", marginTop: 34 }}>
          <Eyebrow>CE QUE LES PLANS ONT RENDU</Eyebrow>
        </div>

        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 176,
            lineHeight: 1,
            color: COULEURS.or,
            letterSpacing: -7,
            marginTop: 14,
          }}
        >
          {euro(d.totalRetour)} €
        </span>

        <span
          style={{
            fontFamily: "Inter",
            fontSize: 27,
            lineHeight: 1.45,
            color: COULEURS.encreDouce,
            marginTop: 18,
          }}
        >
          {d.nbPlansGagnants} plans gagnants sur les {d.nbPlans} calculés aujourd&apos;hui,
          réglés aux rapports officiels du PMU.
        </span>

        <div
          style={{ display: "flex", width: "100%", height: 1, background: COULEURS.ligne, marginTop: 34 }}
        />

        <div style={{ display: "flex", marginTop: 26 }}>
          <span
            style={{
              fontFamily: "Inter",
              fontWeight: 600,
              fontSize: 22,
              letterSpacing: 2.8,
              color: COULEURS.encreTenue,
            }}
          >
            LES TROIS QUI ONT LE PLUS RENDU
          </span>
        </div>

        <div style={{ display: "flex", flexDirection: "column", marginTop: 6 }}>
          {podium.map((p, i) => (
            <LigneCourte key={`${p.code}-${i}`} p={p} rang={i + 1} />
          ))}
        </div>
      </div>

      {/* ══════════ Socle en encre : où aller, et la mention légale ══════════ */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: BANDE_Y,
          width: STORY_L,
          height: STORY_H - BANDE_Y,
          display: "flex",
          background: COULEURS.encre,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: 0,
          top: BANDE_Y - 3,
          width: STORY_L,
          height: 6,
          display: "flex",
          background: "linear-gradient(90deg, #C8901F 0%, #E0A63C 50%, #C8901F 100%)",
        }}
      />

      {/* Tout le socle est UNE colonne, mention légale comprise : posée en absolu, elle
          se retrouvait fatalement dans la zone que l'interface d'Instagram recouvre dès
          qu'un bloc au-dessus changeait de hauteur. Ici elle suit le flux et remonte
          d'elle-même. */}
      <div
        style={{
          position: "absolute",
          left: CARTE_X,
          top: BANDE_CONTENU_Y,
          width: CARTE_L,
          display: "flex",
          flexDirection: "column",
        }}
      >
        <Eyebrow ton="sombre">LE DÉTAIL EST EN LIGNE</Eyebrow>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 42,
            lineHeight: 1.15,
            color: COULEURS.surSombre,
            marginTop: 14,
            letterSpacing: -1.2,
          }}
        >
          Chaque plan du jour, course par course — les perdants aussi.
        </span>
        <div style={{ display: "flex", marginTop: 22 }}>
          <Adresse ton="sombre" />
        </div>
        {/* La mention de jeu responsable est portée par le visuel lui-même : une image
            circule hors de sa légende, et c'est l'image qu'on retrouve republiée. */}
        <span
          style={{
            display: "flex",
            marginTop: 20,
            fontFamily: "Inter",
            fontSize: 20,
            lineHeight: 1.45,
            color: COULEURS.surSombreTenu,
          }}
        >
          {MENTION_LEGALE}
        </span>
      </div>
    </div>
  );
}
