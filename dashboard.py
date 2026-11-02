"""A small, readable Tkinter dashboard for the local SDN experiment."""

import json
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import URLError
from urllib.request import Request, urlopen


API = "http://127.0.0.1:8765"
POLL_MS = 1000
ANIMATION_MS = 90
BG = "#f3f6fb"
INK = "#172033"
MUTED = "#617089"
BLUE = "#2563eb"
GREEN = "#16834b"
RED = "#cc3d43"
AMBER = "#b66a08"
GRAY = "#a7b1c2"


class Dashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("SDN Traffic Rerouting Lab")
        self.root.geometry("1180x790")
        self.root.minsize(980, 700)
        self.root.configure(bg=BG)
        self.messages = queue.Queue()
        self.poll_in_progress = False
        self.command_in_progress = False
        self.last_event_keys = set()
        self.last_state = None
        self.animation_phase = 0.0
        self.animation_enabled = False
        self.active_path = None
        self.rate = tk.DoubleVar(value=3.0)
        self.duration = tk.IntVar(value=15)
        self.threshold = tk.IntVar(value=75)
        self.mode = tk.StringVar(value="adaptive")

        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("TFrame", background=BG)
        self.style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        self.style.configure("TLabelframe", background=BG, foreground=INK)
        self.style.configure("TLabelframe.Label", background=BG, foreground=INK,
                             font=("Segoe UI", 10, "bold"))
        self.style.configure("TButton", font=("Segoe UI", 10), padding=(9, 6))
        self.style.configure("TSpinbox", padding=5)

        self.build_window()
        self.root.after(100, self.read_messages)
        self.root.after(200, self.poll_state)
        self.root.after(ANIMATION_MS, self.animate_packets)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

    def build_window(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="SDN Traffic Rerouting Lab",
                  font=("Segoe UI", 22, "bold")).pack(anchor="w")
        self.connection_label = ttk.Label(header, text="Connecting to the experiment manager…",
                                          foreground=MUTED)
        self.connection_label.pack(anchor="w", pady=(2, 0))

        controls = ttk.LabelFrame(outer, text="Run an experiment", padding=12)
        controls.pack(fill="x", pady=(0, 12))
        for col in range(8):
            controls.columnconfigure(col, weight=1)
        self.add_scale(controls, 0, "Traffic offered", self.rate, 0.1, 10.0,
                       "Mbps", "%.1f")
        self.add_spinbox(controls, 2, "Run length", self.duration, 3, 300, "seconds")
        self.add_spinbox(controls, 4, "Congestion threshold", self.threshold, 10, 99, "%")
        mode_frame = ttk.Frame(controls)
        mode_frame.grid(row=0, column=6, columnspan=2, sticky="w", padx=8)
        ttk.Label(mode_frame, text="Routing mode").pack(anchor="w")
        choice = ttk.Frame(mode_frame)
        choice.pack(anchor="w", pady=7)
        ttk.Radiobutton(choice, text="Static", value="static", variable=self.mode).pack(side="left")
        ttk.Radiobutton(choice, text="Adaptive", value="adaptive", variable=self.mode).pack(side="left")

        buttons = ttk.Frame(controls)
        buttons.grid(row=1, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        for col in range(8):
            buttons.columnconfigure(col, weight=1)
        self.buttons = []
        self.add_button(buttons, "Start network", "/command/start-network", {}, 0)
        self.add_button(buttons, "Start test", "/command/start-test", self.test_settings, 1)
        self.add_button(buttons, "Apply live rate", "/command/set-rate", self.rate_settings, 2)
        self.add_button(buttons, "Stop test", "/command/stop-test", {}, 3)
        self.add_button(buttons, "Reset to Path A", "/command/reset", self.test_settings, 4)
        self.add_button(buttons, "Apply settings", "/command/configure", self.test_settings, 5)
        self.add_button(buttons, "Stop network", "/command/stop-network", {}, 6)
        self.add_button(buttons, "Export CSV", "/export", {}, 7)

        state_bar = ttk.Frame(outer)
        state_bar.pack(fill="x", pady=(0, 10))
        self.state_badge = tk.Label(state_bar, text="WAITING", bg="#e3e8f0", fg=INK,
                                    font=("Segoe UI", 10, "bold"), padx=12, pady=7)
        self.state_badge.pack(side="left")
        self.state_summary = ttk.Label(state_bar, text="Start the network to begin.",
                                       font=("Segoe UI", 11, "bold"))
        self.state_summary.pack(side="left", padx=12)

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.rowconfigure(0, weight=3)
        left.rowconfigure(1, weight=2)
        network = ttk.LabelFrame(left, text="Live network: highlighted route is the selected route",
                                 padding=8)
        network.grid(row=0, column=0, sticky="nsew", pady=(0, 9))
        network.rowconfigure(0, weight=1)
        network.columnconfigure(0, weight=1)
        self.topology = tk.Canvas(network, background="#ffffff", highlightthickness=0,
                                  height=330)
        self.topology.grid(row=0, column=0, sticky="nsew")
        self.topology.bind("<Configure>", self.on_canvas_resize)
        legend = ttk.Label(network,
                           text="Blue = selected route   Red = congestion confirmed   Gray = other route",
                           foreground=MUTED)
        legend.grid(row=1, column=0, sticky="w", pady=(6, 0))

        metrics = ttk.LabelFrame(left, text="Live measurements", padding=10)
        metrics.grid(row=1, column=0, sticky="nsew")
        for col in range(4):
            metrics.columnconfigure(col, weight=1)
        self.metric_labels = {}
        metric_names = [
            ("Path A load", 0, 0), ("Path B load", 0, 2),
            ("Receiver rate", 1, 0), ("Packet loss", 1, 2),
            ("Packets received", 2, 0), ("Inter-arrival variation", 2, 2),
            ("Recovery", 3, 0), ("Rule update", 3, 2),
        ]
        for name, row, col in metric_names:
            ttk.Label(metrics, text=name, foreground=MUTED).grid(
                row=row, column=col, sticky="w", padx=(0, 8), pady=5)
            value = ttk.Label(metrics, text="—", font=("Segoe UI", 12, "bold"))
            value.grid(row=row, column=col + 1, sticky="w", padx=(0, 12), pady=5)
            self.metric_labels[name] = value

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        result_frame = ttk.LabelFrame(right, text="Last completed test", padding=12)
        result_frame.grid(row=0, column=0, sticky="ew", pady=(0, 9))
        self.result_label = ttk.Label(result_frame, text="No completed test yet",
                                      wraplength=390, justify="left", font=("Segoe UI", 10))
        self.result_label.pack(anchor="w")

        events_frame = ttk.LabelFrame(right, text="What is happening", padding=8)
        events_frame.grid(row=1, column=0, sticky="nsew")
        events_frame.rowconfigure(0, weight=1)
        events_frame.columnconfigure(0, weight=1)
        self.event_text = tk.Text(events_frame, height=18, wrap="word", state="disabled",
                                  font=("Segoe UI", 9), bg="#ffffff", fg=INK,
                                  relief="flat", padx=8, pady=8)
        self.event_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(events_frame, orient="vertical", command=self.event_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.event_text.configure(yscrollcommand=scrollbar.set)
        self.event_text.tag_configure("time", foreground=MUTED)
        self.event_text.tag_configure("success", foreground=GREEN)
        self.event_text.tag_configure("warning", foreground=AMBER)
        self.event_text.tag_configure("error", foreground=RED)
        self.action_label = ttk.Label(outer, text="Ready", foreground=MUTED)
        self.action_label.pack(anchor="w", pady=(8, 0))
        self.draw_topology({}, None, None, False)

    def add_scale(self, parent, column, label, variable, minimum, maximum, unit, fmt):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, columnspan=2, sticky="ew", padx=8)
        ttk.Label(frame, text=label).pack(anchor="w")
        scale = ttk.Scale(frame, from_=minimum, to=maximum, variable=variable,
                          orient="horizontal", command=lambda _value: self.update_rate_label(fmt, unit))
        scale.pack(fill="x", pady=(8, 2))
        rate_value = ttk.Label(frame, text="", font=("Segoe UI", 10, "bold"))
        rate_value.pack(anchor="e")
        self.rate_label = rate_value
        self.update_rate_label(fmt, unit)

    def update_rate_label(self, fmt="%.1f", unit="Mbps"):
        if hasattr(self, "rate_label"):
            self.rate_label.configure(text=f"{fmt % self.rate.get()} {unit}")

    def add_spinbox(self, parent, column, label, variable, minimum, maximum, unit):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, columnspan=2, sticky="w", padx=8)
        ttk.Label(frame, text=label).pack(anchor="w")
        row = ttk.Frame(frame)
        row.pack(anchor="w", pady=7)
        ttk.Spinbox(row, from_=minimum, to=maximum, textvariable=variable, width=7).pack(side="left")
        ttk.Label(row, text=unit, foreground=MUTED).pack(side="left", padx=5)

    def add_button(self, parent, label, path, body, column):
        button = ttk.Button(parent, text=label, command=lambda: self.run_command(path, body))
        button.grid(row=0, column=column, sticky="ew", padx=3, pady=2)
        self.buttons.append(button)

    def test_settings(self):
        return {"rate_mbps": round(self.rate.get(), 1),
                "duration_seconds": int(self.duration.get()),
                "mode": self.mode.get(), "threshold_percent": int(self.threshold.get())}

    def rate_settings(self):
        return {"rate_mbps": round(self.rate.get(), 1)}

    @staticmethod
    def get_json(path):
        with urlopen(API + path, timeout=2.0) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def post_json(path, body):
        request = Request(API + path, data=json.dumps(body).encode("utf-8"),
                          headers={"Content-Type": "application/json"}, method="POST")
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
        for button in self.buttons:
            button.configure(state="disabled")
        self.action_label.configure(text="Working…")
        payload = body() if callable(body) else body
        def send():
            try:
                self.messages.put(("command", (path, self.post_json(path, payload))))
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
                for button in self.buttons:
                    button.configure(state="normal")
                if path == "/export":
                    self.action_label.configure(text=f"CSV saved at {result.get('path') or 'not available'}")
                elif path == "/command/start-test":
                    self.action_label.configure(text=f"Test started: {result.get('test_id', '')}")
                    self.animation_enabled = True
                elif path == "/command/stop-test":
                    self.action_label.configure(text="Test stopped and results saved")
                    self.animation_enabled = False
                else:
                    self.action_label.configure(text=result.get("message", "Command completed"))
                    if path == "/command/stop-network":
                        self.animation_enabled = False
                if path == "/command/start-network":
                    self.action_label.configure(text="Network started; waiting for live switch data")
            elif kind == "command_error":
                self.command_in_progress = False
                for button in self.buttons:
                    button.configure(state="normal")
                self.action_label.configure(text=value)
                messagebox.showerror("Experiment command failed", value)
        self.root.after(100, self.read_messages)

    def show_disconnected(self, details):
        self.connection_label.configure(text="Manager unavailable — live measurements hidden",
                                        foreground=RED)
        self.state_badge.configure(text="OFFLINE", bg="#fde8e8", fg=RED)
        self.state_summary.configure(text="Start the experiment manager in Linux.")
        self.set_all_metrics("—")
        self.draw_topology({}, None, None, False)
        self.action_label.configure(text=details[:120])

    def show_state(self, state):
        controller = state.get("controller") or {}
        live = bool(state.get("controller_available"))
        network_running = bool(state.get("network_running"))
        active_path = controller.get("active_path") if live else None
        congestion = bool(controller.get("congestion_active")) if live else False
        mode = controller.get("mode", "—") if live else "—"
        self.active_path = active_path
        self.animation_enabled = bool(state.get("test_running"))
        if live:
            self.connection_label.configure(text="Experiment manager connected · controller live",
                                            foreground=GREEN)
        else:
            self.connection_label.configure(text=state.get("controller_error") or "Controller unavailable",
                                            foreground=AMBER)

        if not network_running:
            badge, bg, fg = "NETWORK STOPPED", "#e3e8f0", INK
            summary = "Start the network before running a test."
        elif not live:
            badge, bg, fg = "WAITING FOR SWITCHES", "#fff1d6", AMBER
            summary = "The controller is waiting for all four switches."
        elif state.get("test_running"):
            badge = "CONGESTION DETECTED" if congestion else "TEST RUNNING"
            bg, fg = ("#fde8e8", RED) if congestion else ("#e8f0ff", BLUE)
            summary = (f"Traffic uses Path {active_path or '—'} · {mode} routing · "
                       f"{'congestion above threshold' if congestion else 'monitoring both routes'}")
        else:
            badge, bg, fg = "READY", "#e5f5eb", GREEN
            summary = f"Path {active_path or '—'} selected · {mode} routing · ready for traffic"
        self.state_badge.configure(text=badge, bg=bg, fg=fg)
        self.state_summary.configure(text=summary)

        path_values = state.get("path_utilisation_percent", {}) if live else {}
        self.set_metric("Path A load", percent(path_values.get("A")))
        self.set_metric("Path B load", percent(path_values.get("B")))
        receiver = state.get("receiver_live") or {}
        self.set_metric("Receiver rate", mbps(receiver.get("receiver_throughput_mbps")))
        self.set_metric("Packet loss", percent(receiver.get("packet_loss_percent")))
        received = receiver.get("unique_packets_received")
        sent = receiver.get("sent_packets")
        self.set_metric("Packets received", f"{received:,} / {sent:,}" if received is not None and sent is not None else "—")
        variation = receiver.get("inter_arrival_variation_ms")
        self.set_metric("Inter-arrival variation", f"{variation:.1f} ms" if isinstance(variation, (int, float)) else "—")
        self.set_metric("Recovery", milliseconds(controller.get("recovery_time_ms")))
        self.set_metric("Rule update", milliseconds(controller.get("rule_installation_time_ms")))
        self.draw_topology(state.get("links", {}) if live else {}, active_path,
                           path_values, congestion)
        self.show_result(state.get("last_result"))
        events = state.get("events", [])
        test = state.get("test") or {}
        result = state.get("last_result") or {}
        current_test_id = test.get("test_id") or result.get("test_id")
        if current_test_id:
            matching = [event for event in events
                        if current_test_id in event.get("message", "")]
            # Controller events do not carry the test ID, so use the test's
            # start event as the boundary and show only later events.
            start_index = next((i for i, event in enumerate(events)
                                if current_test_id in event.get("message", "")), None)
            if start_index is not None:
                events = events[start_index:]
            elif matching:
                events = matching
            elif not state.get("test_running"):
                events = []
        self.add_events(events)
        self.last_state = state

    def set_metric(self, name, value):
        self.metric_labels[name].configure(text=value)

    def set_all_metrics(self, value):
        for label in self.metric_labels.values():
            label.configure(text=value)

    def draw_topology(self, links, active_path, path_values, congestion):
        canvas = self.topology
        canvas.delete("all")
        width = max(canvas.winfo_width(), 420)
        height = max(canvas.winfo_height(), 260)
        margin = 42
        left_x = margin
        right_x = width - margin
        quarter_x = left_x + (right_x - left_x) * .25
        center_x = left_x + (right_x - left_x) * .5
        three_quarter_x = left_x + (right_x - left_x) * .75
        points = {
            "h1": (left_x, height * .5),
            "s1": (quarter_x, height * .5),
            "s2": (center_x, height * .22),
            "s3": (center_x, height * .78),
            "s4": (three_quarter_x, height * .5),
            "h2": (right_x, height * .5),
        }
        paths = {
            "h1-s1": ("h1", "s1", {"A", "B"}),
            "s1-s2": ("s1", "s2", {"A"}),
            "s2-s4": ("s2", "s4", {"A"}),
            "s1-s3": ("s1", "s3", {"B"}),
            "s3-s4": ("s3", "s4", {"B"}),
            "s4-h2": ("s4", "h2", {"A", "B"}),
        }
        for name, (left, right, belongs) in paths.items():
            x1, y1 = points[left]
            x2, y2 = points[right]
            selected = active_path in belongs
            color = BLUE if selected else GRAY
            if selected and congestion:
                color = RED
            width_px = 7 if selected else 3
            canvas.create_line(x1, y1, x2, y2, fill=color, width=width_px,
                               capstyle="round", tags=("link", name))
            sample = links.get(name, {})
            utilization = sample.get("utilisation_percent")
            label = percent(utilization) if isinstance(utilization, (int, float)) else "—"
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            canvas.create_text(mx, my - 16, text=f"{name}  {label}", fill=INK,
                               font=("Segoe UI", 9, "bold" if selected else "normal"))

        for name, (x, y) in points.items():
            fill = "#e8f0ff" if name.startswith("h") else "#f0f2f6"
            canvas.create_rectangle(x - 30, y - 21, x + 30, y + 21,
                                    fill=fill, outline="#71809a", width=2)
            canvas.create_text(x, y, text=name, fill=INK,
                               font=("Segoe UI", 10, "bold"))

        if self.animation_enabled and active_path in ("A", "B"):
            selected_links = [name for name, (_l, _r, belongs) in paths.items()
                              if active_path in belongs]
            index = int(self.animation_phase) % len(selected_links)
            name = selected_links[index]
            left, right, _belongs = paths[name]
            x1, y1 = points[left]
            x2, y2 = points[right]
            fraction = self.animation_phase % 1
            x = x1 + (x2 - x1) * fraction
            y = y1 + (y2 - y1) * fraction
            packet_color = "#7f1d1d" if congestion else "#f59e0b"
            canvas.create_oval(x - 9, y - 9, x + 9, y + 9,
                               fill=packet_color, outline="#ffffff", width=2,
                               tags="packet")
            canvas.create_text(width - 100, 18,
                               text="CONGESTED PACKET" if congestion else "UDP PACKET",
                               fill=packet_color, font=("Segoe UI", 9, "bold"))

    def animate_packets(self):
        if self.animation_enabled and self.last_state:
            self.animation_phase += 0.07
            controller = self.last_state.get("controller") or {}
            self.draw_topology(self.last_state.get("links", {}),
                               controller.get("active_path"),
                               self.last_state.get("path_utilisation_percent", {}),
                               bool(controller.get("congestion_active")))
        self.root.after(ANIMATION_MS, self.animate_packets)

    def on_canvas_resize(self, _event):
        if self.last_state:
            controller = self.last_state.get("controller") or {}
            self.draw_topology(
                self.last_state.get("links", {}),
                controller.get("active_path"),
                self.last_state.get("path_utilisation_percent", {}),
                bool(controller.get("congestion_active")),
            )

    def show_result(self, result):
        if not result:
            self.result_label.configure(text="No completed test yet")
            return
        if result.get("error"):
            self.result_label.configure(text=f"Test failed: {result['error']}")
            return
        receiver = result.get("receiver", {})
        sender = result.get("sender", {})
        self.result_label.configure(text=(
            f"ID: {result.get('test_id')}\n"
            f"Mode: {result.get('mode', '—').title()}   ·   Final route: {result.get('active_path') or '—'}\n"
            f"Offered rate: {sender.get('rate_mbps_final', result.get('rate_mbps', '—'))} Mbps   ·   "
            f"Duration: {result.get('duration_seconds', '—')} s\n"
            f"Delivered: {mbps(receiver.get('receiver_throughput_mbps'))}   ·   "
            f"Loss: {percent(receiver.get('packet_loss_percent'))}\n"
            f"Packets: {count(receiver.get('received_expected_packets'))} received / "
            f"{count(receiver.get('sent_packets'))} sent   ·   "
            f"Recovery: {milliseconds(result.get('recovery_time_ms'))}"
        ))

    def add_events(self, events):
        self.event_text.configure(state="normal")
        friendly = {
            "Installing initial Path A forwarding rules": "Setting the initial route to Path A…",
            "Path A flow entries verified in every required switch": "Path A forwarding is installed and verified.",
            "Path B flow entries verified; checking its link counters": "Path B rules are verified; checking that packets use it…",
            "Traffic-counter changes verified on Path B": "Packets are now confirmed on Path B.",
            "Traffic-counter changes verified on Path A": "Packets are now confirmed on Path A.",
            "Measured utilisation has fallen below the threshold": "Traffic load is below the congestion threshold again.",
        }
        for event in events:
            key = (event.get("time"), event.get("message"))
            if key in self.last_event_keys:
                continue
            self.last_event_keys.add(key)
            message = event.get("message", "")
            if message.startswith("Congestion confirmed on Path "):
                message = message.replace("Congestion confirmed on Path ", "Congestion detected on route ")
                message = message.replace("measured utilisation", "measured link load")
            elif message.startswith("Installing Path "):
                message = message.replace("Installing Path ", "Switching traffic to Path ")
                message = message.replace(" rules after congestion detection", " after congestion was confirmed")
            elif message.startswith("Recovery verified in "):
                message = message.replace("Recovery verified in ", "Traffic confirmed on the new route after ")
                message = message.replace("(congestion confirmation to alternate-path counters)", "(from congestion detection to packet counters on the new route)")
            else:
                message = friendly.get(message, message)
            timestamp = event.get("time", "")
            clock = timestamp[11:19] if len(timestamp) >= 19 else ""
            self.event_text.insert("end", f"{clock}  ", "time")
            self.event_text.insert("end", message + "\n", event.get("kind", "info"))
        lines = int(self.event_text.index("end-1c").split(".")[0])
        if lines > 100:
            self.event_text.delete("1.0", f"{lines - 100}.0")
        self.event_text.see("end")
        self.event_text.configure(state="disabled")


def count(value):
    return f"{value:,}" if isinstance(value, int) else "—"


def percent(value):
    return f"{value:.1f}%" if isinstance(value, (int, float)) else "—"


def mbps(value):
    return f"{value:.2f} Mbps" if isinstance(value, (int, float)) else "—"


def milliseconds(value):
    return f"{value:.0f} ms" if isinstance(value, (int, float)) else "—"


def main():
    root = tk.Tk()
    Dashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
