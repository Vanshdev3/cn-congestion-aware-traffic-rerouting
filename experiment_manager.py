"""Local HTTP control service for Mininet, traffic, and experiment results."""

import argparse
import csv
import json
import os
import subprocess
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from mininet.log import setLogLevel

from topology import create_network, discover_port_map, print_port_map, write_port_map


ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "run"
RESULTS_DIR = ROOT / "results"
CONTROLLER_STATE = RUN_DIR / "controller_state.json"
CONTROLLER_COMMAND = RUN_DIR / "controller_command.json"
PORT_MAP_FILE = RUN_DIR / "port_map.json"
RESULTS_FILE = RESULTS_DIR / "experiments.csv"
LIVE_SECONDS = 3.0


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(target)


def age_seconds(iso_time):
    if not iso_time:
        return None
    try:
        recorded = datetime.fromisoformat(iso_time)
        return max((datetime.now(timezone.utc) - recorded).total_seconds(), 0)
    except (TypeError, ValueError):
        return None


class ExperimentManager:
    """Own the Mininet network and coordinate one repeatable test at a time."""

    def __init__(self, controller_ip, controller_port):
        self.controller_ip = controller_ip
        self.controller_port = controller_port
        self.network = None
        self.port_map = None
        self.map_generation = None
        self.sender_process = None
        self.receiver_process = None
        self.sender_log = None
        self.receiver_log = None
        self.current_test = None
        self.last_result = None
        self.events = deque(maxlen=100)
        self.command_id = 0
        self.lock = threading.RLock()
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        previous = read_json(CONTROLLER_STATE) or {}
        command_file = read_json(CONTROLLER_COMMAND) or {}
        self.command_id = max(
            int(previous.get("command_id", 0)),
            int(command_file.get("command_id", 0)),
        )

    def add_event(self, message, kind="info"):
        self.events.append(
            {"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
             "kind": kind,
             "message": message}
        )

    def controller_state(self):
        state = read_json(CONTROLLER_STATE)
        if not state or age_seconds(state.get("updated_at")) is None:
            return None
        if age_seconds(state.get("updated_at")) > LIVE_SECONDS:
            return None
        return state

    def send_controller_command(self, action, mode=None, threshold_percent=None):
        self.command_id += 1
        command = {
            "command_id": self.command_id,
            "action": action,
            "mode": mode or "static",
            "threshold_percent": threshold_percent or 75,
        }
        write_json(CONTROLLER_COMMAND, command)
        return command

    def wait_for_path_a(self, timeout=15, command_id=None, generation=None):
        stop_at = time.monotonic() + timeout
        while time.monotonic() < stop_at:
            state = self.controller_state()
            if (
                state
                and state.get("active_path") == "A"
                and state.get("route_status") == "active"
                and state.get("flow_entries_verified")
                and state.get("port_map_loaded")
                and (generation is None or state.get("mapping_generation") == generation)
                and (command_id is None or state.get("command_id", 0) >= command_id)
                and set(state.get("expected_switches", []))
                <= set(state.get("connected_switches", []))
            ):
                return state
            time.sleep(0.2)
        raise RuntimeError(
            "The controller did not verify Path A within 15 seconds. "
            "Check the OS-Ken terminal and switch connections."
        )

    def start_network(self):
        with self.lock:
            if self.network:
                return {"started": False, "message": "Network is already running"}
            if not self.controller_state():
                raise RuntimeError(
                    "OS-Ken is not responding. Start `osken-manager controller.py` first."
                )

            setLogLevel("warning")
            network = create_network(self.controller_ip, self.controller_port)
            generation = uuid.uuid4().hex
            try:
                # Clear the previous run's map before any new switches connect.
                write_json(PORT_MAP_FILE, {"pending": True, "generation": generation})
                network.start()
                port_map, lines = discover_port_map(network)
                port_map["generation"] = generation
                write_port_map(port_map, PORT_MAP_FILE)
                print_port_map(lines)
                self.network = network
                self.port_map = port_map
                self.map_generation = generation
                self.add_event("Mininet network started and actual port map saved")
                self.wait_for_path_a(generation=generation)
            except Exception:
                network.stop()
                self.network = None
                self.port_map = None
                self.map_generation = None
                raise
            self.add_event("Controller connected and verified initial Path A rules")
            return {"started": True, "port_map": port_map}

    def stop_network(self):
        with self.lock:
            self.stop_test()
            if not self.network:
                return {"stopped": False, "message": "Network is already stopped"}
            self.network.stop()
            self.network = None
            self.port_map = None
            self.map_generation = None
            self.add_event("Mininet network stopped")
            return {"stopped": True}

    def reset_experiment(self, mode="static", threshold_percent=75):
        with self.lock:
            self.stop_test()
            if mode not in ("static", "adaptive"):
                raise ValueError("mode must be static or adaptive")
            threshold_percent = float(threshold_percent)
            if not 10 <= threshold_percent <= 99:
                raise ValueError("threshold must be between 10 and 99 percent")

            self.last_result = None
            if self.network:
                command = self.send_controller_command("reset", mode, threshold_percent)
                self.wait_for_path_a(command_id=command["command_id"])
                self.add_event("Experiment reset; counters will use new baselines")
            else:
                self.add_event("Local experiment state reset; network is stopped")
            return {"reset": True}

    def configure(self, mode, threshold_percent):
        with self.lock:
            if mode not in ("static", "adaptive"):
                raise ValueError("mode must be static or adaptive")
            threshold_percent = float(threshold_percent)
            if not 10 <= threshold_percent <= 99:
                raise ValueError("threshold must be between 10 and 99 percent")
            if not self.controller_state():
                raise RuntimeError("The controller is unavailable; settings were not applied")
            self.send_controller_command("configure", mode, threshold_percent)
            self.add_event(f"Settings sent: {mode} mode, {threshold_percent:g}% threshold")
            return {"configured": True}

    def set_rate(self, rate_mbps):
        with self.lock:
            rate_mbps = float(rate_mbps)
            if not 0.1 <= rate_mbps <= 10:
                raise ValueError("UDP rate must be between 0.1 and 10 Mbps")
            if not self.current_test or not self.sender_process:
                raise RuntimeError("Start a UDP test before changing its live rate")
            if self.sender_process.poll() is not None:
                raise RuntimeError("The UDP sender has already finished")
            write_json(self.current_test["rate_file"], {"rate_mbps": rate_mbps})
            self.add_event(f"UDP sender rate changed to {rate_mbps:g} Mbps")
            return {"rate_mbps": rate_mbps, "applied": True}

    def start_test(self, rate_mbps=4, duration_seconds=20, mode="adaptive", threshold_percent=75):
        with self.lock:
            if not self.network:
                self.start_network()
            rate_mbps = float(rate_mbps)
            duration_seconds = float(duration_seconds)
            if not 0.1 <= rate_mbps <= 10:
                raise ValueError("UDP rate must be between 0.1 and 10 Mbps")
            if not 3 <= duration_seconds <= 300:
                raise ValueError("test duration must be between 3 and 300 seconds")

            self.reset_experiment(mode, threshold_percent)
            test_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
            sender_summary = RUN_DIR / f"{test_id}-sender.json"
            receiver_stats = RUN_DIR / f"{test_id}-receiver.json"
            receiver_ready = RUN_DIR / f"{test_id}-receiver-ready.json"
            rate_file = RUN_DIR / f"{test_id}-rate.json"
            sender_log_path = RUN_DIR / f"{test_id}-sender.log"
            receiver_log_path = RUN_DIR / f"{test_id}-receiver.log"

            receiver_command = [
                "python3", "-u", str(ROOT / "udp_receiver.py"),
                "--bind", "10.0.0.2",
                "--port", "5001",
                "--stats-file", str(receiver_stats),
                "--sender-summary", str(sender_summary),
                "--test-id", test_id,
                "--ready-file", str(receiver_ready),
            ]
            self.receiver_log = open(receiver_log_path, "w", encoding="utf-8")
            self.receiver_process = self.network.get("h2").popen(
                receiver_command,
                stdout=self.receiver_log,
                stderr=subprocess.STDOUT,
            )

            ready_deadline = time.monotonic() + 5
            while time.monotonic() < ready_deadline and not receiver_ready.exists():
                if self.receiver_process.poll() is not None:
                    raise RuntimeError("UDP receiver stopped before it was ready")
                time.sleep(0.1)
            if not receiver_ready.exists():
                self.stop_test()
                raise RuntimeError("UDP receiver did not bind to h2 within five seconds")

            sender_command = [
                "python3", "-u", str(ROOT / "udp_sender.py"),
                "--destination", "10.0.0.2",
                "--port", "5001",
                "--rate-mbps", str(rate_mbps),
                "--duration", str(duration_seconds),
                "--summary-file", str(sender_summary),
                "--rate-file", str(rate_file),
            ]
            write_json(rate_file, {"rate_mbps": rate_mbps})
            self.sender_log = open(sender_log_path, "w", encoding="utf-8")
            self.sender_process = self.network.get("h1").popen(
                sender_command,
                stdout=self.sender_log,
                stderr=subprocess.STDOUT,
            )
            self.current_test = {
                "test_id": test_id,
                "mode": mode,
                "rate_mbps": rate_mbps,
                "duration_seconds": duration_seconds,
                "threshold_percent": float(threshold_percent),
                "rate_file": rate_file,
                "started_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "sender_summary": sender_summary,
                "receiver_stats": receiver_stats,
                "sender_log": sender_log_path,
                "receiver_log": receiver_log_path,
            }
            self.add_event(
                f"UDP test {test_id} started at {rate_mbps:g} Mbps in {mode} mode"
            )
            return {"started": True, "test_id": test_id}

    def finish_test_if_ready(self):
        if self.current_test and self.sender_process and self.sender_process.poll() is not None:
            try:
                self.finish_test()
            except Exception as error:
                test_id = self.current_test["test_id"]
                self.stop_process(self.receiver_process)
                self.close_logs()
                self.last_result = {"test_id": test_id, "error": str(error)}
                self.current_test = None
                self.sender_process = None
                self.receiver_process = None
                self.add_event(f"Test {test_id} could not be finalized: {error}", "error")

    def stop_test(self):
        with self.lock:
            if not self.current_test:
                self.stop_process(self.sender_process)
                self.stop_process(self.receiver_process)
                self.close_logs()
                return {"stopped": False}
            self.stop_process(self.sender_process)
            return self.finish_test()

    @staticmethod
    def stop_process(process):
        if not process or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    def finish_test(self):
        test = self.current_test
        if not test:
            return {"stopped": False}
        if self.sender_process and self.sender_process.poll() is None:
            self.stop_process(self.sender_process)
        self.stop_process(self.receiver_process)
        self.close_logs()

        sender = read_json(test["sender_summary"])
        receiver = read_json(test["receiver_stats"])
        if not sender:
            raise RuntimeError("The sender did not save its final packet summary")
        if not receiver:
            raise RuntimeError("The receiver did not save its final measurements")

        controller = self.controller_state() or {}
        result = {
            "test_id": test["test_id"],
            "mode": test["mode"],
            "rate_mbps": test["rate_mbps"],
            "duration_seconds": test["duration_seconds"],
            "threshold_percent": test["threshold_percent"],
            "active_path": controller.get("active_path"),
            "sender": sender,
            "receiver": receiver,
            "path_utilisation_percent": self.fresh_path_utilisation(controller),
            "recovery_time_ms": controller.get("recovery_time_ms"),
            "rule_installation_time_ms": controller.get("rule_installation_time_ms"),
            "congestion_confirmed_at": controller.get("congestion_confirmed_at"),
            "path_b_verified_at": controller.get("path_b_verified_at"),
            "congestion_route_timing": controller.get("last_congestion_route_timing"),
            "finished_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        self.append_result(result)
        self.last_result = result
        self.current_test = None
        self.sender_process = None
        self.receiver_process = None
        self.add_event(
            f"UDP test {test['test_id']} finished; receiver measured "
            f"{receiver['receiver_throughput_mbps']:.3f} Mbps",
            "success",
        )
        return {"stopped": True, "result": result}

    def fresh_path_utilisation(self, controller):
        if not self.port_map:
            return {"A": None, "B": None}
        values_by_link = controller.get("links", {})
        result = {"A": None, "B": None}
        for path_name, entries in self.port_map["forward_counters"].items():
            values = []
            for entry in entries:
                measurement = values_by_link.get(entry["link"], {})
                age = age_seconds(measurement.get("sampled_at"))
                utilisation = measurement.get("utilisation_percent")
                if age is None or age > LIVE_SECONDS or utilisation is None:
                    values = []
                    break
                values.append(utilisation)
            if values:
                result[path_name] = max(values)
        return result

    def close_logs(self):
        for name in ("sender_log", "receiver_log"):
            handle = getattr(self, name)
            if handle:
                handle.close()
                setattr(self, name, None)

    def append_result(self, result):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        sender = result["sender"]
        receiver = result["receiver"]
        row = {
            "test_id": result["test_id"],
            "mode": result["mode"],
            "offered_rate_mbps": result["rate_mbps"],
            "final_rate_mbps": sender.get("rate_mbps_final"),
            "rate_changes": json.dumps(sender.get("rate_changes", []), separators=(",", ":")),
            "duration_seconds": result["duration_seconds"],
            "active_path": result["active_path"],
            "sent_packets": sender.get("sent_packets"),
            "received_packets": receiver.get("received_expected_packets"),
            "lost_packets": receiver.get("lost_packets"),
            "packet_loss_percent": receiver.get("packet_loss_percent"),
            "receiver_throughput_mbps": receiver.get("receiver_throughput_mbps"),
            "path_a_utilisation_percent": result["path_utilisation_percent"].get("A"),
            "path_b_utilisation_percent": result["path_utilisation_percent"].get("B"),
            "recovery_time_ms": result["recovery_time_ms"],
            "rule_installation_time_ms": result["rule_installation_time_ms"],
            "congestion_confirmed_at": result["congestion_confirmed_at"],
            "rules_installation_started_at": (
                result["congestion_route_timing"].get("rules_installation_started_at")
                if result["congestion_route_timing"] else None
            ),
            "rules_installed_at": (
                result["congestion_route_timing"].get("rules_installed_at")
                if result["congestion_route_timing"] else None
            ),
            "flow_entries_verified_at": (
                result["congestion_route_timing"].get("flow_entries_verified_at")
                if result["congestion_route_timing"] else None
            ),
            "path_verified_at": (
                result["congestion_route_timing"].get("path_verified_at")
                if result["congestion_route_timing"] else None
            ),
        }
        has_file = RESULTS_FILE.exists()
        with RESULTS_FILE.open("a", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=list(row))
            if not has_file:
                writer.writeheader()
            writer.writerow(row)

    def export_results(self):
        return {
            "exported": RESULTS_FILE.exists(),
            "path": str(RESULTS_FILE) if RESULTS_FILE.exists() else None,
        }

    def state(self):
        with self.lock:
            self.finish_test_if_ready()
            controller_heartbeat = self.controller_state()
            switches_ready = bool(
                controller_heartbeat
                and controller_heartbeat.get("port_map_loaded")
                and set(controller_heartbeat.get("expected_switches", []))
                <= set(controller_heartbeat.get("connected_switches", []))
                and controller_heartbeat.get("expected_switches")
            )
            controller_available = bool(self.network and switches_ready)
            controller = controller_heartbeat if controller_available else None
            links = {}
            path_utilisation = {"A": None, "B": None}
            if controller:
                for name, values in controller.get("links", {}).items():
                    age = age_seconds(values.get("sampled_at"))
                    fresh = age is not None and age <= LIVE_SECONDS
                    links[name] = dict(values)
                    links[name]["fresh"] = fresh
                    if not fresh:
                        links[name]["rate_bps"] = None
                        links[name]["utilisation_percent"] = None
                if self.port_map:
                    for path_name, entries in self.port_map["forward_counters"].items():
                        samples = [links.get(item["link"], {}) for item in entries]
                        if (
                            samples
                            and all(sample.get("fresh") for sample in samples)
                            and all(
                                sample.get("utilisation_percent") is not None
                                for sample in samples
                            )
                        ):
                            path_utilisation[path_name] = max(
                                sample["utilisation_percent"] for sample in samples
                            )

            receiver_live = None
            if self.current_test:
                current = read_json(self.current_test["receiver_stats"])
                if current and self.receiver_process and self.receiver_process.poll() is None:
                    age = age_seconds_from_unix_ns(current.get("measured_at_unix_ns"))
                    if age is not None and age <= LIVE_SECONDS:
                        receiver_live = current

            events = list(self.events)
            if controller_heartbeat:
                events.extend(controller_heartbeat.get("events", []))
            events.sort(key=lambda item: item.get("time", ""))
            if not self.network:
                controller_error = "Network is stopped; live network measurements are hidden."
            elif not controller_heartbeat:
                controller_error = "Controller is unavailable; live measurements are hidden."
            elif not switches_ready:
                controller_error = "Waiting for all OpenFlow switches; live measurements are hidden."
            else:
                controller_error = None
            return {
                "network_running": self.network is not None,
                "test_running": self.current_test is not None,
                "test": {
                    key: value
                    for key, value in (self.current_test or {}).items()
                    if key not in (
                        "sender_summary", "receiver_stats", "sender_log",
                        "receiver_log", "rate_file",
                    )
                } or None,
                "controller_process_available": controller_heartbeat is not None,
                "controller_available": controller_available,
                "controller_error": controller_error,
                "controller": controller,
                "links": links,
                "path_utilisation_percent": path_utilisation,
                "receiver_live": receiver_live,
                "last_result": self.last_result,
                "events": events[-200:],
            }

    def handle(self, path, body):
        if path == "/command/start-network":
            return self.start_network()
        if path == "/command/stop-network":
            return self.stop_network()
        if path == "/command/start-test":
            return self.start_test(
                body.get("rate_mbps", 4),
                body.get("duration_seconds", 20),
                body.get("mode", "adaptive"),
                body.get("threshold_percent", 75),
            )
        if path == "/command/stop-test":
            return self.stop_test()
        if path == "/command/reset":
            return self.reset_experiment(
                body.get("mode", "static"), body.get("threshold_percent", 75)
            )
        if path == "/command/configure":
            return self.configure(
                body.get("mode", "static"), body.get("threshold_percent", 75)
            )
        if path == "/command/set-rate":
            return self.set_rate(body.get("rate_mbps", 1))
        if path == "/export":
            return self.export_results()
        raise ValueError(f"Unknown endpoint: {path}")


def age_seconds_from_unix_ns(value):
    if value is None:
        return None
    try:
        return max(time.time() - int(value) / 1_000_000_000, 0)
    except (TypeError, ValueError):
        return None


def make_handler(manager):
    class ApiHandler(BaseHTTPRequestHandler):
        def send_json(self, status, value):
            content = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/state":
                self.send_json(200, manager.state())
            elif path == "/events":
                self.send_json(200, {"events": manager.state()["events"]})
            elif path == "/health":
                state = manager.state()
                self.send_json(200, {"ok": True, "controller_available": state["controller_available"]})
            else:
                self.send_json(404, {"error": "Not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                result = manager.handle(path, body)
                self.send_json(200, result)
            except (ValueError, RuntimeError, OSError) as error:
                self.send_json(400, {"error": str(error)})
            except Exception as error:
                self.send_json(500, {"error": f"Experiment command failed: {error}"})

        def log_message(self, _format, *_args):
            return

    return ApiHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise SystemExit("Start this service with sudo; Mininet needs root privileges.")

    manager = ExperimentManager(args.controller_ip, args.controller_port)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(manager))
    print(f"Experiment manager listening at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop_network()
        server.server_close()


if __name__ == "__main__":
    main()

