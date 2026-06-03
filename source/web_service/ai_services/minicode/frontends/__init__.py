"""Adaptadores de interfaz (frontends) para el core de mini-code.

El core (``minicode.agent``) no conoce ninguna interfaz: hace ``yield`` de eventos
(``minicode.events``). Cada frontend de este paquete CONSUME ese stream de eventos
y lo materializa a su manera. Aquí vive el de terminal; una web (SSE/websocket) o
una API JSON serían módulos hermanos que reutilizan el mismo core sin tocarlo.
"""
