"""Fixed Spanish phrases in "usted", for clients who write formally.

The model mirrors "usted" on its own (style_hints tells it to), but the fixed
phrases (welcome, email ask, season warning, video-call close) are written
with "vos". A client who writes "¿Usted me podría indicar…?" and gets "Si
querés, pasame tu email" in the same reply reads two different people.

Only whole known phrases are swapped, never single words: a word-by-word
"vos to usted" rewrite would break the model's text. Placeholders like {email}
match any text and are carried over. tests/test_usted.py checks that every
phrase here still exists in the code, so a reworded phrase can't be missed.
"""
from __future__ import annotations

import re

# vos phrase (exact, as in server.I18N_PHRASES["es"] or sales_rules) -> usted.
USTED_PHRASES: dict[str, str] = {
    # server.I18N_PHRASES["es"]
    "Conversación reiniciada. ¿En qué te puedo ayudar?": "Conversación reiniciada. ¿En qué le puedo ayudar?",
    "Dale, te paso con un asesor del equipo. ¿Me dejás tu email así te contacta?": (
        "Perfecto, lo paso con un asesor del equipo. ¿Me deja su email así lo contacta?"
    ),
    "Listo, ya le pasé tu consulta a un asesor del equipo. Te escribe por acá en breve 🙌": (
        "Listo, ya le pasé su consulta a un asesor del equipo. Le escribe por acá en breve."
    ),
    "Me falta tu email para pasarte con el asesor. ¿Cuál es?": "Me falta su email para pasarlo con el asesor. ¿Cuál es?",
    "Si querés, pasame tu email y te mando el detalle completo con precios y fechas.": (
        "Si quiere, páseme su email y le mando el detalle completo con precios y fechas."
    ),
    "Genial, ya me quedó tu email. Si después querés hablar con un asesor, avisame y te paso.": (
        "Perfecto, ya me quedó su email. Si después quiere hablar con un asesor, avíseme y lo paso."
    ),
    "Gracias, ya me quedó tu email. Si en algún momento querés hablar con un asesor, avisame.": (
        "Gracias, ya me quedó su email. Si en algún momento quiere hablar con un asesor, avíseme."
    ),
    "Ya le pasé tu consulta a un asesor, te escribe por acá en breve.": (
        "Ya le pasé su consulta a un asesor, le escribe por acá en breve."
    ),
    "Perfecto, te escribimos en breve.": "Perfecto, le escribimos en breve.",
    "Pasame tu email cuando puedas y seguimos.": "Páseme su email cuando pueda y seguimos.",
    "Ya quedó todo registrado. En breve te escribe alguien del equipo por acá, no hace falta que mandes nada más 👍": (
        "Ya quedó todo registrado. En breve le escribe alguien del equipo por acá, no hace falta que mande nada más."
    ),
    "Como te decía,": "Como le decía,",
    "¡De nada! Cualquier cosa me escribís por acá.": "¡De nada! Cualquier cosa me escribe por acá.",
    "¡Un placer! Si te surge otra duda, acá estoy.": "¡Un placer! Si le surge otra duda, acá estoy.",
    "Dale, cuando quieras.": "Cuando guste.",
    "Soy el asistente digital del equipo de Acomara 🙂 Te respondo por acá lo que necesites, y si preferís hablar con un asesor, avisame y te paso.": (
        "Soy el asistente digital del equipo de Acomara. Le respondo por acá lo que necesite, y si prefiere hablar con un asesor, avíseme y lo paso."
    ),
    "¡Gracias! Ya tengo tu email, se lo paso a un asesor del equipo.": (
        "¡Gracias! Ya tengo su email, se lo paso a un asesor del equipo."
    ),
    "¡Gracias! Ya tengo tu email ({email}). Un asesor del equipo revisa tu consulta y te escribe por acá. Si querés sumar algo (fechas, cuántos son, experiencia previa), contame y lo agrego.": (
        "¡Gracias! Ya tengo su email ({email}). Un asesor del equipo revisa su consulta y le escribe por acá. Si quiere sumar algo (fechas, cuántos son, experiencia previa), cuénteme y lo agrego."
    ),
    "Ojo: las expediciones al Aconcagua son solo de noviembre a marzo (temporada del hemisferio sur), así que para esa fecha no tenemos salidas. Si querés te paso las fechas de la próxima temporada.": (
        "Le comento: las expediciones al Aconcagua son solo de noviembre a marzo (temporada del hemisferio sur), así que para esa fecha no tenemos salidas. Si quiere le paso las fechas de la próxima temporada."
    ),
    "¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?\n\nSi te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.": (
        "¡Hola! Gracias por escribirnos. ¿En qué le puedo ayudar?\n\nSi le sirve, además de responderle por acá le mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones."
    ),
    # sales_rules
    "Te soy sincero: el {program} es solo para quien ya estuvo arriba de los 6.000 m, está muy entrenado y llega aclimatado. ": (
        "Le soy sincero: el {program} es solo para quien ya estuvo arriba de los 6.000 m, está muy entrenado y llega aclimatado. "
    ),
    "Te recomiendo el 18+2: cuesta lo mismo y tiene más días para aclimatar, que es lo que más sube las chances de cumbre.": (
        "Le recomiendo el 18+2: cuesta lo mismo y tiene más días para aclimatar, que es lo que más sube las chances de cumbre."
    ),
    "Si querés, armamos una videollamada corta y lo vemos juntos: decime día, hora y desde qué ciudad me escribís, y pasame tu email así te mando el detalle.": (
        "Si quiere, armamos una videollamada corta y lo vemos juntos: dígame día, hora y desde qué ciudad me escribe, y páseme su email así le mando el detalle."
    ),
    "Si querés, armamos una videollamada corta y lo vemos juntos: decime día, hora y desde qué ciudad me escribís.": (
        "Si quiere, armamos una videollamada corta y lo vemos juntos: dígame día, hora y desde qué ciudad me escribe."
    ),
    "La disponibilidad de esa fecha te la confirma un asesor.": "La disponibilidad de esa fecha se la confirma un asesor.",
    "La disponibilidad de la fecha que elijas te la confirma un asesor.": (
        "La disponibilidad de la fecha que elija se la confirma un asesor."
    ),
    "Si no es tu caso, te conviene el 18+2, que cuesta lo mismo: la salida más cercana es el {alt}.": (
        "Si no es su caso, le conviene el 18+2, que cuesta lo mismo: la salida más cercana es el {alt}."
    ),
}

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _compile(source: str) -> re.Pattern[str]:
    parts = _PLACEHOLDER_RE.split(source)
    # split() alternates literal text and placeholder names.
    pattern = "".join(
        re.escape(part) if i % 2 == 0 else f"(?P<{part}>.+?)" for i, part in enumerate(parts)
    )
    return re.compile(pattern, re.DOTALL)


# Longest first, so a phrase that contains a shorter one wins.
_COMPILED = [
    (_compile(src), dst) for src, dst in sorted(USTED_PHRASES.items(), key=lambda kv: -len(kv[0]))
]


def to_usted(text: str) -> str:
    """Swap the fixed "vos" phrases in a reply for their "usted" version."""
    if not text:
        return text
    for pattern, target in _COMPILED:
        text = pattern.sub(lambda m: target.format(**m.groupdict()), text)
    return text
