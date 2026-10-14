from controller.profiling import resolve_endpoint, resolve_source_attributes


class TestResolveEndpoint:
    def test_returns_none_when_profiling_disabled(self) -> None:
        assert resolve_endpoint("http://otel-collector:4318", enabled=False) is None

    def test_returns_none_when_endpoint_unset(self) -> None:
        assert resolve_endpoint(None, enabled=True) is None

    def test_returns_none_when_endpoint_empty(self) -> None:
        assert resolve_endpoint("", enabled=True) is None

    def test_returns_endpoint_when_both_set(self) -> None:
        assert (
            resolve_endpoint("http://otel-collector:4318", enabled=True)
            == "http://otel-collector:4318"
        )


class TestResolveSourceAttributes:
    def test_returns_all_three_when_fully_configured(self) -> None:
        assert resolve_source_attributes(
            "https://github.com/o/r", "abc123", "controller"
        ) == {
            "service_repository": "https://github.com/o/r",
            "service_git_ref": "abc123",
            "service_root_path": "controller",
        }

    def test_omits_root_path_when_empty(self) -> None:
        assert resolve_source_attributes("https://github.com/o/r", "abc123", "") == {
            "service_repository": "https://github.com/o/r",
            "service_git_ref": "abc123",
        }

    def test_empty_when_repository_missing(self) -> None:
        assert resolve_source_attributes("", "abc123", "controller") == {}

    def test_empty_when_git_ref_missing(self) -> None:
        assert (
            resolve_source_attributes("https://github.com/o/r", "", "controller") == {}
        )
