"""
Universal LLM Client using LiteLLM.

Provides a unified interface for 400+ LLMs with built-in rate limiting,
exponential backoff, and daily budget tracking.

Supports intelligent fallback across multiple LLM providers:
1. Gemini (primary)
2. OpenAI (fallback)
3. Groq (secondary fallback)

Usage:
    from llm_client import primary_client

    response = primary_client.generate_content(
        prompt="Hello!",
        system_prompt="You are a helpful assistant.",
        temperature=0.2,
        response_format=MyPydanticModel  # Optional structured output
    )
"""

import os
import time
import random
import logging
import threading
from typing import Optional, Any, Type, List

import litellm
from pydantic import BaseModel

import config

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging unless DEBUG is set
litellm.suppress_debug_info = True
if os.environ.get("LLM_DEBUG", "").lower() == "true":
    litellm.set_verbose = True


PROVIDER_ENV_VARS = {
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _provider_for_model(model: str) -> str:
    """Return a normalized provider name from a LiteLLM model string."""
    if "/" in model:
        provider = model.split("/", 1)[0].lower()
    elif model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3") or model.startswith("o4"):
        provider = "openai"
    elif model.startswith("gemini"):
        provider = "gemini"
    else:
        provider = model.lower()

    return "gemini" if provider == "google" else provider


def _configured_key_for_provider(provider: str) -> Optional[str]:
    provider = "gemini" if provider == "google" else provider
    config_key_map = {
        "gemini": getattr(config, "GEMINI_API_KEY", None),
        "openai": getattr(config, "OPENAI_API_KEY", None),
        "anthropic": getattr(config, "ANTHROPIC_API_KEY", None),
        "groq": getattr(config, "GROQ_API_KEY", None),
    }
    key = config_key_map.get(provider) or os.environ.get(PROVIDER_ENV_VARS.get(provider, ""))
    return key.strip() if key else None


def _looks_like_key_for_provider(provider: str, api_key: Optional[str]) -> bool:
    """Reject obvious provider/key mismatches before LiteLLM makes a slow failing call."""
    if not api_key:
        return False

    api_key = api_key.strip()
    provider = "gemini" if provider == "google" else provider
    if provider == "gemini":
        return api_key.startswith("AIza")
    if provider == "openai":
        return api_key.startswith("sk-")
    if provider == "anthropic":
        return api_key.startswith("sk-ant-")
    if provider == "groq":
        return api_key.startswith("gsk_")
    return True


class RateLimiter:
    """Token-bucket rate limiter for requests per minute."""

    def __init__(self, max_rpm: int):
        self.max_rpm = max_rpm
        self.tokens = max_rpm
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        """Block until a request token is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_refill
                # Refill tokens based on elapsed time
                refill = elapsed * (self.max_rpm / 60.0)
                self.tokens = min(self.max_rpm, self.tokens + refill)
                self.last_refill = now

                if self.tokens >= 1:
                    self.tokens -= 1
                    return

            # Wait a bit before retrying
            time.sleep(0.5)


class LLMClient:
    """
    Universal LLM client powered by LiteLLM with intelligent fallback.

    Wraps litellm.completion() with rate limiting, exponential backoff,
    daily budget tracking, and intelligent fallback across multiple providers:
    - Primary: Gemini
    - Fallback 1: OpenAI
    - Fallback 2: Groq
    """

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        max_rpm: int = 10,
        max_retries: int = 3,
        retry_base_delay: int = 10,
        daily_budget: int = 0,
        request_delay: float = 0,
        fallback_models: Optional[List[str]] = None,
    ):
        """
        Initialize the LLM client.

        Args:
            model: Primary LiteLLM model string (e.g., "gemini/gemini-2.5-flash-lite")
            api_key: API key for the provider (auto-detected from env if not set)
            max_rpm: Maximum requests per minute
            max_retries: Max retries on rate-limit errors
            retry_base_delay: Base delay in seconds for exponential backoff
            daily_budget: Max requests per day (0 = unlimited)
            request_delay: Fixed delay between requests in seconds
            fallback_models: List of fallback models in priority order
        """
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.daily_budget = daily_budget
        self.request_delay = request_delay
        self.rate_limiter = RateLimiter(max_rpm)
        self.fallback_models = fallback_models or []

        # Daily budget tracking
        self._daily_count = 0
        self._daily_reset_time = time.time()

        # Set primary provider API key in environment if provided (LiteLLM reads from env).
        if api_key:
            self._set_api_key_env(api_key.strip())

    def _set_api_key_env(self, api_key: str):
        """Set the appropriate environment variable based on the model provider."""
        provider = _provider_for_model(self.model)
        env_var = PROVIDER_ENV_VARS.get(provider)
        if env_var and _looks_like_key_for_provider(provider, api_key) and not os.environ.get(env_var):
            os.environ[env_var] = api_key

    def _api_key_for_model(self, model: str) -> Optional[str]:
        """Return a validated API key for the model's provider, if configured."""
        provider = _provider_for_model(model)
        key = _configured_key_for_provider(provider)

        # Use the optional generic key only for the primary model's provider.
        if not key and model == self.model and self.api_key:
            key = self.api_key

        key = key.strip() if key else None
        if not _looks_like_key_for_provider(provider, key):
            return None
        return key

    def _check_daily_budget(self):
        """Check if daily request budget is exceeded. Resets at midnight."""
        if self.daily_budget <= 0:
            return  # Unlimited

        # Reset counter if 24 hours have passed
        if time.time() - self._daily_reset_time > 86400:
            self._daily_count = 0
            self._daily_reset_time = time.time()

        if self._daily_count >= self.daily_budget:
            raise RuntimeError(
                f"Daily LLM request budget exceeded ({self.daily_budget} requests). "
                f"Increase LLM_DAILY_REQUEST_BUDGET or wait for reset."
            )

    def _get_model_pool(self) -> List[str]:
        """
        Get the model pool for fallback strategy.
        
        Returns a list of models in priority order:
        1. Primary model
        2. Fallback models (if configured)
        """
        return [self.model] + self.fallback_models

    def generate_content(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 1,
        response_format: Optional[Type[BaseModel]] = None,
        model_override: Optional[str] = None,
    ) -> str:
        """
        Generate content using the configured LLM with intelligent fallback.

        Args:
            prompt: The user prompt/message
            system_prompt: Optional system instruction
            temperature: Temperature for generation (0.0-1.0)
            response_format: Optional Pydantic model for structured JSON output
            model_override: Override the default model for this call

        Returns:
            The generated text content as a string

        Raises:
            RuntimeError: If daily budget is exceeded
            Exception: If all retries are exhausted
        """
        self._check_daily_budget()

        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Build base kwargs for litellm.completion
        base_kwargs = {
            "messages": messages,
            "temperature": temperature,
        }

        # Add structured output (Pydantic model)
        if response_format is not None:
            base_kwargs["response_format"] = response_format

        # Get model pool (primary + fallbacks)
        requested_pool = [model_override] if model_override else self._get_model_pool()
        model_pool = []
        skipped_models = []
        for model in requested_pool:
            if self._api_key_for_model(model):
                model_pool.append(model)
            else:
                skipped_models.append(model)

        if skipped_models:
            logger.warning(
                "Skipping LLM model(s) with missing or invalid provider API key: %s",
                ", ".join(skipped_models),
            )

        if not model_pool:
            raise RuntimeError(
                "No LLM models have a valid provider API key. Configure GEMINI_API_KEY, "
                "OPENAI_API_KEY, ANTHROPIC_API_KEY, or GROQ_API_KEY for the models in "
                "LLM_MODEL/LLM_FALLBACK_MODELS."
            )

        pool_index = 0
        
        # Calculate max attempts to cover all models in pool with retries
        max_attempts = len(model_pool) + self.max_retries

        last_exception = None

        for attempt in range(max_attempts):
            try:
                # Rate limiting
                self.rate_limiter.acquire()

                # Fixed inter-request delay (only on first attempt)
                if self.request_delay > 0 and attempt == 0:
                    time.sleep(self.request_delay)
                    
                # Get current model from pool
                current_model = model_pool[pool_index % len(model_pool)]
                kwargs = base_kwargs.copy()
                kwargs["model"] = current_model
                kwargs["api_key"] = self._api_key_for_model(current_model)

                logger.debug(f"LLM request attempt {attempt + 1}/{max_attempts} to {current_model}")
                response = litellm.completion(**kwargs)

                # Track daily usage
                self._daily_count += 1

                # Extract text from response
                content = response.choices[0].message.content
                if content:
                    logger.info(f"LLM request successful using model: {current_model}")
                    return content.strip()
                else:
                    logger.warning("LLM returned empty content")
                    return ""

            except Exception as e:
                last_exception = e
                error_str = str(e).lower()

                # Check if it's a rate limit / quota error
                is_rate_limit = any(keyword in error_str for keyword in [
                    "429", "rate_limit", "rate limit", "resource_exhausted",
                    "quota", "too many requests", "retry"
                ])

                current_model = model_pool[pool_index % len(model_pool)]

                if attempt < max_attempts - 1:
                    if is_rate_limit:
                        # Try next model in fallback pool
                        next_model_index = (pool_index + 1) % len(model_pool)
                        next_model = model_pool[next_model_index]
                        
                        delay = random.uniform(1, 4) if next_model_index != 0 else random.uniform(2, 8)
                        logger.warning(
                            f"Rate limit/quota hit for {current_model}. "
                            f"Falling back to {next_model}... "
                            f"(attempt {attempt + 1}/{max_attempts}). Retrying in {delay:.1f}s. Error: {e}"
                        )
                        pool_index = next_model_index
                    else:
                        # Non-rate-limit error — try next model in fallback pool
                        next_model_index = (pool_index + 1) % len(model_pool)
                        next_model = model_pool[next_model_index]
                        
                        # Exponential backoff with jitter
                        delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 5)
                        logger.warning(
                            f"LLM API error on {current_model} (attempt {attempt + 1}/{max_attempts}). "
                            f"Falling back to {next_model}. Retrying in {delay:.1f}s... Error: {e}"
                        )
                        pool_index = next_model_index
                    
                    time.sleep(delay)
                    continue

        # All retries exhausted with all models
        failed_model = model_pool[pool_index % len(model_pool)]
        logger.error(
            f"All {max_attempts} attempts exhausted across models {model_pool}. "
            f"Last failed model: {failed_model}. Last error: {last_exception}"
        )
        raise last_exception


def _create_client(
    model: str,
    api_key: Optional[str] = None,
    fallback_models: Optional[List[str]] = None,
) -> LLMClient:
    """Create an LLMClient instance with config-based defaults."""
    return LLMClient(
        model=model,
        api_key=api_key,
        max_rpm=config.LLM_MAX_RPM,
        max_retries=config.LLM_MAX_RETRIES,
        retry_base_delay=config.LLM_RETRY_BASE_DELAY,
        daily_budget=config.LLM_DAILY_REQUEST_BUDGET,
        request_delay=config.LLM_REQUEST_DELAY_SECONDS,
        fallback_models=fallback_models or config.LLM_FALLBACK_MODELS,
    )


# --- Global Client Instances ---

# Primary client (used by score_jobs, resume_parser, custom_resume_generator)
# Uses configured fallback strategy: Gemini → OpenAI → Groq
primary_client = _create_client(
    model=config.LLM_MODEL,
    api_key=config.LLM_API_KEY,
    fallback_models=config.LLM_FALLBACK_MODELS,
)
