# Checks and test runs

## Local checks

The small standard-library test suite covers the counter formulas, the selected
switch ports for each route, sequence accounting, loss calculation, and a real
UDP sender/receiver exchange over loopback:

```bash
python3 -m unittest discover -s tests -v
```

The loopback test checks the traffic programs only. It does not prove Mininet
forwarding or controller behavior.

## Linux network checks

On the Linux machine or VM, follow the setup guide and run the Mininet smoke
test first. Then use the demo checklist to verify both network paths, OS-Ken
connections, flow-table entries, measured congestion, and counter-confirmed
rerouting. Record the actual output; a successful unit suite is not a
substitute for those network checks.

