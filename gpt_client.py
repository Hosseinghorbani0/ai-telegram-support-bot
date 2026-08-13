from openai import OpenAI
from config import OPENAI_API_KEY
from db_client import get_dyn

# Initialize client globally for connection reuse
client = OpenAI(api_key=OPENAI_API_KEY)

# Default model configuration (gpt-4o-mini offers the best balance of cost, speed, and vision support)
DEFAULT_MODEL = "gpt-4o-mini"

def get_gpt(prompt: str, messages: list, img=None, model: str = None):
    """
    Sends request to OpenAI Chat Completion model.
    Prevents modifying caller's message list and handles error edge-cases.
    """
    try:
        formatted_messages = list(messages) if messages else []

        # Allow dynamic override or fallback to default cost-effective model
        active_model = model or get_dyn('openai_model') or DEFAULT_MODEL

        # Fetch persona safely without breaking on non-list returns
        persona = get_dyn('default_persona')
        if isinstance(persona, list):
            persona_content = " ".join(persona)
        elif isinstance(persona, str):
            persona_content = persona
        else:
            persona_content = ""

        system_msg = {"role": "system", "content": persona_content}

        if formatted_messages:
            # Replace existing system message or override the first message
            formatted_messages[0] = system_msg
        else:
            formatted_messages.append(system_msg)

        if img:
            img_url = img if str(img).startswith("data:image") else f"data:image/jpeg;base64,{img}"
            formatted_messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": str(prompt or "")},
                    {"type": "image_url", "image_url": {"url": img_url}}
                ]
            })
        elif prompt:
            formatted_messages.append({"role": "user", "content": str(prompt)})

        response = client.chat.completions.create(
            model=active_model,
            messages=formatted_messages,
        )

        # Extract and return response content
        if response.choices and response.choices[0].message.content:
            return response.choices[0].message.content.strip()
        return ""

    except Exception as e:
        print(f"[get_gpt Error]: {e}")
        return False
