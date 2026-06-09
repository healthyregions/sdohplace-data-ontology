import argparse
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
}

HERO_LAB_ONTOLOGY_NAME = "HeroP Lab's Suggested SDOH Ontology"

CURATED_TRIGGERS = {
    "food-access": ["access to food", "food access"],
    "food-affordability": ["food prices", "affordable food"],
    "food-availability": [
        "availability of food",
        "presence of food",
        "supply of food",
        "lack grocery",
        "lack grocery stores",
        "lacking grocery stores",
        "neighborhoods that lack grocery stores",
        "grocery stores selling fresh produce",
    ],
    "food-insecurity": ["limited or uncertain availability", "uncertain availability of food"],
    "food-deserts": ["food desert", "food deserts"],
    "child-poverty": ["child poverty", "children poverty", "poverty among children", "poverty rates among children", "poverty rates in households with children", "poverty in households with children"],
    "household-poverty": ["household poverty", "households poverty", "poverty rates in households", "poverty in households", "low-income households"],
    "healthy-food-environment": ["healthy food environment"],
    "access-to-fresh-foods": ["access to fresh foods", "fresh food access", "fresh foods", "fresh food"],
    "access-to-healthy-foods": ["access to healthy foods", "healthy food access", "healthy foods"],
    "housing-instability": ["housing stability", "housing instability", "stable housing", "unstable housing"],
    "neighborhood-characteristics": ["neighborhood characteristics"],
}


def _text(node):
    return "".join(node.itertext()).strip()


def _local_resource(value):
    return value.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _unique(values):
    seen = set()
    result = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _load_owl(owl_path):
    tree = ET.parse(owl_path)
    root = tree.getroot()
    classes = {}
    for class_node in root.findall(".//owl:Class", NS):
        about = class_node.attrib.get(f"{{{NS['rdf']}}}about")
        if not about:
            continue
        node_id = _local_resource(about)
        labels = [_text(label) for label in class_node.findall("rdfs:label", NS)]
        label = next((item for item in labels if item), "")
        if not label:
            continue
        definitions = [_text(defn) for defn in class_node.findall("skos:definition", NS)]
        alt_labels = [_text(alt) for alt in class_node.findall("skos:altLabel", NS)]
        parent_ids = []
        for parent in class_node.findall("rdfs:subClassOf", NS):
            resource = parent.attrib.get(f"{{{NS['rdf']}}}resource")
            if resource:
                parent_ids.append(_local_resource(resource))
        classes[node_id] = {
            "id": node_id,
            "label": label.strip(),
            "definition": next((item for item in definitions if item), "").strip(),
            "ontologyAliases": _unique(alt_labels),
            "parentIds": _unique(parent_ids),
        }
    return classes


def _children_by_parent(classes):
    children = defaultdict(list)
    for node_id, item in classes.items():
        for parent_id in item["parentIds"]:
            if parent_id in classes:
                children[parent_id].append(node_id)
    for parent_id in children:
        children[parent_id].sort(key=lambda item: classes[item]["label"])
    return children


def _root_id(classes):
    for node_id, item in classes.items():
        if item["label"] == "sdoh-community":
            return node_id
    raise ValueError("Could not find sdoh-community root class")


def _path_for(node_id, classes, root_id, cache):
    if node_id in cache:
        return cache[node_id]
    item = classes[node_id]
    parent_ids = [parent_id for parent_id in item["parentIds"] if parent_id in classes]
    parent_ids = [parent_id for parent_id in parent_ids if parent_id != root_id]
    if not parent_ids:
        path = [item["label"]]
    else:
        parent_id = sorted(parent_ids, key=lambda value: classes[value]["label"])[0]
        path = _path_for(parent_id, classes, root_id, cache) + [item["label"]]
    cache[node_id] = path
    return path


def _format_class(node_id, classes, depth=0, max_def_chars=120):
    item = classes[node_id]
    indent = "  " * depth
    parts = [f"{indent}- {item['label']}"]
    aliases = item.get("ontologyAliases", [])
    if aliases:
        parts.append(f" (also: {', '.join(aliases[:2])})")
    definition = item.get("definition", "")
    if definition and max_def_chars > 0:
        parts.append(f": {definition[:max_def_chars].strip()}")
    return "".join(parts)


