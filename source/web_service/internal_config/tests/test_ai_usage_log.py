import pytest

from internal_config.models import AIUsageLog, Config
from vm_manager.test_utils import create_user, create_container

pytestmark = pytest.mark.django_db


def _set_pricing(input_price: str, output_price: str) -> None:
    # update_or_create: the post_migrate seeder already inserts default pricing.
    Config.objects.update_or_create(
        name="token_input_price", defaults={"value": input_price}
    )
    Config.objects.update_or_create(
        name="token_output_price", defaults={"value": output_price}
    )


def test_get_request_price_charges_prompt_and_completion():
    _set_pricing("0.001", "0.002")
    log = AIUsageLog(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    price = log.get_request_price()
    assert price["cost_input"] == pytest.approx(100 * 0.001)
    assert price["cost_output"] == pytest.approx(50 * 0.002)
    assert price["total_cost"] == pytest.approx(0.1 + 0.1)


def test_get_request_price_bills_surplus_total_tokens_at_output_rate():
    # The provider reports more total than prompt+completion (e.g. reasoning
    # tokens folded only into the aggregate). The surplus must be billed.
    _set_pricing("0.001", "0.002")
    log = AIUsageLog(prompt_tokens=100, completion_tokens=50, total_tokens=200)
    price = log.get_request_price()
    # 50 completion + 50 surplus = 100 tokens at the output rate.
    assert price["cost_output"] == pytest.approx(100 * 0.002)
    assert price["cost_input"] == pytest.approx(100 * 0.001)


def test_get_request_price_total_below_parts_never_reduces_cost():
    _set_pricing("0.001", "0.002")
    log = AIUsageLog(prompt_tokens=100, completion_tokens=50, total_tokens=0)
    price = log.get_request_price()
    assert price["cost_output"] == pytest.approx(50 * 0.002)
    assert price["cost_input"] == pytest.approx(100 * 0.001)


def test_deleting_container_keeps_usage_logs_and_does_not_reset_quota():
    # Regression: deleting a container must NOT cascade-delete the user's usage
    # logs, otherwise the daily AI-use counter resets (a quota-reset exploit).
    user = create_user("alice")
    container = create_container(user=user, container_id="vm-del-hack")
    quota = user.quota

    AIUsageLog.objects.create(user=user, container=container, total_tokens=2)
    AIUsageLog.objects.create(user=user, container=container, total_tokens=2)
    assert user.ai_usage_logs.count() == 2
    uses_left_before = quota.ai_uses_left_today()

    container.delete()

    # Logs survive with container nulled; the daily counter is unchanged.
    assert AIUsageLog.objects.filter(user=user).count() == 2
    assert AIUsageLog.objects.filter(user=user, container__isnull=True).count() == 2
    assert quota.ai_uses_left_today() == uses_left_before
