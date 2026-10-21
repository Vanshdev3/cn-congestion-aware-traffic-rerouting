"""Small calculations shared by the controller and experiment manager."""


def rate_from_counter(previous_bytes, current_bytes, elapsed_seconds):
    """Return bits per second from a byte-counter change, or None for a reset."""
    if previous_bytes is None or elapsed_seconds <= 0:
        return None
    difference = current_bytes - previous_bytes
    if difference < 0:
        return None
    return difference * 8 / elapsed_seconds


def utilisation_percent(rate_bps, capacity_mbps):
    if rate_bps is None or capacity_mbps <= 0:
        return None
    capacity_bps = capacity_mbps * 1_000_000
    return rate_bps * 100 / capacity_bps


def path_utilisation(rates_by_link, path_links):
    """Use the busiest measured directed link as the path's utilisation."""
    values = [
        rates_by_link[item["link"]]
        for item in path_links
        if rates_by_link.get(item["link"]) is not None
    ]
    return max(values) if values else None

