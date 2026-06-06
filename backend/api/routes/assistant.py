"""
Assistant IA — BlackTurf.
Claude API proxy avec contexte hippique + function calling DB.
Plan Expert uniquement.
"""
import json
import re
import structlog
from datetime import date
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
import anthropic

from api.config import get_settings
from api.routes.auth import get_current_user
from api.middleware.rate_limit import rate_limit_assistant
from db.database import get_db
from db.models import (
    User, Course, Prediction, ValueBet, Participation, Cheval,
    ModelVersion, BankrollEntry, RaceLearningLog
)

settings = get_settings()
log = structlog.get_logger()
router = APIRouter()

SYSTEM_PROMPT = """Tu es BlackTurf IA, l'assistant expert en courses hippiques de la plateforme BlackTurf.fr.

Tu aides les parieurs à analyser les courses, comprendre les value bets, gérer leur bankroll et prendre de meilleures décisions.

Tes domaines d'expertise :
- Pronostics et analyses hippiques (PMU : Plat, Trot Attelé, Monté, Haies, Steeple)
- Mathématiques des paris : EV (Expected Value), Kelly Criterion, ROI
- Interprétation des cotes et probabilités IA
- Stratégies de gestion de bankroll
- Types de paris PMU : Simple Gagnant/Placé, Couplé, Tiercé, Quarté+, Quinté+, 2sur4, etc.
- Lecture de la musique hippique (historique des performances)
- Facteurs d'analyse : ELO, terrain, distance, jockey, entraîneur, équipement

RÈGLES IMPORTANTES :
- Tu ne garantis JAMAIS un gain. Les paris comportent toujours un risque.
- Tu rappelles systématiquement le jeu responsable sur les questions de mise.
- Tu ne donnes JAMAIS de conseil de mise supérieure à 5% de la bankroll (Kelly).
- Sur chaque réponse concernant des paris, tu inclus : "⚠️ Outil d'aide à la décision uniquement."
- Tu réponds en français.
- Tu es concis et factuel. Pas de blabla.

Tu as accès aux données temps réel de la plateforme via les outils fournis."""

