import pandas as pd
from rdflib import Graph, Namespace, URIRef, Literal
from rdflib.namespace import RDF, RDFS, OWL, SKOS

# Change this before running; it should be the CSV file with approved mappings from the previous step
INPUT_OWL = "test.owl"
APPROVED_CSV = "mesh_mapping.csv"
OUTPUT_OWL = "ontology_with_approved_mappings.owl"

OBOINOWL = Namespace("http://www.geneontology.org/formats/oboInOwl#")

predicate_map = {
    "skos:exactMatch": SKOS.exactMatch,
    "skos:closeMatch": SKOS.closeMatch,
    "owl:equivalentClass": OWL.equivalentClass,
}

g = Graph()
g.parse(INPUT_OWL)

df = pd.read_csv(APPROVED_CSV).fillna("")

added = 0

for _, row in df.iterrows():
    approved = str(row["approved"]).strip().lower()
    if approved not in {"yes", "y", "true", "1"}:
        continue

    class_iri = str(row["class_iri"]).strip()
    chosen_uri = str(row["chosen_uri"]).strip()
    chosen_id = str(row["chosen_id"]).strip()
    mapping_property = str(row["mapping_property"]).strip()

    if not class_iri or not chosen_uri or mapping_property not in predicate_map:
        continue

    subj = URIRef(class_iri)
    pred = predicate_map[mapping_property]
    obj = URIRef(chosen_uri)

    g.add((subj, pred, obj))

    if chosen_id:
        g.add((subj, OBOINOWL.hasDbXref, Literal(chosen_id)))

    added += 1

g.serialize(destination=OUTPUT_OWL, format="xml")
print(f"Added {added} approved mappings.")
print(f"Wrote {OUTPUT_OWL}")