def build_prompt_context_from_classes(classes, mode="global", branch=None, max_depth=2):
    root_id = _root_id(classes)
    children = _children_by_parent(classes)
    lines = [
        "# SDOH Domain Knowledge Context",
        "The following is a controlled vocabulary for Social Determinants of Health (SDOH) data discovery.",
        "Use these concepts to interpret the user's query and identify relevant datasets.",
        "",
    ]

    if mode == "global":
        lines.append("## Top-level concept branches:")
        for top_child in children.get(root_id, []):
            lines.append(_format_class(top_child, classes, depth=0))
            for sub in children.get(top_child, []):
                lines.append(_format_class(sub, classes, depth=1, max_def_chars=0))
        return "\n".join(lines)

    branch_id = next((node_id for node_id in children.get(root_id, []) if classes[node_id]["label"] == branch), None)
    if not branch_id:
        return build_prompt_context_from_classes(classes, mode="global")

    def recurse(node_id, depth):
        lines.append(_format_class(node_id, classes, depth=depth))
        if depth < max_depth:
            for child_id in children.get(node_id, []):
                recurse(child_id, depth + 1)

    lines.append(f"## Concepts in branch: {branch}")
    recurse(branch_id, 0)
    return "\n".join(lines)


def build_prompt_context(owl_path, mode="global", branch=None, max_depth=2):
    return build_prompt_context_from_classes(_load_owl(owl_path), mode=mode, branch=branch, max_depth=max_depth)


def _structured_ontology(classes):
    root_id = _root_id(classes)
    cache = {}
    items = []
    for node_id, item in sorted(classes.items(), key=lambda pair: _path_for(pair[0], classes, root_id, cache)):
        if node_id == root_id:
            continue
        output = {
            "id": item["label"],
            "label": item["label"],
            "path": _path_for(node_id, classes, root_id, cache),
        }
        aliases = item.get("ontologyAliases", [])
        if aliases:
            output["ontologyAliases"] = aliases
        triggers = CURATED_TRIGGERS.get(item["label"], [])
        if triggers:
            output["triggers"] = triggers
        items.append(output)
    return items


def _template_literal(value):
    return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def build_js_module(owl_path):
    classes = _load_owl(owl_path)
    global_context = build_prompt_context_from_classes(classes, mode="global")
    scoped_context = build_prompt_context_from_classes(classes, mode="scoped", branch="food-environment", max_depth=2)
    context = (
        "=== GLOBAL MODE ===\n"
        f"{global_context}\n\n"
        f"[chars: {len(global_context)}]\n\n\n"
        "=== SCOPED MODE: food-environment ===\n"
        f"{scoped_context}\n\n"
        f"[chars: {len(scoped_context)}]"
    )
    ontology = _structured_ontology(classes)
    return "\n".join([
        f"export const HERO_LAB_ONTOLOGY_NAME = {json.dumps(HERO_LAB_ONTOLOGY_NAME)};",
        "",
        f"export const ontologyContext = `{_template_literal(context)}`;",
        "",
        f"export const HERO_SDOH_ONTOLOGY = {json.dumps(ontology, indent=2)};",
        "",
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("owl_path")
    parser.add_argument("--out", default=None)
    parser.add_argument("--mode", choices=["module", "print"], default="module")
    args = parser.parse_args()

    if args.mode == "print":
        print("=== GLOBAL MODE ===")
        ctx = build_prompt_context(args.owl_path, mode="global")
        print(ctx)
        print(f"\n[chars: {len(ctx)}]")
        print("\n\n=== SCOPED MODE: food-environment ===")
        ctx2 = build_prompt_context(args.owl_path, mode="scoped", branch="food-environment", max_depth=2)
        print(ctx2)
        print(f"\n[chars: {len(ctx2)}]")
        return

    module = build_js_module(args.owl_path)
    if args.out:
        Path(args.out).write_text(module, encoding="utf-8")
    else:
        print(module)


if __name__ == "__main__":
    main()
