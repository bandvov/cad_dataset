"""
orchestrator.py
The self-correcting generate/repair loop:
  1. render the user turn (chat_format.py -- same phrasing training used)
  2. call llama.cpp's OpenAI-compatible /v1/chat/completions
  3. parse the model's output as JSON IR
  4. call the geometry service's /v1/compile to validate
  5. on failure, feed the real error back as a repair turn
     (chat_format.render_repair_user_turn -- the exact shape
     gen_repair.py trained the model to handle) and retry
  6. give up after max_attempts, returning the last error and IR attempt

`generate_stream()` is the single implementation of this loop, an async
generator yielding one newline-JSON-friendly event dict per step
(attempt_start, llm_response, validating, attempt_failed, repairing,
terminating in exactly one of success/failure). `generate()` is a thin
wrapper that drains it for callers that only want the final answer -- see
main.py for both a streaming (NDJSON) and buffered HTTP endpoint over the
same underlying loop.

Using chat_format.py here (not ad-hoc string building) is the entire
reason that module exists: the wording the model sees at inference time
must match what build_dataset.py rendered at training time, or you
reintroduce exactly the kind of train/serve skew bug this project already
hit once (the "model" vs "assistant" role mismatch).

DEBUGGING: set LLM_SERVICE_DEBUG=0 to silence the print()s below (on by
default). They print straight to stdout/container logs, not through
python's `logging` module -- deliberately simple since this is meant for
"what is the model actually generating" visibility during development,
not structured production logging. Long values (raw model output, full
IR) are printed in full, not truncated, since truncating is exactly what
you don't want while debugging a bad generation.

NOTE on the removed root "operation" normalization: an earlier version of
this file patched around the model emitting {"part": "part", ...} instead
of the schema's root shape by rewriting the key here. That's no longer
needed -- schema.py dropped the root "operation" requirement entirely
(see its module docstring), so a stray "part" key, or no root
discriminator at all, is now just an unrecognized extra key that
validate_ir() never looks at. Fixing the root cause in the schema made
this file's patch dead code; removed rather than left around.

NOTE: not executed in the sandbox this was authored in -- no httpx
installed there, no network to reach a real llama.cpp or geometry
service. `extract_json()` (the one dependency-free piece) was smoke-
tested standalone; the async HTTP flow was not. Test against a real
llama.cpp + geometry service stack before trusting this in production.
"""

from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass, field

import httpx

import chat_format

_DEBUG = os.environ.get("LLM_SERVICE_DEBUG", "1") not in ("0", "false", "False", "")


def _debug(*args) -> None:
    if _DEBUG:
        print(*args, flush=True)


# Gemma 4's own native structured-output convention uses control tokens
# instead of plain JSON punctuation -- <|"|> delimits string values
# (unquoted keys) in its tool-call/structured-data format. That's a
# DIFFERENT convention from the plain-JSON-as-text this project trains
# for, and it's a documented source of mangled JSON when it leaks through
# anyway (see e.g. ggml-org/llama.cpp#21384, vllm-project/vllm#38946 --
# same <|"|> leakage corrupting quote placement in other Gemma 4
# deployments, not something specific to this pipeline). If any of these
# ever show up as literal text in a completion (llama.cpp/training decode
# not stripping them, or the base model's habit winning out over the
# LoRA), un-corrupt rather than discard -- <|"|> IS a quote character by
# definition, so replacing it with one is a correction, not a guess.
# Channel/tool-call wrapper tokens are stripped outright since nothing in
# this pipeline's prompts asks for thinking or tool use.
_GEMMA4_LEAK_PATTERNS = [
    ('<|"|>', '"'),
    ("<|tool_call>", ""), ("<tool_call|>", ""),
    ("<|tool_response>", ""), ("<tool_response|>", ""),
    ("<|tool>", ""), ("<tool|>", ""),
    ("<|channel>", ""), ("<channel|>", ""),
]


def _strip_gemma4_leaks(text: str) -> str:
    cleaned = text
    for token, replacement in _GEMMA4_LEAK_PATTERNS:
        if token in cleaned:
            cleaned = cleaned.replace(token, replacement)
    if cleaned != text:
        _debug(f"[orchestrator] stripped leaked Gemma 4 control token(s) from raw output")
    return cleaned


