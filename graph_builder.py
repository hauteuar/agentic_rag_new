
import os, json
from typing import Dict, Any, List, Tuple, Optional
import networkx as nx
from pyvis.network import Network

def _lineage_to_edges(lineage: Dict[str, Any]) -> Tuple[List[Tuple[str,str,dict]], List[str]]:
    edges = []
    nodes = set()

    # Files
    for fname, meta in lineage.get("files", {}).items():
        nodes.add(f"FILE::{fname}")
        for prog in meta.get("programs", []):
            nodes.add(f"PGM::{prog}")
            # Edge program -> file with op label summary
            op_label = ",".join(sorted(meta.get("ops", {}).keys()))
            edges.append((f"PGM::{prog}", f"FILE::{fname}", {"label": op_label, "group":"file"}))

    # Tables
    for tname, meta in lineage.get("tables", {}).items():
        nodes.add(f"TABLE::{tname}")
        for prog in meta.get("programs", []):
            nodes.add(f"PGM::{prog}")
            op_label = ",".join(sorted(meta.get("ops", {}).keys()))
            edges.append((f"PGM::{prog}", f"TABLE::{tname}", {"label": op_label, "group":"table"}))

    return edges, list(nodes)

def build_crud_graph(lineage: Dict[str, Any]) -> nx.DiGraph:
    G = nx.DiGraph()
    edges, nodes = _lineage_to_edges(lineage)
    for n in nodes:
        if n.startswith("PGM::"):
            G.add_node(n, label=n.split("::",1)[1], type="program", color="#A3A3A3", shape="box")
        elif n.startswith("FILE::"):
            G.add_node(n, label=n.split("::",1)[1], type="file", color="#60A5FA", shape="ellipse")
        elif n.startswith("TABLE::"):
            G.add_node(n, label=n.split("::",1)[1], type="table", color="#34D399", shape="ellipse")
        else:
            G.add_node(n, label=n)
    for u,v,data in edges:
        G.add_edge(u, v, **data)
    return G

def neighborhood_subgraph(G: nx.DiGraph, element: str, radius: int = 2) -> nx.DiGraph:
    # element can be raw like "ACCT_FILE" or "PGM::X". Match by suffix.
    target = None
    for n in G.nodes:
        if n == element or n.endswith("::"+element):
            target = n
            break
    if target is None:
        # try fuzzy (case-insensitive contains)
        for n in G.nodes:
            if element.lower() in n.lower():
                target = n
                break
    if target is None:
        return nx.DiGraph()

    nodes = set([target])
    # bfs out/in by radius
    frontier = set([target])
    for _ in range(radius):
        new_frontier = set()
        for u in list(frontier):
            new_frontier.update(G.successors(u))
            new_frontier.update(G.predecessors(u))
        nodes.update(new_frontier)
        frontier = new_frontier
    return G.subgraph(nodes).copy()

def to_pyvis_html(G: nx.DiGraph, out_html_path: str, title: str = "CRUD Map") -> str:
    net = Network(height="700px", width="100%", directed=True, notebook=False, bgcolor="#111111", font_color="#ffffff")
    net.barnes_hut()
    for n, data in G.nodes(data=True):
        net.add_node(n, label=data.get("label", n), color=data.get("color"), shape=data.get("shape","dot"))
    for u,v,data in G.edges(data=True):
        net.add_edge(u, v, title=data.get("label",""), label=data.get("label",""))
    net.set_options('var options = { "nodes": { "borderWidth": 1 }, "edges": { "smooth": true }, "physics": { "stabilization": true } }')
    net.show(out_html_path)
    return out_html_path
