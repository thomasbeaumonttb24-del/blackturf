/**
 * Les plans d'un Reel — images verticales 1080 × 1920, assemblées ensuite en vidéo.
 *
 * ─────────────────────────── LA CHARTE EST CELLE DU SITE ───────────────────────────────
 *
 * Première version : encre sombre et un or approximatif. Le résultat ne ressemblait à
 * rien de ce que le visiteur trouve en arrivant sur blackturf.fr — or c'est exactement
 * ce qu'une vidéo de présentation doit promettre. Les valeurs ci-dessous sont donc
 * reprises telles quelles de `tailwind.config.ts` et de `globals.css` :
 *
 *   rampe or  #B45309 → #D97706 → #F59E0B → #FCD34D → #FEF3C7 → #FFFBEB
 *   encre     #111827, charbon #374151
 *   fonds     crème #FFFBF0, chaud #FAFAF8
 *   vert      #059669 (positif)
 *   dégradé   linear-gradient(135deg, #B45309, #D97706, #F59E0B)
 *   halos     radial-gradient(ellipse, rgba(245,158,11,.10), transparent)
 *   ombre     0 12px 40px rgba(0,0,0,.10), 0 0 0 1px rgba(245,158,11,.18)
 *
 * ─────────────────────────── CE QUE LE FORMAT IMPOSE ───────────────────────────────────
 *
 * 1. LA PREMIÈRE SECONDE DÉCIDE DE TOUT. Le plan 0 ne présente rien : il interpelle.
 * 2. ON REGARDE SANS LE SON, et l'API ne permet pas d'attacher un son tendance : tout
 *    passe par le texte et par l'image, donc UNE idée par plan, en très gros.
 * 3. L'INTERFACE D'INSTAGRAM RECOUVRE LE BAS. Rien d'important sous 1560 px.
 * 4. UN CHIFFRE SEUL NE CONVAINC PAS. Le plan du taux porte un GRAPHIQUE comparatif :
 *    « 60 % » ne veut rien dire tant qu'on ne voit pas ce que fait le hasard à côté.
 * 5. ON MONTRE LE PRODUIT. Un plan reproduit l'écran du plan de mise : c'est ce qui
 *    donne envie d'aller voir, bien plus qu'une promesse écrite.
 *
 * Satori : pas de fragments React enfants d'un flex (les éléments se superposent en
 * silence), et pas de `background-clip: text` — un dégradé dans une police n'est pas
 * rendu. Les dégradés vivent donc dans des aplats, jamais dans du texte.
 */

export const REEL_L = 1080;
export const REEL_H = 1920;

const OR = "#F59E0B";
const OR_PROFOND = "#D97706";
const OR_SOMBRE = "#B45309";
const OR_TEINTE = "#FEF3C7";
const ENCRE = "#111827";
const CHARBON = "#374151";
const GRIS = "#6B7280";
const CREME = "#FFFBF0";
const VERT = "#047857";
const DEGRADE_OR = `linear-gradient(135deg, ${OR_SOMBRE} 0%, ${OR_PROFOND} 50%, ${OR} 100%)`;
const OMBRE_CARTE = "0 12px 40px rgba(0,0,0,0.10), 0 0 0 1px rgba(245,158,11,0.18)";

const MARGE = 84;
const utile = REEL_L - MARGE * 2;

export interface DonneesReel {
  precisionTop3: number | null;
  hasardTop3: number | null;
  coursesMesurees: number;
  photo: string | null;
}

const pct = (n: number) => `${n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;
const nb = (n: number) => n.toLocaleString("fr-FR").replace(/[  ]/g, " ");

/* ─────────────────────────────────── Le cadre ─────────────────────────────────────── */

/**
 * Fond crème + halos dorés, exactement comme le `body` du site. Les halos ne sont pas
 * décoratifs : sans eux un aplat crème en 1080 × 1920 paraît plat et bon marché.
 */
function Fond({ sombre = false }: { sombre?: boolean }) {
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: REEL_L,
        height: REEL_H,
        display: "flex",
        background: sombre
          ? "linear-gradient(180deg, #0E1116 0%, #111827 55%, #0B0E13 100%)"
          : `linear-gradient(180deg, ${CREME} 0%, #FFFFFF 60%, ${CREME} 100%)`,
      }}
    />
  );
}

