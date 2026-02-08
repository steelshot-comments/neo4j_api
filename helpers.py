from uuid import UUID
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USERNAME")
NEO4J_PASS = os.getenv("NEO4J_PASSWORD")
NEO4J_DB = os.getenv("NEO4J_DATABASE")

# Initialize Neo4j driver
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))

# Utility function to run Cypher queries
def serialize_params(params):
    if isinstance(params, dict):
        return {k: serialize_params(v) for k, v in params.items()}
    if isinstance(params, UUID):
        return str(params)
    if isinstance(params, list):
        return [serialize_params(v) for v in params]
    return params

async def run_query(query: str, parameters: dict = {}):
    params = serialize_params(parameters)

    with driver.session(database=NEO4J_DB) as session:
        result = session.run(query, params)
        return list(result) # Fetch all records before session closes