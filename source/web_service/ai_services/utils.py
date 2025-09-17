from openai import OpenAI


def _get_openai_client(open_ai_data: dict) -> OpenAI:
    """
    Get OpenAI data using the OpenAI API.
    """

    api_key = open_ai_data.get("openai_api_key")
    if not api_key:
        raise ValueError("API key is not set in the configuration.")

    openai_api_url = open_ai_data.get("openai_api_url", "https://api.openai.com/v1")

    return OpenAI(
        api_key=api_key,
        base_url=openai_api_url,
    )
