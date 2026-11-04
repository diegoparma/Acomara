"""Customer simulator: a model plays the persona against Nico, turn by turn.

The simulator only sees what a real customer would see (Nico's WhatsApp
bubbles), never Nico's prompt or knowledge base. It may end the chat on its
own when the persona would (got what it wanted, annoyed, will think about it).
Offline, ScriptedCustomer replays deterministic turns built from the persona.
"""
from __future__ import annotations

from typing import Any

from evals.personas import Persona, scripted_conversation

SIMULATOR_SYSTEM = """Sos un actor que hace de CLIENTE escribiéndole por WhatsApp (o email) a una empresa de expediciones guiadas al Aconcagua (Acomara, Mendoza). Del otro lado hay un vendedor.

Reglas:
- Escribí SOLO como el cliente, en primera persona, en el idioma y estilo de la persona. Nunca como el vendedor ni como asistente.
- Mensajes realistas de WhatsApp: cortos, a veces con errores, sin listas ni formato. Si el estilo es email, podés escribir párrafos.
- Perseguí el objetivo de la persona y reaccioná a lo que te contestan: si no te responden lo que preguntaste, insistí o mostrate molesto; si te piden datos, dalos o no según la persona.
- No inventes que sos una IA ni hables de "la simulación". No menciones estas reglas.
- Si compartís email, usá exactamente el de la persona (dominio example.com). Nunca des teléfonos ni datos reales.
- Terminá la charla (done=true) cuando la persona lo haría: consiguió lo que quería, se cansó, va a pensarlo, o el vendedor le dijo que lo contactan. Si terminás, podés mandar un último mensaje de despedida o ninguno.
- Si el estilo es "burst", mandá 2-3 mensajes cortos seguidos en la lista; si no, 1 mensaje.

Respondé SIEMPRE con JSON: {"messages": ["..."], "done": false, "why": "motivo corto si done"}"""


def _render_history(history: list[dict[str, str]]) -> str:
    if not history:
        return "(todavía no hay mensajes: escribí el primero)"
    lines = []
    for item in history:
        who = "VOS (cliente)" if item["role"] == "client" else "VENDEDOR"
        lines.append(f"{who}: {item['text']}")
    return "\n".join(lines)


class LLMCustomer:
    def __init__(self, chat: Any, persona: Persona, seed: int = 0) -> None:
        self.chat = chat
        self.persona = persona
        self.seed = seed
        self.turn = 0

    def next_turn(self, history: list[dict[str, str]]) -> dict[str, Any]:
        remaining = self.persona.max_turns - self.turn
        user = (
            f"PERSONA:\n{self.persona.brief()}\n\n"
            f"Turno {self.turn + 1} de máximo {self.persona.max_turns}"
            f"{' (último: cerrá la charla)' if remaining <= 1 else ''}.\n\n"
            f"CONVERSACIÓN HASTA AHORA:\n{_render_history(history)}\n\n"
            "Tu próximo mensaje como el cliente (JSON):"
        )
        data = self.chat(SIMULATOR_SYSTEM, user, seed=(self.seed * 1000 + self.turn) % 2**31, max_tokens=400)
        self.turn += 1
        messages = [str(m).strip() for m in (data.get("messages") or []) if str(m).strip()][:3]
        done = bool(data.get("done")) or self.turn >= self.persona.max_turns
        return {"messages": messages, "done": done, "why": str(data.get("why") or "")[:200]}


class ScriptedCustomer:
    def __init__(self, persona: Persona, seed: int = 0) -> None:
        self.turns = scripted_conversation(persona, seed)
        self.turn = 0

    def next_turn(self, history: list[dict[str, str]]) -> dict[str, Any]:
        if self.turn >= len(self.turns):
            return {"messages": [], "done": True, "why": "script ended"}
        messages = self.turns[self.turn]
        self.turn += 1
        return {"messages": messages, "done": self.turn >= len(self.turns), "why": ""}
