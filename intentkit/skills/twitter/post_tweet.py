import logging
from decimal import Decimal

import httpx
from langchain_core.tools import ArgsSchema, ToolException
from pydantic import BaseModel, Field

from intentkit.clients import get_twitter_client
from intentkit.clients.s3 import get_cdn_url
from intentkit.config.config import config
from intentkit.skills.twitter.base import TwitterBaseTool

NAME = "twitter_post_tweet"
PROMPT = "Post a new tweet. To attach an image, use the image parameter instead of adding a link in text."

logger = logging.getLogger(__name__)


class TwitterPostTweetInput(BaseModel):
    """Input for TwitterPostTweet tool."""

    text: str = Field(
        description="Tweet text",
        max_length=25000,
    )
    image: str | None = Field(default=None, description="Image URL to attach")


class TwitterPostTweet(TwitterBaseTool):
    """Post a new tweet to Twitter."""

    name: str = NAME
    description: str = PROMPT
    price: Decimal = Decimal("60")
    args_schema: ArgsSchema | None = TwitterPostTweetInput

    async def _arun(
        self,
        text: str,
        image: str | None = None,
        **kwargs,
    ):
        context = self.get_context()
        try:
            skill_config = context.agent.skill_config(self.category)
            mock_webhook_url = skill_config.get("mock_webhook_url")
            if mock_webhook_url:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(
                        str(mock_webhook_url),
                        json={
                            "agent_id": context.agent_id,
                            "text": text,
                            "image": image,
                        },
                    )
                    response.raise_for_status()
                return (
                    "Tweet captured by mock webhook. "
                    f"Response: {response.text}"
                )

            twitter = get_twitter_client(
                agent_id=context.agent_id,
                config=skill_config,
            )
            # Check rate limit only when not using OAuth
            if not twitter.use_key:
                await self.check_rate_limit(max_requests=24, interval=1440)

            media_ids = []
            image_warning = ""

            # Handle image upload if provided
            if image:
                # Validate image URL - must be from system's S3 CDN
                aws_s3_cdn_url = config.aws_s3_cdn_url
                if aws_s3_cdn_url and image.startswith(aws_s3_cdn_url):
                    # Already a full CDN URL from agent output
                    media_ids = await twitter.upload_media(context.agent_id, image)
                elif aws_s3_cdn_url and not image.startswith("http"):
                    # Relative path - build full CDN URL for upload
                    full_url = get_cdn_url(image)
                    media_ids = await twitter.upload_media(context.agent_id, full_url)
                else:
                    # Image is not from system's S3 CDN, skip upload but warn
                    image_warning = "Warning: The provided image URL is not from the system's S3 CDN and has been ignored. "
                    logger.warning(
                        f"Image URL validation failed for agent {context.agent_id}: {image}"
                    )

            response = await twitter.create_tweet(text=text, media_ids=media_ids)
            if "data" in response and "id" in response["data"]:
                # Return response with warning if image was ignored
                result = (
                    f"{image_warning}Tweet posted successfully. Response: {response}"
                )
                return result
            else:
                logger.error("Error posting tweet: %s", response)
                raise ToolException("Failed to post tweet.")

        except Exception as e:
            logger.error("Error posting tweet: %s", e)
            if isinstance(e, httpx.HTTPStatusError):
                status_code = e.response.status_code if e.response is not None else "?"
                response_text = (
                    e.response.text if e.response is not None else "<no response body>"
                )
                raise ToolException(
                    f"[agent:{context.agent_id}]: "
                    f"Twitter API returned HTTP {status_code}: {response_text}"
                ) from e
            raise ToolException(f"[agent:{context.agent_id}]: {e}") from e
