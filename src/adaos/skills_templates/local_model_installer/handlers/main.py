from __future__ import annotations

import os
import re
import importlib.resources as ir
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping

import requests
from huggingface_hub import snapshot_download

from adaos.services.agent_context import get_ctx


def _ok(**kw):
    out = {"ok": True}
    out.update(kw)
    return out


def _err(msg: str, **kw):
    out = {"ok": False, "error": msg}
    out.update(kw)
    return out


def _write_env_var(key: str, value: str):
    try:
        from dotenv import find_dotenv

        from pathlib import Path

        dotenv_path = Path(find_dotenv() or ".env")
        lines: list[str] = []
        if dotenv_path.exists():
            lines = dotenv_path.read_text(encoding="utf-8").splitlines()
        found = False
        for i, ln in enumerate(lines):
            if ln.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        dotenv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


def _safe_dirname(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.\-]+", "_", text).strip("._-") or "model"


def _resolve_ollama_installer() -> Path | None:
    resource = "install.ps1" if sys.platform.startswith("win") else "install.sh"
    try:
        import adaos.local_models.presets.ollama as pkg

        res = ir.files(pkg) / resource
        with ir.as_file(res) as fp:
            script = Path(fp)
            if script.exists():
                return script
    except Exception:
        pass

    adaos_root = Path(__file__).resolve()
    candidates = [
        adaos_root.parents[3] / "local_models" / "presets" / "ollama" / resource,
        adaos_root.parents[4] / "local_models" / "presets" / "ollama" / resource if len(adaos_root.parents) >= 5 else None,
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return None


def _ensure_ollama_available():
    """Ensure Ollama binary is available; prepare manual installer if missing."""
    if shutil.which("ollama"):
        return True, None

    installer = _resolve_ollama_installer()
    if not installer:
        return False, "installer script for ollama not found"

    if installer.suffix == ".ps1":
        cmd = [
            "powershell",
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(installer),
        ]
    else:
        cmd = ["bash", str(installer)]

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
    except Exception as exc:
        return False, f"failed to run installer: {exc}"

    if proc.returncode != 0:
        details = (proc.stdout or "") + (proc.stderr or "")
        details = details.strip() or f"exit code {proc.returncode}"
        return False, details

    if shutil.which("ollama"):
        return True, None
    details = (proc.stdout or "") + (proc.stderr or "")
    details = details.strip() or "ollama still not in PATH after running installer script"
    return False, details


def _hf_install(payload: Mapping[str, Any]):
    repo_id = payload.get("repo_id") or payload.get("model")
    if not repo_id:
        return _err("repo_id is required for hf provider")

    revision = payload.get("revision") or None
    allow = payload.get("allow_patterns") or None

    ctx = get_ctx()
    base = ctx.paths.cache_dir() / "models" / "hf" / _safe_dirname(repo_id)
    base.mkdir(parents=True, exist_ok=True)
    token = payload.get("token") or payload.get("hf_token") or None
    path = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        allow_patterns=allow,
        local_dir=str(base),
        resume_download=True,
        max_workers=4,
        token=token,
    )
    return _ok(provider="hf", repo_id=repo_id, path=path)


def _ollama_api_base(payload: Mapping[str, Any]) -> str:
    # Prefer explicit base; else infer from ADAOS_LLM_BASE_URL (strip trailing /v1)
    base = payload.get("base_url") or os.getenv("OLLAMA_API_BASE")
    if not base:
        v1 = os.getenv("ADAOS_LLM_BASE_URL") or "http://127.0.0.1:11434/v1"
        base = re.sub(r"/v1/?$", "", v1)
    return base.rstrip("/")


def _ollama_install(payload: Mapping[str, Any]):
    model = payload.get("model")
    if not model:
        return _err("model is required for ollama provider")

    ensure_ok, ensure_details = _ensure_ollama_available()
    if not ensure_ok:
        hint = ensure_details or "installer prepared; run OllamaSetup.exe manually, then rerun command"
        return _err(
            "ollama not installed; manual setup required",
            details=hint,
            next_steps="Запустите скачанный OllamaSetup.exe от администратора и повторите команду.",
        )

    base = _ollama_api_base(payload)
    url = f"{base}/api/pull"
    try:
        r = requests.post(url, json={"name": model}, timeout=5)
        if r.status_code not in (200, 201):
            return _err(f"pull failed: {r.status_code}", details=r.text)
    except Exception as e:
        return _err(f"cannot connect to ollama api: {e}")

    # Poll tags to confirm presence
    time.sleep(0.5)
    try:
        r = requests.get(f"{base}/api/tags", timeout=5)
        if r.status_code == 200 and model.split(":")[0] in r.text:
            return _ok(provider="ollama", model=model, status="installed")
    except Exception:
        pass
    return _ok(provider="ollama", model=model, status="requested")


def _preset_smallset(payload: Mapping[str, Any]):
    provider = payload.get("provider", "ollama")
    items = payload.get("models")
    if not items:
        if provider == "ollama":
            items = [
                "llama3.2:3b-instruct",
                "qwen2.5:3b-instruct",
                "mistral:7b-instruct",
                "phi3:mini",
                "gemma2:2b-instruct",
            ]
        else:
            return _err("preset requires explicit models for provider != ollama")
    ok = []
    for m in items:
        res = _ollama_install({"model": m, **payload}) if provider == "ollama" else _err("unsupported provider")
        ok.append(res)
    return _ok(provider=provider, results=ok)


def _use_default(payload: Mapping[str, Any]):
    # Set environment for OpenAI-compatible clients
    base_url = payload.get("base_url")
    model = payload.get("model")
    api_key = payload.get("api_key")
    provider = payload.get("provider") or "custom"

    if base_url:
        _write_env_var("ADAOS_LLM_BASE_URL", base_url)
    if model:
        _write_env_var("ADAOS_LLM_MODEL", model)
    if provider:
        _write_env_var("ADAOS_LLM_PROVIDER", provider)
    if api_key:
        _write_env_var("ADAOS_LLM_API_KEY", api_key)
    return _ok(base_url=base_url, model=model, provider=provider)


def handle(topic: str, payload: Mapping[str, Any]):
    """
    Topics:
      - llm.model.install: { provider: 'ollama'|'hf', model?: str, repo_id?: str, ... }
      - llm.model.list:    TODO
      - llm.model.use:     { base_url: str, model: str, provider?: str, api_key?: str }
      - llm.model.preset.small: { provider: 'ollama', models?: [..] }
    """
    if topic == "llm.model.install":
        provider = (payload.get("provider") or "").lower()
        if provider == "ollama":
            return _ollama_install(payload)
        if provider in {"hf", "huggingface"}:
            return _hf_install(payload)
        return _err("unsupported provider")

    if topic == "llm.model.use":
        return _use_default(payload)

    if topic == "llm.model.preset.small":
        return _preset_smallset(payload)

    return _err("unknown topic")
