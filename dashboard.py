"""Tkinter controls for the local congestion and rerouting experiment."""

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import URLError
from urllib.request import Request, urlopen


API = "http://127.0.0.1:8765"
POLL_MS = 1000


class Dashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Congestion-Aware SDN Lab")
        self.root.geometry("1120x780")
        self.root.minsize(920, 680)
        self.messages = queue.Queue()
        self.poll_in_progress = False
        self.command_in_progress = False
        self.last_event_keys = set()

        self.rate = tk.DoubleVar(value=4.0)
        self.duration = tk.IntVar(value=20)
        self.threshold = tk.IntVar(value=75)
        self.mode = tk.StringVar(value="adaptive")
        self.build_window()
        self.root.after(100, self.read_messages)
        self.root.after(200, self.poll_state)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def build_window(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="Congestion-Aware SDN Lab",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")
        self.connection_label = ttk.Label(outer, text="Connecting to experiment manager…")
        self.connection_label.pack(anchor="w", pady=(2, 10))

        controls = ttk.LabelFrame(outer, text="Experiment controls", padding=10)
        controls.pack(fill="x", pady=(0, 10))
        for column in range(6):
            controls.columnconfigure(column, weight=1)

        self.add_scale(controls, 0, "UDP offered rate (Mbps)", self.rate, 0.1, 10.0, 1)
        self.add_spinbox(controls, 2, "Duration (seconds)", self.duration, 3, 300)
        self.add_spinbox(controls, 4, "Congestion threshold (%)", self.threshold, 10, 99)

        mode_frame = ttk.Frame(controls)
        mode_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(mode_frame, text="Routing mode:").pack(side="left", padx=(0, 8))
        ttk.Radiobutton(mode_frame, text="Static", value="static", variable=self.mode).pack(side="left")
        ttk.Radiobutton(mode_frame, text="Adaptive", value="adaptive", variable=self.mode).pack(side="left")

        buttons = ttk.Frame(controls)
        buttons.grid(row=2, column=2, columnspan=4, sticky="e", pady=(8, 0))
        self.button_count = 0
        self.add_button(buttons, "Start network", "/command/start-network", {})
        self.add_button(buttons, "Start test", "/command/start-test", self.test_settings)
        self.add_button(buttons, "Apply rate", "/command/set-rate", self.rate_settings)
        self.add_button(buttons, "Stop test", "/command/stop-test", {})
        self.add_button(buttons, "Reset", "/command/reset", self.test_settings)
        self.add_button(buttons, "Apply settings", "/command/configure", self.test_settings)
        self.add_button(buttons, "Stop network", "/command/stop-network", {})
        self.add_button(buttons, "Export CSV", "/export", {})

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        network_panel = ttk.LabelFrame(body, text="Live network", padding=10)
        network_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.status = ttk.Label(network_panel, text="Network: stopped   |   Active path: N/A")
        self.status.pack(anchor="w")
        self.topology = tk.Canvas(
            network_panel, height=300, background="#fbfcfe", highlightthickness=0
        )
        self.topology.pack(fill="x", pady=8)

        self.metric_labels = {}
        metrics = ttk.Frame(network_panel)
        metrics.pack(fill="x")
        names = [
            "Path A utilisation",
            "Path B utilisation",
            "Receiver throughput",
            "Packet loss",
            "Received / sent packets",
            "Inter-arrival variation",
            "Recovery time",
            "Rule installation time",
        ]
        for row, name in enumerate(names):
            column = (row % 2) * 2
            line = row // 2
            ttk.Label(metrics, text=name + ":").grid(
                row=line, column=column, sticky="w", padx=(0, 6), pady=2
            )
            value = ttk.Label(metrics, text="N/A", font=("Segoe UI", 10, "bold"))
            value.grid(row=line, column=column + 1, sticky="w", padx=(0, 18), pady=2)
            self.metric_labels[name] = value

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        result_panel = ttk.LabelFrame(right, text="Last completed run", padding=10)
        result_panel.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.result_label = ttk.Label(
            result_panel, text="No completed run yet", wraplength=320, justify="left"
        )
        self.result_label.pack(anchor="w")

        event_panel = ttk.LabelFrame(right, text="Event log", padding=8)
        event_panel.grid(row=1, column=0, sticky="nsew")
        event_panel.rowconfigure(0, weight=1)
        event_panel.columnconfigure(0, weight=1)
        self.event_text = tk.Text(
            event_panel, height=18, wrap="word", state="disabled", font=("Consolas", 9)
        )
        self.event_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(event_panel, orient="vertical", command=self.event_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.event_text.configure(yscrollcommand=scrollbar.set)
        self.action_label = ttk.Label(outer, text="Ready")
        self.action_label.pack(anchor="w", pady=(8, 0))

    def add_scale(self, parent, column, label, variable, minimum, maximum, row):
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=column, columnspan=2, sticky="ew", padx=(0, 10))
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Scale(
            frame, from_=minimum, to=maximum, variable=variable, orient="horizontal"
        ).pack(fill="x")
        ttk.Label(frame, textvariable=variable).pack(anchor="e")

    def add_spinbox(self, parent, column, label, variable, minimum, maximum):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, columnspan=2, sticky="ew", padx=(0, 10))
        ttk.Label(frame, text=label).pack(anchor="w")
        ttk.Spinbox(
            frame, from_=minimum, to=maximum, textvariable=variable, width=8
        ).pack(anchor="w", pady=(4, 0))

    def add_button(self, parent, label, path, body):
        index = self.button_count
        self.button_count += 1
        button = ttk.Button(
            parent,
            text=label,
            command=lambda: self.run_command(path, body),
        )
        button.grid(row=index // 4, column=index % 4, sticky="ew", padx=2, pady=2)
        parent.columnconfigure(index % 4, weight=1)

    def test_settings(self):
        return {
            "rate_mbps": round(self.rate.get(), 1),
            "duration_seconds": self.duration.get(),
            "mode": self.mode.get(),
            "threshold_percent": self.threshold.get(),
        }

    def rate_settings(self):
        return {"rate_mbps": round(self.rate.get(), 1)}

    @staticmethod
    def get_json(path):
        with urlopen(API + path, timeout=1.5) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def post_json(path, body):
        request = Request(
            API + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def poll_state(self):
        if not self.poll_in_progress and not self.command_in_progress:
            self.poll_in_progress = True

            def request_state():
                try:
                    self.messages.put(("state", self.get_json("/state")))
                except (URLError, TimeoutError, OSError, ValueError) as error:
                    self.messages.put(("connection_error", str(error)))

            threading.Thread(target=request_state, daemon=True).start()
        self.root.after(POLL_MS, self.poll_state)

    def run_command(self, path, body):
        if self.command_in_progress:
            return
        self.command_in_progress = True
        self.action_label.configure(text="Sending command…")
        payload = body() if callable(body) else body

        def send():
            try:
                result = self.post_json(path, payload)
                self.messages.put(("command", (path, result)))
            except Exception as error:
                self.messages.put(("command_error", str(error)))

        threading.Thread(target=send, daemon=True).start()

    def read_messages(self):
        while True:
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "state":
                self.poll_in_progress = False
                self.show_state(value)
            elif kind == "connection_error":
                self.poll_in_progress = False
                self.show_disconnected(value)
            elif kind == "command":
                path, result = value
                self.command_in_progress = False
                if path == "/export":
                    self.action_label.configure(
                        text=f"CSV: {result.get('path') or 'No results yet'}"
                    )
                elif path == "/command/start-test":
                    self.action_label.configure(
                        text=f"Started test {result.get('test_id', '')}"
                    )
                elif path == "/command/set-rate":
                    self.action_label.configure(
                        text=f"Sender rate set to {result.get('rate_mbps')} Mbps"
                    )
                else:
                    self.action_label.configure(
                        text=result.get("message", "Command completed")
                    )
            elif kind == "command_error":
                self.command_in_progress = False
                self.action_label.configure(text=value)
                messagebox.showerror("Experiment command failed", value)
        self.root.after(100, self.read_messages)

    def show_disconnected(self, details):
        self.connection_label.configure(
            text="Experiment manager unavailable — live values hidden"
        )
        self.status.configure(text="Network: unknown   |   Active path: N/A")
        for label in self.metric_labels.values():
            label.configure(text="N/A")
        self.draw_topology({}, None, {})
        self.action_label.configure(
            text="Start experiment_manager.py in Linux. " + details[:100]
        )

    def show_state(self, state):
        if not state.get("controller_available"):
            self.connection_label.configure(
                text=state.get("controller_error")
                or "Controller unavailable — live values hidden"
            )
        else:
            self.connection_label.configure(
                text="Experiment manager connected · controller live"
            )

        controller = state.get("controller") or {}
        live = state.get("controller_available")
        active_path = controller.get("active_path") if live else None
        route_status = controller.get("route_status", "waiting") if live else "unavailable"
        network_text = "running" if state.get("network_running") else "stopped"
        congestion = (
            ("detected" if controller.get("congestion_active") else "clear")
            if live
            else "N/A"
        )
        mode = controller.get("mode", "N/A") if live else "N/A"
        self.status.configure(
            text=(
                f"Network: {network_text}   |   Mode: {mode}   |   "
                f"Path: {active_path or 'N/A'}   |   Congestion: {congestion}   |   "
                f"Status: {route_status}"
            )
        )

        path_values = state.get("path_utilisation_percent", {}) if live else {}
        self.set_metric("Path A utilisation", percent(path_values.get("A")))
        self.set_metric("Path B utilisation", percent(path_values.get("B")))

        receiver = state.get("receiver_live") or {}
        self.set_metric("Receiver throughput", mbps(receiver.get("receiver_throughput_mbps")))
        self.set_metric("Packet loss", percent(receiver.get("packet_loss_percent")))
        received = receiver.get("unique_packets_received")
        sent = receiver.get("sent_packets")
        self.set_metric(
            "Received / sent packets",
            f"{received} / {sent}" if received is not None and sent is not None else "N/A",
        )
        variation = receiver.get("inter_arrival_variation_ms")
        self.set_metric(
            "Inter-arrival variation",
            f"{variation:.2f} ms" if variation is not None else "N/A",
        )
        self.set_metric("Recovery time", milliseconds(controller.get("recovery_time_ms")))
        self.set_metric(
            "Rule installation time",
            milliseconds(controller.get("rule_installation_time_ms")),
        )

        links = state.get("links", {}) if live else {}
        self.draw_topology(links, active_path, path_values)
        self.show_result(state.get("last_result"))
        self.add_events(state.get("events", []))

    def set_metric(self, name, value):
        self.metric_labels[name].configure(text=value)

    def draw_topology(self, links, active_path, path_values):
        canvas = self.topology
        canvas.delete("all")
        points = {
            "h1": (55, 145),
            "s1": (205, 145),
            "s2": (400, 70),
            "s3": (400, 220),
            "s4": (610, 145),
            "h2": (770, 145),
        }
        links_to_draw = {
            "h1-s1": ("h1", "s1", {"A", "B"}),
            "s1-s2": ("s1", "s2", {"A"}),
            "s2-s4": ("s2", "s4", {"A"}),
            "s1-s3": ("s1", "s3", {"B"}),
            "s3-s4": ("s3", "s4", {"B"}),
            "s4-h2": ("s4", "h2", {"A", "B"}),
        }
        for link_name, (left, right, used_by) in links_to_draw.items():
            first, second = points[left], points[right]
            selected = active_path in used_by
            selected_utilisation = path_values.get(active_path)
            congested = (
                selected_utilisation is not None
                and selected_utilisation >= self.threshold.get()
            )
            colour = "#9ca3af"
            if selected:
                colour = "#dc2626" if congested else "#15803d"
            canvas.create_line(*first, *second, fill=colour, width=5 if selected else 2)
            middle = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
            measurement = links.get(link_name, {})
            label = percent(measurement.get("utilisation_percent"))
            canvas.create_text(
                middle[0], middle[1] - 10,
                text=f"{link_name}: {label}",
                fill="#374151",
                font=("Segoe UI", 8),
            )

        for name, (x, y) in points.items():
            fill = "#dbeafe" if name.startswith("h") else "#e5e7eb"
            canvas.create_rectangle(
                x - 32, y - 22, x + 32, y + 22,
                fill=fill, outline="#475569", width=2,
            )
            canvas.create_text(x, y, text=name, font=("Segoe UI", 10, "bold"))

    def show_result(self, result):
        if not result:
            self.result_label.configure(text="No completed run yet")
            return
        if result.get("error"):
            self.result_label.configure(
                text=f"Run {result.get('test_id')} did not finish: {result['error']}"
            )
            return
        receiver = result.get("receiver", {})
        sender = result.get("sender", {})
        self.result_label.configure(
            text=(
                f"Run: {result.get('test_id')}\n"
                f"Mode: {result.get('mode')}  ·  Path: {result.get('active_path') or 'N/A'}\n"
                f"Rate: {result.get('rate_mbps')} Mbps initial, "
                f"{sender.get('rate_mbps_final', 'N/A')} Mbps final\n"
                f"Received: {mbps(receiver.get('receiver_throughput_mbps'))}  ·  "
                f"Loss: {percent(receiver.get('packet_loss_percent'))}\n"
                f"Packets: {receiver.get('received_expected_packets', 'N/A')} / "
                f"{receiver.get('sent_packets', 'N/A')} expected  ·  "
                f"Duplicates: {receiver.get('duplicate_packets', 'N/A')}  ·  "
                f"Out of order: {receiver.get('out_of_order_packets', 'N/A')}\n"
                f"Recovery: {milliseconds(result.get('recovery_time_ms'))}"
            )
        )

    def add_events(self, events):
        self.event_text.configure(state="normal")
        for event in events:
            key = (event.get("time"), event.get("message"))
            if key in self.last_event_keys:
                continue
            self.last_event_keys.add(key)
            self.event_text.insert(
                "end", f"{event.get('time', '')}  {event.get('message', '')}\n"
            )
        self.event_text.see("end")
        self.event_text.configure(state="disabled")


def percent(value):
    return f"{value:.1f}%" if isinstance(value, (int, float)) else "N/A"


def mbps(value):
    return f"{value:.3f} Mbps" if isinstance(value, (int, float)) else "N/A"


def milliseconds(value):
    return f"{value:.1f} ms" if isinstance(value, (int, float)) else "N/A"


def main():
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()

