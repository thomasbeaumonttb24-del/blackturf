"use client";

/**
 * Page de contrôle visuel TEMPORAIRE du classement de l'algorithme.
 *
 * La table réelle est derrière l'abonnement : impossible de la relire en
 * production sans session. Cette page rend le composant avec un jeu de données
 * représentatif (mêmes ordres de grandeur qu'une vraie course) pour vérifier la
 * mise en page. À supprimer une fois le rendu validé.
 */

import { ClassementAlgo, type ClassementPrediction, type ClassementSignal } from "@/components/courses/classement";

const P = (
  numero: number, nom: string, rang: number, p1: number, p3: number,
  cotePmu: number, coteJuste: number, vb?: number,
): ClassementPrediction => ({
  prediction_id: `p${numero}`,
  numero,
  nom_cheval: nom,
  proba_top1: p1,
  proba_top3: p3,
  proba_top1_low: Math.max(0, p1 - 0.05),
  proba_top1_high: p1 + 0.06,
  rang_predit: rang,
  confidence_score: 62,
  cote_pmu: cotePmu,
  cote_juste: coteJuste,
  value_bet: vb ? { ev_max: vb, niveau: 3, meilleure_source: "pmu" } : null,
});

const PREDICTIONS: ClassementPrediction[] = [
  P(3, "LOTUS PIERJI", 1, 0.32, 0.61, 2.6, 3.1),
  P(2, "LAMPARO", 2, 0.18, 0.44, 8.2, 5.6, 0.27),
  P(8, "LOVE FEELING", 3, 0.12, 0.36, 9.9, 8.3),
  P(5, "LOULOU DU PRATEL", 4, 0.08, 0.27, 10.0, 12.5),
  P(16, "LE SENS DE PADD", 5, 0.06, 0.21, 13.0, 16.7),
  P(11, "LYPSTIC ATOUT", 6, 0.02, 0.09, 117.0, 50.0),
];

const SIGNAUX: Record<number, ClassementSignal[]> = {
  3: [
    { label: "Forme récente", detail: "3 podiums sur ses 5 dernières sorties", sens: "positif", score: 0.8 },
    { label: "Association J/E", detail: "16 % de réussite sur 44 courses ensemble", sens: "positif", score: 0.6 },
  ],
  2: [
    { label: "Cote qui baisse", detail: "de 11,0 à 8,2 depuis l'ouverture", sens: "positif", score: 0.7 },
    { label: "Distance inhabituelle", detail: "1 seule sortie sur 2650 m", sens: "negatif", score: -0.4 },
  ],
  8: [
    { label: "Rentre de loin", detail: "247 jours depuis sa dernière course", sens: "negatif", score: -0.6 },
    { label: "Changement de driver", detail: "S. BOURLIER remplace A. COLLETTE", sens: "neutre", score: 0.2 },
  ],
  11: [
    { label: "Jamais placé cette année", detail: "0 podium en 9 sorties", sens: "negatif", score: -0.8 },
  ],
};

export default function PreviewClassement() {
  return (
    <div className="min-h-screen bg-[#FFFDF6] p-6">
      <div className="mx-auto max-w-5xl space-y-6">
        <p className="text-xs font-semibold uppercase tracking-wider text-amber-800">
          Contrôle visuel — données d&apos;exemple
        </p>
        <ClassementAlgo
          predictions={PREDICTIONS}
          signauxParNumero={SIGNAUX}
          coteLive={{ 3: 2.5, 2: 7.9 }}
          nonPartants={new Set([11])}
          onLegende={() => {}}
        />
        <ClassementAlgo
          predictions={PREDICTIONS.slice(0, 4)}
          signauxParNumero={SIGNAUX}
          positionsReelles={{ 3: 4, 2: 1, 8: 7, 5: 2 }}
          onLegende={() => {}}
        />
      </div>
    </div>
  );
}
