import pytest
from asgiref.sync import async_to_sync

# We import the module as packaged in this codebase
import pequeroku.redis as redis_mod


class FakeRedisAsyncClient:
    def __init__(self):
        # Store integer counters per key
        self._data = {}

    async def get(self, key):
        if key in self._data:
            # redis with decode_responses returns strings for get
            return str(self._data[key])
        return None

    async def incr(self, key):
        self._data[key] = int(self._data.get(key, 0)) + 1
        # incr returns integer
        return self._data[key]

    async def delete(self, key):
        if key in self._data:
            del self._data[key]
            return 1
        return 0


@pytest.fixture
def fake_redis(monkeypatch, settings):
    # Ensure a deterministic prefix during tests
    settings.REDIS_PREFIX = "testprefix"
    fake = FakeRedisAsyncClient()
    # Patch the cached client to our fake so _get_client() returns it
    monkeypatch.setattr(redis_mod, "_client", fake)
    return fake


def test_get_rev_defaults_to_zero(fake_redis):
    val = async_to_sync(redis_mod.VersionStore.get_rev)("c1", "/app/file.txt")
    assert val == 0


def test_bump_rev_increments_and_persists(fake_redis):
    v1 = async_to_sync(redis_mod.VersionStore.bump_rev)("c1", "/app/file.txt")
    assert v1 == 1

    v2 = async_to_sync(redis_mod.VersionStore.bump_rev)("c1", "/app/file.txt")
    assert v2 == 2

    # Ensure get_rev reflects the last value
    vget = async_to_sync(redis_mod.VersionStore.get_rev)("c1", "/app/file.txt")
    assert vget == 2


def test_reset_path_deletes_key(fake_redis):
    # Bump once, then reset, then get should be 0
    async_to_sync(redis_mod.VersionStore.bump_rev)("c1", "/app/file.txt")
    async_to_sync(redis_mod.VersionStore.reset_path)("c1", "/app/file.txt")
    v = async_to_sync(redis_mod.VersionStore.get_rev)("c1", "/app/file.txt")
    assert v == 0


def test_independent_counters_by_cid_and_path(fake_redis):
    # Bump different cid/path combinations and verify independence
    v_a1 = async_to_sync(redis_mod.VersionStore.bump_rev)("c1", "/a")
    v_b1 = async_to_sync(redis_mod.VersionStore.bump_rev)("c2", "/a")
    v_a2 = async_to_sync(redis_mod.VersionStore.bump_rev)("c1", "/b")

    assert v_a1 == 1
    assert v_b1 == 1
    assert v_a2 == 1

    # Further increments on one key should not affect the others
    v_a1_again = async_to_sync(redis_mod.VersionStore.bump_rev)("c1", "/a")
    assert v_a1_again == 2

    get_a = async_to_sync(redis_mod.VersionStore.get_rev)("c1", "/a")
    get_b = async_to_sync(redis_mod.VersionStore.get_rev)("c2", "/a")
    get_c = async_to_sync(redis_mod.VersionStore.get_rev)("c1", "/b")

    assert get_a == 2
    assert get_b == 1
    assert get_c == 1
