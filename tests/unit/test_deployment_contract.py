from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_source_image_bundles_python_service_and_exact_workflow_checker() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert ".crystra-inputs/contracts/workflow-dsl-2-candidate" in dockerfile
    assert "COPY pyproject.toml uv.lock README.md" in dockerfile
    assert 'CMD ["python", "-m", "crystra_evolution"]' in dockerfile
    assert "EXPOSE 8000" in dockerfile


def test_runtime_dependencies_have_no_database_driver() -> None:
    project = (ROOT / "pyproject.toml").read_text().lower()

    for forbidden in ("psycopg", "asyncpg", "sqlalchemy"):
        assert forbidden not in project


def test_release_image_has_exact_bases_identity_and_multi_platform_provenance() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    workflow = (ROOT / ".github" / "workflows" / "release-candidate.yml").read_text()

    assert all(
        line.count("@sha256:") == 1 for line in dockerfile.splitlines() if line.startswith("FROM ")
    )
    assert "org.opencontainers.image.source" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile
    assert "permissions:\n  contents: read\n  packages: write" in workflow
    assert "--platform linux/amd64,linux/arm64" in workflow
    assert "--provenance=mode=max" in workflow
    assert "--sbom=true" in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert 'index("amd64") != null and index("arm64") != null' in workflow
    assert ".config.Labels" not in workflow


def test_release_image_builds_from_exact_component_and_contract() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-candidate.yml").read_text()

    assert "config/development-contract.json" in workflow
    assert "submodules: recursive" not in workflow
    assert "git -C evolution-system rev-parse HEAD" in workflow
    assert 'test "$(git -C evolution-system rev-parse HEAD)" = "$PRODUCT_COMMIT"' in workflow
    assert "--file evolution-system/Dockerfile" in workflow


def test_release_next_request_does_not_confuse_publisher_sha_with_product_commit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-candidate.yml").read_text()

    assert "release/request.json" in workflow
    assert "PRODUCT_COMMIT: ${{ github.sha }}" in workflow
    assert "steps.request.outputs.product_commit" not in workflow
    assert "workflow_dispatch:" not in workflow
    assert "workflow_call:" not in workflow


def test_candidate_persists_exact_qualification_for_later_promotion() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-candidate.yml").read_text()

    assert "release-qualification.json" in workflow
    assert 'gh release create "$CANDIDATE_TAG"' in workflow
    assert "--prerelease" in workflow
    assert "actions/create-github-app-token@" in workflow
    assert "actions/create-github-app-token@v3" in workflow
    assert "client-id: ${{ vars.CRYSTRA_RELEASE_CLIENT_ID }}" in workflow
    assert "app-id:" not in workflow
    assert "docker/setup-buildx-action@v4" in workflow
    assert "docker/setup-buildx-action@v3" not in workflow
    assert '"ociDigest":digest' in workflow
    assert '"platforms":["linux/amd64","linux/arm64"]' in workflow
    assert '"provenance":{"mode":"max","status":"PASS"}' in workflow
    assert "evolution-system/release/validate_image_qualification.py" in workflow
    assert '--provenance "$RUNNER_TEMP/provenance.json"' in workflow
    assert '--image-config "$RUNNER_TEMP/qualified-image-config.json"' in workflow
    assert ".SLSA.buildDefinition" not in workflow


def test_stable_promotion_retags_only_the_exact_qualified_candidate_digest() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release-promote.yml").read_text()

    assert "release-qualification.json" in workflow
    assert "docker buildx build" not in workflow
    assert ":latest" not in workflow
    assert 'CANDIDATE_DIGEST="$(jq -er .ociDigest' in workflow
    assert 'test "$REMOTE_DIGEST" = "$CANDIDATE_DIGEST"' in workflow
    assert ".config.Labels" not in workflow
    assert 'index("amd64") != null and index("arm64") != null' in workflow
    assert "--format '{{json .Provenance}}'" in workflow
    assert "docker buildx imagetools create" in workflow
    assert 'test "$STABLE_DIGEST" = "$CANDIDATE_DIGEST"' in workflow
    assert "stable-qualification.json" in workflow
    assert "actions/create-github-app-token@" in workflow
    assert "actions/create-github-app-token@v3" in workflow
    assert "client-id: ${{ vars.CRYSTRA_RELEASE_CLIENT_ID }}" in workflow
    assert "app-id:" not in workflow
    assert "docker/setup-buildx-action@v4" in workflow
    assert "docker/setup-buildx-action@v3" not in workflow
    assert "release-publisher/release/validate_image_qualification.py" in workflow
    assert '--provenance "$RUNNER_TEMP/candidate-provenance.json"' in workflow
    assert '--image-config "$RUNNER_TEMP/candidate-image.json"' in workflow
    assert ".SLSA.buildDefinition" not in workflow


def test_release_workflows_use_explicit_validator_revision() -> None:
    candidate = (ROOT / ".github/workflows/release-candidate.yml").read_text()
    promote = (ROOT / ".github/workflows/release-promote.yml").read_text()
    assert "ref: ${{ github.sha }}" in candidate
    assert "python evolution-system/release/validate_image_qualification.py" in candidate
    assert "release-publisher" not in candidate
    assert "ref: ${{ github.workflow_sha }}" in promote
    assert "python release-publisher/release/validate_image_qualification.py" in promote
    assert 'git rev-parse HEAD)" = "$EXPECTED_COMMIT"' in promote
