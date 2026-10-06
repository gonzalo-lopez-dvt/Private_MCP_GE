import os
import random

from mcp.server import MCPServer

# MCP server con transporte Streamable HTTP (el que consumen los agentes
# tipo Vertex AI / Gemini Enterprise). En mcp 2.x la clase es MCPServer
# (antes FastMCP). host/port/stateless se pasan en run().
mcp = MCPServer(name="mcp-test")


@mcp.tool()
def saluda(nombre: str) -> str:
    """Devuelve un saludo personalizado."""
    return f"¡Hola, {nombre}! Soy un MCP de prueba corriendo en Cloud Run 🚀"


@mcp.tool()
def suma(a: float, b: float) -> float:
    """Suma dos números y devuelve el resultado."""
    return a + b


@mcp.tool()
def tira_dado(caras: int = 6) -> int:
    """Tira un dado de N caras (por defecto 6) y devuelve el resultado."""
    caras = max(1, caras)
    return random.randint(1, caras)


if __name__ == "__main__":
    # stateless_http=True => cada request es independiente, ideal para el
    # autoescalado de Cloud Run. Endpoint MCP expuesto en /mcp
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        stateless_http=True,
    )
