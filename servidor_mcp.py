"""MCP server for the Agents Tutorials series (TA07 / TA08).

Exposes three tools, two resources, and two prompts over the Model Context
Protocol using FastMCP. The server runs in stdio mode and is consumed by
MCP-compatible clients such as Claude Desktop and LangChain's
MultiServerMCPClient (TA08).

Run commands
------------
Start in stdio mode (used by MCP hosts and LangChain):
    python servidor_mcp.py

Open the interactive MCP Inspector in the browser:
    mcp dev servidor_mcp.py

Tools     : convert_units, calculate, get_weather
Resources : config://server/info, units://reference/{category}
Prompts   : conversion_assistant, math_tutor
"""

from mcp.server.fastmcp import FastMCP
from typing import Annotated
from pydantic import Field
import ast, operator, json
import requests


# ── conversion table ───────────────────────────────────────────────────────
# Each key is a (from_unit, to_unit) tuple; the value is a conversion lambda.
# Lookup is O(1) and adding a new unit pair requires only a new entry here —
# no changes to the tool logic are needed.
CONVERSIONS = {
    ("km", "miles"):           lambda x: x * 0.621371,
    ("miles", "km"):           lambda x: x * 1.60934,
    ("celsius", "fahrenheit"): lambda x: x * 9 / 5 + 32,
    ("fahrenheit", "celsius"): lambda x: (x - 32) * 5 / 9,
    ("kg", "lbs"):             lambda x: x * 2.20462,
    ("lbs", "kg"):             lambda x: x * 0.453592,
    ("meters", "feet"):        lambda x: x * 3.28084,
    ("feet", "meters"):        lambda x: x * 0.3048,
    ("liters", "gallons"):     lambda x: x * 0.264172,
    ("gallons", "liters"):     lambda x: x * 3.78541,
}

# Whitelist of AST node types mapped to their safe Python operator equivalents.
# Any node NOT listed here — function calls, attribute access, name lookups,
# imports — causes _safe_eval to raise ValueError, blocking code injection
# at the parse stage before any execution occurs.
ALLOWED_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Pow:  operator.pow,
    ast.Mod:  operator.mod,
    ast.USub: operator.neg,
}


def _safe_eval(node):

    """Recursively evaluate an AST node using only whitelisted arithmetic operators.

    Walks the syntax tree produced by ast.parse() and applies the corresponding
    Python operator for each node. Accepts only numeric constants, binary
    operations (e.g. +, *, **), and unary negation. Any other node type —
    function calls, attribute access, name lookups — raises ValueError before
    any code executes, blocking injection attempts at the AST level.

    Args:
        node: An ast.expr node, typically tree.body from
              ast.parse(expression, mode="eval").

    Returns:
        The numeric result (int or float) of the expression.

    Raises:
        ValueError: If the node type is not in ALLOWED_OPS or is not a numeric
                    constant. The caller wraps this in a user-facing message.
    """

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value

    elif isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))

    elif isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPS:
        return ALLOWED_OPS[type(node.op)](_safe_eval(node.operand))

    # Anything else — Call, Attribute, Name, Import — is rejected.
    raise ValueError(f"Unsupported node type: {type(node).__name__}")


# ── static data ────────────────────────────────────────────────────────────
# Unit reference tables keyed by category, used by the get_units_reference resource.
# Each inner dict maps the short symbol used in CONVERSIONS to a human-readable name.

UNITS_REFERENCE = {
    "length":      {"km": "kilometers", "miles": "miles", "meters": "meters", "feet": "feet"},
    "temperature": {"celsius": "Celsius (C)", "fahrenheit": "Fahrenheit (F)"},
    "mass":        {"kg": "kilograms", "lbs": "pounds"},
    "volume":      {"liters": "liters", "gallons": "gallons"},
}


# ── server ─────────────────────────────────────────────────────────────────
# instructions is included in the server manifest sent to MCP clients.
# Hosts may surface it as context when the model decides which server to query.
mcp = FastMCP(
    name="agents-tutorial-server",
    instructions=(
        "Educational MCP server — unit conversion, arithmetic, and weather tools. "
        "Part of the Agents Tutorials series (TA07/TA08)."
    ),
)


# ── tools ──────────────────────────────────────────────────────────────────
@mcp.tool()
def convert_units(
    value:     Annotated[float, Field(description="Numeric value to convert")],
    from_unit: Annotated[str,   Field(description="Source unit: km, miles, celsius, fahrenheit, kg, lbs, meters, feet, liters, gallons")],
    to_unit:   Annotated[str,   Field(description="Target unit: km, miles, celsius, fahrenheit, kg, lbs, meters, feet, liters, gallons")],
) -> str:
    
    """Convert a numeric value between supported units of measurement.

    Supports ten bidirectional pairs: km↔miles, celsius↔fahrenheit, kg↔lbs,
    meters↔feet, liters↔gallons. Returns a formatted equality string on success
    or a descriptive error message when the pair is not in CONVERSIONS, letting
    the model relay a meaningful response instead of an opaque failure.

    Args:
        value:     The numeric quantity to convert.
        from_unit: Source unit name (case-insensitive, whitespace stripped).
        to_unit:   Target unit name (same normalisation as from_unit).

    Returns:
        "{value} {from_unit} = {result:.4f} {to_unit}" on success, or an
        unsupported-pair message listing valid combinations.
    """

    # Normalise before lookup so "KM", " km " and "km" all resolve correctly.
    key = (from_unit.lower().strip(), to_unit.lower().strip())

    if key in CONVERSIONS:
        return f"{value} {from_unit} = {CONVERSIONS[key](value):.4f} {to_unit}"

    return (
        f"Conversion from {from_unit!r} to {to_unit!r} is not supported. "
        f"Valid pairs: km/miles, celsius/fahrenheit, kg/lbs, meters/feet, liters/gallons."
    )


