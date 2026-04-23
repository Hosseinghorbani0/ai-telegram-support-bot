from openai import OpenAI

from config import OPENAI_API_KEY
from db_client import get_dyn

client = OpenAI(api_key=OPENAI_API_KEY)

def get_gpt(prompt: str, messages: list, img):
    default_persona_content = " ".join(get_dyn('default_persona'))
    default_persona_dic = {"role": "system", "content": default_persona_content}

    messages.pop(0)
    messages.insert(0, default_persona_dic)
    if img:
        img_str = f"data:image/jpeg;base64,{img}"
        messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": img_str}}
                ],
            })
    else:
        messages.append({"role": "user", "content": prompt})
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
    )
    return response.choices[0].message.content.strip()

