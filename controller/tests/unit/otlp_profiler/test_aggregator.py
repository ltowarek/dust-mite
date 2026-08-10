from otlp_profiler.aggregator import Aggregator

_STACK = (("main", "app.py", 10),)


def test_add_sample_accumulates_counts() -> None:
    aggregator = Aggregator()
    aggregator.add_sample(_STACK, "MainThread", None)
    aggregator.add_sample(_STACK, "MainThread", None)

    counts = aggregator.drain()

    expected_count = 2
    assert counts[(_STACK, "MainThread", None)] == expected_count


def test_distinct_keys_are_counted_separately() -> None:
    aggregator = Aggregator()
    aggregator.add_sample(_STACK, "MainThread", None)
    aggregator.add_sample(_STACK, "worker-1", None)
    aggregator.add_sample(_STACK, "MainThread", (1, 42))

    counts = aggregator.drain()

    assert counts == {
        (_STACK, "MainThread", None): 1,
        (_STACK, "worker-1", None): 1,
        (_STACK, "MainThread", (1, 42)): 1,
    }


def test_drain_resets_the_aggregate() -> None:
    aggregator = Aggregator()
    aggregator.add_sample(_STACK, "MainThread", None)

    first = aggregator.drain()
    second = aggregator.drain()

    assert first == {(_STACK, "MainThread", None): 1}
    assert second == {}
