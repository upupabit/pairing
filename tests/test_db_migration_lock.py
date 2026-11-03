"""app/db_migration_lock.py: one migration at a time on a shared database."""

import threading
import time

from app.db_migration_lock import MigrationLock


def test_a_second_server_waits_for_the_first_to_finish_migrating(tmp_path):
    url = f"sqlite:///{tmp_path / 'p.db'}"
    events: list[str] = []
    first_has_lock = threading.Event()

    def first() -> None:
        with MigrationLock(url):
            events.append("first in")
            first_has_lock.set()
            time.sleep(0.3)
            events.append("first out")

    def second() -> None:
        first_has_lock.wait()
        with MigrationLock(url):
            events.append("second in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert events == ["first in", "first out", "second in"]


def test_an_in_memory_database_needs_no_lock():
    with MigrationLock("sqlite:///:memory:"):
        pass
