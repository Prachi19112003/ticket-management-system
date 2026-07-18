import asyncio
from openai import AsyncOpenAI, APIConnectionError, APITimeoutError
from app.core.config import settings
from app.core.exceptions import LLMException
from app.core.logging import logger

_client = None

def get_openai_client() -> AsyncOpenAI:
    """Lazily initializes and returns the AsyncOpenAI client configured for OpenRouter."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY
        )
    return _client

async def generate_completion_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 1500,
    temperature: float = 0.2
) -> tuple[str, dict]:
    """
    Submits a system and user prompt to OpenRouter and returns the output string.
    - Enforces JSON output mode using response_format={"type": "json_object"}.
    - Limits retries exclusively to network connection and timeout errors, capped at 2 attempts.
    - Incorporates a 1-second delay doubling on backoff.
    - Raises custom LLMException on final retries or non-retriable failures.
    """
    client = get_openai_client()
    model = settings.OPENROUTER_MODEL
    
    attempts = 0
    max_attempts = 2
    backoff = 1.0

    while attempts < max_attempts:
        attempts += 1
        try:
            logger.info("Submitting completion request to OpenRouter", model=model, attempt=attempts)
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=settings.LLM_TIMEOUT_SECONDS
            )
            
            output = response.choices[0].message.content
            if not output:
                raise LLMException("Received empty response payload from OpenRouter.")
            
            usage = getattr(response, "usage", None)
            usage_dict = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
            }
            
            logger.info("Successfully received completion from OpenRouter", model=model, usage=usage_dict)
            return output, usage_dict

        except (APIConnectionError, APITimeoutError) as e:
            logger.warning(
                "OpenRouter transport or timeout exception occurred",
                attempt=attempts,
                error=str(e)
            )
            if attempts >= max_attempts:
                logger.error("OpenRouter connection retries exhausted.")
                raise LLMException(
                    "Connection timeout or link failure while connecting to OpenRouter.",
                    details={"attempts": attempts, "original_error": str(e)}
                )
            await asyncio.sleep(backoff)
            backoff *= 2.0

        except Exception as e:
            logger.error("OpenRouter request failed with non-retriable error", error=str(e))
            raise LLMException(
                "LLM inference operation encountered an unrecoverable failure.",
                details={"original_error": str(e)}
            )
