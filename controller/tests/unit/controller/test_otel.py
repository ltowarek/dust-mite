from opentelemetry.sdk.resources import SERVICE_NAME

from controller.otel import resolve_git_ref, resolve_vcs_attributes, service_resource


class TestResolveGitRef:
    def test_extracts_hash_from_dev_version(self) -> None:
        assert resolve_git_ref("0.1.dev198+g48a5c9bc9.d20260811") == "48a5c9bc9"

    def test_extracts_hash_without_dirty_date_suffix(self) -> None:
        assert resolve_git_ref("0.1.dev198+g48a5c9bc9") == "48a5c9bc9"

    def test_returns_empty_when_built_exactly_on_a_tag(self) -> None:
        assert resolve_git_ref("1.0.0") == ""


class TestResolveVcsAttributes:
    def test_returns_both_when_fully_configured(self) -> None:
        assert resolve_vcs_attributes("https://github.com/o/r", "abc123") == {
            "vcs.repository.url.full": "https://github.com/o/r",
            "vcs.ref.head.revision": "abc123",
        }

    def test_empty_when_repository_missing(self) -> None:
        assert resolve_vcs_attributes(None, "abc123") == {}

    def test_empty_when_git_ref_missing(self) -> None:
        assert resolve_vcs_attributes("https://github.com/o/r", "") == {}


class TestServiceResource:
    def test_names_the_service(self) -> None:
        resource = service_resource("dust-mite-test", None)

        assert resource.attributes[SERVICE_NAME] == "dust-mite-test"

    def test_omits_vcs_attributes_without_a_repository(self) -> None:
        resource = service_resource("dust-mite-test", None)

        assert "vcs.repository.url.full" not in resource.attributes
