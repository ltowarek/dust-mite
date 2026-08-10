from controller.profiling import resolve_endpoint


class TestResolveEndpoint:
    def test_returns_none_when_profiling_disabled(self) -> None:
        assert resolve_endpoint("", "http://otel-collector:4318") is None

    def test_returns_none_when_endpoint_unset(self) -> None:
        assert resolve_endpoint("1", None) is None

    def test_returns_none_when_endpoint_empty(self) -> None:
        assert resolve_endpoint("1", "") is None

    def test_returns_endpoint_when_both_set(self) -> None:
        assert (
            resolve_endpoint("1", "http://otel-collector:4318")
            == "http://otel-collector:4318"
        )

    def test_rejects_non_canonical_spelling(self) -> None:
        assert resolve_endpoint("true", "http://otel-collector:4318") is None

    def test_rejects_zero(self) -> None:
        assert resolve_endpoint("0", "http://otel-collector:4318") is None
