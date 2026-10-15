import pytest
from opentelemetry.sdk.resources import Resource

from controller.otel import VCS_REF_HEAD_REVISION, VCS_REPOSITORY_URL_FULL
from controller.profiling import source_link_attributes

_REPOSITORY = "https://github.com/o/r"
_REVISION = "abc123"


class TestSourceLinkAttributes:
    def test_links_profiles_to_the_resources_repository_and_revision(self) -> None:
        resource = Resource(
            {VCS_REPOSITORY_URL_FULL: _REPOSITORY, VCS_REF_HEAD_REVISION: _REVISION}
        )

        assert source_link_attributes(resource) == {
            "service_repository": _REPOSITORY,
            "service_git_ref": _REVISION,
            "service_root_path": "controller",
        }

    @pytest.mark.parametrize(
        "attributes",
        [
            pytest.param({VCS_REF_HEAD_REVISION: _REVISION}, id="no_repository"),
            pytest.param({VCS_REPOSITORY_URL_FULL: _REPOSITORY}, id="no_revision"),
        ],
    )
    def test_links_nothing_without_both(self, attributes: dict[str, str]) -> None:
        assert source_link_attributes(Resource(attributes)) == {}
