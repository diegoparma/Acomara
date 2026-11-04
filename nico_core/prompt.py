"""The per-message instructions the model gets next to the evidence.

Moved from orchestrator/server.py `generate_reply`. The grounding rules are
the engine's; a tenant adds rules about its own listings (Acomara: departure
dates), names who confirms what the evidence lacks, and sets reply lengths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

LANG_INSTRUCTIONS = {
    "es": "Responde en español.",
    "en": "Respond in English.",
    "pt": "Responda em português.",
}
UNKNOWN_LANG_INSTRUCTION = "Respond in the user's language."


@dataclass(frozen=True)
class PromptConfig:
    # Who confirms what the evidence does not say.
    human_name: str = "alguien del equipo"
    # Reply length per channel; channels not listed use "default".
    length_instructions: Mapping[str, str] = field(
        default_factory=lambda: {
            "whatsapp": "Mantén la respuesta muy corta: máximo 2 líneas y 280 caracteres.",
            "default": "Mantén la respuesta corta: máximo 3 líneas y 450 caracteres.",
        }
    )
    # Extra rules, placed right after the length rule.
    extra_rules: tuple[str, ...] = ()


def build_user_prompt(
    cfg: PromptConfig,
    *,
    today: str,
    tz_label: str,
    channel: str,
    conversation_id: str,
    question: str,
    session_vars_json: str,
    crm_context: str,
    context: str,
    lang: str,
) -> str:
    is_whatsapp = channel.strip().lower() == "whatsapp"
    length = cfg.length_instructions["whatsapp" if is_whatsapp else "default"]
    rules = [
        LANG_INSTRUCTIONS.get(lang, UNKNOWN_LANG_INSTRUCTION),
        "Basa tu respuesta ÚNICAMENTE en la evidencia recuperada y en lo que ya le dijiste al cliente en esta conversación "
        "(si ya le diste un precio o una fecha, podés repetirlo).",
        "Si la evidencia trae información relacionada, aunque sea parcial, respondé con eso. "
        "Decir que no lo tenés es el último recurso.",
        "Puedes traducir la respuesta del FAQ al idioma del usuario si es necesario.",
        "Pero NO INVENTES, NO AGREGUES ni NO EMBELLEZCAS información más allá de lo que dice el FAQ.",
        "La estructura y contenido de la respuesta debe ser fiel al FAQ, solo adaptado en idioma y claridad.",
        length,
        *cfg.extra_rules,
        "Arriba tenés los mensajes anteriores de esta conversación. Si ya hablaron, no vuelvas a saludar, "
        "no repitas lo que ya dijiste y no preguntes datos que el cliente ya te dio.",
        "NO hagas preguntas de cierre ni acciones siguientes que no vengan del FAQ.",
        f"Si de verdad no hay nada relacionado, decilo con tus palabras y ofrecé que {cfg.human_name} lo confirme. "
        "Si ya lo dijiste antes en esta conversación, no lo repitas: respondé lo que sí sabés o preguntá qué necesita exactamente.",
        "No pidas el email si ya lo pediste en esta conversación.",
        "Nunca menciones FAQ, documentación, evidencia ni base de datos.",
    ]
    return (
        f"Fecha de hoy ({tz_label}): {today}\n"
        f"Canal: {channel}\n"
        f"Conversation ID: {conversation_id}\n"
        f"Cliente pregunta:\n{question}\n\n"
        f"Variables de sesion actuales:\n{session_vars_json}\n\n"
        f"{crm_context}"
        f"\n\nEvidencia interna recuperada:\n{context}\n\n"
        "Instrucciones CRÍTICAS:\n" + "\n".join(f"- {rule}" for rule in rules)
    )
