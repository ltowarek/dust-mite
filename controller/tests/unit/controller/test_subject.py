from controller.subject import Subject


class _Recorder:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def __call__(self, message: str) -> None:
        self.messages.append(message)


class TestSubject:
    def test_delivers_published_messages_to_every_subscriber(self) -> None:
        subject = Subject()
        first, second = _Recorder(), _Recorder()

        with subject.subscription(first), subject.subscription(second):
            subject.publish("frame")

        assert first.messages == ["frame"]
        assert second.messages == ["frame"]

    def test_stops_delivering_once_the_subscription_ends(self) -> None:
        subject = Subject()
        recorder = _Recorder()

        with subject.subscription(recorder):
            subject.publish("before")
        subject.publish("after")

        assert recorder.messages == ["before"]

    def test_activates_on_the_first_subscriber_and_deactivates_after_the_last(
        self,
    ) -> None:
        events: list[str] = []
        subject = Subject(
            on_active=lambda: events.append("active"),
            on_idle=lambda: events.append("idle"),
        )

        with subject.subscription(_Recorder()):
            with subject.subscription(_Recorder()):
                events.append("both subscribed")
            events.append("one left")

        assert events == ["active", "both subscribed", "one left", "idle"]

    def test_publishing_without_subscribers_is_a_no_op(self) -> None:
        Subject().publish("nobody listening")
