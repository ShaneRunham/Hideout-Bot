import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import common  # noqa: E402


class Containers(unittest.TestCase):
    def test_leaves_out_ci_job_containers(self):
        out = "radio\nFORGEJO-ACTIONS-TASK-70_WORKFLOW-" + "a" * 64 + "_JOB-javascript\nhomeassistant\n"
        with mock.patch.object(common.collect, "_cmd", return_value=(0, out)):
            self.assertEqual(common.containers(), ["homeassistant", "radio"])

    def test_docker_failing_gives_nothing(self):
        with mock.patch.object(common.collect, "_cmd", return_value=(1, "no docker")):
            self.assertEqual(common.containers(), [])


if __name__ == "__main__":
    unittest.main()
