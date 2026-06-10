import pytest

from .conftest import make_key

pytestmark = pytest.mark.django_db


def test_rate_limit_returns_429_with_envelope(
    api, fake_vm, owned_container, monkeypatch
):
    # Drop the per-key budget to 2/min so the third call trips it. The rate is a
    # class attribute read in SimpleRateThrottle.__init__, so patching it here
    # changes the limit for the throttle instances built per request.
    monkeypatch.setattr("platform_api.throttling.APIKeyRateThrottle.rate", "2/min")

    user, _ct, c = owned_container
    client = api(make_key(user))
    url = f"/api/v1/containers/{c.pk}/ports/"

    assert client.get(url).status_code == 200
    assert client.get(url).status_code == 200
    blocked = client.get(url)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


def test_rate_limit_is_per_key(api, fake_vm, owned_container, monkeypatch):
    """One key burning its budget must not throttle another key."""
    monkeypatch.setattr("platform_api.throttling.APIKeyRateThrottle.rate", "1/min")

    user, _ct, c = owned_container
    url = f"/api/v1/containers/{c.pk}/ports/"

    first = api(make_key(user, name="k1"))
    assert first.get(url).status_code == 200
    assert first.get(url).status_code == 429  # k1 exhausted

    second = api(make_key(user, name="k2"))
    assert second.get(url).status_code == 200  # k2 has its own budget
