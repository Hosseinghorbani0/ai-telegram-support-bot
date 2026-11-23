
import logging

from openai import OpenAI
from config import OPENAI_API_KEY
from db_client import get_dyn


# -------------------------
# Logging
# -------------------------

logger = logging.getLogger(__name__)


# -------------------------
# Client configuration
# -------------------------

DEFAULT_MODEL = "gpt-4o-mini"

client = OpenAI(
    api_key=OPENAI_API_KEY,
    timeout=60.0,
    max_retries=2,
)


# -------------------------
# Internal helpers
# -------------------------

def _get_model(model=None):
    """Resolve model using explicit override, dynamic config, or default."""
    configured_model = get_dyn("openai_model")

    active_model = (
        model
        or configured_model
        or DEFAULT_MODEL
    )

    if not isinstance(active_model, str):
        return DEFAULT_MODEL

    active_model = active_model.strip()

    return active_model or DEFAULT_MODEL


def _get_persona():
    """Load persona safely from dynamic configuration."""
    persona = get_dyn("default_persona")

    if isinstance(persona, str):
        return persona.strip()

    if isinstance(persona, list):
        return " ".join(
            str(item).strip()
            for item in persona
            if item is not None and str(item).strip()
        )

    return ""


def _prepare_messages(messages, persona):
    """
    Prepare messages without modifying the original list.
    Replace existing system message or insert a new one.
    """
    formatted_messages = []

    if isinstance(messages, list):
        formatted_messages = [
            dict(message)
            for message in messages
            if isinstance(message, dict)
        ]

    system_msg = {
        "role": "system",
        "content": persona
    }

    system_index = next(
        (
            index
            for index, message in enumerate(formatted_messages)
            if message.get("role") == "system"
        ),
        None
    )

    if system_index is not None:
        formatted_messages[system_index] = system_msg
    else:
        formatted_messages.insert(0, system_msg)

    return formatted_messages


def _format_image(img):
    """Normalize image input into an OpenAI-compatible image URL."""
    if not img:
        return None

    img = str(img).strip()

    if not img:
        return None

    # Already formatted Data URL
    if img.startswith("data:image/"):
        return img

    # Raw Base64 image (legacy behavior: JPEG)
    return f"data:image/jpeg;base64,{img}"


# -------------------------
# Main function
# -------------------------

def get_gpt(prompt: str, messages: list, img=None, model: str = None):
    """
    Send a request to OpenAI Chat Completions.

    Args:
        prompt (str): User text prompt.
        messages (list): Conversation history.
        img (str, optional): Base64 image or image Data URL.
        model (str, optional): Model override.

    Returns:
        str: Generated response text.
        False: If the request fails.
    """
    try:
        # Resolve runtime configuration
        active_model = _get_model(model)
        persona = _get_persona()

        # Prepare history without mutating caller's data
        formatted_messages = _prepare_messages(
            messages,
            persona
        )

        # Normalize prompt
        prompt = str(prompt).strip() if prompt else ""

        # Format image if provided
        img_url = _format_image(img)

        # Build user message
        if img_url:
            user_content = [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": img_url
                    }
                }
            ]

            formatted_messages.append({
                "role": "user",
                "content": user_content
            })

        elif prompt:
            formatted_messages.append({
                "role": "user",
                "content": prompt
            })

        # Request completion
        response = client.chat.completions.create(
            model=active_model,
            messages=formatted_messages
        )

        # Safely extract response
        if not response or not response.choices:
            return ""

        content = response.choices[0].message.content

        if not isinstance(content, str):
            return ""

        return content.strip()

    except Exception:
        logger.exception("get_gpt request failed")
        return False
