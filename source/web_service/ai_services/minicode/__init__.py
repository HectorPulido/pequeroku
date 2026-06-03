"""mini-code: una versión miniatura (pero potente) del núcleo agéntico de opencode.

El corazón del sistema es el *bucle agéntico* (``agent.Agent.run``): pensar →
llamar herramientas → ver resultados → repetir, hasta que el modelo responde sin
pedir más herramientas. El resto son piezas de soporte: herramientas (manos del
modelo), ensamblado de contexto, y el puente con un LLM compatible con OpenAI.
"""

__version__ = "0.1.0"
