from controller.collision_monitor import CollisionMonitor
from controller.command import Command

_SPEED = 50


def _packet(command: Command, value: int | None = _SPEED) -> dict[str, int | None]:
    return {"command": command.value, "value": value}


def _stopping_monitor() -> CollisionMonitor:
    monitor = CollisionMonitor()
    monitor.update(CollisionMonitor.STOP_DISTANCE_CM - 1)
    return monitor


class TestCollisionMonitorUpdate:
    def test_starts_stopping_below_the_stop_distance(self) -> None:
        monitor = CollisionMonitor()

        changed = monitor.update(CollisionMonitor.STOP_DISTANCE_CM - 1)

        assert changed is True
        assert monitor.stopping is True

    def test_does_not_stop_at_the_stop_distance(self) -> None:
        monitor = CollisionMonitor()

        changed = monitor.update(CollisionMonitor.STOP_DISTANCE_CM)

        assert changed is False
        assert monitor.stopping is False

    def test_keeps_stopping_until_past_the_resume_distance(self) -> None:
        monitor = _stopping_monitor()

        monitor.update(CollisionMonitor.RESUME_DISTANCE_CM - 1)

        assert monitor.stopping is True

    def test_resumes_at_the_resume_distance(self) -> None:
        monitor = _stopping_monitor()

        changed = monitor.update(CollisionMonitor.RESUME_DISTANCE_CM)

        assert changed is True
        assert monitor.stopping is False

    def test_ignores_a_reading_with_no_echo(self) -> None:
        monitor = _stopping_monitor()

        changed = monitor.update(-1)

        assert changed is False
        assert monitor.stopping is True


class TestCollisionMonitorFilter:
    def test_turns_advance_into_brake_while_stopping(self) -> None:
        monitor = _stopping_monitor()

        assert monitor.filter(_packet(Command.ADVANCE)) == _packet(Command.BRAKE, None)

    def test_passes_advance_through_when_not_stopping(self) -> None:
        monitor = CollisionMonitor()

        assert monitor.filter(_packet(Command.ADVANCE)) == _packet(Command.ADVANCE)

    def test_lets_the_operator_back_away_or_turn_while_stopping(self) -> None:
        monitor = _stopping_monitor()

        for command in (Command.RETREAT, Command.TURN_LEFT, Command.TURN_RIGHT):
            assert monitor.filter(_packet(command)) == _packet(command)