function Halos({ sombre = false }: { sombre?: boolean }) {
  const a = sombre ? "rgba(245,158,11,0.16)" : "rgba(245,158,11,0.13)";
  const b = sombre ? "rgba(217,119,6,0.12)" : "rgba(217,119,6,0.09)";
  return (
    <div
      style={{
        position: "absolute",
        left: 0,
        top: 0,
        width: REEL_L,
        height: REEL_H,
        display: "flex",
        background:
          `radial-gradient(ellipse 70% 40% at 15% 12%, ${a} 0%, transparent 60%),` +
          `radial-gradient(ellipse 80% 45% at 90% 88%, ${b} 0%, transparent 60%)`,
      }}
    />
  );
}

/** Le bandeau de marque, identique sur tous les plans : c'est lui qui fait la série. */
function Marque({ sombre = false }: { sombre?: boolean }) {
  return (
    <div
      style={{
        position: "absolute",
        left: MARGE,
        top: 118,
        width: utile,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}
    >
      <div style={{ display: "flex", alignItems: "center" }}>
        <div
          style={{
            display: "flex",
            width: 46,
            height: 46,
            borderRadius: 12,
            background: DEGRADE_OR,
          }}
        />
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 40,
            color: sombre ? "#FFFFFF" : ENCRE,
            marginLeft: 18,
            letterSpacing: -1,
          }}
        >
          BlackTurf
        </span>
      </div>
      <span
        style={{
          fontFamily: "Inter",
          fontWeight: 600,
          fontSize: 26,
          color: sombre ? OR : OR_SOMBRE,
        }}
      >
        blackturf.fr
      </span>
    </div>
  );
}

/** Progression de la série : on sait où on en est, et qu'il reste quelque chose. */
function Progression({ n, sombre = false }: { n: number; sombre?: boolean }) {
  return (
    <div style={{ position: "absolute", left: MARGE, top: 196, width: utile, display: "flex" }}>
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          style={{
            display: "flex",
            width: Math.floor((utile - 5 * 10) / 6),
            height: 5,
            marginLeft: i ? 10 : 0,
            borderRadius: 3,
            background: i <= n ? OR : sombre ? "rgba(255,255,255,0.16)" : "rgba(17,24,39,0.10)",
          }}
        />
      ))}
    </div>
  );
}

function Legal({ sombre = false }: { sombre?: boolean }) {
  return (
    <div style={{ position: "absolute", left: MARGE, top: 1712, width: utile, display: "flex" }}>
      <span
        style={{
          fontFamily: "Inter",
          fontSize: 23,
          lineHeight: 1.4,
          color: sombre ? "rgba(255,255,255,0.55)" : "#9CA3AF",
        }}
      >
        Jouer comporte des risques : endettement, isolement, dépendance.
        09&#160;74&#160;75&#160;13&#160;13. Interdit aux mineurs.
      </span>
    </div>
  );
}

function Plan({
  n,
  children,
  photo,
  sombre = false,
}: {
  n: number;
  children: React.ReactNode;
  photo?: string | null;
  sombre?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        position: "relative",
        width: REEL_L,
        height: REEL_H,
        background: sombre ? ENCRE : CREME,
      }}
    >
      {/* Expressions séparées, jamais un fragment : Satori les ignore dans un flex. */}
      {photo ? null : <Fond sombre={sombre} />}
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
              "linear-gradient(180deg, rgba(10,13,18,0.78) 0%, rgba(10,13,18,0.34) 38%, rgba(10,13,18,0.86) 74%, #0B0E13 100%)",
          }}
        />
      ) : null}
      {photo ? null : <Halos sombre={sombre} />}

      <Marque sombre={sombre} />
      <Progression n={n} sombre={sombre} />

      {/* Contenu centré dans la zone sûre : sur un téléphone, le regard est au milieu. */}
      <div
        style={{
          position: "absolute",
          left: MARGE,
          top: 300,
          width: utile,
          height: 1280,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        {children}
      </div>

      <Legal sombre={sombre} />
    </div>
  );
}

/* ──────────────────────────────── Briques réutilisées ─────────────────────────────── */

