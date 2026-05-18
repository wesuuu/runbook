"""TD-0082: verify offline + sync routers are gated by features.offline_mode.enabled."""

from fastapi import FastAPI

from app.core.config import FeaturesConfig, OfflineModeFeatureConfig, Settings
from app.main import _register_offline_routers


def _settings(*, offline_enabled: bool) -> Settings:
    return Settings(
        features=FeaturesConfig(
            offline_mode=OfflineModeFeatureConfig(enabled=offline_enabled),
        ),
    )


def _route_paths(app: FastAPI) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def test_offline_routers_absent_when_flag_off():
    app = FastAPI()
    _register_offline_routers(app, _settings(offline_enabled=False))
    paths = _route_paths(app)

    assert "/offline/runs/{run_id}/prefetch" not in paths
    assert "/auth/offline-session" not in paths
    assert "/auth/offline-session/{jti}" not in paths
    assert "/sync/offline-queue/{run_id}" not in paths


def test_offline_routers_present_when_flag_on():
    app = FastAPI()
    _register_offline_routers(app, _settings(offline_enabled=True))
    paths = _route_paths(app)

    assert "/offline/runs/{run_id}/prefetch" in paths
    assert "/auth/offline-session" in paths
    assert "/auth/offline-session/{jti}" in paths
    assert "/sync/offline-queue/{run_id}" in paths
