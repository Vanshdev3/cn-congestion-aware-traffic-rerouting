# Setup guide

## Where the project runs

The project runs inside Linux. The demo machine may be a physical Linux
computer or a Linux virtual machine, but Mininet, Open vSwitch, OS-Ken, the
traffic programs, and the commands below all run inside Linux.

## Install the base packages

On Ubuntu, install the system packages from a terminal:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3 python3-pip python3-venv wireshark
```

Start Open vSwitch if the service is not already running:

```bash
sudo systemctl enable --now openvswitch-switch
```

Create a virtual environment for the Python controller dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Mininet and Open vSwitch come from the operating system packages. Only the
controller framework is installed from `requirements.txt`. If the optional GUI
is needed later, install `python3-tk` as an extra package.

## Milestone 1 smoke test

Run the standard Mininet connectivity check:

```bash
sudo mn --switch ovsbr --test pingall
```

This proves only that the basic Mininet setup can create a small network and
pass pings. It does not check our topology, OS-Ken connection, flow rules,
congestion detection, or rerouting.

Record the environment versions for the team:

```bash
python3 --version
mn --version
ovs-vsctl --version
osken-manager --version
```

If `mn --version` or `osken-manager --version` is not accepted by the installed
version, record the package version shown by `apt` or `pip` instead.

## Run the project

Start the controller and experiment manager in separate Linux terminals:

```bash
sudo .venv/bin/osken-manager --ofp-tcp-listen-port 6653 controller.py
sudo python3 experiment_manager.py
```

Once both are running, use a third Linux terminal for the raw demo commands:

```bash
python3 raw_demo.py start-network
python3 raw_demo.py status
```

Run a repeatable adaptive test:

```bash
python3 raw_demo.py reset --mode adaptive --threshold 75
python3 raw_demo.py start-test --mode adaptive --rate 4 --duration 20
python3 raw_demo.py status
python3 raw_demo.py stop-test
python3 raw_demo.py export
```

For comparison, repeat the same settings with `--mode static`. The manager
starts Mininet, so do not also run `start_network.py` at the same time. Use
`start_network.py` separately when you want the plain Mininet CLI for topology
inspection.

The Tkinter dashboard is optional and is not needed for the demo:

```bash
python3 dashboard.py
```

## Wireshark note

Capture on the Linux interface that carries the Mininet link traffic. In a
capture, use the display filter `udp`. Select the interface after the topology
has started and check that packets appear before saving evidence.

