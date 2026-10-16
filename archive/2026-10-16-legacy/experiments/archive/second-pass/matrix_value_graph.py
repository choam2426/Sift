"""Conservative source-position value graph from neutral C CodeQL facts.

The graph combines local exact/taint steps with static argument/parameter and
return/call links. Its paths are possible influences, not execution proofs.
"""

from collections import defaultdict, deque
import re


class ValueGraph:
    def __init__(self, facts):
        self.facts = facts
        self.forward_edges = defaultdict(list)
        self.backward_edges = defaultdict(list)
        self.edge_keys = set()
        self.parameter_sources = defaultdict(list)
        self.field_sources = defaultdict(list)
        self.effects = defaultdict(list)
        self.cross_function_edges = []
        self._load()
        self._connect_effects()

    def node(self, unit, coords):
        values = tuple(map(int, coords))
        if (not unit["start_line"] <= values[0] <= values[2] <= unit["end_line"] or
                values[1] < 1 or values[3] < 1):
            return None
        return (unit["id"], *values)

    def add_edge(self, source, sink, kind, evidence=None):
        if source is None or sink is None:
            return
        key = (source, sink, kind)
        if key in self.edge_keys:
            return
        self.edge_keys.add(key)
        edge = {"source": source, "sink": sink, "kind": kind, "evidence": evidence}
        self.forward_edges[source].append(edge)
        self.backward_edges[sink].append(edge)
        if source[0] != sink[0]:
            self.cross_function_edges.append(edge)

    def _load(self):
        facts = self.facts
        param_refs = defaultdict(list)
        for row in facts.rows("parameter_accesses"):
            unit = facts.unit(row["col0"], row["col1"], row["col2"])
            if unit is None or row["col9"] == "modified":
                continue
            node = self.node(unit, [row[f"col{i}"] for i in range(5, 9)])
            if node is not None:
                key = (unit["id"], int(row["index"]))
                param_refs[key].append(node)
                self.parameter_sources[key].append({"node": node, "name": row["col4"]})
        field_rows = facts.rows("field_accesses")
        field_declarations = {}
        for row in field_rows:
            unit = facts.unit(row["col0"], row["col1"], row["col2"])
            if unit is None or row["col6"] != unit["file"]:
                continue
            key = (unit["id"], *[int(row[f"col{i}"]) for i in range(7, 11)])
            field_declarations[key] = (row["col3"], row["col4"], row["col5"])
        returns = defaultdict(list)
        for row in facts.rows("observable_effects"):
            unit = facts.unit(row["col0"], row["col1"], row["col2"])
            if unit is None:
                continue
            node = self.node(unit, [row[f"col{i}"] for i in range(4, 8)])
            if node is None:
                continue
            target = row.get("targetText", "")
            if row["kind"] == "field_write" and all(row.get(f"col{i}") for i in range(9, 13)):
                target_location = (unit["id"], *[int(row[f"col{i}"]) for i in range(9, 13)])
                declaration = field_declarations.get(target_location)
                if declaration is not None:
                    target = f"{declaration[0]}@{declaration[1]}:{declaration[2]}"
            if row["kind"] == "pointer_write" and all(row.get(f"col{i}") for i in range(9, 13)):
                target_code = facts.expr(unit["file"], *[row[f"col{i}"] for i in range(9, 13)])
                target = re.sub(r"\[[^][]*\]", "[]", re.sub(r"\s+", "", target_code))
            effect = {"node": node, "kind": row["kind"],
                      "target": target}
            if effect not in self.effects[unit["id"]]:
                self.effects[unit["id"]].append(effect)
            if row["kind"] == "return_value":
                returns[unit["id"]].append(node)
        for row in field_rows:
            unit = facts.unit(row["col0"], row["col1"], row["col2"])
            if unit is None or row["col12"] == "modified" or row["col6"] != unit["file"]:
                continue
            node = self.node(unit, [row[f"col{i}"] for i in range(7, 11)])
            if node is not None:
                key = (unit["id"], row["col3"], row["col4"], int(row["col5"]))
                self.field_sources[key].append(node)
        for row in facts.rows("local_value_steps"):
            unit = facts.unit(row["col0"], row["col1"], row["col2"])
            if unit is None:
                continue
            source = self.node(unit, [row[f"col{i}"] for i in range(4, 8)])
            sink = self.node(unit, [row[f"col{i}"] for i in range(8, 12)])
            self.add_edge(source, sink, row["kind"])
        for row in facts.rows("call_arguments"):
            caller = facts.unit(row["col0"], row["col1"], row["col2"])
            callee = facts.unit(row["col3"], row["col4"], row["col5"])
            if caller is None or callee is None or row["col12"] != caller["file"]:
                continue
            index = int(row["index"])
            argument = self.node(caller, [row[f"col{i}"] for i in range(13, 17)])
            call = self.node(caller, [row[f"col{i}"] for i in range(7, 11)])
            evidence = {"file": row["col6"], "line": int(row["col7"]),
                        "argument_index": index}
            for access in param_refs[(callee["id"], index)]:
                self.add_edge(argument, access, "argument_to_parameter", evidence)
            for returned in returns[callee["id"]]:
                self.add_edge(returned, call, "return_to_call",
                              {"file": row["col6"], "line": int(row["col7"])})

    def _connect_effects(self):
        nodes_by_function = defaultdict(set)
        for node in (*self.forward_edges.keys(), *self.backward_edges.keys()):
            nodes_by_function[node[0]].add(node)
        for items in self.parameter_sources.values():
            for item in items:
                nodes_by_function[item["node"][0]].add(item["node"])
        for items in self.field_sources.values():
            for node in items:
                nodes_by_function[node[0]].add(node)
        for function_id, effects in self.effects.items():
            for effect in effects:
                target = effect["node"]
                for node in nodes_by_function[function_id]:
                    if node != target and (target[1], target[2]) <= (node[1], node[2]) and (node[3], node[4]) <= (target[3], target[4]):
                        self.add_edge(node, target, "syntactic_part_of_effect")

    def reachable(self, start_nodes, *, reverse=False, allowed=None):
        edges = self.backward_edges if reverse else self.forward_edges
        seen = set(start_nodes)
        queue = deque(start_nodes)
        while queue:
            current = queue.popleft()
            for edge in edges[current]:
                other = edge["source"] if reverse else edge["sink"]
                if other in seen or (allowed is not None and other not in allowed):
                    continue
                seen.add(other)
                queue.append(other)
        return seen

    def path_nodes(self, sources, sink, reachable=None):
        reachable = reachable if reachable is not None else self.reachable(sources)
        if sink not in reachable:
            return set()
        return self.reachable([sink], reverse=True, allowed=reachable)

    def path_edges(self, nodes):
        return [edge for source in nodes for edge in self.forward_edges[source]
                if edge["sink"] in nodes]
