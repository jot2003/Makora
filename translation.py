"""Japanese -> Vietnamese translation via Azure OpenAI."""

from openai import AzureOpenAI

SYSTEM_PROMPT = (
    "You are a Japanese-Vietnamese translator for job interviews. "
    "Translate the following Japanese text to Vietnamese. "
    "Output ONLY the Vietnamese translation, nothing else. "
    "Keep the tone natural and appropriate for interview context."
)


class Translator:
    """Translates Japanese text to Vietnamese using Azure OpenAI API."""

    def __init__(self, api_key: str, endpoint: str, deployment: str):
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-12-01-preview",
        )
        self.deployment = deployment

    def translate(self, japanese_text: str) -> str:
        if not japanese_text.strip():
            return ""

        try:
            response = self.client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": japanese_text},
                ],
                max_completion_tokens=500,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"Translation error: {e}")
            return f"[Translation error]"
