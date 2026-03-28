from openai import OpenAI

from app.config import get_openai_settings
from app.core.errors import ServiceError
from app.core.prompt_builder import build_prompt


def generate_sql(
    user_query: str,
    schema_text: str,
    fk_text: str = "",
    database_name: str = "",
) -> str:
    if not user_query.strip():
        raise ServiceError("message is required")
    if not schema_text.strip():
        raise ServiceError("schema context is required")

    api_key, model = get_openai_settings()
    if not api_key:
        raise ServiceError("OPENAI_API_KEY is missing")

    if not fk_text:
        fk_text = "No foreign key relationships provided."

    system_content, user_prompt = build_prompt(
        user_query=user_query,
        schema_text=schema_text,
        fk_text=fk_text,
        database_name=database_name,
    )

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
    )

    sql = (response.choices[0].message.content or "").replace("```sql", "").replace("```", "").strip()
    if not sql:
        raise ServiceError("Model returned empty SQL")
    return sql
