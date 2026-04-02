import csv
import re
import requests
import time
from rdflib import Graph
from rdflib.namespace import RDF, RDFS, OWL

INPUT_OWL = "test.owl"
OUTPUT_CSV = "mesh_mapping.csv"
MESH_SPARQL = "https://id.nlm.nih.gov/mesh/sparql"

def normalize_label(text: str) -> str:
    text = text.strip().lower()
    text = text.replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    return text

def mesh_exact_label_match(label: str):
    norm = normalize_label(label)
    safe_label = norm.replace('"', '\\"')

    query = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    PREFIX meshv: <http://id.nlm.nih.gov/mesh/vocab#>

    SELECT ?d ?lab WHERE {{
      ?d a meshv:Descriptor .
      ?d rdfs:label ?lab .
      FILTER(LCASE(STR(?lab)) = "{safe_label}")
    }}
    LIMIT 1
    """

    resp = requests.get(
        MESH_SPARQL,
        params={"query": query, "format": "JSON", "inference": "true"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        return None, None

    return bindings[0]["d"]["value"], bindings[0]["lab"]["value"]

def extract_mesh_id(mesh_uri: str) -> str:
    return mesh_uri.rstrip("/").split("/")[-1]

g = Graph()
g.parse(INPUT_OWL)

rows = []

for cls in g.subjects(RDF.type, OWL.Class):
    labels = list(g.objects(cls, RDFS.label))
    if not labels:
        continue

    label = str(labels[0]).strip()
    if not label:
        continue

    try:
        mesh_uri, mesh_label = mesh_exact_label_match(label)
        time.sleep(0.2)

        if mesh_uri:
            rows.append({
                "class_iri": str(cls),
                "label": label,
                "normalized_label": normalize_label(label),
                "mesh_uri": mesh_uri,
                "mesh_id": f"MESH:{extract_mesh_id(mesh_uri)}",
                "mesh_label": mesh_label,
                "mapping_property": "skos:exactMatch",
                "approved": "",
                "notes": ""
            })
            print(f"Candidate: {label} -> {mesh_uri}")
        else:
            rows.append({
                "class_iri": str(cls),
                "label": label,
                "normalized_label": normalize_label(label),
                "mesh_uri": "",
                "mesh_id": "",
                "mesh_label": "",
                "mapping_property": "",
                "approved": "",
                "notes": "No exact MeSH match"
            })
            print(f"No exact MeSH match: {label}")

    except Exception as e:
        rows.append({
            "class_iri": str(cls),
            "label": label,
            "normalized_label": normalize_label(label),
            "mesh_uri": "",
            "mesh_id": "",
            "mesh_label": "",
            "mapping_property": "",
            "approved": "",
            "notes": f"Error: {e}"
        })
        print(f"Error on {label}: {e}")

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "class_iri",
            "label",
            "normalized_label",
            "mesh_uri",
            "mesh_id",
            "mesh_label",
            "mapping_property",
            "approved",
            "notes",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)

print(f"Review CSV written to: {OUTPUT_CSV}")