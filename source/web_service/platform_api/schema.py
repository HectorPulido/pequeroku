"""drf-spectacular glue to keep the IDE schema and the v1 schema separate.

The default ``/api/schema/`` enumerates the whole root urlconf, which now includes
``/api/v1``. This preprocessing hook drops v1 paths from that (IDE) schema. The v1
schema view scopes itself by urlconf AND sets ``PREPROCESSING_HOOKS=[]`` so this
hook does not run there (it would otherwise strip every v1 path).
"""

from __future__ import annotations


def exclude_v1_from_default(endpoints, **kwargs):
    return [ep for ep in endpoints if not ep[0].startswith("/api/v1/")]