def extract_json(text: str) -> dict | None:
    """The model was trained to emit raw JSON with nothing else, but
    sampling can still occasionally wrap it in markdown fences or add
    stray text -- try increasingly permissive extraction before giving up."""
    text = _strip_gemma4_leaks(text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return None


@dataclass
class GenerateResult:
    success: bool
    json_ir: dict | None
    attempts: int
    stats: dict | None = None
    error: str | None = None
    conversation: list[dict] = field(default_factory=list)


class Orchestrator:
    def __init__(self, llama_url: str, geometry_url: str, http_timeout: float = 60.0):
        self.llama_url = llama_url.rstrip("/")
        self.geometry_url = geometry_url.rstrip("/")
        self.http_timeout = http_timeout

    async def _chat(self, client: httpx.AsyncClient, messages: list[dict]) -> str:
        resp = await client.post(
            f"{self.llama_url}/v1/chat/completions",
            json={"messages": messages, "temperature": 0.0, "max_tokens": 2048},
            timeout=self.http_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        _debug(f"[orchestrator] <<< raw model output ({len(content)} chars):\n{content}")
        return content

    async def _compile(self, client: httpx.AsyncClient, ir: dict) -> dict:
        resp = await client.post(
            f"{self.geometry_url}/v1/compile", json={"json_ir": ir}, timeout=self.http_timeout,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("valid"):
            _debug(f"[orchestrator] compile OK -- stats={result.get('stats')}")
        else:
            _debug(f"[orchestrator] compile FAILED -- {result.get('error_type')}: {result.get('error')}")
        return result

    async def generate_stream(self, prompt: str, base_ir: dict | None = None,
                               max_attempts: int = 3):
        """Async generator yielding one event dict per step, e.g.:
          {"event": "attempt_start", "attempt": 1, "max_attempts": 3}
          {"event": "llm_response", "attempt": 1, "content": "..."}
          {"event": "validating", "attempt": 1}
          {"event": "attempt_failed", "attempt": 1, "error_type": "...", "error": "..."}
          {"event": "repairing", "attempt": 1, "next_attempt": 2}
          {"event": "success", "attempts": 2, "json_ir": {...}, "stats": {...}, "conversation": [...]}
        Terminal event is always exactly one of "success" or "failure".
        This is the single source of truth for the loop; generate() (the
        non-streaming form) just drains this and returns the terminal
        event, so there's one implementation, not two copies that can
        drift apart."""
        if base_ir is not None:
            user_turn = chat_format.render_regenerate_user_turn(base_ir, prompt)
        else:
            user_turn = chat_format.render_generate_user_turn(prompt)

        _debug(f"[orchestrator] === generate start === prompt={prompt!r} "
               f"base_ir={'yes' if base_ir is not None else 'no'} max_attempts={max_attempts}")

        yield {"event": "start", "max_attempts": max_attempts}

        messages = [{"role": "user", "content": user_turn}]
        conversation = list(messages)
        last_error: str | None = None
        last_ir: dict | None = None

        async with httpx.AsyncClient() as client:
            for attempt in range(1, max_attempts + 1):
                yield {"event": "attempt_start", "attempt": attempt, "max_attempts": max_attempts}
                _debug(f"[orchestrator] --- attempt {attempt}/{max_attempts} ---")

                try:
                    raw = await self._chat(client, messages)
                except httpx.HTTPError as e:
                    _debug(f"[orchestrator] LLM request failed: {e}")
                    yield {"event": "failure", "attempts": attempt, "json_ir": last_ir,
                           "error": f"llm request failed: {e}", "conversation": conversation}
                    return

                messages.append({"role": "assistant", "content": raw})
                conversation.append({"role": "assistant", "content": raw})
                yield {"event": "llm_response", "attempt": attempt, "content": raw}

                ir = extract_json(raw)
                if ir is None:
                    last_error = "model output was not valid JSON"
                    _debug(f"[orchestrator] JSON parse FAILED: {last_error}")
                    yield {"event": "attempt_failed", "attempt": attempt,
                           "error_type": "ParseError", "error": last_error}
                    repair_turn = (
                        "Your last response was not valid JSON. Respond with ONLY "
                        "the JSON feature tree, no other text.\n\n"
                        f"Error: {last_error}"
                    )
                else:
                    last_ir = ir
                    n_features = len(ir.get("features", []))
                    _debug(f"[orchestrator] parsed IR OK -- {n_features} feature(s):\n"
                           f"{json.dumps(ir, indent=2)}")
                    yield {"event": "validating", "attempt": attempt}
                    try:
                        result = await self._compile(client, ir)
                    except httpx.HTTPError as e:
                        _debug(f"[orchestrator] geometry service request failed: {e}")
                        yield {"event": "failure", "attempts": attempt, "json_ir": ir,
                               "error": f"geometry service request failed: {e}",
                               "conversation": conversation}
                        return
                    if result.get("valid"):
                        _debug(f"[orchestrator] === generate SUCCESS on attempt {attempt} ===")
                        yield {"event": "success", "attempts": attempt, "json_ir": ir,
                               "stats": result.get("stats"), "conversation": conversation}
                        return
                    last_error = result.get("error", "unknown validation error")
                    yield {"event": "attempt_failed", "attempt": attempt,
                           "error_type": result.get("error_type"), "error": last_error}
                    repair_turn = chat_format.render_repair_user_turn(broken_ir=ir, error=last_error)

                messages.append({"role": "user", "content": repair_turn})
                conversation.append({"role": "user", "content": repair_turn})
                if attempt < max_attempts:
                    _debug(f"[orchestrator] repairing -- feeding error back for attempt {attempt + 1}")
                    yield {"event": "repairing", "attempt": attempt, "next_attempt": attempt + 1}

        _debug(f"[orchestrator] === generate FAILURE -- exhausted {max_attempts} attempts. "
               f"last_error={last_error!r} ===")
        yield {"event": "failure", "attempts": max_attempts, "json_ir": last_ir,
               "error": last_error, "conversation": conversation}

    async def generate(self, prompt: str, base_ir: dict | None = None,
                        max_attempts: int = 3) -> GenerateResult:
        """Non-streaming form: drains generate_stream() and returns just
        the terminal outcome. Prefer generate_stream() directly (see
        main.py's /v1/generate/stream) when the caller can show progress;
        this exists for callers that just want the final answer."""
        async for event in self.generate_stream(prompt, base_ir, max_attempts):
            if event["event"] == "success":
                return GenerateResult(True, event["json_ir"], event["attempts"],
                                       stats=event.get("stats"),
                                       conversation=event.get("conversation", []))
            if event["event"] == "failure":
                return GenerateResult(False, event.get("json_ir"), event["attempts"],
                                       error=event.get("error"),
                                       conversation=event.get("conversation", []))
        # generate_stream() always yields exactly one terminal event -- if
        # we get here, that invariant broke
        return GenerateResult(False, None, max_attempts, error="generator produced no terminal event")

    async def compile_only(self, ir: dict) -> dict:
        """Direct validate-only call to the geometry service, bypassing
        the model entirely. Used by the structured-editing fallback (Phase
        2 item 4: a user edits a dimension directly in the feature tree,
        not via a prompt) -- there's no generation loop here because
        there's nothing to generate, just geometry to check."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.geometry_url}/v1/compile", json={"json_ir": ir},
                timeout=self.http_timeout,
            )
        resp.raise_for_status()
        result = resp.json()
        _debug(f"[orchestrator] compile_only -- valid={result.get('valid')} "
               f"error={result.get('error')}")
        return result

    async def export(self, ir: dict, fmt: str) -> tuple[bytes, str, dict] | None:
        """Returns (file_bytes, content_type, stats) or None on failure."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.geometry_url}/v1/export", json={"json_ir": ir, "format": fmt},
                timeout=self.http_timeout,
            )
        if resp.status_code != 200:
            _debug(f"[orchestrator] export FAILED -- status={resp.status_code}")
            return None
        stats = json.loads(resp.headers.get("X-Geometry-Stats", "{}"))
        return resp.content, resp.headers.get("content-type", "application/octet-stream"), stats
