"""AI layer. Claude (via OpenRouter's OpenAI-compatible API) for vision, writing and tool-using agents."""
from __future__ import annotations

import base64
import io
import json
import re
from typing import Any, Callable

from openai import OpenAI
from PIL import Image

from . import config

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        _client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=config.OPENROUTER_API_KEY,
                         default_headers={"HTTP-Referer": config.PUBLIC_URL, "X-Title": "Little Makers Market"})
    return _client


def image_part(img: Image.Image, max_side: int = 1024) -> dict:
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}


def parse_json(text: str) -> Any:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = min([i for i in (text.find("{"), text.find("[")) if i >= 0], default=0)
    return json.loads(text[start:text.rfind("}" if text[start] == "{" else "]") + 1])


def ask_json(system: str, content: list | str, model: str | None = None, max_tokens: int = 1200) -> dict:
    r = client().chat.completions.create(
        model=model or config.AI_MODEL, max_tokens=max_tokens, temperature=0.6,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": content}])
    return parse_json(r.choices[0].message.content or "{}")


# ------------------------------------------------------------------ maker pipeline

ANALYZE_SYSTEM = """You are the friendly art buddy inside Little Makers Market, where kids' drawings become plush 3D toys, stickers and prints that their family can buy.
Look at the photo and return ONLY JSON:
{
 "is_drawing": bool,                 // a hand-made drawing/painting by a child (not a photo of a person, not printed art)
 "safe": bool,                       // false if it contains a real face photo, names/addresses/phone numbers/school names, or anything not OK for a kids' shop
 "safety_note": str,                 // short, kind reason if not safe or not a drawing, else ""
 "kind": str,                        // what the main character is, 1-3 words, e.g. "dragon"
 "description": str,                 // one warm sentence describing the character as drawn
 "colors": [str],                    // main crayon colours
 "quirks": [str],                    // 2-5 delightful details that make it THIS kid's version (e.g. "three legs", "crown is bigger than its head"). Never call them mistakes.
 "name_ideas": [str],                // 3 fun names a kid would love
 "questions": [str]                  // exactly 2 short questions to ask the young artist, max 12 words each, e.g. "What is your dragon's name?", "What is its secret superpower?"
}"""

LISTING_SYSTEM = """You write shop listings for Little Makers Market, where a child's drawing becomes products their family can buy.
Rules: keep every quirk of the drawing (they are features, never fix them); use the kid's own answers; warm, playful, short; never mention the child's full name, school or location.
Return ONLY JSON:
{
 "character_name": str,
 "title": str,                       // e.g. "Sparky the Three-Legged Dragon"
 "story": str,                       // 50-80 word origin story, told like a picture book, based on the kid's answers
 "tagline": str,                     // max 10 words
 "products": {
   "plush3d": {"name": str, "description": str, "price_cents": int},   // digital 3D plush model (AR + download), suggest 300-700
   "sticker": {"name": str, "description": str, "price_cents": int},   // die-cut vinyl sticker, suggest 300-600
   "print":   {"name": str, "description": str, "price_cents": int}    // 8x10 art print, suggest 1200-2500
 },
 "coach_line": str                   // one sentence the money coach could say to the kid when the first item sells
}"""


def analyze_drawing(img: Image.Image) -> dict:
    return ask_json(ANALYZE_SYSTEM, [{"type": "text", "text": "Here is the drawing."}, image_part(img)])


def write_listing(img: Image.Image, analysis: dict, answers: dict, nickname: str, age: int | None) -> dict:
    facts = {"artist_nickname": nickname, "artist_age": age, "analysis": analysis, "kid_answers": answers}
    return ask_json(LISTING_SYSTEM, [{"type": "text", "text": json.dumps(facts)}, image_part(img, 768)], max_tokens=1500)


# ------------------------------------------------------------------ tool-using agent loop

def run_agent(system: str, messages: list[dict], tools: list[dict], execute: Callable[[str, dict], Any],
              model: str | None = None, max_steps: int = 8) -> tuple[str, list[dict]]:
    """OpenAI-style tool loop. Returns (final_text, trace) where trace lists each tool call + result."""
    convo = [{"role": "system", "content": system}, *messages]
    trace: list[dict] = []
    for _ in range(max_steps):
        r = client().chat.completions.create(model=model or config.AI_MODEL, max_tokens=1500,
                                             messages=convo, tools=tools or None)
        msg = r.choices[0].message
        if not msg.tool_calls:
            return msg.content or "", trace
        convo.append({"role": "assistant", "content": msg.content or "",
                      "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {}
            try:
                result = execute(tc.function.name, args)
            except Exception as e:  # report tool errors back to the model
                result = {"error": str(e)[:800]}
            text = result if isinstance(result, str) else json.dumps(result, default=str)
            trace.append({"tool": tc.function.name, "args": args, "result": text[:2000]})
            convo.append({"role": "tool", "tool_call_id": tc.id, "content": text[:12000]})
    return "I hit my step limit — please try a smaller request.", trace
