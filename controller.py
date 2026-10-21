"""OS-Ken controller for the measured two-path UDP experiment."""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, DEAD_DISPATCHER, MAIN_DISPATCHER
from os_ken.controller.handler import set_ev_cls
from os_ken.lib import hub
from os_ken.ofproto import ofproto_v1_3

from flow_rules import rules_for_path
from metrics import rate_from_counter, utilisation_percent


LOG = logging.getLogger("congestion_controller")
COOKIE_PREFIX = 0xC0DE000000000000
COOKIE_MASK = 0xFFFFFFFF00000000
SOURCE_IP = "10.0.0.1"
DESTINATION_IP = "10.0.0.2"
UDP_PORT = 5001


def write_json(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(target)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class CongestionController(app_manager.OSKenApp):
    """Poll port counters and change the UDP flow's OpenFlow path."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.datapaths = {}
        self.port_map = None
        self.last_command_id = 0
        self.mode = "static"
        self.threshold_percent = 75.0
        self.required_high_samples = 3
        self.high_samples = 0
        self.low_samples = 0
        self.cooldown_seconds = 5
        self.last_reroute_ns = 0

        self.active_path = None
        self.candidate_path = None
        self.transition = None
        self.transition_number = 0
        self.flow_entries_verified = False
        self.last_route_timing = None
        self.path_b_verified_at = None
        self.recovery_time_ms = None
        self.last_rule_installation_time_ms = None
        self.barrier_xids = {}
        self.flow_xids = {}
        self.flow_check = None

        self.previous_link_counters = {}
        self.link_measurements = {}
        self.latest_path_utilisation = {"A": None, "B": None}
        self.congestion_active = False
        self.congestion_confirmed_at = None
        self.congestion_confirmed_ns = None
        self.last_event = None
        self.events = []
        self.route_status = "waiting_for_switches"
        self.last_error = None
        self.pending_port_replies = set()
        self.port_reply_xids = {}
        self.sample_ports = {}
        self.sample_started_ns = None
        self.last_port_request_ns = 0

        self.port_map_file = "run/port_map.json"
        self.command_file = "run/controller_command.json"
        self.state_file = "run/controller_state.json"
        self.monitor_thread = hub.spawn(self.monitor_loop)

    def add_event(self, message, kind="info"):
        event = {"time": now_iso(), "kind": kind, "message": message}
        self.events.append(event)
        self.events = self.events[-100:]
        LOG.info(message)

    def expected_dpids(self):
        if not self.port_map:
            return set()
        return set(self.port_map["switch_ids"].values())

    def all_switches_connected(self):
        expected = self.expected_dpids()
        return bool(expected) and expected.issubset(self.datapaths)

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def switch_state_changed(self, event):
        datapath = event.datapath
        if event.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
            switch_name = self.switch_name(datapath.id)
            self.add_event(f"OpenFlow switch connected: {switch_name} ({datapath.id})")
        elif event.state == DEAD_DISPATCHER:
            self.datapaths.pop(datapath.id, None)
            self.add_event(
                f"OpenFlow switch disconnected: {self.switch_name(datapath.id)}",
                "error",
            )
            self.route_status = "switch_disconnected"

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_received(self, event):
        datapath = event.msg.datapath
        self.datapaths[datapath.id] = datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch()
        instructions = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, [])
        ]
        datapath.send_msg(
            parser.OFPFlowMod(
                datapath=datapath,
                table_id=0,
                priority=0,
                match=match,
                instructions=instructions,
            )
        )
        self.add_event(f"Switch ready for OpenFlow 1.3: {self.switch_name(datapath.id)}")

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_received(self, event):
        message = event.msg
        datapath_id = message.datapath.id
        if message.xid not in self.port_reply_xids:
            return

        self.sample_ports[datapath_id] = {
            item.port_no: {"rx_bytes": item.rx_bytes, "tx_bytes": item.tx_bytes}
            for item in message.body
        }
        more = bool(message.flags & message.datapath.ofproto.OFPMPF_REPLY_MORE)
        if more:
            return

        self.port_reply_xids.pop(message.xid, None)
        self.pending_port_replies.discard(datapath_id)
        if not self.pending_port_replies:
            self.finish_port_sample()

    @set_ev_cls(ofp_event.EventOFPBarrierReply, MAIN_DISPATCHER)
    def barrier_reply_received(self, event):
        message = event.msg
        pending = self.barrier_xids.pop(message.xid, None)
        if not pending or not self.transition:
            return
        transition_id, datapath_id = pending
        if transition_id != self.transition["id"]:
            return

        self.transition["pending_barriers"].discard(datapath_id)
        if self.transition["pending_barriers"]:
            return

        self.transition["rules_installed_ns"] = time.monotonic_ns()
        self.transition["rules_installed_at"] = now_iso()
        self.transition["pending_flow_replies"] = set(
            self.transition["expected_by_dpid"]
        )
        self.transition["seen_rules"] = set()
        self.route_status = "checking_flow_entries"
        for dpid in self.transition["pending_flow_replies"]:
            datapath = self.datapaths.get(dpid)
            if not datapath:
                self.fail_transition("A switch disconnected before flow verification")
                return
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto
            request = parser.OFPFlowStatsRequest(
                datapath,
                flags=0,
                table_id=ofproto.OFPTT_ALL,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                cookie=0,
                cookie_mask=0,
                match=parser.OFPMatch(),
            )
            datapath.set_xid(request)
            self.flow_xids[request.xid] = (self.transition["id"], dpid)
            datapath.send_msg(request)

    @set_ev_cls(ofp_event.EventOFPFlowStatsReply, MAIN_DISPATCHER)
    def flow_stats_received(self, event):
        message = event.msg
        request = self.flow_xids.get(message.xid)
        if not request or not self.transition:
            return
        transition_id, datapath_id = request
        if transition_id != self.transition["id"]:
            return

        for stat in message.body:
            if not self.is_project_flow(stat.match):
                continue
            for instruction in stat.instructions:
                for action in getattr(instruction, "actions", []):
                    if hasattr(action, "port"):
                        self.transition["seen_rules"].add(
                            (datapath_id, stat.match.get("in_port"), action.port)
                        )

        more = bool(message.flags & message.datapath.ofproto.OFPMPF_REPLY_MORE)
        if more:
            return

        self.flow_xids.pop(message.xid, None)
        self.transition["pending_flow_replies"].discard(datapath_id)
        if self.transition["pending_flow_replies"]:
            return

        expected = self.transition["expected_rules"]
        if not expected.issubset(self.transition["seen_rules"]):
            missing = expected - self.transition["seen_rules"]
            self.fail_transition(f"Flow-table verification missed rules: {sorted(missing)}")
            return
        self.rules_verified()

    @staticmethod
    def is_project_flow(match):
        return (
            match.get("eth_type") == 0x0800
            and match.get("ip_proto") == 17
            and match.get("ipv4_src") == SOURCE_IP
            and match.get("ipv4_dst") == DESTINATION_IP
            and match.get("udp_dst") == UDP_PORT
        )

    def switch_name(self, datapath_id):
        if not self.port_map:
            return f"dpid-{datapath_id}"
        for name, value in self.port_map["switch_ids"].items():
            if value == datapath_id:
                return name
        return f"dpid-{datapath_id}"

    def monitor_loop(self):
        while True:
            try:
                self.load_port_map()
                self.read_command()
                if self.all_switches_connected():
                    self.start_initial_route_if_needed()
                    self.request_port_stats_if_ready()
                self.check_transition_timeout()
                self.write_state()
            except Exception:
                LOG.exception("Controller monitor loop failed")
                self.last_error = "Controller monitor loop failed; see controller log"
            hub.sleep(0.2)

    def load_port_map(self):
        if self.port_map:
            return
        saved_map = read_json(self.port_map_file)
        if not saved_map:
            return
        required = {"switch_ids", "links", "paths", "forward_counters"}
        if not required.issubset(saved_map):
            self.last_error = "The discovered port map is missing required fields"
            return
        self.port_map = saved_map
        self.add_event("Loaded the discovered Mininet port map")

    def read_command(self):
        command = read_json(self.command_file)
        if not command:
            return
        command_id = int(command.get("command_id", 0))
        if command_id <= self.last_command_id:
            return
        self.last_command_id = command_id

        mode = command.get("mode", self.mode)
        threshold = float(command.get("threshold_percent", self.threshold_percent))
        if mode in ("static", "adaptive"):
            self.mode = mode
        if 10 <= threshold <= 99:
            self.threshold_percent = threshold

        action = command.get("action")
        if action == "reset":
            self.reset_experiment()
        elif action == "configure":
            self.add_event(
                f"Controller settings changed: {self.mode} mode, "
                f"{self.threshold_percent:g}% threshold"
            )

    def reset_experiment(self):
        self.high_samples = 0
        self.low_samples = 0
        self.congestion_active = False
        self.congestion_confirmed_at = None
        self.congestion_confirmed_ns = None
        self.path_b_verified_at = None
        self.recovery_time_ms = None
        self.last_route_timing = None
        self.last_rule_installation_time_ms = None
        self.flow_entries_verified = False
        self.previous_link_counters.clear()
        self.link_measurements.clear()
        self.latest_path_utilisation = {"A": None, "B": None}
        self.last_reroute_ns = 0
        self.last_error = None
        self.transition = None
        self.candidate_path = None
        self.active_path = None
        self.flow_entries_verified = False
        self.barrier_xids.clear()
        self.flow_xids.clear()
        self.pending_port_replies.clear()
        self.port_reply_xids.clear()
        self.sample_ports.clear()
        self.sample_started_ns = None
        self.last_port_request_ns = 0
        self.route_status = "resetting"
        self.events.clear()
        self.add_event("Experiment measurements and controller state reset")
        if self.all_switches_connected() and self.port_map:
            self.start_route_change("A", reason="initial")

    def start_initial_route_if_needed(self):
        if self.port_map and not self.active_path and not self.transition:
            self.start_route_change("A", reason="initial")

    def request_port_stats_if_ready(self):
        if not self.port_map or self.transition and self.route_status == "resetting":
            return
        now_ns = time.monotonic_ns()
        if self.pending_port_replies:
            if self.sample_started_ns and now_ns - self.sample_started_ns < 5_000_000_000:
                return
            self.add_event("A switch did not answer the port-statistics request", "error")
            self.pending_port_replies.clear()
            self.port_reply_xids.clear()

        if now_ns - self.last_port_request_ns < 1_000_000_000:
            return

        self.last_port_request_ns = now_ns
        self.sample_started_ns = now_ns
        self.pending_port_replies = set(self.expected_dpids())
        self.sample_ports = {}
        for datapath_id in sorted(self.pending_port_replies):
            datapath = self.datapaths.get(datapath_id)
            if not datapath:
                self.pending_port_replies.discard(datapath_id)
                continue
            request = datapath.ofproto_parser.OFPPortStatsRequest(
                datapath, 0, datapath.ofproto.OFPP_ANY
            )
            datapath.set_xid(request)
            self.port_reply_xids[request.xid] = datapath_id
            datapath.send_msg(request)
        if not self.pending_port_replies:
            self.finish_port_sample()

    def finish_port_sample(self):
        now_ns = time.monotonic_ns()
        by_link = {}
        for path_entries in self.port_map["forward_counters"].values():
            for entry in path_entries:
                by_link[entry["link"]] = entry

        for link_name, entry in by_link.items():
            port_values = self.sample_ports.get(entry["dpid"], {}).get(entry["port"])
            if not port_values:
                continue
            counter = port_values[entry["counter"]]
            previous = self.previous_link_counters.get(link_name)
            if previous:
                elapsed = (now_ns - previous["time_ns"]) / 1_000_000_000
                rate = rate_from_counter(previous["bytes"], counter, elapsed)
            else:
                rate = None
            self.previous_link_counters[link_name] = {
                "bytes": counter,
                "time_ns": now_ns,
            }
            self.link_measurements[link_name] = {
                "switch": entry["switch"],
                "port": entry["port"],
                "counter": entry["counter"],
                "bytes_total": counter,
                "rate_bps": rate,
                "utilisation_percent": utilisation_percent(
                    rate, entry["bandwidth_mbps"]
                ),
                "capacity_mbps": entry["bandwidth_mbps"],
                "sampled_at": now_iso(),
            }

        for path_name, entries in self.port_map["forward_counters"].items():
            values = [
                self.link_measurements.get(item["link"], {}).get(
                    "utilisation_percent"
                )
                for item in entries
            ]
            measured = [value for value in values if value is not None]
            self.latest_path_utilisation[path_name] = max(measured) if measured else None

        self.verify_path_movement()
        self.evaluate_congestion()
        self.sample_started_ns = None

    def evaluate_congestion(self):
        if not self.active_path or self.transition:
            return
        current = self.latest_path_utilisation.get(self.active_path)
        if current is None:
            return

        if current >= self.threshold_percent:
            self.high_samples += 1
            self.low_samples = 0
            if self.high_samples >= self.required_high_samples and not self.congestion_active:
                self.congestion_active = True
                self.congestion_confirmed_at = now_iso()
                self.congestion_confirmed_ns = time.monotonic_ns()
                self.add_event(
                    f"Congestion confirmed on Path {self.active_path} "
                    f"({current:.1f}% measured utilisation)",
                    "warning",
                )
            if self.congestion_active and self.mode == "adaptive":
                self.try_adaptive_reroute(current)
        else:
            self.high_samples = 0
            if self.congestion_active:
                self.low_samples += 1
                if self.low_samples >= 2:
                    self.congestion_active = False
                    self.low_samples = 0
                    self.add_event("Measured utilisation has fallen below the threshold")

    def try_adaptive_reroute(self, current_utilisation):
        now_ns = time.monotonic_ns()
        if now_ns - self.last_reroute_ns < self.cooldown_seconds * 1_000_000_000:
            return
        alternative = "B" if self.active_path == "A" else "A"
        alternative_utilisation = self.latest_path_utilisation.get(alternative)
        if (
            alternative_utilisation is None
            or alternative_utilisation >= self.threshold_percent
            or alternative_utilisation >= current_utilisation
        ):
            return
        self.start_route_change(alternative, reason="congestion")

    def start_route_change(self, path_name, reason):
        if not self.port_map or not self.all_switches_connected():
            self.route_status = "waiting_for_switches"
            return

        path_rules = rules_for_path(self.port_map, path_name)
        by_dpid = {}
        for rule in path_rules:
            by_dpid.setdefault(rule["dpid"], []).append(rule)

        self.transition_number += 1
        started_ns = time.monotonic_ns()
        transition = {
            "id": self.transition_number,
            "path": path_name,
            "reason": reason,
            "started_ns": started_ns,
            "started_at": now_iso(),
            "confirmed_ns": self.congestion_confirmed_ns,
            "confirmed_at": self.congestion_confirmed_at,
            "pending_barriers": set(self.expected_dpids()),
            "expected_by_dpid": {
                dpid: [(rule["in_port"], rule["out_port"]) for rule in rules]
                for dpid, rules in by_dpid.items()
            },
            "expected_rules": {
                (dpid, rule["in_port"], rule["out_port"])
                for dpid, rules in by_dpid.items()
                for rule in rules
            },
        }
        self.transition = transition
        self.candidate_path = path_name
        self.flow_entries_verified = False
        self.route_status = "installing_rules"
        self.last_error = None
        if reason == "congestion":
            self.last_reroute_ns = started_ns
            self.add_event(f"Installing Path {path_name} rules after congestion detection")
        else:
            self.add_event(f"Installing initial Path {path_name} forwarding rules")

        for datapath_id, datapath in self.datapaths.items():
            self.delete_project_flows(datapath)
            for rule in by_dpid.get(datapath_id, []):
                self.add_udp_flow(datapath, rule)
            barrier = datapath.ofproto_parser.OFPBarrierRequest(datapath)
            datapath.set_xid(barrier)
            self.barrier_xids[barrier.xid] = (transition["id"], datapath_id)
            datapath.send_msg(barrier)

    def delete_project_flows(self, datapath):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        datapath.send_msg(
            parser.OFPFlowMod(
                datapath=datapath,
                cookie=COOKIE_PREFIX,
                cookie_mask=COOKIE_MASK,
                table_id=ofproto.OFPTT_ALL,
                command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                match=parser.OFPMatch(),
            )
        )

    def add_udp_flow(self, datapath, rule):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        match = parser.OFPMatch(
            in_port=rule["in_port"],
            eth_type=0x0800,
            ip_proto=17,
            ipv4_src=SOURCE_IP,
            ipv4_dst=DESTINATION_IP,
            udp_dst=UDP_PORT,
        )
        actions = [parser.OFPActionOutput(rule["out_port"])]
        instructions = [
            parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)
        ]
        datapath.send_msg(
            parser.OFPFlowMod(
                datapath=datapath,
                cookie=COOKIE_PREFIX | self.transition_number,
                table_id=0,
                command=ofproto.OFPFC_ADD,
                priority=100,
                idle_timeout=0,
                hard_timeout=0,
                match=match,
                instructions=instructions,
            )
        )

    def rules_verified(self):
        transition = self.transition
        if not transition:
            return
        transition["rules_verified_at"] = now_iso()
        self.flow_entries_verified = True
        path_name = transition["path"]
        if transition["reason"] == "initial":
            self.active_path = path_name
            self.candidate_path = None
            self.route_status = "active"
            self.save_route_timing(transition, None)
            self.add_event(f"Path {path_name} flow entries verified in every required switch")
            self.transition = None
            return

        other_paths = set(self.port_map["paths"]) - {path_name}
        other_links = {
            item["link"]
            for other in other_paths
            for item in self.port_map["forward_counters"][other]
        }
        transition["verify_links"] = [
            item["link"]
            for item in self.port_map["forward_counters"][path_name]
            if item["link"] not in other_links
        ]
        transition["counter_baseline"] = {
            name: self.link_measurements.get(name, {}).get("bytes_total")
            for name in transition["verify_links"]
        }
        transition["flow_entries_verified"] = True
        self.route_status = "waiting_for_path_counters"
        self.add_event(f"Path {path_name} flow entries verified; checking its link counters")

    def verify_path_movement(self):
        transition = self.transition
        if not transition or not transition.get("flow_entries_verified"):
            return
        baselines = transition["counter_baseline"]
        for link_name in transition["verify_links"]:
            current = self.link_measurements.get(link_name, {}).get("bytes_total")
            baseline = baselines.get(link_name)
            if current is None:
                return
            if baseline is None:
                baselines[link_name] = current
                return
            if current <= baseline:
                return

        self.finish_route_change()

    def finish_route_change(self):
        transition = self.transition
        if not transition:
            return
        self.active_path = transition["path"]
        self.candidate_path = None
        self.route_status = "active"
        verified_at = now_iso()
        self.save_route_timing(transition, verified_at)
        self.add_event(f"Traffic-counter changes verified on Path {self.active_path}")

        if transition["reason"] == "congestion" and transition["confirmed_ns"]:
            verified_ns = time.monotonic_ns()
            self.recovery_time_ms = (verified_ns - transition["confirmed_ns"]) / 1_000_000
            if self.active_path == "B":
                self.path_b_verified_at = verified_at
            self.congestion_active = False
            self.add_event(
                f"Recovery verified in {self.recovery_time_ms:.1f} ms "
                f"(congestion confirmation to alternate-path counters)",
                "success",
            )
        self.transition = None

    def save_route_timing(self, transition, path_verified_at):
        installed_ns = transition.get("rules_installed_ns")
        self.last_rule_installation_time_ms = (
            (installed_ns - transition["started_ns"]) / 1_000_000
            if installed_ns
            else None
        )
        self.last_route_timing = {
            "path": transition["path"],
            "congestion_confirmed_at": transition.get("confirmed_at"),
            "rules_installation_started_at": transition["started_at"],
            "rules_installed_at": transition.get("rules_installed_at"),
            "flow_entries_verified_at": transition.get("rules_verified_at"),
            "path_verified_at": path_verified_at,
            "rule_installation_time_ms": self.last_rule_installation_time_ms,
        }

    def fail_transition(self, reason):
        self.last_error = reason
        self.route_status = "verification_failed"
        self.flow_entries_verified = False
        self.active_path = None
        self.add_event(reason, "error")
        self.transition = None
        self.candidate_path = None

    def check_transition_timeout(self):
        if not self.transition:
            return
        elapsed = time.monotonic_ns() - self.transition["started_ns"]
        if elapsed > 10_000_000_000:
            self.fail_transition(
                f"Path {self.transition['path']} did not pass rule and counter "
                "verification within 10 seconds"
            )

    def write_state(self):
        path_measurements = {
            name: value for name, value in self.link_measurements.items()
        }
        state = {
            "controller_connected": True,
            "updated_at": now_iso(),
            "mode": self.mode,
            "threshold_percent": self.threshold_percent,
            "expected_switches": sorted(self.switch_name(dpid) for dpid in self.expected_dpids()),
            "connected_switches": sorted(self.switch_name(dpid) for dpid in self.datapaths),
            "port_map_loaded": self.port_map is not None,
            "active_path": self.active_path,
            "candidate_path": self.candidate_path,
            "route_status": self.route_status,
            "flow_entries_verified": self.flow_entries_verified,
            "congestion_active": self.congestion_active,
            "congestion_confirmed_at": self.congestion_confirmed_at,
            "path_b_verified_at": self.path_b_verified_at,
            "recovery_time_ms": self.recovery_time_ms,
            "rule_installation_time_ms": self.rule_installation_time_ms(),
            "last_route_timing": self.last_route_timing,
            "path_utilisation_percent": self.latest_path_utilisation,
            "links": path_measurements,
            "last_error": self.last_error,
            "command_id": self.last_command_id,
            "events": self.events,
        }
        write_json(self.state_file, state)

    def rule_installation_time_ms(self):
        if not self.transition:
            return self.last_rule_installation_time_ms
        installed_ns = self.transition.get("rules_installed_ns")
        if not installed_ns:
            return None
        return (installed_ns - self.transition["started_ns"]) / 1_000_000


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    from os_ken.cmd import manager

    manager.main()


if __name__ == "__main__":
    main()

