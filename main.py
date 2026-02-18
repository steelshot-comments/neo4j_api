import uvicorn
from fastapi import FastAPI, HTTPException, Body, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR
import json
import logging
from models import *
from helpers import *

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastAPI instance
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or restrict to specific frontend origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def wrap_success_responses(request: Request, call_next):
    body = await request.body()
    print("📥 Raw body:", body)
    print("📋 Headers:", request.headers)
    try:
        response = await call_next(request)

        # Skip wrapping errors or already-JSON responses
        if response.status_code >= 400:
            return response

        # Only wrap JSON responses
        if hasattr(response, "media_type") and response.media_type == "application/json":
            body = b"".join([chunk async for chunk in response.body_iterator])
            response.body_iterator = iter([body])
            try:
                data = json.loads(body)
            except Exception:
                data = body.decode()

            # If already has 'success', leave it
            if isinstance(data, dict) and "success" in data:
                return response

            message = "Success"
            if isinstance(data, dict) and "message" in data:
                message = data.pop("message")

            # Wrap into standard format
            wrapped = {
                "success": True,
                "message": message,
                "data": data,
            }
            finalResponse = JSONResponse(content=wrapped, status_code=response.status_code)
            print("📥 Response:", finalResponse)
            return finalResponse
        return response
    except Exception as e:
        # Let global handler deal with unhandled errors
        raise e

# Route to add a node
@app.post("/add-node")
async def add_node(request: NodeCreateRequest):
    query = """
    UNWIND $nodes AS node
    CREATE (n)
    SET n += node.properties
    SET n.uuid = randomUUID()
    SET n.user_id = $user_id,
        n.graph_id = $graph_id,
        n.project_id = $project_id
    WITH n, node
    CALL apoc.create.addLabels(n, node.labels) YIELD node as updatedNode
    RETURN elementId(n) as id,
           labels(n) as labels,
           apoc.map.removeKeys(n, ['user_id', 'graph_id', 'project_id']) AS properties
    """
    
    # print(request)

    # Convert request to a list of dictionaries with labels and properties
    nodes_data = [{"labels": node.labels, "properties": node.properties} for node in request.nodes]

    result = await run_query(query, {
        "nodes": nodes_data,
        "graph_id": request.graph_id,
        "user_id": request.user_id,
        "project_id": request.project_id
    })
    records = result
    if not records:
        raise HTTPException(status_code=500, detail="Failed to add node")
    
    return {
        "message": "Nodes added successfully",
        "nodes": result,
        # "source_node_ids": [n.source_node_id for n in request.nodes]
    }

# @app.post("/debug")
# async def debug(req: dict):
#     print(req)
#     return req

# Route to view all nodes
@app.get("/view-nodes")
async def view_nodes():
    query = "MATCH (n) RETURN labels(n) AS labels, n AS node"
    result = await run_query(query)
    nodes = [{"labels": record["labels"], "properties": record["node"]} for record in result]
    return {"nodes": nodes}

# Route to get the full graph (nodes + relationships)
@app.get("/graph")
async def get_graph():
    # query = """
    # MATCH (n)
    # WHERE n.user_id = $user_id AND n.project_id = $project_id AND n.graph_id = $graph_id
    # OPTIONAL MATCH (n)-[r]->(m)
    # WHERE m.user_id = $user_id AND m.project_id = $project_id AND m.graph_id = $graph_id
    # RETURN {
    #     id: elementId(n),
    #     labels: labels(n),
    #     properties: apoc.map.removeKeys(n, ['user_id', 'project_id', 'graph_id'])
    # } AS n, r, m
    # """
    query = """
    MATCH (n)
    OPTIONAL MATCH (n)-[r]->(m)
    RETURN {
        id: elementId(n),
        labels: labels(n),
        properties: apoc.map.removeKeys(n, ['user_id', 'project_id', 'graph_id'])
    } AS n, r, m
    """
    # result = await run_query(query, {"user_id": request.user_id, "project_id": request.project_id, "graph_id": request.graph_id})
    result = await run_query(query)

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
    MATCH (a) WHERE elementId(a)=pair.from_node
    MATCH (b) WHERE elementId(b)=pair.to_node
    CALL apoc.create.relationship(a, $relationship, {}, b) YIELD rel as r
    RETURN collect(r) AS relationships
    """
    result = await run_query(query, request.model_dump())

    if not result:
        raise HTTPException(status_code=500, detail="Failed to create relationship")
    return {"message": "Relationship created successfully", "relationship": result[0]["relationships"]}

# Route to edit nodes
@app.put("/edit-nodes")
async def update_node(request: NodeUpdateRequest):
    if not request.updates:
        raise HTTPException(status_code=400, detail="Updates are required")

    set_query = ", ".join([f"n.{key} = ${key}" for key in request.updates.keys()])
    query = f"MATCH (n) WHERE elementId(n) = $id SET {set_query} RETURN n"

    parameters = {"id": request.id, **request.updates}
    result = await run_query(query, parameters)
    records = result.data()
    if not records:
        raise HTTPException(status_code=404, detail="No matching node found")
    return {"message": "Node updated successfully", "node": records[0]["n"]}

# Route to delete a node
@app.delete("/delete-node/{node_id}")
async def delete_node(node_id: UUID):
    print(node_id)
    query = "MATCH (n) WHERE elementId(n)=$id DETACH DELETE n"
    # AND n.user_id = $user_id AND n.project_id = $project_id
    await run_query(query, {"id": node_id})
    return {"message": "Node deleted successfully"}

# Route to delete all nodes
@app.delete("/delete-all")
async def delete_node(request: BaseRequest = Body(...)):
    query = "MATCH (n) WHERE n.user_id = $user_id AND n.project_id = $project_id DETACH DELETE n"
    await run_query(query, {"user_id": request.user_id, "project_id": request.project_id})
    return {"message": "Nodes deleted successfully"}

@app.exception_handler(Exception)
def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "There is a problem with our servers. Please try again later.",
            "code": "SERVER_ERROR"
        },
    )

@app.exception_handler(HTTPException)
def http_exception_handler(request: Request, exc: HTTPException):
    # If developer raises HTTPException(detail=...)
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": str(exc.detail)},
    )

# Run the FastAPI server
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5500, reload=True)
