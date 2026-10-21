import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def free_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as test_socket:
        test_socket.bind(("127.0.0.1", 0))
        return test_socket.getsockname()[1]


class UdpLoopbackTests(unittest.TestCase):
    def test_sender_and_receiver_exchange_real_udp_packets(self):
        port = free_udp_port()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            receiver_stats = folder / "receiver.json"
            sender_summary = folder / "sender.json"
            ready_file = folder / "ready.json"
            receiver = subprocess.Popen(
                [
                    sys.executable,
                    str(ROOT / "udp_receiver.py"),
                    "--bind", "127.0.0.1",
                    "--port", str(port),
                    "--stats-file", str(receiver_stats),
                    "--sender-summary", str(sender_summary),
                    "--ready-file", str(ready_file),
                    "--test-id", "loopback",
                    "--duration", "3",
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                ready_deadline = time.monotonic() + 5
                while time.monotonic() < ready_deadline and not ready_file.exists():
                    if receiver.poll() is not None:
                        self.fail("Receiver exited before binding its UDP socket")
                    time.sleep(0.05)
                self.assertTrue(ready_file.exists(), "Receiver did not report ready")

                sender = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "udp_sender.py"),
                        "--destination", "127.0.0.1",
                        "--port", str(port),
                        "--rate-mbps", "0.1",
                        "--duration", "2",
                        "--summary-file", str(sender_summary),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                )
                self.assertTrue(sender.stdout.strip())
                receiver.wait(timeout=6)
                result = json.loads(receiver_stats.read_text(encoding="utf-8"))
                self.assertTrue(result["final"])
                self.assertGreater(result["sent_packets"], 0)
                self.assertEqual(result["lost_packets"], 0)
                self.assertEqual(result["duplicate_packets"], 0)
                self.assertEqual(result["out_of_order_packets"], 0)
            finally:
                if receiver.poll() is None:
                    receiver.terminate()
                    receiver.wait(timeout=3)
                if receiver.stdout:
                    receiver.stdout.close()


if __name__ == "__main__":
    unittest.main()

