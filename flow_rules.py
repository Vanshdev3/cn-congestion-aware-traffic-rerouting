"""Turn the discovered topology into the switch ports used by a UDP route."""


def port_for_switch(link, switch_name):
    for end in link["switch_ends"]:
        if end["switch"] == switch_name:
            return end["port"]
    raise ValueError(f"{switch_name} is not connected to link {link['name']}")


def rules_for_path(port_map, path_name):
    """Return each switch's input and output ports for h1-to-h2 traffic."""
    nodes = port_map["paths"][path_name]
    links = port_map["links"]
    switch_ids = port_map["switch_ids"]
    rules = []

    for index, node in enumerate(nodes):
        if node not in switch_ids:
            continue

        previous_node = nodes[index - 1]
        next_node = nodes[index + 1]
        incoming_link = links[link_name(previous_node, node)]
        outgoing_link = links[link_name(node, next_node)]
        rules.append(
            {
                "switch": node,
                "dpid": switch_ids[node],
                "in_port": port_for_switch(incoming_link, node),
                "out_port": port_for_switch(outgoing_link, node),
            }
        )
    return rules


def link_name(left, right):
    return "-".join(sorted((left, right)))

