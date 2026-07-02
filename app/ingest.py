"""Parse WhatsApp chat exports and (optionally) extract Q&A pairs with Claude."""
import json
import os
import re

# WhatsApp export lines look like:
#   [dd/mm/yyyy, hh:mm:ss] Name: message
#   dd/mm/yyyy, hh:mm - Name: message
# We normalise both into (author, text). Continuation lines (no header)
# are appended to the previous message.
_LINE_RE = re.compile(
    r"^\[?(?P<date>\d{1,2}[/.]\d{1,2}[/.]\d{2,4})[,\s]+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?)\]?\s*[-–]?\s*"
    r"(?P<author>[^:]{1,60}):\s(?P<text>.*)$"
)


def parse_export(raw: str) -> list[dict]:
    """Turn a raw .txt export into a list of {author, text, date} messages."""
    messages: list[dict] = []
    for line in raw.splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            messages.append(
                {
                    "author": m.group("author").strip(),
                    "text": m.group("text").strip(),
                    "date": m.group("date"),
                }
            )
        elif messages:
            messages[-1]["text"] += "\n" + line.rstrip()
    # Drop system noise (encryption notices, media placeholders, etc.).
    noise = ("<Media omitted>", "Mensagem apagada", "This message was deleted",
             "‎", "end-to-end encrypted", "criptografia de ponta")
    return [
        msg for msg in messages
        if msg["text"] and not any(n in msg["text"] for n in noise)
    ]


def extract_qa(messages: list[dict]) -> dict:
    """Return {"pairs": [...], "ai": bool}.

    With ANTHROPIC_API_KEY set, ask Claude to group the conversation into
    question->answer pairs. Otherwise return the parsed messages so an admin
    can build pairs by hand.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"pairs": [], "ai": False, "messages": messages}

    from anthropic import Anthropic

    transcript = "\n".join(f"{m['author']}: {m['text']}" for m in messages)
    # Guard against oversized prompts; caller should chunk large exports.
    transcript = transcript[:120_000]

    prompt = (
        "Você recebe uma transcrição de um grupo de WhatsApp em português.\n"
        "Extraia os pares de PERGUNTA e RESPOSTA úteis e reutilizáveis. "
        "Ignore conversa fiada, saudações e mensagens sem valor de conhecimento.\n"
        "Para cada par, sugira um título curto, o assunto/grupo, a pergunta e a "
        "melhor resposta consolidada.\n"
        "Responda APENAS com JSON no formato:\n"
        '{"pairs":[{"title":"","group":"","question":"","answer":"",'
        '"asked_by":"","answered_by":""}]}\n\n'
        f"Transcrição:\n{transcript}"
    )

    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=os.getenv("EXTRACT_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    text_out = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )
    pairs = _parse_json_pairs(text_out)
    return {"pairs": pairs, "ai": True}


def extract_qa_freeform(raw: str) -> dict:
    """Extract Q&A pairs from arbitrary pasted text (not a WhatsApp export):
    FAQs, policy docs, articles, plain notes, etc. Returns {"pairs": [...], "ai": True}.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"pairs": [], "ai": False, "messages": []}

    from anthropic import Anthropic

    text_in = raw[:120_000]
    prompt = (
        "Você recebe um texto em português (pode ser um documento, FAQ, "
        "artigo, anotações ou qualquer conteúdo colado por um usuário — não "
        "necessariamente uma conversa).\n"
        "Extraia ou sintetize pares de PERGUNTA e RESPOSTA úteis e "
        "reutilizáveis a partir desse conteúdo. Se o texto já tiver "
        "perguntas explícitas, use-as; senão, formule perguntas razoáveis "
        "que o conteúdo responde.\n"
        "Para cada par, sugira um título curto, o assunto/grupo, a pergunta "
        "e a melhor resposta consolidada.\n"
        "Responda APENAS com JSON no formato:\n"
        '{"pairs":[{"title":"","group":"","question":"","answer":"",'
        '"asked_by":"","answered_by":""}]}\n\n'
        f"Texto:\n{text_in}"
    )

    client = Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=os.getenv("EXTRACT_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    text_out = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    )
    return {"pairs": _parse_json_pairs(text_out), "ai": True}


def _parse_json_pairs(text_out: str) -> list[dict]:
    """Extract the JSON object from a model response, tolerating stray prose."""
    start, end = text_out.find("{"), text_out.rfind("}")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text_out[start : end + 1])
    except json.JSONDecodeError:
        return []
    return data.get("pairs", []) if isinstance(data, dict) else []
