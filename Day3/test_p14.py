import tempfile
import unittest
from datetime import date
from pathlib import Path

from p11_task import Priority, Task, load_tasks, save_tasks


class TaskRoundTripTests(unittest.TestCase):
    def test_save_and_load_preserves_tasks(self) -> None:
        tasks = [
            Task(
                "Prepare UAT test cases",
                "Rahul",
                priority=Priority.LOW,
                due=date(2026, 10, 24),
            )
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "tasks.json"
            save_tasks(tasks, path)
            loaded = load_tasks(path)

        self.assertEqual(loaded, tasks)


if __name__ == "__main__":
    unittest.main()