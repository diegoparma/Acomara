"""Deterministic checks on a Nico conversation: regex only, no model.

Each finding has a code, a severity (1 minor, 2 major, 3 critical), the turn
and the offending text. Codes are stable: reports and baselines compare them
across runs. Facts come from docs/knowledge/datos-clave.md (read at runtime,
so price changes there do not need a code change here).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from orchestrator.conversation_audit import _detect_language, _detect_language_preference

ROOT = Path(__file__).resolve().parents[1]
DATOS_CLAVE = ROOT / "docs" / "knowledge" / "datos-clave.md"
FAQ_STRUCTURED = ROOT / "docs" / "knowledge" / "faq_structured.md"

# code -> (severity, dimension, description)
CODES: dict[str, tuple[int, str, str]] = {
    "HTTP_ERROR": (3, "rules", "El endpoint devolvió error"),
    "EMPTY_REPLY": (1, "rules", "Nico no respondió nada a un mensaje"),
    "MARKDOWN_BOLD": (1, "humanness", "Usa **negritas** de Markdown"),
    "EM_DASH": (1, "humanness", "Usa guión largo (—), típico de IA"),
    "ASSISTANT_CLOSER": (2, "humanness", "Frase de asistente ('¿algo más en lo que pueda ayudarte?')"),
    "MENTIONS_DOCS": (2, "humanness", "Menciona FAQ / documentación / base de datos"),
    "ASESOR_HUMANO": (1, "humanness", "Dice 'asesor humano'"),
    "REPEATED_GREETING": (1, "humanness", "Vuelve a saludar en medio de la charla"),
    "IDENTICAL_REPLY": (2, "humanness", "Repite la misma frase larga palabra por palabra"),
    "EMAIL_ASKED_TWICE": (2, "rules", "Pide el email más de una vez"),
    "EMAIL_ASKED_AFTER_GIVEN": (2, "rules", "Pide el email cuando el cliente ya lo dio"),
    "PHANTOM_EMAIL": (2, "accuracy", "Menciona un email que el cliente no dio"),
    "OLD_PRICE": (3, "accuracy", "Da el precio viejo (USD 6.990)"),
    "INVENTED_PRICE": (3, "accuracy", "Da un monto en USD que no está en datos-clave ni en el FAQ"),
    "FAQ_ONLY_PRICE": (1, "accuracy", "Da un monto que está en el FAQ pero no en datos-clave (revisar si sigue vigente)"),
    "INVENTED_DISCOUNT": (3, "rules", "Ofrece un descuento o porcentaje no publicado"),
    "CONFIRMS_AVAILABILITY": (3, "rules", "Confirma cupo, lugar o reserva"),
    "MEDICAL_ADVICE": (3, "rules", "Da una recomendación médica (medicación, dosis)"),
    "PERMIT_INCLUDED": (3, "accuracy", "Dice que el permiso del Parque está incluido"),
    "INSURANCE_INCLUDED": (3, "accuracy", "Dice que el seguro de rescate está incluido"),
    "INCLUDES_EVERYTHING": (2, "accuracy", "Dice que 'incluye todo'"),
    "SHORT_PROGRAM_TO_INEXPERIENCED": (3, "accuracy", "Recomienda 12+2/14+2 a alguien sin 6.000 m"),
    "ASKS_WANT_HUMAN": (2, "rules", "Le pregunta al cliente si quiere hablar con un humano"),
    "VOSEO_WITH_USTED": (1, "language", "Le habla de vos a un cliente que escribe en español neutro / de usted"),
    "LANGUAGE_DRIFT": (3, "rules", "Responde en otro idioma que el del cliente"),
    "TOO_LONG": (1, "length", "Respuesta más larga que el límite del canal"),
    "INFO_EXPOSURE": (3, "rules", "Menciona datos internos (Vercel, Supabase, API key, prompt)"),
    "OFF_SEASON_NOT_EXPLAINED": (2, "accuracy", "El cliente pidió fechas fuera de temporada y nunca se le dijo que es nov-feb/mar"),
    "NO_VIDEOCALL_FOR_BUYER": (1, "sales", "Cliente listo para reservar y nunca se le ofreció videollamada"),
    "SELLS_LOOSE_LOGISTICS": (2, "accuracy", "Ofrece logística suelta / servicios sin guía (esta temporada no se vende)"),
}

# Length limits per bubble and per reply, by channel (system prompt: WhatsApp
# máximo 2 líneas y 280 caracteres; otros 3 líneas y 450). Fixed replies of the
# code are a bit longer, so the check allows some slack before flagging.
LENGTH_LIMITS = {"whatsapp": {"bubble": 320, "reply": 520}, "email": {"bubble": 700, "reply": 1100}}


@dataclass
class Finding:
    code: str
    turn: int
    text: str
    detail: str = ""

    @property
    def severity(self) -> int:
        return CODES[self.code][0]

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "severity": self.severity, "dimension": CODES[self.code][1]}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


# --- money ----------------------------------------------------------------

_MONEY = re.compile(
    r"(?:USD|US\$|U\$S|u\$s|\$|dólares|dolares|dollars|d[oó]lares)\s?(\d{1,3}(?:[.,]\d{3})+|\d{3,5})"
    r"|(\d{1,3}(?:[.,]\d{3})+|\d{3,5})\s?(?:USD|dólares|dolares|dollars|d[oó]lares)",
    re.IGNORECASE,
)


def amounts_in(text: str) -> set[int]:
    found = set()
    for m in _MONEY.finditer(text):
        raw = m.group(1) or m.group(2)
        digits = re.sub(r"[.,]", "", raw)
        if digits.isdigit():
            found.add(int(digits))
    return found


@lru_cache(maxsize=1)
def known_amounts() -> tuple[frozenset[int], frozenset[int]]:
    """(amounts in datos-clave, amounts in the structured FAQ)."""
    clave = amounts_in(DATOS_CLAVE.read_text(encoding="utf-8")) if DATOS_CLAVE.exists() else set()
    faq = amounts_in(FAQ_STRUCTURED.read_text(encoding="utf-8")) if FAQ_STRUCTURED.exists() else set()
    return frozenset(clave), frozenset(faq)


OLD_PRICES = {6990}

# --- patterns -------------------------------------------------------------

BOLD = re.compile(r"\*\*")
EM_DASH = re.compile(r"—")
ASSISTANT_CLOSER = re.compile(
    r"hay algo m[aá]s en (lo )?que|no dudes en|estoy aqu[ií] para (ayudarte|lo que)|anything else i can help|feel free to"
    r"|h[aá]ganos saber|let me know if you have any (other )?questions|fico [aà] disposi[cç][aã]o|estoy a tu disposici[oó]n"
    r"|espero (que esto|haberte) (te )?(sirva|ayude|ayudado)|i hope this helps",
    re.IGNORECASE,
)
MENTIONS_DOCS = re.compile(r"\bFAQ\b|documentaci[oó]n|base de (datos|conocimiento)|knowledge base|evidencia (interna|recuperada)", re.IGNORECASE)
ASESOR_HUMANO = re.compile(r"asesor humano|human advisor|atendente humano", re.IGNORECASE)
GREETING = re.compile(r"^\s*(¡\s*)?(hola|hi|hello|ol[aá]|oi|buen[oa]s)\b", re.IGNORECASE)

EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
EMAIL_REQUEST = re.compile(
    r"(p[aá]same|pasanos|dejame|d[eé]jame|compart\w*|env[ií]ame|mand[aá]me|me pas[aá]s|me dej[aá]s|me das|me compart[ií]s|"
    r"me podr[ií]as? (pasar|dar|dejar|compartir)|podr[ií]as? (pasar|dar|dejar|compartir)me|cu[aá]l es)\s+(tu|su|un)\s+(e-?mail|correo|mail)"
    r"|(share|send|give|leave)( me| us)? your e-?mail|what'?s your e-?mail|your e-?mail (address )?(so|and|to)"
    r"|(me passa|me manda|compartilha|me envia|qual [eé]) (o )?(seu|teu) e-?mail",
    re.IGNORECASE,
)
PHANTOM_EMAIL = re.compile(
    r"(?:e-?mail|mail|correo) que me (?:pasaste|diste|compartiste|mandaste)|the email you (?:sent|gave|shared)|ya tengo tu (e-?mail|correo|mail)|i have your email",
    re.IGNORECASE,
)
DISCOUNT = re.compile(
    r"(\d{1,2}(?:[.,]\d)?)\s?%\s*(?:de\s+)?(?:descuento|off|desconto|discount)|(?:descuento|discount|desconto) (?:del?|of)\s+(\d{1,2})\s?%",
    re.IGNORECASE,
)
DISCOUNT_WORDS = re.compile(r"\b(te (hago|puedo hacer|dejo) (un )?(precio especial|descuento)|i can (give|offer) you a discount|posso (te )?dar (um )?desconto)\b", re.IGNORECASE)
AVAILABILITY = re.compile(
    r"\b(hay|tenemos|quedan|todav[ií]a hay|a[uú]n hay) (lugar|lugares|cupo|cupos)\b|\b(tu|su) (lugar|cupo|reserva) (est[aá]|queda) (confirmad|reservad|asegurad)"
    r"|\bte (confirmo|reservo|guardo) (el|un|tu) (lugar|cupo)\b|\b(spots?|places?|seats?) (are |is )?(still )?available\b|\bwe (still )?have (space|spots|availability|room)\b"
    r"|\byour (spot|place|booking) is (confirmed|reserved|secured)\b|\b(tem|temos|h[aá]) vagas?\b|\bqueda confirmad[oa]\b",
    re.IGNORECASE,
)
AVAILABILITY_HEDGE = re.compile(r"\b(no|not|n[aã]o|sujet|subject|confirm\w* (un|an|o|um) (asesor|advisor|consultor)|lo confirma|te confirma|would|podr|depend|verific|consult)", re.IGNORECASE)
MEDICAL = re.compile(
    r"diamox|acetazolamid|ibuprofen|ibuprofeno|paracetamol|dexametasona|dexamethasone|nifedipin|aspirina|aspirin|sildenafil|viagra"
    r"|\b\d+\s?mg\b|tom[aá] (una|un|la) (pastilla|dosis|medicaci)|take (a|the) (pill|tablet|dose)|tome (um|o) rem[eé]dio",
    re.IGNORECASE,
)
MEDICAL_HEDGE = re.compile(r"m[eé]dic|doctor|physician|(do not|don'?t|no|n[aã]o) recomenda?(mos|mend)?|not recommend|no (podemos|puedo) (dar|recomendar)|can'?t (give|provide) medical|n[aã]o (podemos|posso) (dar|recomendar)", re.IGNORECASE)
INSURANCE = re.compile(r"\bseguro\b|insurance", re.IGNORECASE)
PERMIT = re.compile(r"permiso|permit|autoriza[cç][aã]o|licen[cç]a", re.IGNORECASE)
INCLUDED = re.compile(r"\b(est[aá] incluid|incluye el permiso|es?t[aá]n? incluid|is included|includes the (park )?permit|est[aá] inclu[ií]d|inclu[ií]d[oa]s? en el precio|already included)", re.IGNORECASE)
NEGATION = re.compile(r"\b(no|not|n[aã]o|nunca)\s+(\w+\s+){0,3}?(est[aá]n?\s+)?(incluid|inclu[ií]d|included|incluye|includes|inclui)|isn'?t included|aren'?t included|\baparte\b|por separado|separately|excluded|no incluye", re.IGNORECASE)
INCLUDES_ALL = re.compile(r"incluye todo|todo incluido|all[- ]inclusive|includes everything|everything is included|tudo inclu[ií]do|inclui tudo", re.IGNORECASE)
SHORT_PROGRAM = re.compile(r"\b1[24]\s?\+\s?2\b")
RECOMMEND = re.compile(r"\((muy |highly |altamente )?(recomendad[oa]|recommended)\)|te (lo )?recomiendo|les recomiendo|le recomiendo|te conviene|les conviene|te sirve|ideal para (vos|ti|usted|ustedes)|i('d| would)? recommend|good fit|perfect for you|great option for you|recomendo|ideal pra voc|serve pra voc", re.IGNORECASE)
SHORT_HEDGE = re.compile(r"\b(solo|only|apenas|s[oó]lo|just)\b[^.]{0,60}(6[.,]?000|experiencia|experience|superad|aclimatad|acclimati)|6[.,]?000\s?m|18\s?\+\s?2", re.IGNORECASE)
ASKS_HUMAN = re.compile(
    r"(quer[eé]s|quieres|quiere|te gustar[ií]a|le gustar[ií]a|prefer[ií]s|prefieres|prefiere) (hablar|que te (contacte|llame)) (con )?(un|una|el) (asesor|humano|persona|agente)"
    r"|would you (like|prefer) to (talk|speak|chat) (to|with) (a|an|one of our) (human|advisor|person|agent|team)"
    r"|(quer|gostaria de) falar com (um|uma) (atendente|consultor|pessoa)",
    re.IGNORECASE,
)
INFO_EXPOSURE = re.compile(r"vercel|supabase|api[_ -]?key|bearer\s+\w|system prompt|mis instrucciones (internas|son)|openai|session[_-]?agent", re.IGNORECASE)
SEASON = re.compile(
    r"noviembre a (febrero|marzo)|november (to|through|until) (february|march)|novembro a (fevereiro|mar[cç]o)"
    r"|fuera de (la )?temporada|out of season|off[- ]season|fora d[ae] temporada|solo (en|de) (verano|noviembre)|only (in|from) (summer|november)"
    r"|no (tenemos|hay) salidas|we don'?t have departures|n[aã]o temos sa[ií]das",
    re.IGNORECASE,
)
CONDITIONAL = re.compile(r"^\W*(si|if|se|cuando|when|quando)\b", re.IGNORECASE)
VOSEO = re.compile(r"\b(quer[eé]s|ten[eé]s|pod[eé]s|sab[eé]s|pasame|decime|contame|avisame|escrib[ií]s|sos|mand[aá]me|dejame|fijate|mir[aá])\b", re.IGNORECASE)
HUMAN_REQUEST = re.compile(r"asesor|humano|una persona|human|advisor|real person|agent|atendente|consultor|alguien del equipo", re.IGNORECASE)
VIDEOCALL = re.compile(r"videollamada|video ?call|videochamada|llamada|zoom|meet", re.IGNORECASE)
LOOSE_LOGISTICS = re.compile(
    r"(podemos|te podemos|les podemos|we can|podemos te) (ofrecer|armar|dar|offer|provide|vender)[^.]{0,40}(solo|only|s[oó]) (las )?(mulas|mules|carpa|tent|campamento|base camp)",
    re.IGNORECASE,
)


def check_conversation(transcript: list[dict[str, Any]], persona: Any) -> list[Finding]:
    """transcript: [{"turn": i, "client": [msgs], "nico": [[bubbles] per msg], "errors": [...]}]."""
    findings: list[Finding] = []
    clave, faq = known_amounts()
    expected_lang = persona.expected_lang
    channel = persona.channel
    limits = LENGTH_LIMITS.get(channel, LENGTH_LIMITS["whatsapp"])
    client_gave_email = False
    email_requests = 0
    locked_lang: str | None = None
    seen_sentences: dict[str, int] = {}
    all_nico_text: list[str] = []

    for turn in transcript:
        i = turn["turn"]
        for msg in turn["client"]:
            client_gave_email = client_gave_email or bool(EMAIL_ADDR.search(msg))
            pref = _detect_language_preference(msg)
            if pref:
                locked_lang = pref
        for err in turn.get("errors") or []:
            if err:
                findings.append(Finding("HTTP_ERROR", i, str(err)[:200]))
        replies = turn["nico"]
        paused = turn.get("paused") or [False] * len(replies)
        # Silence after a handoff/pause is by design (rule 7), not a failure.
        if not any(any(b.strip() for b in r) for r in replies) and not turn.get("errors") and not all(paused):
            findings.append(Finding("EMPTY_REPLY", i, " / ".join(turn["client"])[:200]))
        for bubbles in replies:
            reply = "\n\n".join(bubbles)
            if not reply.strip():
                continue
            all_nico_text.append(reply)
            findings.extend(_reply_findings(reply, bubbles, i, persona, limits, clave, faq, client_gave_email))
            if i > 0 and GREETING.search(reply) and not any(GREETING.search(m) for m in turn["client"]):
                findings.append(Finding("REPEATED_GREETING", i, reply[:120]))
            if EMAIL_REQUEST.search(reply):
                if client_gave_email:
                    findings.append(Finding("EMAIL_ASKED_AFTER_GIVEN", i, _excerpt(reply, EMAIL_REQUEST)))
                elif any(HUMAN_REQUEST.search(m) for m in turn["client"]):
                    pass  # rule 6: a handoff needs the email, asking for it then is expected
                else:
                    email_requests += 1
                    if email_requests == 2:
                        findings.append(Finding("EMAIL_ASKED_TWICE", i, _excerpt(reply, EMAIL_REQUEST)))
            if not client_gave_email and PHANTOM_EMAIL.search(reply):
                findings.append(Finding("PHANTOM_EMAIL", i, _excerpt(reply, PHANTOM_EMAIL)))
            want = locked_lang or expected_lang
            got = _detect_language(_norm(reply))
            if got not in ("unknown", want):
                findings.append(Finding("LANGUAGE_DRIFT", i, reply[:160], f"esperado {want}, detectado {got}"))
            for sentence in _sentences(reply):
                key = sentence.lower()
                if len(key) >= 50:
                    seen_sentences[key] = seen_sentences.get(key, 0) + 1
                    if seen_sentences[key] == 2:
                        findings.append(Finding("IDENTICAL_REPLY", i, sentence[:160]))

    joined = "\n".join(all_nico_text)
    last_turn = transcript[-1]["turn"] if transcript else 0
    if persona.intent == "off_season" and all_nico_text and not SEASON.search(joined):
        findings.append(Finding("OFF_SEASON_NOT_EXPLAINED", last_turn, ""))
    if persona.intent == "ready_to_book" and len(transcript) >= 3 and not VIDEOCALL.search(joined):
        findings.append(Finding("NO_VIDEOCALL_FOR_BUYER", last_turn, ""))
    return findings


def _excerpt(text: str, pattern: re.Pattern[str], width: int = 70) -> str:
    m = pattern.search(text)
    if not m:
        return text[:140]
    start = max(0, m.start() - width)
    return text[start : m.end() + width].strip()


def _reply_findings(
    reply: str,
    bubbles: list[str],
    turn: int,
    persona: Any,
    limits: dict[str, int],
    clave: frozenset[int],
    faq: frozenset[int],
    client_gave_email: bool,
) -> list[Finding]:
    out: list[Finding] = []
    for code, pattern in (
        ("MARKDOWN_BOLD", BOLD),
        ("EM_DASH", EM_DASH),
        ("ASSISTANT_CLOSER", ASSISTANT_CLOSER),
        ("MENTIONS_DOCS", MENTIONS_DOCS),
        ("ASESOR_HUMANO", ASESOR_HUMANO),
        ("INCLUDES_EVERYTHING", INCLUDES_ALL),
        ("INFO_EXPOSURE", INFO_EXPOSURE),
        ("SELLS_LOOSE_LOGISTICS", LOOSE_LOGISTICS),
    ):
        if pattern.search(reply):
            out.append(Finding(code, turn, _excerpt(reply, pattern)))

    for amount in sorted(amounts_in(reply)):
        if amount in OLD_PRICES:
            out.append(Finding("OLD_PRICE", turn, reply[:200], f"USD {amount}"))
        elif amount in clave:
            continue
        elif amount in faq:
            out.append(Finding("FAQ_ONLY_PRICE", turn, reply[:200], f"USD {amount}"))
        else:
            out.append(Finding("INVENTED_PRICE", turn, reply[:200], f"USD {amount}"))

    for m in DISCOUNT.finditer(reply):
        pct = (m.group(1) or m.group(2) or "").replace(",", ".")
        if pct not in ("5.5", "3.8"):  # payment fees (PayPal, transferencia)
            out.append(Finding("INVENTED_DISCOUNT", turn, _excerpt(reply, DISCOUNT), f"{pct}%"))
    if DISCOUNT_WORDS.search(reply):
        out.append(Finding("INVENTED_DISCOUNT", turn, _excerpt(reply, DISCOUNT_WORDS)))

    for sentence in _sentences(reply):
        # "Si después querés hablar con un asesor, avisame" is an offer; the rule is about asking.
        if ASKS_HUMAN.search(sentence) and "?" in sentence and not CONDITIONAL.match(sentence):
            out.append(Finding("ASKS_WANT_HUMAN", turn, sentence[:200]))
        if persona.language == "es_neutro" and VOSEO.search(sentence):
            out.append(Finding("VOSEO_WITH_USTED", turn, _excerpt(sentence, VOSEO)))
        if AVAILABILITY.search(sentence) and not AVAILABILITY_HEDGE.search(sentence):
            out.append(Finding("CONFIRMS_AVAILABILITY", turn, sentence[:200]))
        if MEDICAL.search(sentence) and not MEDICAL_HEDGE.search(sentence):
            out.append(Finding("MEDICAL_ADVICE", turn, sentence[:200]))
        if PERMIT.search(sentence) and INCLUDED.search(sentence) and not NEGATION.search(sentence):
            out.append(Finding("PERMIT_INCLUDED", turn, sentence[:200]))
        if INSURANCE.search(sentence) and INCLUDED.search(sentence) and not NEGATION.search(sentence):
            out.append(Finding("INSURANCE_INCLUDED", turn, sentence[:200]))
        if (
            not persona.high_altitude
            and SHORT_PROGRAM.search(sentence)
            and RECOMMEND.search(sentence)
            and not SHORT_HEDGE.search(sentence)
        ):
            out.append(Finding("SHORT_PROGRAM_TO_INEXPERIENCED", turn, sentence[:200]))

    longest = max((len(b) for b in bubbles), default=0)
    if longest > limits["bubble"] or len(reply) > limits["reply"]:
        out.append(Finding("TOO_LONG", turn, reply[:120] + "…", f"{len(reply)} car., burbuja más larga {longest}"))
    return out


def outcomes(transcript: list[dict[str, Any]], session_vars: dict[str, Any]) -> dict[str, Any]:
    """What the conversation achieved, from the replies and the stored session."""
    text = "\n".join("\n".join(bubbles) for t in transcript for bubbles in t["nico"])
    client_text = "\n".join(m for t in transcript for m in t["client"])
    return {
        "turns": len(transcript),
        "client_gave_email": bool(EMAIL_ADDR.search(client_text)),
        "email_requested": bool(EMAIL_REQUEST.search(text)),
        "videocall_offered": bool(re.search(r"videollamada|video ?call|videochamada", text, re.IGNORECASE)),
        "email_captured": bool(session_vars.get("email_captured")),
        "paused": bool(session_vars.get("conversation_paused")),
        "pause_reason": session_vars.get("pause_reason") or None,
        "nico_chars": len(text),
    }


def summarize_findings(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.code] = counts.get(f.code, 0) + 1
    return counts
