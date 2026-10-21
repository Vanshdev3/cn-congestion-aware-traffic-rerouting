"""Receive numbered UDP packets and write live and final measurement summaries."""

import argparse
import json
import signal
import socket
import struct
import time
from pathlib import Path


HEADER = struct.Struct("!IQ")
keep_running = True


def stop_receiver(_signum, _frame):
    global keep_running
    keep_running = False


def save_json(path, data):
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(target)


def read_sender_summary(path):
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def receive_packets(bind_address, port, stats_file, sender_summary_file, test_id):
    global keep_running
    keep_running = True
    signal.signal(signal.SIGINT, stop_receiver)
    signal.signal(signal.SIGTERM, stop_receiver)

    sequences = set()
    duplicate_packets = 0
    out_of_order_packets = 0
    highest_sequence = -1
    received_bytes = 0
    first_receive_ns = None
    last_receive_ns = None
    previous_arrival_ns = None
    previous_gap_duration_ns = None
    gap_variation_total_ns = 0
    gap_variation_samples = 0
    start_ns = time.monotonic_ns()
    last_report_ns = start_ns

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.settimeout(0.2)
        udp_socket.bind((bind_address, port))
        print(f"Receiver listening on {bind_address}:{port}", flush=True)

        while keep_running:
            try:
                packet, _sender = udp_socket.recvfrom(65535)
            except socket.timeout:
                packet = None
            except OSError as error:
                print(f"Receiver socket stopped: {error}", flush=True)
                break

            if packet and len(packet) >= HEADER.size:
                sequence, _sent_ns = HEADER.unpack_from(packet)
                arrival_ns = time.monotonic_ns()
                received_bytes += len(packet)
                last_receive_ns = arrival_ns
                if first_receive_ns is None:
                    first_receive_ns = arrival_ns

                if sequence in sequences:
                    duplicate_packets += 1
                else:
                    if sequence < highest_sequence:
                        out_of_order_packets += 1
                    sequences.add(sequence)
                    highest_sequence = max(highest_sequence, sequence)

                if previous_arrival_ns is not None:
                    gap = arrival_ns - previous_arrival_ns
                    if previous_gap_duration_ns is not None:
                        gap_variation_total_ns += abs(gap - previous_gap_duration_ns)
                        gap_variation_samples += 1
                    previous_gap_duration_ns = gap
                previous_arrival_ns = arrival_ns

            now_ns = time.monotonic_ns()
            if now_ns - last_report_ns >= 1_000_000_000:
                save_json(
                    stats_file,
                    make_summary(
                        test_id,
                        sequences,
                        duplicate_packets,
                        out_of_order_packets,
                        highest_sequence,
                        received_bytes,
                        start_ns,
                        first_receive_ns,
                        last_receive_ns,
                        gap_variation_total_ns,
                        gap_variation_samples,
                        None,
                        final=False,
                    ),
                )
                last_report_ns = now_ns

    sender_summary = read_sender_summary(sender_summary_file)
    summary = make_summary(
        test_id,
        sequences,
        duplicate_packets,
        out_of_order_packets,
        highest_sequence,
        received_bytes,
        start_ns,
        first_receive_ns,
        last_receive_ns,
        gap_variation_total_ns,
        gap_variation_samples,
        sender_summary,
        final=True,
    )
    save_json(stats_file, summary)
    print(json.dumps(summary), flush=True)
    return summary


def make_summary(
    test_id,
    sequences,
    duplicates,
    out_of_order,
    highest_sequence,
    received_bytes,
    start_ns,
    first_receive_ns,
    last_receive_ns,
    gap_variation_total_ns,
    gap_variation_samples,
    sender_summary,
    final,
):
    now_ns = time.monotonic_ns()
    elapsed = max((now_ns - start_ns) / 1_000_000_000, 0.000001)
    summary = {
        "test_id": test_id,
        "final": final,
        "unique_packets_received": len(sequences),
        "duplicate_packets": duplicates,
        "out_of_order_packets": out_of_order,
        "highest_sequence_received": highest_sequence if highest_sequence >= 0 else None,
        "received_bytes": received_bytes,
        "receiver_throughput_mbps": received_bytes * 8 / elapsed / 1_000_000,
        "elapsed_seconds": elapsed,
        "inter_arrival_variation_ms": (
            gap_variation_total_ns / gap_variation_samples / 1_000_000
            if gap_variation_samples
            else None
        ),
        "first_packet_monotonic_ns": first_receive_ns,
        "last_packet_monotonic_ns": last_receive_ns,
        "measured_at_unix_ns": time.time_ns(),
    }

    if sender_summary:
        sent_packets = int(sender_summary.get("sent_packets", 0))
        first_sequence = sender_summary.get("first_sequence")
        last_sequence = sender_summary.get("last_sequence")
        if sent_packets and first_sequence is not None and last_sequence is not None:
            expected = set(range(int(first_sequence), int(last_sequence) + 1))
            received_expected = len(sequences.intersection(expected))
            lost = max(sent_packets - received_expected, 0)
            summary.update(
                {
                    "sent_packets": sent_packets,
                    "expected_packets": sent_packets,
                    "received_expected_packets": received_expected,
                    "lost_packets": lost,
                    "packet_loss_percent": lost * 100 / sent_packets,
                }
            )
        else:
            summary.update(
                {
                    "sent_packets": sent_packets,
                    "expected_packets": sent_packets,
                    "received_expected_packets": 0,
                    "lost_packets": sent_packets,
                    "packet_loss_percent": 100.0 if sent_packets else 0.0,
                }
            )
    else:
        summary.update(
            {
                "sent_packets": None,
                "expected_packets": None,
                "received_expected_packets": None,
                "lost_packets": None,
                "packet_loss_percent": None,
            }
        )
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="10.0.0.2")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--stats-file", default="run/receiver_stats.json")
    parser.add_argument("--sender-summary", default="run/sender_summary.json")
    parser.add_argument("--test-id", default="manual")
    args = parser.parse_args()

    receive_packets(
        args.bind,
        args.port,
        args.stats_file,
        args.sender_summary,
        args.test_id,
    )


if __name__ == "__main__":
    main()

