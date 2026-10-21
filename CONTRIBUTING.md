# Contributing

This repository is a networking learning project. Keep changes small enough
that a beginner teammate can explain them during the demonstration.

## Before changing code

1. Read the README and the milestone notes.
2. Check open issues and tell the team which part you are taking.
3. Work on a short branch such as `topology/port-map` or `traffic/udp-counters`.
4. Avoid changing unrelated files in the same pull request.

## Commits and pull requests

Use short, descriptive commit messages, for example:

```text
docs: add Linux setup guide
topology: print discovered switch ports
traffic: count UDP sequence gaps after a run
```

Pull requests should explain what changed, how to run it, and what was checked.
If a check could not be run because Linux/Mininet was unavailable, say so
plainly. Do not report expected output as measured output.

## Code style

- Prefer small functions and direct names.
- Add comments where they explain a networking decision.
- Avoid clever abstractions that hide the packet path.
- Keep measured values separate from configured settings.
- Do not commit virtual environments, captures, logs, or experiment results
  containing personal data.

