import json
from redis.asyncio import Redis
from app.core.redis_client import get_redis_client
from app.integrations.llm_client import generate_completion_json
from app.core.logging import logger
from app.core.config import settings

class ThreadSummaryService:
    def __init__(self, redis_client: Redis | None = None) -> None:
        # Accept an explicit client (e.g. a fresh per-task client from the
        # Celery worker) or fall back to the shared singleton for FastAPI routes.
        self.redis = redis_client if redis_client is not None else get_redis_client()

    def _get_key(self, thread_id: str) -> str:
        return f"thread:summary:{thread_id}"

    async def get_summary(self, thread_id: str) -> str | None:
        """Reads the current thread summary string from Redis."""
        key = self._get_key(thread_id)
        try:
            summary = await self.redis.get(key)
            return summary
        except Exception as e:
            logger.error("Failed to read thread summary from Redis", thread_id=thread_id, error=str(e))
            # Fallback path: return None and proceed without summary history
            return None

    async def update_summary(self, thread_id: str, new_body: str) -> str:
        """
        Creates or updates a rolling summary of the email thread:
        1. Reads the previous summary from Redis.
        2. Prompts the frontier LLM to merge the previous summary and the new message.
        3. Saves the updated summary back to Redis with a 7-day expiration (604800 seconds).
        4. Returns the updated summary text.
        """
        key = self._get_key(thread_id)
        previous_summary = await self.get_summary(thread_id)
        
        system_prompt = (
            "You are an assistant summarizing customer support email threads. "
            "Your output must be a valid JSON object containing a single key \"summary\". "
            "The summary must be a concise, professional running summary of the thread's history and active issue, "
            "summarizing no more than 3-4 sentences. Do not include signature blocks or greetings in the summary."
        )
        
        # Normalize previous summary checks to ignore literal "None", "null", or empty strings
        has_previous = (
            previous_summary is not None 
            and previous_summary.strip() != "" 
            and previous_summary.strip().lower() not in ("none", "null")
        )

        if has_previous:
            user_prompt = (
                f"Previous Thread Summary: {previous_summary.strip()}\n\n"
                f"New Incoming Message: {new_body}\n\n"
                "Please generate the updated thread summary incorporating the new message."
            )
        else:
            user_prompt = (
                f"Incoming Message: {new_body}\n\n"
                "Please generate the initial thread summary for this message."
            )

        raw_json_str = ""
        try:
            # Call OpenRouter LLM to summarize
            raw_json = await generate_completion_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=300,
                temperature=0.1
            )
            raw_json_str = raw_json
            
            from app.utils.json_cleaner import clean_json_markdown
            cleaned_json = clean_json_markdown(raw_json)
            
            data = json.loads(cleaned_json)
            updated_summary = data.get("summary", "").strip()
            
            if not updated_summary:
                raise ValueError("LLM response did not contain a valid 'summary' key.")

            # Save the new summary to Redis (expiration: 7 days)
            await self.redis.set(key, updated_summary, ex=settings.THREAD_SUMMARY_TTL_SECONDS)
            logger.info("Updated thread summary in Redis", thread_id=thread_id)
            return updated_summary

        except Exception as e:
            logger.error(
                "Failed to generate or cache rolling thread summary",
                thread_id=thread_id,
                error=str(e),
                raw_response=raw_json_str
            )
            # Fallback path: generate a simple summary from the first 150 characters of the body
            fallback = f"Summary unavailable. Recent content: {new_body[:150]}..."
            try:
                await self.redis.set(key, fallback, ex=settings.THREAD_SUMMARY_TTL_SECONDS)
            except Exception:
                pass
            return fallback
