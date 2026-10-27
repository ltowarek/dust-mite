from controller.subject import Subject
from tests.test_doubles import SubscriberSpy


class TestSubject:
    def test_delivers_published_messages_to_every_subscriber(self) -> None:
        subject = Subject[str]()
        first, second = SubscriberSpy[str](), SubscriberSpy[str]()

        with subject.subscription(first), subject.subscription(second):
            subject.publish("frame")

        assert first.messages == ["frame"]
        assert second.messages == ["frame"]

    def test_stops_delivering_once_the_subscription_ends(self) -> None:
        subject = Subject[str]()
        subscriber = SubscriberSpy[str]()

        with subject.subscription(subscriber):
            subject.publish("before")
        subject.publish("after")

        assert subscriber.messages == ["before"]

    def test_activates_on_the_first_subscriber_and_deactivates_after_the_last(
        self,
    ) -> None:
        events: list[str] = []
        subject = Subject[str](
            on_active=lambda: events.append("active"),
            on_idle=lambda: events.append("idle"),
        )

        with subject.subscription(SubscriberSpy[str]()):
            with subject.subscription(SubscriberSpy[str]()):
                events.append("both subscribed")
            events.append("one left")

        assert events == ["active", "both subscribed", "one left", "idle"]

    def test_publishing_without_subscribers_is_a_no_op(self) -> None:
        Subject[str]().publish("nobody listening")

    def test_delivers_to_the_other_subscribers_when_one_raises(self) -> None:
        subject = Subject[str]()
        subscriber = SubscriberSpy[str]()

        def fail(message: str) -> None:
            raise KeyError(message)

        with subject.subscription(fail), subject.subscription(subscriber):
            subject.publish("frame")

        assert subscriber.messages == ["frame"]
