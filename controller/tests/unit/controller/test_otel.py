import pytest
from opentelemetry.sdk.resources import SERVICE_NAME

from controller.otel import resolve_git_ref, resolve_vcs_attributes, service_resource


class TestResolveGitRef:
    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            pytest.param(
                "0.1.dev198+g48a5c9bc9.d20260811",
                "48a5c9bc9",
                id="extracts hash from dev version",
            ),
            pytest.param(
                "0.1.dev198+g48a5c9bc9",
                "48a5c9bc9",
                id="extracts hash without dirty date suffix",
            ),
            pytest.param("1.0.0", "", id="returns empty when built exactly on a tag"),
        ],
    )
    def test_resolves_the_git_ref(self, version: str, expected: str) -> None:
        assert resolve_git_ref(version) == expected


class TestResolveVcsAttributes:
    @pytest.mark.parametrize(
        ("repository", "git_ref", "expected"),
        [
            pytest.param(
                "https://github.com/o/r",
                "abc123",
                {
                    "vcs.repository.url.full": "https://github.com/o/r",
                    "vcs.ref.head.revision": "abc123",
                },
                id="returns both when fully configured",
            ),
            pytest.param(None, "abc123", {}, id="empty when repository missing"),
            pytest.param(
                "https://github.com/o/r", "", {}, id="empty when git ref missing"
            ),
        ],
    )
    def test_resolves_the_vcs_attributes(
        self, repository: str | None, git_ref: str, expected: dict[str, str]
    ) -> None:
        assert resolve_vcs_attributes(repository, git_ref) == expected


class TestServiceResource:
    def test_names_the_service(self) -> None:
        resource = service_resource("dust-mite-test", None)

        assert resource.attributes[SERVICE_NAME] == "dust-mite-test"

    def test_omits_vcs_attributes_without_a_repository(self) -> None:
        resource = service_resource("dust-mite-test", None)

        assert "vcs.repository.url.full" not in resource.attributes