TOOLS = [
    {
        "name": "get_programme_today",
        "description": "Récupère le programme des courses d'aujourd'hui depuis la DB.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_value_bets_actifs",
        "description": "Récupère les value bets actifs en ce moment (EV > 0).",
        "input_schema": {
            "type": "object",
            "properties": {
                "niveau_min": {"type": "integer", "description": "Niveau minimum (1-4)", "default": 1}
            },
            "required": [],
        },
    },
    {
        "name": "get_course_predictions",
        "description": "Récupère les prédictions IA pour une course spécifique.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "string", "description": "ID de la course (ex: R1C3)"}
            },
            "required": ["course_id"],
        },
    },
    {
        "name": "get_model_metrics",
        "description": "Retourne les métriques du modèle IA actif (AUC, précision top-3, ROI simulé).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_bankroll_stats",
        "description": "Retourne les statistiques bankroll de l'utilisateur.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


async def _execute_tool(
    tool_name: str,
    tool_input: dict,
    db: AsyncSession,
    user: User,
) -> str:
    """Exécute un tool call et retourne le résultat en JSON string."""
    try:
        if tool_name == "get_programme_today":
            q = (
                select(Course)
                .where(func.date(Course.date_heure) == date.today())
                .order_by(Course.date_heure)
                .limit(20)
            )
            courses = (await db.execute(q)).scalars().all()
            return json.dumps([
                {
                    "course_id": c.course_id,
                    "nom": c.nom,
                    "hippodrome": c.hippodrome_nom,
                    "heure": c.date_heure.strftime("%H:%M"),
                    "discipline": c.discipline,
                    "distance": c.distance,
                    "nb_partants": c.nb_partants,
                    "statut": c.statut,
                    "est_quinte": c.est_quinte,
                }
                for c in courses
            ])

        elif tool_name == "get_value_bets_actifs":
            niveau_min = tool_input.get("niveau_min", 1)
            q = (
                select(ValueBet, Participation, Cheval, Course)
                .join(Participation, Participation.participation_id == ValueBet.participation_id)
                .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
                .join(Course, Course.course_id == ValueBet.course_id)
                .where(
                    ValueBet.actif == True,
                    ValueBet.niveau >= niveau_min,
                    Course.statut.in_(["a_venir", "en_cours"]),
                )
                .order_by(desc(ValueBet.ev_max))
                .limit(10)
            )
            rows = (await db.execute(q)).all()
            return json.dumps([
                {
                    "cheval": cheval.nom,
                    "hippodrome": course.hippodrome_nom,
                    "heure": course.date_heure.strftime("%H:%M"),
                    "cote": part.cote_pmu,
                    "ev": round(vb.ev_max * 100, 1),
                    "niveau": "⭐" * vb.niveau,
                    "source": vb.meilleure_source,
                }
                for vb, part, cheval, course in rows
            ])

        elif tool_name == "get_course_predictions":
            course_id = tool_input.get("course_id", "")
            q = (
                select(Prediction, Participation, Cheval)
                .join(Participation, Participation.participation_id == Prediction.participation_id)
                .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
                .where(Prediction.course_id == course_id)
                .order_by(Prediction.rang_predit)
                .limit(10)
            )
            rows = (await db.execute(q)).all()
            if not rows:
                return json.dumps({"error": "Aucune prédiction disponible pour cette course."})
            return json.dumps([
                {
                    "rang": pred.rang_predit,
                    "numero": part.numero,
                    "cheval": cheval.nom,
                    "proba_top3": f"{pred.proba_top3 * 100:.0f}%",
                    "cote": part.cote_pmu,
                    "confidence": pred.confidence_score,
                }
                for pred, part, cheval in rows
            ])

        elif tool_name == "get_model_metrics":
            mv = (await db.execute(
                select(ModelVersion).where(ModelVersion.est_actif == True)
            )).scalar_one_or_none()
            if not mv:
                return json.dumps({"error": "Pas de modèle actif."})
            # Précision RÉELLE observée (race_learning_log), pas la métadonnée d'entraînement
            rll_total = (await db.execute(
                select(func.count(RaceLearningLog.log_id))
            )).scalar() or 0
            rll_top3 = (await db.execute(
                select(func.count(RaceLearningLog.log_id)).where(
                    RaceLearningLog.gagnant_rang_predit <= 3
                )
            )).scalar() or 0
            out: dict = {
                "auc_roc": round(float(mv.auc_roc), 4) if mv.auc_roc else None,
                "nb_courses_train": mv.nb_courses_train,
                "nb_courses_evaluees": rll_total,
            }
            if rll_total >= 10:
                out["precision_top3_reelle"] = f"{rll_top3 / rll_total * 100:.0f}%"
            # ROI simulé : n'afficher que s'il est plausible (sinon métadonnée non fiable)
            roi = float(mv.roi_simule) if mv.roi_simule is not None else None
            if roi is not None and -0.5 <= roi <= 1.0:
                out["roi_simule"] = f"{roi * 100:+.1f}%"
            return json.dumps(out)

        elif tool_name == "get_bankroll_stats":
            entries = (await db.execute(
                select(BankrollEntry).where(BankrollEntry.user_id == user.user_id)
            )).scalars().all()
            mise = sum(e.mise for e in entries)
            net = sum(e.gain_perte or 0 for e in entries)
            roi = (net / mise * 100) if mise > 0 else 0
            return json.dumps({
                "nb_paris": len(entries),
                "mise_totale": round(mise, 2),
                "gain_net": round(net, 2),
                "roi": f"{roi:+.1f}%",
            })

    except Exception as e:
        log.error("assistant.tool_error", tool=tool_name, error=str(e))
        return json.dumps({"error": str(e)})
    return json.dumps({"error": "Tool inconnu"})


# ───────────────────────────────────────────────────────────────────────────
# Moteur rule-based — fonctionne SANS clé LLM, répond depuis les données réelles
# ───────────────────────────────────────────────────────────────────────────

DISCLAIMER = "\n\n⚠️ Outil d'aide à la décision uniquement — aucune garantie de gain. Jouez responsable."

KELLY_EXPLAIN = (
    "📐 **Critère de Kelly** — calcule la fraction optimale de bankroll à miser.\n\n"
    "Formule : f = (p × c − 1) / (c − 1)\n"
    "• p = probabilité réelle de gain (estimée par l'IA)\n"
    "• c = cote décimale\n\n"
    "Exemple : cheval à cote 4.0, proba IA 30% → f = (0,30 × 4 − 1) / (4 − 1) = 0,067 → 6,7% de la bankroll.\n\n"
    "BlackTurf plafonne toujours à **5% maximum** (Kelly fractionné) pour limiter la variance. "
    "Si le résultat est négatif, l'espérance est défavorable : on ne joue pas." + DISCLAIMER
)

MUSIQUE_EXPLAIN = (
    "🎵 **Lire la musique** — l'historique codé des dernières performances (plus récent à gauche).\n\n"
    "• Chiffre 1-9 = place à l'arrivée (1 = victoire)\n"
    "• 0 = hors des 10 premiers\n"
    "• D = disqualifié · T = tombé · A = arrêté · Ret = rétrogradé\n"
    "• Lettre après le chiffre = discipline : a = attelé, m = monté, p = plat, h = haies, s = steeple, c = cross\n"
    "• La parenthèse (23) sépare les saisons (année 2023)\n\n"
    "Exemple : `1a 2a 3a (23) 5a` → 1er, 2e, 3e en attelé cette saison, puis 5e la saison passée. "
    "Régularité = chiffres bas et stables. Méfiance si que des 0 ou des D récents." + DISCLAIMER
)


def _last_user_msg(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user" and m.get("content"):
            return str(m["content"]).lower().strip()
    return ""


async def _resolve_course_id(db: AsyncSession, r: int, c: int) -> Optional[str]:
    """Résout 'R{r}C{c}' vers le course_id (daté) du jour."""
    suffix = f"R{r}C{c}"
    q = (
        select(Course.course_id)
        .where(
            func.date(Course.date_heure) == date.today(),
            Course.course_id.ilike(f"%{suffix}"),
        )
        .order_by(desc(Course.date_heure))
        .limit(1)
    )
    return (await db.execute(q)).scalar_one_or_none()


async def _answer_value_bets(db: AsyncSession, user: User) -> str:
    data = json.loads(await _execute_tool("get_value_bets_actifs", {"niveau_min": 1}, db, user))
    if not isinstance(data, list) or not data:
        return ("Aucun value bet actif en ce moment. Les value bets apparaissent quand l'IA "
                "estime qu'un cheval est sous-coté par le marché (EV positive). Reviens après le "
                "scraping des cotes du jour." + DISCLAIMER)
    lines = [f"🎯 **{len(data)} value bets actifs** (triés par espérance) :\n"]
    for v in data[:8]:
        lines.append(
            f"• **{v['cheval']}** — {v['hippodrome']} {v['heure']} · cote {v['cote']} · "
            f"EV **+{v['ev']}%** {v['niveau']}"
        )
    lines.append("\nL'EV (espérance) mesure l'avantage estimé vs le marché. Une EV très élevée "
                 "concerne souvent un outsider à grosse cote : fort potentiel mais variance élevée. "
                 "Priorise les ⭐⭐⭐+ avec une mise raisonnable (≤5% bankroll).")
    return "\n".join(lines) + DISCLAIMER


async def _answer_programme(db: AsyncSession, user: User) -> str:
    data = json.loads(await _execute_tool("get_programme_today", {}, db, user))
    if not isinstance(data, list) or not data:
        return "Aucune course enregistrée pour aujourd'hui. Le programme se remplit chaque matin via le scraper PMU." + DISCLAIMER
    by_hippo: dict[str, list] = {}
    for c in data:
        by_hippo.setdefault(c["hippodrome"] or "?", []).append(c)
    lines = [f"📅 **Programme du jour** — {len(data)} courses :\n"]
    for hippo, courses in list(by_hippo.items())[:6]:
        lines.append(f"**{hippo}**")
        for c in courses[:8]:
            q = " 👑Quinté" if c.get("est_quinte") else ""
            code = c["course_id"][-4:] if c.get("course_id") else ""
            lines.append(f"  • {code} {c['heure']} · {c['discipline']} {c['distance']}m · {c['nb_partants']} part.{q}")
    lines.append("\nDemande-moi « analyse R1C3 » pour les pronostics d'une course précise.")
    return "\n".join(lines) + DISCLAIMER


async def _answer_course(db: AsyncSession, user: User, r: int, c: int) -> str:
    cid = await _resolve_course_id(db, r, c)
    if not cid:
        return (f"Course R{r}C{c} introuvable dans le programme d'aujourd'hui. "
                "Vérifie le numéro de réunion (R) et de course (C)." + DISCLAIMER)
    data = json.loads(await _execute_tool("get_course_predictions", {"course_id": cid}, db, user))
    if isinstance(data, dict) and data.get("error"):
        return (f"Pas encore de prédictions IA pour R{r}C{c}. L'analyse se lance "
                "automatiquement avant la course." + DISCLAIMER)
    if not isinstance(data, list) or not data:
        return f"Pas de prédictions disponibles pour R{r}C{c}." + DISCLAIMER
    lines = [f"🔮 **Pronostics IA — R{r}C{c}** (top {min(len(data), 6)}) :\n"]
    for p in data[:6]:
        cote = f"cote {p['cote']}" if p.get("cote") else "cote n/d"
        lines.append(f"{p['rang']}. **N°{p['numero']} {p['cheval']}** — top-3 {p['proba_top3']} · {cote}")
    lines.append("\nLe « top-3 » = probabilité estimée de finir dans les 3 premiers. "
                 "Croise avec les cotes pour repérer la valeur.")
    return "\n".join(lines) + DISCLAIMER


async def _answer_metrics(db: AsyncSession, user: User) -> str:
    data = json.loads(await _execute_tool("get_model_metrics", {}, db, user))
    if isinstance(data, dict) and data.get("error"):
        return "Pas de modèle IA actif pour le moment." + DISCLAIMER
    lines = ["📊 **Modèle IA actif** :"]
    if data.get("auc_roc"):
        lines.append(f"• AUC-ROC : **{data['auc_roc']}** (pouvoir discriminant, >0.7 = bon)")
    if data.get("precision_top3_reelle"):
        lines.append(f"• Précision top-3 réelle observée : **{data['precision_top3_reelle']}** "
                     f"(sur {data.get('nb_courses_evaluees', 0)} courses évaluées)")
    elif data.get("nb_courses_evaluees", 0) < 10:
        lines.append("• Précision réelle : en cours de mesure (pas assez de courses évaluées)")
    if data.get("roi_simule"):
        lines.append(f"• ROI simulé : **{data['roi_simule']}**")
    if data.get("nb_courses_train"):
        lines.append(f"• Entraîné sur **{data['nb_courses_train']}** courses")
    lines.append("\nLe modèle se ré-entraîne chaque nuit avec les résultats du jour (apprentissage continu).")
    return "\n".join(lines) + DISCLAIMER


async def _answer_bankroll(db: AsyncSession, user: User) -> str:
    data = json.loads(await _execute_tool("get_bankroll_stats", {}, db, user))
    if isinstance(data, dict) and data.get("error"):
        return "Impossible de lire ta bankroll pour le moment." + DISCLAIMER
    if data.get("nb_paris", 0) == 0:
        return ("Aucun pari enregistré dans ta bankroll. Ajoute tes paris depuis la page Capital "
                "pour suivre ton ROI réel." + DISCLAIMER)
    return (
        "💰 **Ta bankroll** :\n"
        f"• Paris enregistrés : {data['nb_paris']}\n"
        f"• Mise totale : {data['mise_totale']}€\n"
        f"• Gain net : {data['gain_net']}€\n"
        f"• ROI : **{data['roi']}**" + DISCLAIMER
    )


def _answer_mise() -> str:
    return (
        "🧮 **Répartir tes mises** — méthode BlackTurf :\n\n"
        "1. Définis ta bankroll totale et ne risque jamais plus de 5% sur une course.\n"
        "2. Sur chaque page course, entre ton montant dans le **calculateur de mise** : "
        "l'IA répartit automatiquement sur plusieurs paris (Simple Gagnant, Couplé, Trio…) "
        "selon les probabilités réelles et ton niveau de risque.\n"
        "3. Privilégie les paris à EV positive (value bets).\n"
        "4. Mise fixe minimale 2€, arrondie à l'euro.\n\n"
        "Donne-moi ton montant et je t'explique la logique, ou utilise directement le calculateur sur la course."
        + DISCLAIMER
    )


def _answer_help() -> str:
    return (
        "👋 Je suis **BlackTurf IA**. Je réponds depuis les données réelles de la plateforme. "
        "Voici ce que je peux faire :\n\n"
        "• **« Les value bets du jour »** — paris à valeur détectés par l'IA\n"
        "• **« Le programme »** — courses du jour\n"
        "• **« Analyse R1C3 »** — pronostics IA d'une course\n"
        "• **« Les métriques du modèle »** — fiabilité de l'IA\n"
        "• **« Ma bankroll »** — ton ROI et tes paris\n"
        "• **« Comment répartir mes mises ? »** — stratégie de staking\n"
        "• **« Explique le critère de Kelly »** / **« Comment lire la musique ? »**\n\n"
        "Pose ta question en langage naturel." + DISCLAIMER
    )


async def _rule_based_answer(messages: list[dict], db: AsyncSession, user: User) -> str:
    """Routeur d'intention sans LLM — répond depuis la DB réelle."""
    q = _last_user_msg(messages)
    if not q:
        return _answer_help()

    # Code course R{r}C{c}
    m = re.search(r"\br\s*0*(\d{1,2})\s*c\s*0*(\d{1,2})\b", q)
    if m and any(k in q for k in ("analys", "pronostic", "course", "predi", "prono", "r")):
        return await _answer_course(db, user, int(m.group(1)), int(m.group(2)))

    if any(k in q for k in ("value", "valeur", "vb", "meilleur pari", "bon pari", "paris du jour")):
        return await _answer_value_bets(db, user)
    if "kelly" in q:
        return KELLY_EXPLAIN
    if "musique" in q:
        return MUSIQUE_EXPLAIN
    if any(k in q for k in ("programme", "courses du jour", "aujourd", "quinté", "quinte", "réunion", "reunion")):
        return await _answer_programme(db, user)
    if any(k in q for k in ("modèle", "modele", "auc", "précision", "precision", "fiab", "performance", "perf ia", "roi simul")):
        return await _answer_metrics(db, user)
    if any(k in q for k in ("bankroll", "capital", "mon roi", "mes paris", "mes gains", "mon solde")):
        return await _answer_bankroll(db, user)
    if any(k in q for k in ("répart", "repart", "miser", "mise", "combien jouer", "combien miser", "staking", "stratégie de mise")):
        return _answer_mise()
    if m:  # code course détecté sans mot-clé explicite
        return await _answer_course(db, user, int(m.group(1)), int(m.group(2)))
    if any(k in q for k in ("bonjour", "salut", "hello", "aide", "help", "que peux", "tu fais quoi", "comment ça marche", "qui es")):
        return _answer_help()

    # Fallback — pas d'intention reconnue
    return (
        "Je n'ai pas de réponse fiable à cette question précise sans inventer de données. "
        "Je préfère ne répondre que sur du concret.\n\n" + _answer_help()
    )


def _stream_chunks(text: str):
    """Découpe un texte en petits morceaux pour un rendu progressif type streaming."""
    for token in re.findall(r"\S+\s*|\n", text):
        yield token


class ChatRequest(BaseModel):
    messages: list[dict]  # [{role, content}]
    stream: bool = True


@router.post("/assistant/chat")
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _rl: None = Depends(rate_limit_assistant),
):
    """Chat avec l'IA hippique. Plan Expert uniquement."""
    if user.plan not in ("pro", "expert"):
        raise HTTPException(status_code=403, detail="Assistant IA réservé au plan Pro")

    # Valider et nettoyer les messages
    messages = [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in body.messages[-20:]  # max 20 tours de contexte
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    if not messages:
        raise HTTPException(status_code=400, detail="Messages vides")

    sse_headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

    # ── Pas de clé LLM → moteur rule-based sur données réelles ──────────────
    if not settings.anthropic_api_key:
        async def generate_rb() -> AsyncIterator[str]:
            try:
                answer = await _rule_based_answer(messages, db, user)
            except Exception as e:
                log.error("assistant.rule_based_error", error=str(e))
                answer = "Erreur lors de la récupération des données. Réessaie."
            for chunk in _stream_chunks(answer):
                yield f"data: {json.dumps({'type': 'text', 'text': chunk})}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(generate_rb(), media_type="text/event-stream", headers=sse_headers)

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate() -> AsyncIterator[str]:
        try:
            # Premier appel avec tools (non-streaming pour gérer le tool_use)
            _model = settings.anthropic_model
            current_messages = messages[:]
            response = await client.messages.create(
                model=_model,
                max_tokens=1500,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=current_messages,
            )

            # Traiter tool calls si besoin (boucle pour les multi-tours)
            while response.stop_reason == "tool_use":
                tool_results = []
                text_so_far = ""

                for block in response.content:
                    if hasattr(block, "text"):
                        text_so_far += block.text
                    elif block.type == "tool_use":
                        result = await _execute_tool(block.name, block.input, db, user)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })

                if text_so_far:
                    yield f"data: {json.dumps({'type': 'text', 'text': text_so_far})}\n\n"

                # Continuer avec les résultats — accumuler le contexte
                current_messages = current_messages + [
                    {"role": "assistant", "content": response.content},
                    {"role": "user", "content": tool_results},
                ]
                response = await client.messages.create(
                    model=_model,
                    max_tokens=1500,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=current_messages,
                )

            # Réponse finale — stream si demandé avec le contexte complet
            if body.stream:
                async with client.messages.stream(
                    model=_model,
                    max_tokens=1500,
                    system=SYSTEM_PROMPT,
                    messages=current_messages,  # contexte avec tool results inclus
                ) as stream:
                    async for text in stream.text_stream:
                        yield f"data: {json.dumps({'type': 'text', 'text': text})}\n\n"
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        yield f"data: {json.dumps({'type': 'text', 'text': block.text})}\n\n"

            yield "data: [DONE]\n\n"

        except anthropic.RateLimitError:
            yield f"data: {json.dumps({'type': 'error', 'text': 'Limite API atteinte. Réessayez dans quelques secondes.'})}\n\n"
        except Exception as e:
            log.error("assistant.stream_error", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'text': 'Erreur IA. Réessayez.'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/assistant/suggestions")
async def get_suggestions(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Questions suggérées contextuelles."""
    if user.plan not in ("pro", "expert"):
        raise HTTPException(status_code=403, detail="Plan Expert requis")

    # Vérifier s'il y a des courses aujourd'hui
    nb_courses = (await db.execute(
        select(func.count(Course.course_id)).where(
            func.date(Course.date_heure) == date.today()
        )
    )).scalar() or 0

    # Vérifier s'il y a des value bets
    nb_vb = (await db.execute(
        select(func.count(ValueBet.vb_id)).where(ValueBet.actif == True)
    )).scalar() or 0

    suggestions = [
        "Quels sont les meilleurs value bets d'aujourd'hui ?",
        "Comment fonctionne le critère de Kelly ?",
        "Explique-moi comment lire la musique d'un cheval",
    ]

    if nb_vb > 0:
        suggestions.insert(0, f"Il y a {nb_vb} value bets actifs — lesquels prioriser ?")
    if nb_courses > 0:
        suggestions.insert(0, f"Analyse le programme de ce jour ({nb_courses} courses)")

    return {"suggestions": suggestions[:5]}
