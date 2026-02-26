from __future__ import annotations

from pathlib import Path


def test_prod_compose_uses_prebuilt_images_and_no_build_context() -> None:
    prod_compose = Path(__file__).resolve().parents[2] / "infra" / "docker-compose.prod.yml"
    text = prod_compose.read_text()

    assert "ONCOAI_BACKEND_IMAGE" in text
    assert "ONCOAI_FRONTEND_IMAGE" in text
    assert "build:" not in text
    assert "oncoai_data:" in text
    assert "qdrant_data:" in text


def test_ci_workflow_publishes_to_registry_with_digest_output() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "build-and-publish-images.yml"
    text = workflow.read_text()

    assert "docker/build-push-action" in text
    assert "ghcr.io" in text
    assert "digest" in text
    assert "upload-artifact" in text


def test_deploy_workflow_exists_with_manual_approval_and_ssh() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-prod-ssh.yml"
    text = workflow.read_text()

    assert "workflow_dispatch" in text
    assert "environment: production" in text
    assert "ssh" in text.lower()
    assert "ONCOAI_BACKEND_IMAGE" in text
    assert "ONCOAI_FRONTEND_IMAGE" in text


def test_auto_deploy_workflow_uses_latest_release_artifact() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy-prod-from-latest.yml"
    text = workflow.read_text()

    assert "workflow_dispatch" in text
    assert "environment: production" in text
    assert "build-and-publish-images.yml" in text
    assert "download-artifact" in text
    assert "release-images" in text
    assert "ONCOAI_BACKEND_IMAGE" in text
    assert "ONCOAI_FRONTEND_IMAGE" in text
