"""Expose the same operations individually for the Track 2 comparison."""

from mcp.server.fastmcp import FastMCP

from synapse.workflow import evaluate_routes, get_cancelled_pickup, screen_volunteers

server = FastMCP("Food rescue dispatch: individual operations")
for operation in (get_cancelled_pickup, screen_volunteers, evaluate_routes):
    server.tool()(operation)

if __name__ == "__main__":
    server.run()
