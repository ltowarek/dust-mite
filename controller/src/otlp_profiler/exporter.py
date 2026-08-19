"""Builds and sends OTLP profiles for a drained aggregate.

Serializes as real protobuf. `sample_type`/`period_type` default to
`("samples", "count")`; override via `build_request`/`export`'s
`profile_type` parameter if a different Pyroscope profile type is needed.
"""

import dataclasses
import os
from collections.abc import Callable, Mapping

import requests
from opentelemetry.proto.collector.profiles.v1development import (
    profiles_service_pb2,
)
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.profiles.v1development import profiles_pb2
from opentelemetry.proto.resource.v1 import resource_pb2
from opentelemetry.sdk.resources import SERVICE_NAME

from otlp_profiler.aggregator import SampleKey, Stack

_PROFILES_PATH = "/v1development/profiles"
_THREAD_NAME_KEY = "thread_name"


@dataclasses.dataclass(frozen=True)
class ProfileType:
    """The OTLP `sample_type`/`period_type` a profile is tagged with.

    Defaults to `("samples", "count")` -- see this module's docstring.
    """

    sample_type: str = "samples"
    sample_unit: str = "count"
    period_type: str = "samples"
    period_unit: str = "count"


_DEFAULT_PROFILE_TYPE = ProfileType()


# Same get-or-add-per-table pattern as the OTel Collector's own Go pdata
# implementation (SetString/SetFunction/SetLocation/SetStack/SetAttribute in
# go.opentelemetry.io/collector/pdata/pprofile), consolidated into one
# generic, cache-backed helper instead of one linear-scan function per table.
def _get_or_add[K, V](
    cache: dict[K, int], table: list[V], key: K, factory: Callable[[], V]
) -> int:
    """Return `key`'s index in `table` (via `cache`), building it via `factory` if new.

    `factory` is only called on a cache miss, so it may itself recurse into
    other `_get_or_add` calls (e.g. a location's factory reserving its
    function's string indices) without doing that work redundantly.
    """
    idx = cache.get(key)
    if idx is None:
        idx = len(table)
        table.append(factory())
        cache[key] = idx
    return idx


class _DictionaryBuilder:
    """Accumulates the de-duplicated tables of a `ProfilesDictionary`.

    Every `*_index` method reserves entries lazily and returns the index to
    reference from a `Sample`. Call `build()` only once every reference has
    been made -- protobuf copies list fields at message-construction time, so
    entries added afterwards would silently be missing.
    """

    def __init__(self) -> None:
        """Create an empty dictionary builder."""
        self._strings: list[str] = [""]
        self._string_cache: dict[str, int] = {"": 0}
        self._functions: dict[tuple[str, str], int] = {}
        self._function_table: list[profiles_pb2.Function] = []
        self._locations: dict[tuple[int, int], int] = {}
        self._location_table: list[profiles_pb2.Location] = []
        self._stacks: dict[tuple[int, ...], int] = {}
        self._stack_table: list[profiles_pb2.Stack] = []
        self._attributes: dict[tuple[str, str], int] = {}
        self._attribute_table: list[profiles_pb2.KeyValueAndUnit] = []
        self._links: dict[tuple[int, int], int] = {}
        self._link_table: list[profiles_pb2.Link] = [profiles_pb2.Link()]

    def string_index(self, value: str) -> int:
        """Return `value`'s index in the string table, adding it if new."""
        return _get_or_add(self._string_cache, self._strings, value, lambda: value)

    def _function_index(self, qualname: str, filename: str) -> int:
        return _get_or_add(
            self._functions,
            self._function_table,
            (qualname, filename),
            lambda: profiles_pb2.Function(
                name_strindex=self.string_index(qualname),
                filename_strindex=self.string_index(filename),
            ),
        )

    def _location_index(self, qualname: str, filename: str, lineno: int) -> int:
        func_idx = self._function_index(qualname, filename)
        return _get_or_add(
            self._locations,
            self._location_table,
            (func_idx, lineno),
            lambda: profiles_pb2.Location(
                lines=[profiles_pb2.Line(function_index=func_idx, line=lineno)],
            ),
        )

    def stack_index(self, stack: Stack) -> int:
        """Return `stack`'s index in the stack table, adding it if new."""
        location_indices = tuple(
            self._location_index(qualname, filename, lineno)
            for qualname, filename, lineno in stack
        )
        return _get_or_add(
            self._stacks,
            self._stack_table,
            location_indices,
            lambda: profiles_pb2.Stack(location_indices=list(location_indices)),
        )

    def attribute_index(self, key: str, value: str) -> int:
        """Return the (key, value) pair's index in the attribute table."""
        return _get_or_add(
            self._attributes,
            self._attribute_table,
            (key, value),
            lambda: profiles_pb2.KeyValueAndUnit(
                key_strindex=self.string_index(key),
                value=common_pb2.AnyValue(string_value=value),
            ),
        )

    def link_index(self, trace_id: int, span_id: int) -> int:
        """Return `(trace_id, span_id)`'s index in the link table, adding it if new."""
        return _get_or_add(
            self._links,
            self._link_table,
            (trace_id, span_id),
            lambda: profiles_pb2.Link(
                trace_id=trace_id.to_bytes(16, "big"),
                span_id=span_id.to_bytes(8, "big"),
            ),
        )

    def build(self) -> profiles_pb2.ProfilesDictionary:
        """Freeze the accumulated tables into a `ProfilesDictionary`."""
        mapping_table = [profiles_pb2.Mapping(filename_strindex=self.string_index(""))]
        return profiles_pb2.ProfilesDictionary(
            mapping_table=mapping_table,
            location_table=self._location_table,
            function_table=self._function_table,
            string_table=self._strings,
            attribute_table=self._attribute_table,
            stack_table=self._stack_table,
            link_table=self._link_table,
        )


