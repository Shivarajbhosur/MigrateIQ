"""
LLM Service

Generic LLM service for EnsoAI platform.
Supports multiple models: GPT, Claude, Gemini via single API.
Model switchable via .env config.
"""

import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, List

import httpx
import yaml
from loguru import logger
from dotenv import load_dotenv

# Load .env file BEFORE anything else
load_dotenv()


# ---------------------------------------------------------------------------
# Model registry loader
# ---------------------------------------------------------------------------
# All supported models live in prompts/model_registry.yaml. Switching models
# (or adding a new provider) is a YAML edit — no Python changes needed.

_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "prompts" / "model_registry.yaml"


def _load_model_registry() -> Dict[str, Any]:
    """Load `prompts/model_registry.yaml`.

    Returns a dict with keys:
        default_model: str | None
        configs:       {model_id: {format, provider, label}}
        by_provider:   {provider_name: [{id, label, format}, ...]}
    Falls back gracefully (empty registry) if the file is missing/malformed
    so the service still boots and a stack trace surfaces in logs.
    """
    configs: Dict[str, Dict[str, str]] = {}
    by_provider: Dict[str, List[Dict[str, str]]] = {}
    default_model: Optional[str] = None

    try:
        with _REGISTRY_PATH.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        default_model = raw.get("default_model")
        for provider_name, provider_block in (raw.get("providers") or {}).items():
            models = provider_block.get("models") or []
            by_provider[provider_name] = models
            for m in models:
                mid = m.get("id")
                if not mid:
                    continue
                configs[mid] = {
                    "format": m.get("format", "openai"),
                    "provider": provider_name,
                    "label": m.get("label", mid),
                }
    except FileNotFoundError:
        logger.warning(f"Model registry not found at {_REGISTRY_PATH}; using empty registry")
    except Exception as e:  # pragma: no cover — defensive
        logger.error(f"Failed to load model registry ({_REGISTRY_PATH}): {e}")

    return {
        "default_model": default_model,
        "configs": configs,
        "by_provider": by_provider,
    }


_REGISTRY = _load_model_registry()

