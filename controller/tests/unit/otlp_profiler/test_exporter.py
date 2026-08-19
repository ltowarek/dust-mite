from opentelemetry.proto.collector.profiles.v1development import (
    profiles_service_pb2,
)

from otlp_profiler import exporter
from otlp_profiler.aggregator import SampleKey

_STACK_A = (("main", "app.py", 10), ("busy", "app.py", 20))
_STACK_B = (("main", "app.py", 10),)
_TRACE_ID = 0x0102030405060708090A0B0C0D0E0F10
_SPAN_ID = 0x1234ABCD5678EF90


def _sample_counts() -> dict[SampleKey, int]:
    return {
        (_STACK_A, "MainThread", None): 3,
        (_STACK_B, "worker-1", (_TRACE_ID, _SPAN_ID)): 1,
    }


class TestBuildRequest:
    def test_round_trips_through_protobuf_serialization(self) -> None:
        request = exporter.build_request(
            _sample_counts(),
            "svc",
            sample_rate=100,
            time_unix_nano=1_700_000_000_000_000_000,
            duration_nano=500_000_000,
        )

        wire_bytes = request.SerializeToString()
        round_tripped = profiles_service_pb2.ExportProfilesServiceRequest.FromString(
            wire_bytes
        )

        assert round_tripped == request

    def test_mapping_table_is_non_empty(self) -> None:
        request = exporter.build_request(
            _sample_counts(), "svc", 100, 1_700_000_000_000_000_000, 500_000_000
        )

        assert len(request.dictionary.mapping_table) >= 1

    def test_period_is_non_zero(self) -> None:
        request = exporter.build_request(
            _sample_counts(), "svc", 100, 1_700_000_000_000_000_000, 500_000_000
        )

        profile = request.resource_profiles[0].scope_profiles[0].profiles[0]
        assert profile.period > 0

    def test_period_type_matches_sample_type(self) -> None:
        # Both default to samples/count -- see ProfileType's docstring.
        request = exporter.build_request(
            _sample_counts(), "svc", 100, 1_700_000_000_000_000_000, 500_000_000
        )

        strings = request.dictionary.string_table
        profile = request.resource_profiles[0].scope_profiles[0].profiles[0]
        assert strings[profile.sample_type.type_strindex] == "samples"
        assert strings[profile.sample_type.unit_strindex] == "count"
        assert strings[profile.period_type.type_strindex] == "samples"
        assert strings[profile.period_type.unit_strindex] == "count"

    def test_period_matches_sample_rate(self) -> None:
        request = exporter.build_request(
            _sample_counts(), "svc", sample_rate=50, time_unix_nano=1, duration_nano=1
        )

        profile = request.resource_profiles[0].scope_profiles[0].profiles[0]
        assert profile.period == 1_000_000_000 // 50

    def test_attribute_keys_are_dotless(self) -> None:
        request = exporter.build_request(
            _sample_counts(), "svc", 100, 1_700_000_000_000_000_000, 500_000_000
        )

        strings = request.dictionary.string_table
        for kv in request.dictionary.attribute_table:
            key = strings[kv.key_strindex]
            assert "." not in key

    def test_stack_and_location_indices_are_in_bounds(self) -> None:
        request = exporter.build_request(
            _sample_counts(), "svc", 100, 1_700_000_000_000_000_000, 500_000_000
        )
        dictionary = request.dictionary
        profile = request.resource_profiles[0].scope_profiles[0].profiles[0]

        for sample in profile.samples:
            assert 0 <= sample.stack_index < len(dictionary.stack_table)
            stack = dictionary.stack_table[sample.stack_index]
            for location_index in stack.location_indices:
                assert 0 <= location_index < len(dictionary.location_table)
                location = dictionary.location_table[location_index]
                for line in location.lines:
                    assert 0 <= line.function_index < len(dictionary.function_table)

    def test_link_index_carries_trace_and_span_id_when_present(self) -> None:
        request = exporter.build_request(
            _sample_counts(), "svc", 100, 1_700_000_000_000_000_000, 500_000_000
        )
        dictionary = request.dictionary
        profile = request.resource_profiles[0].scope_profiles[0].profiles[0]

        linked_samples = [s for s in profile.samples if s.link_index != 0]
        assert len(linked_samples) == 1
        link = dictionary.link_table[linked_samples[0].link_index]
        assert int.from_bytes(link.trace_id, "big") == _TRACE_ID
        assert int.from_bytes(link.span_id, "big") == _SPAN_ID

    def test_link_index_is_unset_when_no_span_is_active(self) -> None:
        request = exporter.build_request(
            _sample_counts(), "svc", 100, 1_700_000_000_000_000_000, 500_000_000
        )
        profile = request.resource_profiles[0].scope_profiles[0].profiles[0]

        unlinked_samples = [s for s in profile.samples if s.link_index == 0]
        assert len(unlinked_samples) == 1

    def test_resource_carries_service_name(self) -> None:
        request = exporter.build_request(_sample_counts(), "svc", 100, 1, 500_000_000)

        resource = request.resource_profiles[0].resource
        names = [
            kv.value.string_value
            for kv in resource.attributes
            if kv.key == "service.name"
        ]
        assert names == ["svc"]

    def test_resource_attributes_are_added_when_given(self) -> None:
        request = exporter.build_request(
            _sample_counts(),
            "svc",
            100,
            1,
            500_000_000,
            resource_attributes={"service_repository": "https://github.com/o/r"},
        )

        resource = request.resource_profiles[0].resource
        values = {kv.key: kv.value.string_value for kv in resource.attributes}
        assert values["service_repository"] == "https://github.com/o/r"
        assert values["service.name"] == "svc"

    def test_no_extra_resource_attributes_when_none(self) -> None:
        with_none = exporter.build_request(
            _sample_counts(), "svc", 100, 1, 500_000_000, resource_attributes=None
        )
        without_arg = exporter.build_request(
            _sample_counts(), "svc", 100, 1, 500_000_000
        )

        assert len(with_none.resource_profiles[0].resource.attributes) == 1
        assert (
            with_none.resource_profiles[0].resource
            == without_arg.resource_profiles[0].resource
        )
