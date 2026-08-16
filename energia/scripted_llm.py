from langchain_core.messages import AIMessage


class ScriptedLLM:
    """LLM de prueba: devuelve una secuencia fija de AIMessage (sin Ollama)."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._index = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        if self._index >= len(self._responses):
            return AIMessage(content="No hay más pasos de razonamiento.")
        response = self._responses[self._index]
        self._index += 1
        return response
