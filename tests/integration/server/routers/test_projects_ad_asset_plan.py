"""Tests for the ad asset-plan confirmation endpoint."""

from tests.integration.server.routers.projects_router_support import (
    _FakePM,
    build_projects_client,
)


class TestAdAssetPlanConfirm:
    def test_rejects_confirmation_with_no_assets_registered(self, tmp_path, monkeypatch):
        fake_pm = _FakePM(tmp_path)
        client = build_projects_client(monkeypatch, fake_pm)
        with client:
            response = client.post("/api/v1/projects/ad-ready/ad-asset-plan/confirm", json={})
            assert response.status_code == 400
            assert "workflow" not in fake_pm.project_data["ad-ready"]

    def test_confirms_with_no_additional_assets_flag(self, tmp_path, monkeypatch):
        fake_pm = _FakePM(tmp_path)
        client = build_projects_client(monkeypatch, fake_pm)
        with client:
            response = client.post(
                "/api/v1/projects/ad-ready/ad-asset-plan/confirm",
                json={"no_additional_assets": True},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["no_additional_assets"] is True
            assert body["counts"] == {"characters": 0, "scenes": 0, "props": 0}
            marker = fake_pm.project_data["ad-ready"]["workflow"]["ad_asset_plan"]
            assert marker["confirmed"] is True
            assert marker["no_additional_assets"] is True

    def test_confirms_when_a_character_is_already_registered(self, tmp_path, monkeypatch):
        fake_pm = _FakePM(tmp_path)
        fake_pm.project_data["ad-ready"]["characters"] = {"厨师": {"description": "后厨掌勺", "character_sheet": ""}}
        client = build_projects_client(monkeypatch, fake_pm)
        with client:
            response = client.post("/api/v1/projects/ad-ready/ad-asset-plan/confirm", json={})
            assert response.status_code == 200
            body = response.json()
            assert body["no_additional_assets"] is False
            assert body["counts"]["characters"] == 1

    def test_rejects_for_non_ad_project(self, tmp_path, monkeypatch):
        fake_pm = _FakePM(tmp_path)
        client = build_projects_client(monkeypatch, fake_pm)
        with client:
            response = client.post(
                "/api/v1/projects/ready/ad-asset-plan/confirm",
                json={"no_additional_assets": True},
            )
            assert response.status_code == 400
