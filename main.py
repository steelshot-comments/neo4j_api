import os
import uvicorn
from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from neo4j import GraphDatabase
from dotenv import load_dotenv
from typing import List

# Load environment variables
load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASS = os.getenv("NEO4J_PASS")
NEO4J_DB = os.getenv("NEO4J_DB")

# Initialize Neo4j driver
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

# FastAPI instance
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or restrict to specific frontend origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models for requests
class NodeCreateRequest(BaseModel):
    labels: list[str]
    properties: dict[str, str]

class NodePair(BaseModel):
    from_id: int
    to_id: int

class RelationshipCreateRequest(BaseModel):
    pairs: List[NodePair]
    relationship: str

class NodeUpdateRequest(BaseModel):
    id: int
    updates: dict

class NodeDeleteRequest(BaseModel):
    id: int

class BaseRequest(BaseModel):
    user_id: int
    tab_id: int

# Utility function to run Cypher queries
async def run_query(query: str, parameters: dict = {}):
    with driver.session(database=NEO4J_DB) as session:
        result = session.run(query, parameters)
        return list(result) # Fetch all records before session closes
    
app.get("/")
def root():
    return {
        "message": "Welcome to the neo4j api for OSINT app",
        "routes": {
            "/add-records": "Run an OSINT task with the specified source and query.",
            "/graph": "Get the result of a task by its ID.",
            "/delete-records": "Fetch all results from the database.",
        }
    }

# Route to add a node
@app.post("/add-record/{user_id}/{tab_id}/{source_node_id}")
async def add_node(user_id: int, tab_id: int, source_node_id: str,request: List[NodeCreateRequest]):
    query = """
    UNWIND $nodes AS node
    CREATE (n)
    SET n = node.properties
    SET n.user_id = $user_id, n.tab_id = $tab_id
    WITH n, node
    CALL apoc.create.addLabels(n, node.labels) YIELD node as updatedNode
    RETURN id(n) as id, labels(n) as labels, apoc.map.removeKeys(n, ['user_id', 'tab_id']) AS properties
    """
    
    # print(request)

    # Convert request to a list of dictionaries with labels and properties
    nodes_data = [{"labels": node.labels, "properties": node.properties} for node in request]

    result = await run_query(query, {
        "nodes":nodes_data,
        "user_id": user_id,
        "tab_id": tab_id
    })
    records = result
    if not records:
        raise HTTPException(status_code=500, detail="Failed to add node")
    return {"message": "Node added successfully", "nodes": records, "source_node_id":source_node_id}

# Route to view all nodes
@app.get("/view-nodes")
async def view_nodes():
    query = "MATCH (n) RETURN labels(n) AS labels, n AS node"
    result = await run_query(query)
    nodes = [{"labels": record["labels"], "properties": record["node"]} for record in result]
    return {"nodes": nodes}

# Route to get the full graph (nodes + relationships)
@app.post("/graph")
async def get_graph(request: BaseRequest):
    query = """
    MATCH (n)
    WHERE n.user_id = $user_id AND n.tab_id = $tab_id
    OPTIONAL MATCH (n)-[r]->(m)
    WHERE m.user_id = $user_id AND m.tab_id = $tab_id
    RETURN {
        id: id(n),
        labels: labels(n),
        properties: apoc.map.removeKeys(n, ['user_id', 'tab_id'])
    } AS n, r, m
    """
    result = await run_query(query, {"user_id": request.user_id, "tab_id": request.tab_id})

    nodes = []
    edges = []
    for record in result:
        if record["n"]:
            node = record["n"]
            nodes.append({
                "id": str(node['id']),
                "labels": node['labels'],
                "properties": node['properties']
            })
        r = record["r"]

        if r is not None:
            edge_id = str(r.element_id)
            if edge_id not in {e["id"] for e in edges}:  # Prevent duplicate edges
                edges.append({
                    "id": edge_id,
                    "source": str(r.nodes[0].id),
                    "target": str(r.nodes[1].id),
                    "label": r.type
                })
    
    return {"nodes": nodes, "edges": edges}

# Route to add a relationship
@app.post("/add-relationship")
async def add_relationship(request: RelationshipCreateRequest):
    query = """
    UNWIND $pairs AS pair
    MATCH (a) WHERE id(a)=pair.from_node
    MATCH (b) WHERE id(b)=pair.to_node
    CALL apoc.create.relationship(a, $relationship, {}, b) YIELD rel as r
    RETURN collect(r) AS relationships
    """
    result = await run_query(query, request.model_dump())

    if not result:
        raise HTTPException(status_code=500, detail="Failed to create relationship")
    return {"message": "Relationship created successfully", "relationship": result[0]["relationships"]}

# Route to update a node
@app.put("/update-node")
async def update_node(request: NodeUpdateRequest):
    if not request.updates:
        raise HTTPException(status_code=400, detail="Updates are required")

    set_query = ", ".join([f"n.{key} = ${key}" for key in request.updates.keys()])
    query = f"MATCH (n) WHERE id(n) = $id SET {set_query} RETURN n"

    parameters = {"id": request.id, **request.updates}
    result = await run_query(query, parameters)
    records = result.data()
    if not records:
        raise HTTPException(status_code=404, detail="No matching node found")
    return {"message": "Node updated successfully", "node": records[0]["n"]}

# Route to delete a node
@app.delete("/delete-node/{node_id}")
async def delete_node(node_id: int):
    print(node_id)
    query = "MATCH (n) WHERE ID(n)=$id DETACH DELETE n"
    # AND n.user_id = $user_id AND n.tab_id = $tab_id
    await run_query(query, {"id": node_id})
    return {"message": "Node deleted successfully"}

# Route to delete all nodes
@app.delete("/delete-all-nodes")
async def delete_node(request: BaseRequest = Body(...)):
    query = "MATCH (n) WHERE n.user_id = $user_id AND n.tab_id = $tab_id DETACH DELETE n"
    await run_query(query, {"user_id": request.user_id, "tab_id": request.tab_id})
    return {"message": "Nodes deleted successfully"}

# Run the FastAPI server
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5500, reload=True)
