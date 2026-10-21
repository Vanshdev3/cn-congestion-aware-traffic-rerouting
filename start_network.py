"""Start the lab network and leave it open in the Mininet command line."""

import argparse

from mininet.cli import CLI

from topology import create_network, discover_port_map, print_port_map, write_port_map


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6653)
    parser.add_argument("--map-file", default="run/port_map.json")
    args = parser.parse_args()

    network = create_network(args.controller_ip, args.controller_port)
    try:
        network.start()
        port_map, lines = discover_port_map(network)
        write_port_map(port_map, args.map_file)
        print_port_map(lines)
        print(f"\nPort map saved to {args.map_file}")
        print("Use 'exit' in the Mininet prompt to stop the network.")
        CLI(network)
    finally:
        network.stop()


if __name__ == "__main__":
    main()

