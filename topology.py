"""The two-path Mininet topology and its discovered switch-port map."""

import json
from pathlib import Path

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.topo import Topo


LINKS = [
    # name, node on the left, node on the right, left switch port,
    # right switch port, bandwidth in Mbps
    ("h1-s1", "h1", "s1", None, 1, 10),
    ("s1-s2", "s1", "s2", 2, 1, 2),
    ("s2-s4", "s2", "s4", 2, 1, 2),
    ("s1-s3", "s1", "s3", 3, 1, 5),
    ("s3-s4", "s3", "s4", 2, 2, 5),
    ("s4-h2", "s4", "h2", 3, None, 10),
]

PATHS = {
    "A": ["h1", "s1", "s2", "s4", "h2"],
    "B": ["h1", "s1", "s3", "s4", "h2"],
}

SWITCH_IDS = {
    "s1": "0000000000000001",
    "s2": "0000000000000002",
    "s3": "0000000000000003",
    "s4": "0000000000000004",
}


class ReroutingTopo(Topo):
    """Two hosts, four switches, and two routes between the hosts."""

    def build(self):
        self.addHost("h1", ip="10.0.0.1/24")
        self.addHost("h2", ip="10.0.0.2/24")

        for switch, dpid in SWITCH_IDS.items():
            self.addSwitch(switch, dpid=dpid, protocols="OpenFlow13")

        for _, left, right, left_port, right_port, bandwidth in LINKS:
            options = {"bw": bandwidth}
            if left_port is not None:
                options["port1"] = left_port
            if right_port is not None:
                options["port2"] = right_port
            self.addLink(left, right, **options)


def create_network(controller_ip="127.0.0.1", controller_port=6653):
    """Create, but do not start, a Mininet network for the experiment."""
    network = Mininet(
        topo=ReroutingTopo(),
        controller=None,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True,
        build=False,
    )
    network.addController(
        "c0",
        controller=RemoteController,
        ip=controller_ip,
        port=controller_port,
    )
    network.build()
    return network


def discover_port_map(network):
    """Read the interfaces Mininet actually created and check our plan."""
    discovered_links = {}
    lines = []

    for name, left, right, left_port, right_port, bandwidth in LINKS:
        link = network.linksBetween(network.get(left), network.get(right))[0]
        ends = [
            (link.intf1.node.name, link.intf1.name, link.intf1.port),
            (link.intf2.node.name, link.intf2.name, link.intf2.port),
        ]
        by_node = {node_name: (interface, port) for node_name, interface, port in ends}
        left_interface, actual_left_port = by_node[left]
        right_interface, actual_right_port = by_node[right]

        if left_port is not None and actual_left_port != left_port:
            raise RuntimeError(
                f"{name}: expected {left} port {left_port}, got {actual_left_port}"
            )
        if right_port is not None and actual_right_port != right_port:
            raise RuntimeError(
                f"{name}: expected {right} port {right_port}, got {actual_right_port}"
            )

        switch_ends = []
        for switch_name in (left, right):
            if switch_name in SWITCH_IDS:
                interface, port = by_node[switch_name]
                switch_ends.append(
                    {
                        "switch": switch_name,
                        "dpid": int(SWITCH_IDS[switch_name], 16),
                        "port": port,
                        "interface": interface,
                    }
                )

        discovered_links[name] = {
            "name": name,
            "left": left,
            "right": right,
            "left_interface": left_interface,
            "right_interface": right_interface,
            "left_port": actual_left_port,
            "right_port": actual_right_port,
            "bandwidth_mbps": bandwidth,
            "switch_ends": switch_ends,
        }
        lines.append(
            f"{left_interface} (port {actual_left_port}) <-> "
            f"{right_interface} (port {actual_right_port}) "
            f"[{bandwidth} Mbps]"
        )

    path_links = {}
    for path_name, nodes in PATHS.items():
        entries = []
        for index in range(len(nodes) - 1):
            start, end = nodes[index], nodes[index + 1]
            link_name = next(
                name
                for name, left, right, *_ in LINKS
                if {left, right} == {start, end}
            )
            link = discovered_links[link_name]
            source_switch = start if start in SWITCH_IDS else end
            source_info = next(
                item for item in link["switch_ends"] if item["switch"] == source_switch
            )
            direction_counter = "rx_bytes" if start == "h1" else "tx_bytes"
            entries.append(
                {
                    "link": link_name,
                    "dpid": source_info["dpid"],
                    "switch": source_switch,
                    "port": source_info["port"],
                    "counter": direction_counter,
                    "bandwidth_mbps": link["bandwidth_mbps"],
                }
            )
        path_links[path_name] = entries

    return {
        "switch_ids": {name: int(dpid, 16) for name, dpid in SWITCH_IDS.items()},
        "links": discovered_links,
        "paths": PATHS,
        "forward_counters": path_links,
    }, lines


def write_port_map(port_map, path):
    """Save the discovered map for the controller and experiment manager."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(port_map, indent=2), encoding="utf-8")


def print_port_map(lines):
    print("\nDiscovered Mininet interfaces and switch ports:")
    for line in lines:
        print(f"  {line}")


topos = {"rerouting": lambda: ReroutingTopo()}

