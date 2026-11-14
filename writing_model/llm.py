"""Thin, cached wrapper around the headless Claude Code CLI (`claude -p`).

Every model call in this repo goes through `call()`. Responses are cached on
disk keyed by (model, system, effort, schema, tag, prompt), so re-running any
script replays the recorded responses instead of spending tokens again.
`tag` is how we get independent samples of the same prompt (e.g. tag="seed2").
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(os.environ.get("WRITING_MODEL_CACHE", ROOT / "cache"))
USAGE_LOG = ROOT / "results" / "usage.jsonl"
MAX_PARALLEL = int(os.environ.get("WRITING_MODEL_PARALLEL", "8"))

# Role -> model alias. Kept in one place so the roles are easy to audit.
MODELS = {
    "rewriter": "fable",   # strongest model: writes the rewrite
    "auditor": "fable",    # fidelity audit of the rewrite against the source
    "infra": "opus",       # quiz writer, error planter, graders (never the rewriter)
    "weak": "haiku",       # weak reader (in-loop locator AND held-out evaluator)
    "mid": "sonnet",       # mid reader (held-out evaluator only)
    "novice": "claude-haiku-4-5",  # older small model with reasoning switched off (held-out evaluator only)
}
NO_THINKING = {"claude-haiku-4-5"}  # models run with extended reasoning disabled

_sem = threading.Semaphore(MAX_PARALLEL)
_log_lock = threading.Lock()
_EMPTY_CWD = tempfile.mkdtemp(prefix="writing-model-cli-")


class LLMError(RuntimeError):
    pass


def _key(model, system, effort, schema, tag, prompt) -> str:
    h = hashlib.sha256()
    for part in (model, system or "", effort or "", json.dumps(schema, sort_keys=True) if schema else "", tag or "", prompt):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def call(prompt: str, *, model: str, system: str = "", effort: str | None = None,
         schema: dict | None = None, tag: str = "", timeout: int = 2400,
         retries: int = 5, role: str = "") -> dict:
    """Returns {"text", "data" (parsed JSON if schema given), "usage", "cost", "cached"}."""
    model = MODELS.get(model, model)
    if model in NO_THINKING:
        effort = None
    key = _key(model, system, effort, schema, tag, prompt)
    path = CACHE_DIR / key[:2] / f"{key}.json"
    if path.exists():
        out = json.loads(path.read_text())
        out["cached"] = True
        return out

    cmd = ["claude", "-p", "--model", model, "--tools", "", "--strict-mcp-config",
           "--disable-slash-commands", "--no-session-persistence",
           "--setting-sources", "", "--output-format", "json",
           "--system-prompt", system or "You are a careful mathematician."]
    env = dict(os.environ)
    if model in NO_THINKING:
        env["MAX_THINKING_TOKENS"] = "0"
        effort = None
    if effort:
        cmd += ["--effort", effort]
    if schema:
        cmd += ["--json-schema", json.dumps(schema)]

    last = None
    for attempt in range(retries):
        with _sem:
            t0 = time.time()
            try:
                p = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                   timeout=timeout, cwd=_EMPTY_CWD, env=env)
            except subprocess.TimeoutExpired:
                last = "timeout"
                continue
        try:
            d = json.loads(p.stdout)
        except Exception:
            last = f"bad json (rc={p.returncode}): {p.stdout[:300]!r} {p.stderr[:300]!r}"
            time.sleep(min(300, 20 * 2 ** attempt) + random.random() * 5)
            continue
        if d.get("is_error") or d.get("result") is None:
            last = f"api error: {str(d.get('result'))[:300]}"
            time.sleep(min(300, 20 * 2 ** attempt) + random.random() * 5)
            continue
        data = d.get("structured_output")
        if schema and data is None:
            try:
                data = extract_json(d["result"])
            except Exception:
                last = f"no structured output: {d['result'][:200]!r}"
                continue
        u = d.get("usage", {}) or {}
        out = {
            "text": d["result"],
            "data": data,
            "usage": {
                "input": (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0),
                "output": u.get("output_tokens") or 0,
                "thinking": (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0,
            },
            "cost": d.get("total_cost_usd") or 0.0,
            "model": next(iter(d.get("modelUsage", {}) or {model: 0})),
            "seconds": round(time.time() - t0, 1),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp%d" % threading.get_ident())
        tmp.write_text(json.dumps(out))
        tmp.replace(path)
        with _log_lock:
            USAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_LOG.open("a") as f:
                f.write(json.dumps({"t": int(time.time()), "role": role, "model": out["model"],
                                    "effort": effort, "tag": tag, **out["usage"],
                                    "cost": out["cost"], "seconds": out["seconds"]}) + "\n")
        out["cached"] = False
        return out
    raise LLMError(f"{model} failed after {retries} attempts: {last}")


def extract_json(text: str):
    """Parse the first JSON object/array in `text` (tolerates code fences and prose)."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise ValueError("no JSON found")
    start = min(starts)
    dec = json.JSONDecoder()
    obj, _ = dec.raw_decode(text[start:])
    return obj


def pmap(fn, items, workers: int | None = None):
    """Parallel map preserving order; exceptions are returned as values."""
    items = list(items)
    if not items:
        return []

    def safe(x):
        try:
            return fn(x)
        except Exception as e:  # noqa: BLE001
            return e

    with ThreadPoolExecutor(max_workers=workers or MAX_PARALLEL * 2) as ex:
        return list(ex.map(safe, items))


def total_cost() -> float:
    if not USAGE_LOG.exists():
        return 0.0
    return sum(json.loads(line).get("cost", 0) for line in USAGE_LOG.read_text().splitlines() if line.strip())