function Surtitre({ children, ton = "or" }: { children: string; ton?: "or" | "gris" }) {
  return (
    <span
      style={{
        fontFamily: "Inter",
        fontWeight: 600,
        fontSize: 27,
        letterSpacing: 3.6,
        color: ton === "or" ? OR_SOMBRE : GRIS,
      }}
    >
      {children}
    </span>
  );
}

/** Carte blanche, avec l'ombre et le liseré doré du site. */
function Carte({ children, padding = 52 }: { children: React.ReactNode; padding?: number }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        width: utile,
        padding,
        borderRadius: 28,
        background: "#FFFFFF",
        boxShadow: OMBRE_CARTE,
      }}
    >
      {children}
    </div>
  );
}

/** Une barre de comparaison. C'est elle qui transforme un taux en démonstration. */
function Barre({
  valeur,
  max,
  libelle,
  doree,
}: {
  valeur: number;
  max: number;
  libelle: string;
  doree: boolean;
}) {
  const largeur = Math.max(60, Math.round((utile - 104) * (valeur / max)));
  return (
    <div style={{ display: "flex", flexDirection: "column", marginBottom: 34 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", width: "100%" }}>
        <span style={{ fontFamily: "Inter", fontSize: 27, color: doree ? ENCRE : GRIS }}>{libelle}</span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: doree ? 62 : 50,
            color: doree ? OR_SOMBRE : "#9CA3AF",
            letterSpacing: -2,
          }}
        >
          {pct(valeur)}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          width: largeur,
          height: doree ? 26 : 20,
          marginTop: 12,
          borderRadius: 13,
          background: doree ? DEGRADE_OR : "#E5E7EB",
        }}
      />
    </div>
  );
}

const titre = (taille: number, couleur: string) => ({
  fontFamily: "Grotesk",
  fontWeight: 700 as const,
  fontSize: taille,
  lineHeight: 1.05,
  color: couleur,
  letterSpacing: -3,
});

/* ─────────────────────────────────── Les plans ────────────────────────────────────── */

