"""LLM guionizado para tests y evidencia reproducible (sin Ollama).

Sustituye **únicamente** la decisión del modelo por una secuencia fija de
`AIMessage`. Todo lo demás es real: el servidor MCP se levanta, las
herramientas se ejecutan, la autenticación valida credenciales y el control de
rol rechaza lo que debe rechazar.

## Por qué existe el marcador `<TOKEN>`

Un token de sesión no se conoce hasta que `autenticar` responde. Un LLM real lo
lee del resultado de la herramienta y lo usa en la llamada siguiente. Para que
el guion pueda hacer lo mismo sin acoplarse a un valor concreto, los argumentos
pueden escribir `"<TOKEN>"` y esta clase lo reemplaza por el token que aparezca
en el último `ToolMessage` que lo haya devuelto.

Sin ese mecanismo habría que escribir el token literal en el guion, lo que
haría que la evidencia dependiera de un valor calculado a mano y dejara de
probar que el token realmente viaja desde la herramienta hasta el agente.
"""

from __future__ import annotations

import json

from langchain_core.messages import AIMessage

MARCADOR_TOKEN = "<TOKEN>"


class ScriptedLLM:
    """Devuelve una secuencia fija de AIMessage, resolviendo `<TOKEN>`."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0

    def bind_tools(self, tools):
        return self

    @staticmethod
    def _token_en_historial(messages) -> str | None:
        """Busca hacia atrás el token devuelto por la herramienta de autenticación."""
        for msg in reversed(messages):
            if msg.__class__.__name__ != "ToolMessage":
                continue
            try:
                payload = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(payload, dict) and payload.get("token"):
                return str(payload["token"])
        return None

    @classmethod
    def _resolver(cls, respuesta: AIMessage, messages) -> AIMessage:
        llamadas = getattr(respuesta, "tool_calls", None)
        if not llamadas:
            return respuesta
        necesita = any(
            MARCADOR_TOKEN in str(v) for call in llamadas for v in call["args"].values()
        )
        if not necesita:
            return respuesta

        token = cls._token_en_historial(messages) or MARCADOR_TOKEN
        nuevas = []
        for call in llamadas:
            args = {
                k: (v.replace(MARCADOR_TOKEN, token) if isinstance(v, str) else v)
                for k, v in call["args"].items()
            }
            nuevas.append({**call, "args": args})
        return AIMessage(content=respuesta.content, tool_calls=nuevas)

    async def ainvoke(self, messages):
        if self._index >= len(self._responses):
            return AIMessage(content="No hay más pasos de razonamiento.")
        respuesta = self._responses[self._index]
        self._index += 1
        return self._resolver(respuesta, messages)
