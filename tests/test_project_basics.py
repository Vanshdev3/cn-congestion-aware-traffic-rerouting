import time
import sys
import types
import unittest

from flow_rules import rules_for_path
from metrics import path_utilisation, rate_from_counter, utilisation_percent
from udp_receiver import SequenceTracker, make_summary
from udp_sender import HEADER


def load_discover_port_map():
    """Load the map builder without requiring Mininet on the test machine."""
    mininet = types.ModuleType("mininet")
    mininet_link = types.ModuleType("mininet.link")
    mininet_net = types.ModuleType("mininet.net")
    mininet_node = types.ModuleType("mininet.node")
    mininet_topo = types.ModuleType("mininet.topo")
    mininet_link.TCLink = type("TCLink", (), {})
    mininet_net.Mininet = type("Mininet", (), {})
    mininet_node.OVSSwitch = type("OVSSwitch", (), {})
    mininet_node.RemoteController = type("RemoteController", (), {})
    mininet_topo.Topo = type("Topo", (), {})
    mininet.__path__ = []
    modules = {
        "mininet": mininet,
        "mininet.link": mininet_link,
        "mininet.net": mininet_net,
        "mininet.node": mininet_node,
        "mininet.topo": mininet_topo,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        import topology
        return topology.discover_port_map
    finally:
        for name, module in previous.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


discover_port_map = load_discover_port_map()


def example_port_map():
    def switch_end(name, port):
        return {"switch": name, "port": port}

    links = {
        "h1-s1": {"left": "h1", "right": "s1", "switch_ends": [switch_end("s1", 1)]},
        "s1-s2": {"left": "s1", "right": "s2", "switch_ends": [switch_end("s1", 2), switch_end("s2", 1)]},
        "s2-s4": {"left": "s2", "right": "s4", "switch_ends": [switch_end("s2", 2), switch_end("s4", 1)]},
        "s1-s3": {"left": "s1", "right": "s3", "switch_ends": [switch_end("s1", 3), switch_end("s3", 1)]},
        "s3-s4": {"left": "s3", "right": "s4", "switch_ends": [switch_end("s3", 2), switch_end("s4", 2)]},
        "s4-h2": {"left": "s4", "right": "h2", "switch_ends": [switch_end("s4", 3)]},
    }
    return {
        "switch_ids": {"s1": 1, "s2": 2, "s3": 3, "s4": 4},
        "links": links,
        "paths": {
            "A": ["h1", "s1", "s2", "s4", "h2"],
            "B": ["h1", "s1", "s3", "s4", "h2"],
        },
    }


class MeasurementTests(unittest.TestCase):
    def test_port_discovery_reads_ports_from_mininet_nodes(self):
        class FakeNode:
            def __init__(self, name, ports):
                self.name = name
                self.ports = ports

        class FakeInterface:
            def __init__(self, node, name):
                self.node = node
                self.name = name

        class FakeLink:
            def __init__(self, left, right):
                self.intf1 = left
                self.intf2 = right

        class FakeNetwork:
            def __init__(self):
                self.nodes = {}
                self.links = {}
                for name in ("h1", "h2", "s1", "s2", "s3", "s4"):
                    self.nodes[name] = FakeNode(name, {})

                link_specs = [
                    ("h1", "s1", None, 1),
                    ("s1", "s2", 2, 1),
                    ("s2", "s4", 2, 1),
                    ("s1", "s3", 3, 1),
                    ("s3", "s4", 2, 2),
                    ("s4", "h2", 3, None),
                ]
                for left, right, left_port, right_port in link_specs:
                    left_number = left_port or max(self.nodes[left].ports.values(), default=0) + 1
                    right_number = right_port or max(self.nodes[right].ports.values(), default=0) + 1
                    left_intf = FakeInterface(self.nodes[left], f"{left}-eth{left_number}")
                    right_intf = FakeInterface(self.nodes[right], f"{right}-eth{right_number}")
                    self.nodes[left].ports[left_intf] = left_number
                    self.nodes[right].ports[right_intf] = right_number
                    self.links[(left, right)] = FakeLink(left_intf, right_intf)

            def get(self, name):
                return self.nodes[name]

            def linksBetween(self, left, right):
                return [self.links.get((left.name, right.name)) or self.links[(right.name, left.name)]]

        port_map, _lines = discover_port_map(FakeNetwork())
        self.assertEqual(port_map["links"]["s1-s2"]["left_port"], 2)
        self.assertEqual(port_map["links"]["s1-s2"]["right_port"], 1)
        self.assertEqual(port_map["links"]["s4-h2"]["left_port"], 3)

    def test_rate_uses_counter_delta_and_elapsed_time(self):
        self.assertEqual(rate_from_counter(100, 1100, 2), 4000)
        self.assertIsNone(rate_from_counter(1100, 100, 2))
        self.assertIsNone(rate_from_counter(None, 100, 2))

    def test_utilisation_uses_configured_link_capacity(self):
        self.assertEqual(utilisation_percent(1_000_000, 2), 50)
        self.assertIsNone(utilisation_percent(None, 2))

    def test_path_utilisation_is_busiest_link(self):
        self.assertEqual(
            path_utilisation(
                {"first": 30, "second": 82},
                [{"link": "first"}, {"link": "second"}],
            ),
            82,
        )

    def test_path_a_and_b_use_the_documented_ports(self):
        port_map = example_port_map()
        path_a = rules_for_path(port_map, "A")
        path_b = rules_for_path(port_map, "B")
        self.assertEqual(
            [(item["switch"], item["in_port"], item["out_port"]) for item in path_a],
            [("s1", 1, 2), ("s2", 1, 2), ("s4", 1, 3)],
        )
        self.assertEqual(
            [(item["switch"], item["in_port"], item["out_port"]) for item in path_b],
            [("s1", 1, 3), ("s3", 1, 2), ("s4", 2, 3)],
        )

    def test_receiver_tracks_duplicates_and_out_of_order_separately(self):
        tracker = SequenceTracker()
        for sequence in (10, 11, 11, 13, 12):
            tracker.add(sequence)
        self.assertEqual(len(tracker.sequences), 4)
        self.assertEqual(tracker.duplicate_packets, 1)
        self.assertEqual(tracker.out_of_order_packets, 1)
        self.assertEqual(tracker.highest_sequence, 13)

    def test_loss_is_finalized_against_the_sender_summary(self):
        tracker = SequenceTracker()
        for sequence in (0, 1, 2, 4):
            tracker.add(sequence)
        summary = make_summary(
            "unit-test",
            tracker,
            4 * 1200,
            time.monotonic_ns() - 1_000_000_000,
            None,
            None,
            0,
            0,
            {"sent_packets": 5, "first_sequence": 0, "last_sequence": 4},
            True,
        )
        self.assertEqual(summary["lost_packets"], 1)
        self.assertEqual(summary["received_expected_packets"], 4)
        self.assertEqual(summary["packet_loss_percent"], 20)

    def test_udp_header_contains_sequence_and_timestamp(self):
        packet = HEADER.pack(42, 123456789)
        self.assertEqual(HEADER.unpack(packet), (42, 123456789))


if __name__ == "__main__":
    unittest.main()