class LLMService:
    """
    LLM Service for AI-powered analysis via EnsoAI.
    
    EnsoAI provides access to multiple LLMs:
    - GPT-5, GPT-5 Mini, gpt-5.2
    - Azure OpenAI (gpt-4.1)
    - Claude (opus-4-5, sonnet-4-5, haiku-4-5)
    - Google (Gemini)
    - AWS Bedrock
    
    Switch model via `DEFAULT_MODEL` (or legacy `LLM_MODEL`) in .env, or per
    call by passing `model=` to chat/chat_stream/chat_with_tools/call_llm.
    """

    # Supported models — populated from prompts/model_registry.yaml at import
    # time. Kept on the class so external callers can still do
    # `LLMService.MODEL_CONFIGS` (back-compat) and so the future model-picker
    # UI has a single place to read from.
    MODEL_CONFIGS: Dict[str, Dict[str, str]] = _REGISTRY["configs"]
    MODELS_BY_PROVIDER: Dict[str, List[Dict[str, str]]] = _REGISTRY["by_provider"]

    def __init__(self):
        """Initialize LLM Service from .env + model registry."""
        # ── Primary endpoint (EnsoAI unified gateway) ────────────────
        self.api_url = os.getenv("API_URL")
        self.api_key = os.getenv("API_KEY")

        # ── Failover endpoint (Azure OpenAI direct) ──────────────────
        # Used automatically by `_post_with_failover` if the primary call
        # raises a transport / 5xx / timeout error. Optional — if either
        # var is missing, failover is disabled and errors propagate.
        self.fallback_url = os.getenv("ENSO_AI_API_URL")
        self.fallback_key = os.getenv("ENSO_AI_API_KEY")
        self.fallback_model = os.getenv("FALLBACK_MODEL", "gpt-4.1")

        # Default model: env override → registry default → hard fallback.
        self.model = (
            os.getenv("DEFAULT_MODEL")
            or _REGISTRY["default_model"]
            or "gpt-4.1"
        )

        self.model_config = self.MODEL_CONFIGS.get(
            self.model,
            {"format": "openai", "provider": "unknown"},  # safe default
        )

        # Detect Portkey-style unified gateway (auth via x-portkey-api-key,
        # `model` field always required in body).
        self._is_gateway = bool(self.api_url) and "ensoai.ensono.com" in self.api_url

        if not self.api_url:
            logger.warning("API_URL not set in .env")
        if not self.api_key:
            logger.warning("API_KEY not set in .env")
        if self.fallback_url and self.fallback_key:
            logger.info(f"Failover endpoint configured: {self.fallback_url[:60]}…")
        else:
            logger.info("No failover endpoint configured (ENSO_AI_API_URL/KEY)")

        # Default request settings
        self.default_max_tokens = 4096
        self.default_temperature = 0.2
        self.timeout = 120  # seconds

        logger.info(
            f"LLMService initialized: model={self.model}, "
            f"format={self.model_config['format']}, "
            f"gateway={'yes' if self._is_gateway else 'no'}"
        )
    
    def set_model(self, model_name: str) -> None:
        """
        Switch to a different model at runtime.

        Args:
            model_name: Model id as listed in prompts/model_registry.yaml.
        """
        if model_name in self.MODEL_CONFIGS:
            self.model = model_name
            self.model_config = self.MODEL_CONFIGS[model_name]
            logger.info(f"Switched to model: {model_name}")
        else:
            logger.warning(
                f"Unknown model: {model_name}. Using default openai format."
            )
            self.model = model_name
            self.model_config = {"format": "openai", "provider": "unknown"}

    def get_available_models(self) -> List[str]:
        """Get list of supported model ids (flat)."""
        return list(self.MODEL_CONFIGS.keys())

    def get_models_by_provider(self) -> Dict[str, List[Dict[str, str]]]:
        """Return models grouped by provider — handy for a UI selector."""
        return self.MODELS_BY_PROVIDER

    def get_current_model(self) -> str:
        """Get currently active model."""
        return self.model
    
    def _build_headers(self) -> Dict[str, str]:
        """Build request headers based on endpoint + model format."""
        # EnsoAI / Portkey gateway: single auth header for every provider.
        if self._is_gateway:
            return {
                "Content-Type": "application/json",
                "x-portkey-api-key": self.api_key,
            }

        api_format = self.model_config["format"]

        if api_format == "openai":
            # Azure OpenAI / OpenAI direct
            return {
                "Content-Type": "application/json",
                "api-key": self.api_key,
            }

        if api_format == "anthropic":
            return {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            }

        if api_format == "google":
            return {"Content-Type": "application/json"}

        return {
            "Content-Type": "application/json",
            "api-key": self.api_key,
        }
    
    def _token_field(self) -> str:
        """Return the correct max-tokens field name for the active OpenAI model.

        Newer OpenAI models (gpt-5.x, o1, o3, o4) reject ``max_tokens`` and
        require ``max_completion_tokens``. Older ones (gpt-4.x, gpt-3.5)
        require ``max_tokens``. Detect by substring match on the model id
        (works for both bare ids like ``gpt-5.4`` and gateway-prefixed ids
        like ``@openai-foundry-devgateway/gpt-5.4``).
        """
        mid = (self.model or "").lower()
        if any(tag in mid for tag in ("gpt-5", "/o1", "/o3", "/o4", "-o1", "-o3", "-o4")):
            return "max_completion_tokens"
        return "max_tokens"

    def _supports_custom_temperature(self) -> bool:
        """Whether the active model accepts a non-default ``temperature``.

        Several model families now reject any custom temperature and only
        accept the provider default — sending one gets a 400:
          * OpenAI gpt-5.x and reasoning o-series (o1/o3/o4) → "only
            default (1) is supported".
          * AWS Bedrock Anthropic Claude (opus/sonnet/haiku 4.x+) →
            "temperature is deprecated for this model".
        For those families we omit the field entirely and let the
        provider use its own default.
        """
        mid = (self.model or "").lower()
        # OpenAI gpt-5.x / o-series
        if any(tag in mid for tag in ("gpt-5", "/o1", "/o3", "/o4", "-o1", "-o3", "-o4")):
            return False
        # Anthropic Claude via AWS Bedrock gateway (any version)
        if "anthropic" in mid and "claude" in mid:
            return False
        return True

    def _build_payload(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float
    ) -> Dict[str, Any]:
        """Build request payload based on model format."""
        api_format = self.model_config["format"]
        
        if api_format == "openai":
            # OpenAI / Azure OpenAI / EnsoAI-gateway format
            payload: Dict[str, Any] = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                self._token_field(): max_tokens,
            }
            # Newer OpenAI models only accept temperature=1 (the default);
            # omit it entirely for them so the gateway doesn't 400.
            if self._supports_custom_temperature():
                payload["temperature"] = temperature
            # Gateway / non-Azure-direct endpoints need `model` in the body.
            # Azure direct embeds it in the URL and rejects it in the body.
            if self._is_gateway or "/deployments/" not in (self.api_url or ""):
                payload["model"] = self.model
            return payload
        
        elif api_format == "anthropic":
            # Anthropic Claude format
            return {
                "model": self.model,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
        
        elif api_format == "google":
            # Google Gemini format
            combined_prompt = f"{system_prompt}\n\n{user_prompt}"
            return {
                "contents": [
                    {"role": "user", "parts": [{"text": combined_prompt}]}
                ],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature
                }
            }
        
        else:
            # Default to OpenAI format
            return {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
    
    def _parse_response(self, result: Dict[str, Any]) -> str:
        """Parse response based on model format."""
        api_format = self.model_config["format"]
        
        try:
            if api_format == "openai":
                return result["choices"][0]["message"]["content"]
            
            elif api_format == "anthropic":
                return result["content"][0]["text"]
            
            elif api_format == "google":
                return result["candidates"][0]["content"]["parts"][0]["text"]
            
            else:
                # Try OpenAI format as default
                return result["choices"][0]["message"]["content"]
        
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to parse response: {e}")
            logger.debug(f"Raw response: {result}")
            return ""

    # ------------------------------------------------------------------
    # Failover helpers
    # ------------------------------------------------------------------
    # Every outgoing request goes through `_post_with_failover_*`. If the
    # primary endpoint (gateway) raises a transport / 5xx / timeout error,
    # we retry once against the configured Azure-direct fallback.
    # Failover is skipped for 4xx auth / bad-request errors so we don't
    # mask a real bug behind a working backup.

    def _build_fallback_payload_openai(
        self,
        primary_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Reshape an OpenAI-format payload for Azure-direct fallback.

        Azure direct embeds the deployment in the URL and rejects ``model``
        in the body. Also normalises the token-budget field to whatever the
        fallback model expects (``max_tokens`` for gpt-4.1, etc.).
        """
        fb = dict(primary_payload)
        fb.pop("model", None)

        # Translate token-budget field for the fallback model.
        fb_id = (self.fallback_model or "").lower()
        wants_completion = any(
            tag in fb_id for tag in ("gpt-5", "o1", "o3", "o4")
        )
        target_field = "max_completion_tokens" if wants_completion else "max_tokens"
        other_field = "max_tokens" if wants_completion else "max_completion_tokens"
        if other_field in fb and target_field not in fb:
            fb[target_field] = fb.pop(other_field)
        return fb

    def _fallback_headers(self) -> Dict[str, str]:
        """Azure-direct auth header."""
        return {
            "Content-Type": "application/json",
            "api-key": self.fallback_key,
        }

    @staticmethod
    def _is_failover_eligible(exc: Exception) -> bool:
        """Decide whether an error should trigger fallback retry.

        - Network / timeout: yes (transient).
        - 5xx: yes (provider outage).
        - 4xx: no (real client bug — fail loudly).
        """
        if isinstance(exc, (httpx.TimeoutException, httpx.RequestError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code >= 500
        return False

    async def _post_with_failover_async(
        self,
        primary_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Async POST against primary endpoint, with retry to fallback."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.api_url,
                    headers=self._build_headers(),
                    json=primary_payload,
                )
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            if not (self.fallback_url and self.fallback_key) or not self._is_failover_eligible(exc):
                raise
            logger.warning(
                f"Primary endpoint failed ({exc!r}); retrying via fallback."
            )
            fb_payload = self._build_fallback_payload_openai(primary_payload)
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.fallback_url,
                    headers=self._fallback_headers(),
                    json=fb_payload,
                )
                response.raise_for_status()
                return response.json()

    def _post_with_failover_sync(
        self,
        primary_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Sync POST against primary endpoint, with retry to fallback."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.api_url,
                    headers=self._build_headers(),
                    json=primary_payload,
                )
                response.raise_for_status()
                return response.json()
        except Exception as exc:
            if not (self.fallback_url and self.fallback_key) or not self._is_failover_eligible(exc):
                raise
            logger.warning(
                f"Primary endpoint failed ({exc!r}); retrying via fallback."
            )
            fb_payload = self._build_fallback_payload_openai(primary_payload)
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.fallback_url,
                    headers=self._fallback_headers(),
                    json=fb_payload,
                )
                response.raise_for_status()
                return response.json()

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None
    ) -> str:
        """
        Send chat completion request.
        
        Args:
            system_prompt: System prompt (SKILL.md content)
            user_prompt: User prompt (analysis request)
            max_tokens: Maximum response tokens
            temperature: Response randomness (0-1)
            model: Override model for this request only
        
        Returns:
            AI response text
        """
        if not self.api_url or not self.api_key:
            logger.error("EnsoAI API not configured")
            raise ValueError("ENSO_AI_API_URL and ENSO_AI_API_KEY must be set in .env")
        
        # Temporarily switch model if specified
        original_model = None
        if model and model != self.model:
            original_model = self.model
            self.set_model(model)
        
        try:
            # Build request
            payload = self._build_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens or self.default_max_tokens,
                temperature=temperature or self.default_temperature
            )

            logger.info(f"→ LLM call (async)  model={self.model}  prompt={len(user_prompt)} chars")

            result = await self._post_with_failover_async(payload)
            content = self._parse_response(result)

            logger.debug(f"Response ({self.model}): {len(content)} chars")
            return content
        
        except httpx.TimeoutException:
            logger.error(f"EnsoAI API timeout ({self.model})")
            raise TimeoutError("EnsoAI API request timed out")
        
        except httpx.HTTPStatusError as e:
            logger.error(f"EnsoAI API error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"EnsoAI API error: {e.response.status_code}")
        
        except Exception as e:
            logger.error(f"EnsoAI API error: {e}")
            raise
        
        finally:
            # Restore original model if temporarily switched
            if original_model:
                self.set_model(original_model)
    
    def chat_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None
    ) -> str:
        """
        Synchronous version of chat.
        
        Args:
            system_prompt: System prompt
            user_prompt: User prompt
            max_tokens: Maximum response tokens
            temperature: Response randomness
            model: Override model for this request only
        
        Returns:
            AI response text
        """
        if not self.api_url or not self.api_key:
            logger.error("EnsoAI API not configured")
            raise ValueError("ENSO_AI_API_URL and ENSO_AI_API_KEY must be set in .env")
        
        # Temporarily switch model if specified
        original_model = None
        if model and model != self.model:
            original_model = self.model
            self.set_model(model)
        
        try:
            payload = self._build_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens or self.default_max_tokens,
                temperature=temperature or self.default_temperature
            )

            logger.info(f"→ LLM call (sync)   model={self.model}  prompt={len(user_prompt)} chars")

            result = self._post_with_failover_sync(payload)
            content = self._parse_response(result)

            logger.debug(f"Response ({self.model}): {len(content)} chars")
            return content
        
        except httpx.TimeoutException:
            logger.error(f"EnsoAI API timeout ({self.model})")
            raise TimeoutError("EnsoAI API request timed out")
        
        except httpx.HTTPStatusError as e:
            logger.error(f"EnsoAI API error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"EnsoAI API error: {e.response.status_code}")
        
        except Exception as e:
            logger.error(f"EnsoAI API error: {e}")
            raise
        
        finally:
            if original_model:
                self.set_model(original_model)

    # ------------------------------------------------------------------
    # Streaming entry point (ChatGPT/Copilot-style)
    # ------------------------------------------------------------------
    async def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ):
        """Async generator yielding text chunks as they arrive.

        Real SSE streaming for **all supported providers**:

        * **OpenAI / Azure OpenAI** — ``data: {...}\\n`` frames, ended by
          ``data: [DONE]``. Token in ``choices[0].delta.content``.
        * **Anthropic (Claude)** — SSE frames with event types; tokens
          arrive in ``content_block_delta`` events as
          ``delta.text``.
        * **Google (Gemini)** — SSE ``data: {...}`` frames carrying
          ``candidates[0].content.parts[*].text``.

        Safety net: if the upstream gateway does not stream for the
        currently selected provider (e.g. ignores ``"stream": true`` and
        returns a single JSON body), this falls back to the non-streaming
        :meth:`chat` and yields the full response as one chunk so the
        model switch keeps working end-to-end.
        """
        if not self.api_url or not self.api_key:
            logger.error("EnsoAI API not configured")
            raise ValueError("ENSO_AI_API_URL and ENSO_AI_API_KEY must be set in .env")

        original_model = None
        if model and model != self.model:
            original_model = self.model
            self.set_model(model)

        yielded_any = False
        try:
            api_format = self.model_config["format"]
            headers = self._build_headers()
            payload = self._build_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=max_tokens or self.default_max_tokens,
                temperature=temperature if temperature is not None else self.default_temperature,
            )
            # Universal streaming hint — providers that don't honour this
            # field simply return a non-SSE body, which the safety-net
            # fallback below handles transparently.
            payload["stream"] = True

            logger.debug(
                f"Streaming EnsoAI ({self.model}, {api_format}): "
                f"{len(user_prompt)} chars prompt"
            )

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    async with client.stream(
                        "POST", self.api_url, headers=headers, json=payload
                    ) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            for token in self._parse_stream_line(line, api_format):
                                if token:
                                    yielded_any = True
                                    yield token
            except httpx.TimeoutException:
                # Timeouts always propagate — same UX as non-streaming chat().
                logger.error(f"EnsoAI API timeout ({self.model})")
                raise TimeoutError("EnsoAI API request timed out")
            except httpx.HTTPStatusError as e:
                # If we already streamed tokens, surface the error so the
                # caller knows the response was truncated. Otherwise let
                # the non-streaming fallback try.
                if yielded_any:
                    logger.error(
                        f"EnsoAI streaming error mid-response "
                        f"({self.model}): {e.response.status_code} - {e.response.text}"
                    )
                    raise RuntimeError(f"EnsoAI API error: {e.response.status_code}")
                logger.warning(
                    f"EnsoAI streaming HTTP error for {self.model}, "
                    f"will fall back to non-stream: "
                    f"{e.response.status_code}"
                )
            except Exception as e:
                if yielded_any:
                    logger.error(f"EnsoAI streaming error mid-response: {e}")
                    raise
                logger.warning(
                    f"EnsoAI streaming failed for {self.model}, "
                    f"will fall back to non-stream: {e}"
                )

            # Safety net: provider gateway may not actually stream for
            # this model (returns a complete JSON body). Fall back to the
            # non-streaming path so the user still gets a response.
            if not yielded_any:
                logger.info(
                    f"Streaming yielded no tokens for {self.model} — "
                    "falling back to non-streaming chat()."
                )
                text = await self.chat(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if text:
                    yield text
        finally:
            if original_model:
                self.set_model(original_model)

    @staticmethod
    def _parse_stream_line(line: str, api_format: str) -> List[str]:
        """Extract text token(s) from one SSE line for the given format.

        Returns a (possibly empty) list of text fragments. Non-data lines
        (e.g. Anthropic's ``event:`` headers, blank keep-alives, comments)
        return an empty list.
        """
        if not line:
            return []

        # All three providers wrap content frames in ``data: <json>``.
        # Anything else (event:, :, keep-alives) is metadata we skip.
        if not line.startswith("data:"):
            return []

        data = line[5:].strip()
        if not data:
            return []
        # OpenAI marks end-of-stream with ``[DONE]``; other providers
        # signal end via a typed event we already skip.
        if data == "[DONE]":
            return []

        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            return []

        try:
            if api_format == "openai":
                delta = chunk["choices"][0].get("delta") or {}
                token = delta.get("content")
                return [token] if token else []

            if api_format == "anthropic":
                # Only ``content_block_delta`` carries text tokens.
                if chunk.get("type") != "content_block_delta":
                    return []
                delta = chunk.get("delta") or {}
                if delta.get("type") != "text_delta":
                    return []
                token = delta.get("text")
                return [token] if token else []

            if api_format == "google":
                # Gemini streams full ``candidates`` snapshots; each frame
                # may contain one or more text parts.
                parts = (
                    chunk.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [])
                ) or []
                tokens = [p.get("text", "") for p in parts if p.get("text")]
                return tokens
        except (KeyError, IndexError, TypeError):
            return []

        return []

    # ------------------------------------------------------------------
    # Multi-model tool-calling helpers
    # ------------------------------------------------------------------
    # These methods convert between OpenAI function-calling format (used
    # internally by the orchestrator) and each provider's native format.
    # The orchestrator always works with OpenAI-shaped messages and tools;
    # translation happens here at the boundary.

    def _convert_tools_for_format(self, tools: List[Dict[str, Any]]) -> Any:
        """Convert OpenAI-format tool schemas to the current model's format."""
        api_format = self.model_config["format"]

        if api_format == "anthropic":
            return [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
                for t in tools
            ]

        if api_format == "google":
            return [
                {
                    "function_declarations": [
                        {
                            "name": t["function"]["name"],
                            "description": t["function"].get("description", ""),
                            "parameters": t["function"].get(
                                "parameters",
                                {"type": "object", "properties": {}},
                            ),
                        }
                        for t in tools
                    ]
                }
            ]

        # OpenAI / Azure — no conversion needed.
        return tools

    def _convert_messages_for_format(
        self, messages: List[Dict[str, Any]]
    ) -> tuple:
        """Convert OpenAI-format messages to the current model's format.

        Returns ``(system_text, converted_messages)``.
        For OpenAI format ``system_text`` is empty and messages are unchanged.
        """
        api_format = self.model_config["format"]

        if api_format == "anthropic":
            system_text = ""
            converted: List[Dict[str, Any]] = []
            for msg in messages:
                role = msg.get("role", "")
                if role == "system":
                    system_text = msg.get("content", "")
                elif role == "tool":
                    # Anthropic: tool results are user messages with
                    # tool_result content blocks.
                    converted.append(
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": msg.get("tool_call_id", ""),
                                    "content": msg.get("content", ""),
                                }
                            ],
                        }
                    )
                elif role == "assistant" and msg.get("tool_calls"):
                    content: List[Dict[str, Any]] = []
                    if msg.get("content"):
                        content.append({"type": "text", "text": msg["content"]})
                    for tc in msg["tool_calls"]:
                        fn = tc.get("function", {})
                        try:
                            input_data = json.loads(fn.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            input_data = {}
                        content.append(
                            {
                                "type": "tool_use",
                                "id": tc.get("id", ""),
                                "name": fn.get("name", ""),
                                "input": input_data,
                            }
                        )
                    converted.append({"role": "assistant", "content": content})
                else:
                    converted.append(
                        {"role": role, "content": msg.get("content", "")}
                    )
            return system_text, converted

        if api_format == "google":
            system_text = ""
            contents: List[Dict[str, Any]] = []
            # Build tool_call_id → function-name map for tool results.
            tc_name_map: Dict[str, str] = {}
            for msg in messages:
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        tc_name_map[tc.get("id", "")] = (
                            tc.get("function", {}).get("name", "")
                        )
            for msg in messages:
                role = msg.get("role", "")
                if role == "system":
                    system_text = msg.get("content", "")
                elif role == "user":
                    contents.append(
                        {"role": "user", "parts": [{"text": msg.get("content", "")}]}
                    )
                elif role == "assistant":
                    if msg.get("tool_calls"):
                        parts: List[Dict[str, Any]] = []
                        if msg.get("content"):
                            parts.append({"text": msg["content"]})
                        for tc in msg["tool_calls"]:
                            fn = tc.get("function", {})
                            try:
                                args = json.loads(fn.get("arguments", "{}"))
                            except json.JSONDecodeError:
                                args = {}
                            parts.append(
                                {"functionCall": {"name": fn.get("name", ""), "args": args}}
                            )
                        contents.append({"role": "model", "parts": parts})
                    else:
                        contents.append(
                            {"role": "model", "parts": [{"text": msg.get("content", "")}]}
                        )
                elif role == "tool":
                    tc_id = msg.get("tool_call_id", "")
                    fn_name = tc_name_map.get(tc_id, "unknown")
                    contents.append(
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "functionResponse": {
                                        "name": fn_name,
                                        "response": {"content": msg.get("content", "")},
                                    }
                                }
                            ],
                        }
                    )
            return system_text, contents

        # OpenAI / Azure — no conversion.
        return "", messages

    def _normalize_tool_response(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a provider-specific tool response to OpenAI format.

        Always returns ``{"role": "assistant", "content": ...,
        "tool_calls": [...]}`` so the orchestrator works identically
        regardless of which model is active.
        """
        api_format = self.model_config["format"]

        if api_format == "anthropic":
            content_blocks = result.get("content", [])
            text_parts: List[str] = []
            tool_calls: List[Dict[str, Any]] = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": block.get("name", ""),
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        }
                    )
            msg: Dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts) if text_parts else None,
            }
            if tool_calls:
                msg["tool_calls"] = tool_calls
            return msg

        if api_format == "google":
            parts = (
                result.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [])
            )
            text_parts_g: List[str] = []
            tool_calls_g: List[Dict[str, Any]] = []
            for i, part in enumerate(parts):
                if "text" in part:
                    text_parts_g.append(part["text"])
                elif "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls_g.append(
                        {
                            "id": f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": fc.get("name", ""),
                                "arguments": json.dumps(fc.get("args", {})),
                            },
                        }
                    )
            msg_g: Dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts_g) if text_parts_g else None,
            }
            if tool_calls_g:
                msg_g["tool_calls"] = tool_calls_g
            return msg_g

        # OpenAI / Azure — already in the right shape.
        return result["choices"][0]["message"]

    # ------------------------------------------------------------------
    # Tool-calling entry point (model-agnostic)
    # ------------------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a chat completion request with tool/function-calling support.

        Works with **all supported models** (OpenAI/Azure, Claude, Gemini).
        Tools and messages are always supplied in OpenAI format by the
        orchestrator; this method converts them to the active model's
        native format, sends the request, then normalizes the response
        back to OpenAI format so the orchestrator is model-agnostic.

        Args:
            messages: Full conversation in OpenAI format.
            tools: OpenAI-format tool definitions.
            tool_choice: ``"auto"``, ``"none"``, or ``"required"``.
            max_tokens: Maximum response tokens.
            temperature: Response randomness (0-1).
            model: Override model for this request only.

        Returns:
            Normalized assistant message dict (OpenAI format) which may
            contain ``tool_calls`` or plain ``content``.
        """
        if not self.api_url or not self.api_key:
            raise ValueError("ENSO_AI_API_URL and ENSO_AI_API_KEY must be set in .env")

        original_model = None
        if model and model != self.model:
            original_model = self.model
            self.set_model(model)

        try:
            headers = self._build_headers()
            api_format = self.model_config["format"]
            effective_max = max_tokens or self.default_max_tokens
            effective_temp = (
                temperature if temperature is not None else self.default_temperature
            )

            # Convert tools and messages to the active model's format.
            fmt_tools = self._convert_tools_for_format(tools)
            system_text, fmt_messages = self._convert_messages_for_format(messages)

            # ── Build payload per provider ────────────────────────────
            if api_format == "anthropic":
                payload: Dict[str, Any] = {
                    "model": self.model,
                    "system": system_text,
                    "messages": fmt_messages,
                    "max_tokens": effective_max,
                    "temperature": effective_temp,
                    "tools": fmt_tools,
                }
                if tool_choice == "auto":
                    payload["tool_choice"] = {"type": "auto"}
                elif tool_choice == "required":
                    payload["tool_choice"] = {"type": "any"}
                # "none" → omit tool_choice so the model may still respond.

            elif api_format == "google":
                payload = {
                    "contents": fmt_messages,
                    "tools": fmt_tools,
                    "generationConfig": {
                        "maxOutputTokens": effective_max,
                        "temperature": effective_temp,
                    },
                }
                if system_text:
                    payload["system_instruction"] = {
                        "parts": [{"text": system_text}]
                    }

            else:
                # OpenAI / Azure OpenAI / EnsoAI-gateway — native OpenAI format.
                payload = {
                    "messages": fmt_messages,
                    self._token_field(): effective_max,
                }
                if self._supports_custom_temperature():
                    payload["temperature"] = effective_temp
                # Same rule as _build_payload: include `model` for gateway
                # and non-Azure-direct endpoints.
                if self._is_gateway or "/deployments/" not in (self.api_url or ""):
                    payload["model"] = self.model
                if fmt_tools:
                    payload["tools"] = fmt_tools
                    payload["tool_choice"] = tool_choice

            logger.debug(
                f"Calling EnsoAI with tools ({self.model}, {api_format}): "
                f"{len(messages)} messages, {len(tools)} tools"
            )

            # Failover only applies to the OpenAI-format path (the only
            # one the Azure-direct backup speaks). Anthropic/Google native
            # calls go straight through — fallback isn't compatible.
            if api_format == "openai":
                result = await self._post_with_failover_async(payload)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self.api_url, headers=headers, json=payload
                    )
                    response.raise_for_status()
                    result = response.json()

            # Normalize response to OpenAI format for the orchestrator.
            assistant_msg = self._normalize_tool_response(result)
            logger.debug(
                f"Tool response ({self.model}): "
                f"tool_calls={bool(assistant_msg.get('tool_calls'))}, "
                f"content_len={len(assistant_msg.get('content') or '')}"
            )
            return assistant_msg

        except httpx.TimeoutException:
            logger.error(f"EnsoAI API timeout ({self.model})")
            raise TimeoutError("EnsoAI API request timed out")
        except httpx.HTTPStatusError as e:
            logger.error(f"EnsoAI API error: {e.response.status_code} - {e.response.text}")
            raise RuntimeError(f"EnsoAI API error: {e.response.status_code}")
        except Exception as e:
            logger.error(f"EnsoAI chat_with_tools error: {e}")
            raise
        finally:
            if original_model:
                self.set_model(original_model)

    # ------------------------------------------------------------------
    # Convenience wrapper — simplest possible entry point
    # ------------------------------------------------------------------
    async def call_llm(
        self,
        message: str,
        model_override: Optional[str] = None,
        system_prompt: str = "You are a helpful assistant.",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """One-shot LLM call. Uses DEFAULT_MODEL unless `model_override` is set.

        Designed for the future UI model-picker:
            response = await llm.call_llm("Hello", model_override=user_choice)

        For chat history / tool calling use `chat_with_tools` or `chat_stream`.
        """
        return await self.chat(
            system_prompt=system_prompt,
            user_prompt=message,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model_override,
        )

    def call_llm_sync(
        self,
        message: str,
        model_override: Optional[str] = None,
        system_prompt: str = "You are a helpful assistant.",
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Synchronous twin of :meth:`call_llm` for scripts / CLIs."""
        return self.chat_sync(
            system_prompt=system_prompt,
            user_prompt=message,
            max_tokens=max_tokens,
            temperature=temperature,
            model=model_override,
        )


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get singleton instance of LLMService."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service