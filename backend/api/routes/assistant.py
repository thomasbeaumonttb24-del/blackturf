"""
Assistant IA — BlackTurf.
Claude API proxy avec contexte hippique + function calling DB.
Plan Expert uniquement.
"""
import json
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
    ModelVersion, BankrollEntry
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
            return json.dumps({
                "auc_roc": round(mv.auc_roc, 4),
                "precision_top3": f"{mv.precision_top3 * 100:.1f}%",
                "roi_simule": f"+{mv.roi_simule * 100:.1f}%",
                "nb_courses_train": mv.nb_courses_train,
            })

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
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Anthropic API non configurée")

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Valider et nettoyer les messages
    messages = [
        {"role": m["role"], "content": str(m["content"])[:4000]}
        for m in body.messages[-20:]  # max 20 tours de contexte
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]

    if not messages:
        raise HTTPException(status_code=400, detail="Messages vides")

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