export function PlanReel({ n, d }: { n: number; d: DonneesReel }) {
  // ── 0 · l'accroche, sur la photo. Elle ne présente rien, elle interpelle. ──
  if (n === 0) {
    return (
      <Plan n={0} photo={d.photo} sombre>
        <div style={{ width: utile, display: "flex", flexDirection: "column" }}>
          <span style={titre(116, "#FFFFFF")}>Vous pariez</span>
          <span style={titre(116, OR)}>au feeling ?</span>
          <div style={{ display: "flex", width: 140, height: 6, background: DEGRADE_OR, marginTop: 44 }} />
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 40,
              lineHeight: 1.4,
              color: "rgba(255,255,255,0.86)",
              marginTop: 40,
            }}
          >
            Il existe une autre façon de lire une course.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 1 · le taux ET son témoin, dans le même plan. Séparés, ils ne prouvent rien. ──
  if (n === 1) {
    const p = d.precisionTop3;
    const h = d.hasardTop3;
    const max = Math.max(p ?? 60, h ?? 30);
    return (
      <Plan n={1}>
        <div style={{ width: utile, display: "flex", flexDirection: "column" }}>
          <Surtitre>LE GAGNANT EST DANS NOTRE TOP 3</Surtitre>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 40 }}>
            <Carte>
              {p !== null ? (
                <Barre valeur={p} max={max} libelle="BlackTurf" doree />
              ) : null}
              {h !== null ? (
                <Barre valeur={h} max={max} libelle="Le hasard, mêmes courses" doree={false} />
              ) : null}
              <span
                style={{
                  fontFamily: "Inter",
                  fontSize: 26,
                  lineHeight: 1.45,
                  color: GRIS,
                  marginTop: 4,
                }}
              >
                {d.coursesMesurees
                  ? `Mesuré sur ${nb(d.coursesMesurees)} courses réglées aux rapports officiels du PMU.`
                  : "Mesuré sur les courses réglées aux rapports officiels du PMU."}
              </span>
            </Carte>
          </div>
          <span style={{ ...titre(58, ENCRE), marginTop: 52 }}>Deux fois mieux</span>
          <span style={{ ...titre(58, OR_SOMBRE) }}>que le hasard.</span>
        </div>
      </Plan>
    );
  }

  // ── 2 · le produit. On montre l'écran : c'est ce qui donne envie d'aller voir. ──
  if (n === 2) {
    return (
      <Plan n={2}>
        <div style={{ width: utile, display: "flex", flexDirection: "column" }}>
          <Surtitre>VOTRE BUDGET, RÉPARTI PARI PAR PARI</Surtitre>
          <div style={{ display: "flex", flexDirection: "column", marginTop: 40 }}>
            <Carte padding={44}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                <div style={{ display: "flex", flexDirection: "column" }}>
                  <span style={{ fontFamily: "Inter", fontSize: 24, color: GRIS }}>Budget</span>
                  <span
                    style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 52, color: ENCRE, letterSpacing: -1.6 }}
                  >
                    20 €
                  </span>
                </div>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end" }}>
                  <span style={{ fontFamily: "Inter", fontSize: 24, color: GRIS }}>Profil</span>
                  <span
                    style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 52, color: OR_SOMBRE, letterSpacing: -1.6 }}
                  >
                    Modéré
                  </span>
                </div>
              </div>

              {[
                ["SÉCURITÉ", "8,00 €", "Couplé Placé · 2 + 4", "41 %", "#ECFDF5", "#D1FAE5", VERT],
                ["RENDEMENT", "8,00 €", "Simple Gagnant · 4", "17 %", "#FFFBEB", "#FDE68A", OR_SOMBRE],
                ["GROS LOT", "4,00 €", "Couplé Gagnant · 2 + 4", "9 %", "#FEF2F2", "#FECACA", "#B91C1C"],
              ].map(([nom, mise, pari, proba, fond, bord, teinte], i) => (
                <div
                  key={nom}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    marginTop: i === 0 ? 34 : 14,
                    padding: 22,
                    borderRadius: 16,
                    background: fond,
                    border: `1px solid ${bord}`,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", width: "100%" }}>
                    <span
                      style={{ fontFamily: "Inter", fontWeight: 600, fontSize: 22, letterSpacing: 2.2, color: teinte }}
                    >
                      {nom}
                    </span>
                    <span
                      style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 30, color: teinte, letterSpacing: -1 }}
                    >
                      {mise}
                    </span>
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", width: "100%", marginTop: 8 }}>
                    <span style={{ fontFamily: "Inter", fontSize: 26, color: ENCRE }}>{pari}</span>
                    <span style={{ fontFamily: "Inter", fontSize: 23, color: GRIS }}>proba. {proba}</span>
                  </div>
                </div>
              ))}
            </Carte>
          </div>
          <span
            style={{ fontFamily: "Inter", fontSize: 28, lineHeight: 1.4, color: CHARBON, marginTop: 34 }}
          >
            Vous entrez un montant, le plan s&apos;écrit. Aucun ticket type.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 3 · d'où ça vient. ──
  if (n === 3) {
    return (
      <Plan n={3}>
        <div style={{ width: utile, display: "flex", flexDirection: "column" }}>
          <Surtitre>CE QUE L&apos;ALGORITHME REGARDE</Surtitre>
          <div style={{ display: "flex", alignItems: "baseline", marginTop: 28 }}>
            <span style={titre(150, OR_SOMBRE)}>80+</span>
            <span
              style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 60, color: ENCRE, marginLeft: 24, letterSpacing: -2 }}
            >
              critères
            </span>
          </div>
          <span style={{ fontFamily: "Inter", fontSize: 32, color: CHARBON, marginTop: 6 }}>
            par cheval, sur chaque course
          </span>

          <div style={{ display: "flex", flexDirection: "column", marginTop: 46 }}>
            {[
              "Contrecoup après un gros effort",
              "Biais de corde de l’hippodrome",
              "Déferrage, œillères, pénétromètre",
              "Argent professionnel sur la cote",
            ].map((l) => (
              <div
                key={l}
                style={{
                  display: "flex",
                  alignItems: "center",
                  marginBottom: 16,
                  padding: "22px 26px",
                  borderRadius: 16,
                  background: "#FFFFFF",
                  border: `1px solid ${OR_TEINTE}`,
                }}
              >
                <div style={{ display: "flex", width: 10, height: 10, borderRadius: 5, background: OR }} />
                <span style={{ fontFamily: "Inter", fontSize: 30, color: ENCRE, marginLeft: 20 }}>{l}</span>
              </div>
            ))}
          </div>

          <span
            style={{ fontFamily: "Inter", fontSize: 28, lineHeight: 1.4, color: CHARBON, marginTop: 32 }}
          >
            Recalibré chaque nuit sur les arrivées réelles.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 4 · l'honnêteté. C'est elle qui rend tout le reste croyable. ──
  if (n === 4) {
    return (
      <Plan n={4} sombre>
        <div style={{ width: utile, display: "flex", flexDirection: "column" }}>
          <Surtitre ton="gris">ET LES JOURS OÙ ON SE TROMPE ?</Surtitre>
          <span style={{ ...titre(94, "#FFFFFF"), marginTop: 34 }}>Ils sont</span>
          <span style={titre(94, OR)}>publiés aussi.</span>
          <div style={{ display: "flex", width: 140, height: 6, background: DEGRADE_OR, marginTop: 44 }} />
          <span
            style={{
              fontFamily: "Inter",
              fontSize: 34,
              lineHeight: 1.45,
              color: "rgba(255,255,255,0.82)",
              marginTop: 44,
            }}
          >
            {d.coursesMesurees
              ? `${nb(d.coursesMesurees)} courses réglées aux rapports officiels du PMU, pronostic enregistré avant le départ. Le bilan est public, pertes comprises.`
              : "Chaque pronostic est enregistré avant le départ puis réglé aux rapports officiels. Le bilan est public, pertes comprises."}
          </span>
          <span
            style={{
              fontFamily: "Grotesk",
              fontWeight: 700,
              fontSize: 46,
              lineHeight: 1.24,
              color: OR,
              letterSpacing: -1.4,
              marginTop: 48,
            }}
          >
            Le seul service de pronostics qui publie aussi ses pertes.
          </span>
        </div>
      </Plan>
    );
  }

  // ── 5 · l'appel à l'action, en aplat doré plein écran. ──
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        position: "relative",
        width: REEL_L,
        height: REEL_H,
        background: DEGRADE_OR,
      }}
    >
      <div
        style={{
          position: "absolute",
          left: MARGE,
          top: 118,
          width: utile,
          display: "flex",
          alignItems: "center",
        }}
      >
        <div
          style={{ display: "flex", width: 46, height: 46, borderRadius: 12, background: "#1F1300" }}
        />
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 40,
            color: "#1F1300",
            marginLeft: 18,
            letterSpacing: -1,
          }}
        >
          BlackTurf
        </span>
      </div>

      <div
        style={{
          position: "absolute",
          left: MARGE,
          top: 300,
          width: utile,
          height: 1280,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
        }}
      >
        <span style={{ fontFamily: "Inter", fontWeight: 600, fontSize: 34, color: "#3A2400" }}>
          Le programme du jour est déjà en ligne
        </span>
        <span
          style={{
            fontFamily: "Grotesk",
            fontWeight: 700,
            fontSize: 118,
            lineHeight: 1.02,
            color: "#1F1300",
            letterSpacing: -4,
            marginTop: 18,
          }}
        >
          blackturf.fr
        </span>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            marginTop: 54,
            padding: "34px 40px",
            borderRadius: 22,
            background: "rgba(255,255,255,0.92)",
          }}
        >
          <span
            style={{ fontFamily: "Grotesk", fontWeight: 700, fontSize: 52, color: ENCRE, letterSpacing: -1.6 }}
          >
            7 jours offerts
          </span>
          <span style={{ fontFamily: "Inter", fontSize: 27, lineHeight: 1.45, color: CHARBON, marginTop: 10 }}>
            Programme, cotes et rapports gratuits. Prédictions et plan de mise dès 12 €/mois,
            annulation en deux clics.
          </span>
        </div>
      </div>

      <div style={{ position: "absolute", left: MARGE, top: 1712, width: utile, display: "flex" }}>
        <span style={{ fontFamily: "Inter", fontSize: 23, lineHeight: 1.4, color: "#4A3504" }}>
          Jouer comporte des risques : endettement, isolement, dépendance.
          09&#160;74&#160;75&#160;13&#160;13. Interdit aux mineurs.
        </span>
      </div>
    </div>
  );
}

/** Nombre de plans — l'assembleur en a besoin pour savoir combien en demander. */
export const NB_PLANS = 6;
