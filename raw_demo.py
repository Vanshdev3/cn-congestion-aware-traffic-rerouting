"""Small terminal client for the Linux experiment manager."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request(base_url, path, data=None):
    body = None
    headers = {}
    method = "GET"
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"

    request = Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError) as error:
        detail = getattr(error, "reason", error)
        raise SystemExit(f"Manager request failed: {detail}") from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manager", default="http://127.0.0.1:8765")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="show the current experiment state")
    subparsers.add_parser("events", help="show recent controller and manager events")
    subparsers.add_parser("start-network", help="start Mininet and verify Path A")
    subparsers.add_parser("stop-network", help="stop Mininet")
    subparsers.add_parser("stop-test", help="stop the current UDP test")
    subparsers.add_parser("export", help="show the CSV results path")

    reset = subparsers.add_parser("reset", help="restore Path A and clear baselines")
    add_settings(reset)
    start = subparsers.add_parser("start-test", help="run one UDP experiment")
    add_settings(start)
    start.add_argument("--rate", type=float, default=4)
    start.add_argument("--duration", type=float, default=20)

    configure = subparsers.add_parser("configure", help="change mode and threshold")
    add_settings(configure)
    rate = subparsers.add_parser("set-rate", help="change the live UDP rate")
    rate.add_argument("rate", type=float)

    args = parser.parse_args()
    if args.command == "status":
        result = request(args.manager, "/state")
    elif args.command == "events":
        result = request(args.manager, "/events")
    elif args.command == "start-network":
        result = request(args.manager, "/command/start-network", {})
    elif args.command == "stop-network":
        result = request(args.manager, "/command/stop-network", {})
    elif args.command == "stop-test":
        result = request(args.manager, "/command/stop-test", {})
    elif args.command == "export":
        result = request(args.manager, "/export", {})
    elif args.command in ("reset", "configure"):
        result = request(args.manager, f"/command/{args.command}", settings(args))
    elif args.command == "start-test":
        result = request(
            args.manager,
            "/command/start-test",
            {**settings(args), "rate_mbps": args.rate, "duration_seconds": args.duration},
        )
    else:
        result = request(args.manager, "/command/set-rate", {"rate_mbps": args.rate})

    print(json.dumps(result, indent=2))


def add_settings(parser):
    parser.add_argument("--mode", choices=("static", "adaptive"), default="adaptive")
    parser.add_argument("--threshold", type=float, default=75)


def settings(args):
    return {"mode": args.mode, "threshold_percent": args.threshold}


if __name__ == "__main__":
    main()
