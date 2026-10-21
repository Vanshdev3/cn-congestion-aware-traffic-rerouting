# Setup guide

## Where the project runs

Mininet and Open vSwitch need a Linux environment with network namespaces,
traffic control, and permission to create virtual interfaces. Use the team's
Linux VM or a Linux computer. A Windows terminal alone is not enough. WSL may
work depending on its kernel and Open vSwitch setup, but it must pass the same
checks below before the team relies on it for the demo.

Keep the project files in a folder visible from Linux. If using WSL, a Windows
folder is usually reachable under `/mnt/c/Users/<name>/...`; if using a VM,
use a shared folder or clone the GitHub repository in Linux.

## Install the base packages

On Ubuntu, install the system packages from a terminal:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch python3 python3-pip python3-venv python3-tk wireshark
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

Mininet, Open vSwitch, and Tkinter come from the operating system packages.
Only the controller framework is installed from `requirements.txt`.

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

Once both are running, start the dashboard in a third terminal:

```bash
python3 dashboard.py
```

The manager starts Mininet from the dashboard. Do not also run
`start_network.py` at the same time; both programs would try to create the lab
network.

## Wireshark note

Capture on the Linux interface that carries the Mininet link traffic. In a
capture, use the display filter `udp`. Select the interface after the topology
has started and check that packets appear before saving evidence.

