"""Send a rate-limited stream of numbered UDP packets from a Mininet host."""

import argparse
import json
import signal
import socket
import struct
import time
from pathlib import Path


HEADER = struct.Struct("!IQ")
keep_sending = True


def stop_sender(_signum, _frame):
    global keep_sending
    keep_sending = False


def save_json(path, data):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(target)


def read_rate_file(path):
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        rate = float(data["rate_mbps"])
        return rate if 0.1 <= rate <= 10 else None
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def send_packets(
    destination, port, rate_mbps, duration, packet_size, summary_file, rate_file=None
):
    global keep_sending
    keep_sending = True
    signal.signal(signal.SIGINT, stop_sender)
    signal.signal(signal.SIGTERM, stop_sender)
    if packet_size < HEADER.size:
        raise ValueError(f"packet size must be at least {HEADER.size} bytes")
    if rate_mbps <= 0 or duration <= 0:
        raise ValueError("rate and duration must both be greater than zero")

    padding = bytes(packet_size - HEADER.size)
    current_rate_mbps = rate_mbps
    interval = packet_size * 8 / (current_rate_mbps * 1_000_000)
    rate_changes = [{"rate_mbps": current_rate_mbps, "time_unix_ns": time.time_ns()}]
    sent_packets = 0
    sent_bytes = 0
    start_ns = time.monotonic_ns()
    stop_ns = start_ns + int(duration * 1_000_000_000)
    next_send = time.monotonic()
    next_rate_check = next_send

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        while keep_sending and time.monotonic_ns() < stop_ns:
            now = time.monotonic()
            if rate_file and now >= next_rate_check:
                new_rate = read_rate_file(rate_file)
                next_rate_check = now + 0.25
                if new_rate is not None and new_rate != current_rate_mbps:
                    current_rate_mbps = new_rate
                    interval = packet_size * 8 / (current_rate_mbps * 1_000_000)
                    next_send = now
                    rate_changes.append(
                        {"rate_mbps": current_rate_mbps, "time_unix_ns": time.time_ns()}
                    )
            if now < next_send:
                remaining = (stop_ns - time.monotonic_ns()) / 1_000_000_000
                time.sleep(min(next_send - now, max(remaining, 0)))
            if not keep_sending or time.monotonic_ns() >= stop_ns:
                break

            packet = HEADER.pack(sent_packets, time.monotonic_ns()) + padding
            try:
                sent_bytes += udp_socket.sendto(packet, (destination, port))
                sent_packets += 1
            except OSError as error:
                print(f"Could not send UDP packet: {error}", flush=True)

            next_send += interval

    elapsed = max((time.monotonic_ns() - start_ns) / 1_000_000_000, 0.000001)
    summary = {
        "destination": destination,
        "port": port,
        "rate_mbps_configured": rate_mbps,
        "rate_mbps_final": current_rate_mbps,
        "rate_changes": rate_changes,
        "duration_seconds_configured": duration,
        "packet_size_bytes": packet_size,
        "first_sequence": 0 if sent_packets else None,
        "last_sequence": sent_packets - 1 if sent_packets else None,
        "sent_packets": sent_packets,
        "sent_bytes": sent_bytes,
        "elapsed_seconds": elapsed,
        "sender_throughput_mbps": sent_bytes * 8 / elapsed / 1_000_000,
        "finished_unix_ns": time.time_ns(),
    }
    save_json(summary_file, summary)
    print(json.dumps(summary), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default="10.0.0.2")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--rate-mbps", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--packet-size", type=int, default=1200)
    parser.add_argument("--summary-file")
    parser.add_argument("--rate-file")
    args = parser.parse_args()

    send_packets(
        args.destination,
        args.port,
        args.rate_mbps,
        args.duration,
        args.packet_size,
        args.summary_file,
        args.rate_file,
    )


if __name__ == "__main__":
    main()

