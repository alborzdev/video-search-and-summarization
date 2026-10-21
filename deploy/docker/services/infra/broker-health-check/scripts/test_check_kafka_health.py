"""Exercise broker polling without launching Kafka JVMs or sleeping."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("check-kafka-health.sh")


class KafkaHealthPollingTests(unittest.TestCase):
    def run_health(self, required, responses, retries=3):
        with tempfile.TemporaryDirectory(prefix="kafka-health-test-") as temporary:
            root = Path(temporary)
            state = root / "state.json"
            state.write_text(json.dumps({"calls": 0, "responses": responses}))
            commands = {
                "jq": "import json,sys\nfor item in json.load(sys.stdin): print(item['name'])\n",
                "kafka-broker-api-versions": "raise SystemExit(0)\n",
                "sleep": "raise SystemExit(0)\n",
                "kafka-topics": (
                    "import json,os,sys\n"
                    "from pathlib import Path\n"
                    "path=Path(os.environ['KAFKA_TEST_STATE'])\n"
                    "state=json.loads(path.read_text())\n"
                    "assert '--list' in sys.argv\n"
                    "response=state['responses'][min(state['calls'],len(state['responses'])-1)]\n"
                    "state['calls']+=1\n"
                    "path.write_text(json.dumps(state))\n"
                    "sys.stdout.write(response.get('stdout',''))\n"
                    "raise SystemExit(response.get('returncode',0))\n"
                ),
            }
            for name, body in commands.items():
                command = root / name
                command.write_text(f"#!{sys.executable}\n" + body)
                command.chmod(0o755)
            environment = dict(
                os.environ,
                PATH=str(root) + os.pathsep + os.environ["PATH"],
                KAFKA_TEST_STATE=str(state),
                KAFKA_TOPICS=json.dumps([{"name": name} for name in required]),
                MAX_RETRIES=str(retries),
                RETRY_INTERVAL="0",
            )
            completed = subprocess.run(
                ["bash", str(SCRIPT)],
                env=environment,
                text=True,
                capture_output=True,
                timeout=10,
                check=False,
            )
            return completed, json.loads(state.read_text())["calls"]

    def test_topic_names_match_whole_literal_names(self):
        for listed in ("events.raw.extra\n", "eventsXraw\n"):
            with self.subTest(listed=listed):
                completed, calls = self.run_health(
                    ["events.raw"],
                    [{"stdout": listed}],
                    retries=2,
                )
                self.assertEqual(completed.returncode, 1, completed.stderr)
                self.assertEqual(calls, 2)
                self.assertIn("Missing topics: events.raw", completed.stdout)
                self.assertNotIn("completed successfully", completed.stdout)

    def test_failed_query_cannot_pass_with_valid_looking_partial_output(self):
        completed, calls = self.run_health(
            ["events", "captions"],
            [
                {"returncode": 1, "stdout": "events\ncaptions\n"},
                {"stdout": "events\ncaptions\n"},
            ],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(calls, 2)
        self.assertIn("topic query failed", completed.stdout)
        self.assertIn(
            "All required Kafka topics are present after 1 retries", completed.stdout
        )

    def test_eventual_creation_checks_all_22_topics_with_one_query_per_poll(self):
        required = [f"required-topic-{index}" for index in range(22)]
        completed, calls = self.run_health(
            required,
            [
                {"stdout": "\n".join(required[:-1]) + "\n"},
                {"stdout": "\n".join(required) + "\n"},
            ],
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(calls, 2)
        self.assertIn("Waiting for missing topics: required-topic-21", completed.stdout)
        self.assertIn("completed successfully", completed.stdout)

    def test_query_failures_exhaust_retries_without_reporting_health(self):
        completed, calls = self.run_health(
            ["events"],
            [{"returncode": 1, "stdout": "events\n"}],
            retries=2,
        )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(calls, 2)
        self.assertIn("Missing topics: events", completed.stdout)
        self.assertIn(
            "Topic list unavailable: last broker query failed", completed.stdout
        )
        self.assertNotIn("completed successfully", completed.stdout)


if __name__ == "__main__":
    unittest.main()
