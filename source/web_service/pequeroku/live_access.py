"""Current authorization for VM operations that outlive an HTTP request."""

from importlib import import_module

from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user
from django.db import DatabaseError
from django.http import HttpRequest


def vm_accessible(user, vm_pk):
    from vm_manager.models import Container

    if not user.is_authenticated or not user.is_active:
        return False
    containers = Container.objects.exclude(is_pool=True)
    if not user.is_superuser:
        containers = Container.visible_containers_for(user).exclude(is_pool=True)
    return containers.filter(pk=vm_pk).exists()


def current_session_user(session_key, user_id):
    if not session_key or user_id is None:
        return None
    try:
        request = HttpRequest()
        session_store = import_module(settings.SESSION_ENGINE).SessionStore
        request.session = session_store(session_key=session_key)
        user = get_user(request)
        if user.pk == user_id and user.is_active:
            return user
    except DatabaseError:
        pass
    return None


@database_sync_to_async
def session_can_access_vm(session_key, user_id, vm_pk):
    user = current_session_user(session_key, user_id)
    return user is not None and vm_accessible(user, vm_pk)


@database_sync_to_async
def api_key_can_access_vm(key_id, user_id, vm_pk, scope):
    from platform_api.models import APIKey

    key = (
        APIKey.objects.select_related("user")
        .filter(pk=key_id, user_id=user_id, revoked=False)
        .first()
    )
    return key is not None and key.has_scope(scope) and vm_accessible(key.user, vm_pk)