@mcp.tool()
def calculate(
    expression: Annotated[str, Field(description="Arithmetic expression using +, -, *, /, **, % and numbers")],
) -> str:
    
    """Evaluate a mathematical expression safely without using eval().

    Uses ast.parse() to convert the expression to a syntax tree, then walks it
    with _safe_eval(), which only processes nodes listed in ALLOWED_OPS. This
    prevents code injection: __import__('os').system('...') parses to a Call
    node, which _safe_eval rejects before any OS command executes.

    Args:
        expression: A string containing a mathematical expression, e.g. "2 ** 10"
                    or "15 * 7 + 3". Supports +, -, *, /, **, % and unary minus.

    Returns:
        A string of the form "{expression} = {result}".

    Raises:
        ValueError: If the expression contains unsupported syntax or node types.
    """

    try:
        tree = ast.parse(expression, mode="eval")
        return f"{expression} = {_safe_eval(tree.body)}"
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"Invalid expression: {e}")


@mcp.tool()
def get_weather(
    city: Annotated[str, Field(description="City name to get current weather for (e.g. 'London', 'Buenos Aires')")],
) -> str:
    """Return the current weather for a city using the wttr.in public API.

    Fetches real-time conditions from wttr.in, which requires no API key and
    accepts city names in any language. On network failure or an unrecognised
    city, returns a descriptive error string rather than raising an exception,
    so the model always receives a usable result to relay.

    Args:
        city: Name of the city to query.

    Returns:
        A summary string with temperature (°C), weather description, and
        humidity, or an error message if the HTTP request fails.
    """
    try:
        response = requests.get(
            f"https://wttr.in/{city}?format=j1",
            timeout=5,
        )
        response.raise_for_status()
        current  = response.json()["current_condition"][0]
        temp_c   = current["temp_C"]
        desc     = current["weatherDesc"][0]["value"].lower()
        humidity = current["humidity"]
        return f"Weather in {city}: {temp_c}°C, {desc}, humidity {humidity}%"
    except requests.RequestException as e:
        return f"Could not fetch weather for {city!r}: {e}"


# ── resources ──────────────────────────────────────────────────────────────
@mcp.resource("config://server/info")
def get_server_info() -> str:

    """Metadata and capabilities of this MCP server.

    Static resource — every read returns the same server manifest. MCP clients
    can fetch this URI to discover which tools, resources, and prompts are
    available without having to call list_tools() / list_prompts() separately.

    Returns:
        JSON string with name, version, tools, resources, and prompts fields.
    """

    return json.dumps({
        "name":      "agentes-tutorial-server",
        "version":   "1.0.0",
        "tools":     ["convert_units", "calculate", "get_weather"],
        "resources": ["config://server/info", "units://reference/{category}"],
        "prompts":   ["conversion_assistant", "math_tutor"],
    }, indent=2, ensure_ascii=False)


@mcp.resource("units://reference/{category}")
def get_units_reference(category: str) -> str:

    """Unit reference table for a given category.

    Template resource — the {category} segment in the URI is resolved at read
    time and passed as the category argument. One function definition covers all
    of: units://reference/length, units://reference/temperature, etc.

    Args:
        category: One of "length", "temperature", "mass", or "volume".

    Returns:
        JSON string with the symbol-to-name mapping for the requested category,
        or an error object listing available categories when not found.
    """

    data = UNITS_REFERENCE.get(category.lower())
    if data is None:
        return json.dumps(
            {"error": f"Category {category!r} not found", "available": list(UNITS_REFERENCE.keys())},
            ensure_ascii=False,
        )
    return json.dumps({category: data}, indent=2, ensure_ascii=False)


# ── prompts ────────────────────────────────────────────────────────────────
@mcp.prompt()
def conversion_assistant(unit_system: str = "metric") -> str:

    """System prompt that configures the assistant as a unit conversion expert.

    Args:
        unit_system: Preferred measurement system, "metric" or "imperial".
                     Any value other than "metric" is treated as "imperial".

    Returns:
        A system prompt string ready to be injected into a conversation.
    """

    system = "metric" if unit_system == "metric" else "imperial"
    return (
        f"You are a unit conversion expert. The user prefers the {system} system. "
        f"Always show the step-by-step procedure and round results to 4 decimal places."
    )


@mcp.prompt()
def math_tutor(level: str = "intermediate") -> str:

    """System prompt that configures the assistant as a math tutor.

    Args:
        level: Student level — "beginner", "intermediate", or "advanced".
               Unknown values fall back to "intermediate" behaviour.

    Returns:
        A system prompt string ready to be injected into a conversation.
    """
    
    depth = {
        "beginner":     "Use simple examples and avoid formal notation.",
        "intermediate": "Use standard notation and explain the reasoning at each step.",
        "advanced":     "Assume algebra knowledge and use precise mathematical notation.",
    }
    return f"You are a math tutor. Student level: {level}. {depth.get(level, depth['intermediate'])}"


# ── entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # stdio transport: the MCP host spawns this script as a subprocess and
    # communicates over stdin/stdout using the MCP wire protocol.
    # This is the transport expected by Claude Desktop and LangChain's
    # MultiServerMCPClient (used in TA08).
    mcp.run(transport="stdio")
