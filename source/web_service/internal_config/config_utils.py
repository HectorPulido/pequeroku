from .models import Config


def get_config_value(key: str, default: str | None = None):
    """
    Get a configuration value from the database or return a default value.
    """
    value: Config | None = None
    try:
        value = Config.objects.get(name=key)
    except Config.DoesNotExist:
        return default

    if not value.value:
        return default

    return value.value


def get_config_values(keys: list[str]) -> dict[str, str]:
    """
    Get multiple configuration values from the database.
    """
    responses: dict[str, str] = {}

    values = Config.objects.filter(name__in=keys)
    for i in values:
        responses[i.name] = i.value
    return responses