def _build_samples(
    counts: dict[SampleKey, int], dictionary: _DictionaryBuilder
) -> list[profiles_pb2.Sample]:
    samples = []
    for (stack, thread_name, span_context), count in counts.items():
        attribute_indices = [dictionary.attribute_index(_THREAD_NAME_KEY, thread_name)]
        sample = profiles_pb2.Sample(
            stack_index=dictionary.stack_index(stack),
            attribute_indices=attribute_indices,
            values=[count],
        )
        if span_context is not None:
            trace_id, span_id = span_context
            sample.link_index = dictionary.link_index(trace_id, span_id)
        samples.append(sample)
    return samples


def build_request(  # noqa: PLR0913 -- each param is an independent OTLP field
    counts: dict[SampleKey, int],
    service_name: str,
    sample_rate: int,
    time_unix_nano: int,
    duration_nano: int,
    profile_type: ProfileType = _DEFAULT_PROFILE_TYPE,
    resource_attributes: Mapping[str, str] | None = None,
) -> profiles_service_pb2.ExportProfilesServiceRequest:
    """Build one `ExportProfilesServiceRequest` from a drained aggregate."""
    dictionary = _DictionaryBuilder()
    samples = _build_samples(counts, dictionary)

    # Reserve the sample/period type strings before dictionary.build() -- see
    # _DictionaryBuilder's docstring for why ordering matters here.
    sample_type_vt = profiles_pb2.ValueType(
        type_strindex=dictionary.string_index(profile_type.sample_type),
        unit_strindex=dictionary.string_index(profile_type.sample_unit),
    )
    period_type_vt = profiles_pb2.ValueType(
        type_strindex=dictionary.string_index(profile_type.period_type),
        unit_strindex=dictionary.string_index(profile_type.period_unit),
    )

    profile = profiles_pb2.Profile(
        sample_type=sample_type_vt,
        samples=samples,
        time_unix_nano=time_unix_nano,
        duration_nano=duration_nano,
        period_type=period_type_vt,
        period=1_000_000_000 // sample_rate,
        profile_id=os.urandom(16),
    )

    attributes = [
        common_pb2.KeyValue(
            key=SERVICE_NAME,
            value=common_pb2.AnyValue(string_value=service_name),
        )
    ]
    for key, value in (resource_attributes or {}).items():
        attributes.append(
            common_pb2.KeyValue(key=key, value=common_pb2.AnyValue(string_value=value))
        )
    resource = resource_pb2.Resource(attributes=attributes)
    scope_profiles = profiles_pb2.ScopeProfiles(profiles=[profile])
    resource_profiles = profiles_pb2.ResourceProfiles(
        resource=resource, scope_profiles=[scope_profiles]
    )

    return profiles_service_pb2.ExportProfilesServiceRequest(
        resource_profiles=[resource_profiles],
        dictionary=dictionary.build(),
    )


_session = requests.Session()


def send(
    endpoint: str,
    request: profiles_service_pb2.ExportProfilesServiceRequest,
) -> None:
    """POST `request` as protobuf to `endpoint`'s OTLP profiles path.

    Raises if the collector responds with an HTTP error status, so callers
    (see `otlp_profiler.configure`'s export callback) can log the failure
    instead of it being silently swallowed.
    """
    response = _session.post(
        endpoint.rstrip("/") + _PROFILES_PATH,
        data=request.SerializeToString(),
        headers={"Content-Type": "application/x-protobuf"},
        timeout=5,
    )
    response.raise_for_status()


def export(  # noqa: PLR0913 -- each param is an independent OTLP field
    counts: dict[SampleKey, int],
    service_name: str,
    endpoint: str,
    sample_rate: int,
    time_unix_nano: int,
    duration_nano: int,
    profile_type: ProfileType = _DEFAULT_PROFILE_TYPE,
    resource_attributes: Mapping[str, str] | None = None,
) -> None:
    """Build and send one export covering `counts` from the last interval."""
    if not counts:
        return
    request = build_request(
        counts,
        service_name,
        sample_rate,
        time_unix_nano=time_unix_nano,
        duration_nano=duration_nano,
        profile_type=profile_type,
        resource_attributes=resource_attributes,
    )
    send(endpoint, request)
