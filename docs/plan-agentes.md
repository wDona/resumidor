# Agentes que usan Actas en nombre de un usuario

Objetivo: que un agente (Claude, un script, un orquestador) automatice investigaciones con documentos manejando la app como lo
haría la persona: crear el proyecto, subir los archivos, esperar a que se lean, buscar, preguntar con citas, anotar hallazgos,
redactar el informe y exportarlo o enviarlo. Igual en el escritorio que en el servidor de equipo.

## Decisiones

- **Protocolo: UTCP.** `GET /utcp` devuelve un manual UTCP 1.0 y el agente llama a la API real (sin servidor intermedio). El
  servidor MCP sigue como estaba para clientes de chat (Claude Desktop, Cursor…).
- **Operaciones curadas**, no las ~190 rutas: unas 35 con descripción y esquema de entrada propios (`agentes.OPS`). Lo que no está
  en la lista responde 403 a un token de agente. Así el agente no se pierde ni alcanza lo peligroso (ajustes, modelos, usuarios,
  claves).
- **Tokens de agente con permisos**: cada usuario crea los suyos (`agt_…`), con nombre y permisos: `leer`, `escribir`, `ia` (gasta
  en la nube o la GPU) y `borrar`. Por defecto, leer y escribir. El manual solo enseña lo que ese token puede hacer.
- **Autoría**: lo que hace el agente queda en el historial como «Ana (agente: Investigación)».
- **El agente ve lo mismo que su usuario**, también lo no anonimizado: crear el token es la autorización.
- **Escritorio**: la API local no pide credenciales (solo escucha en este equipo), así que los permisos protegen de errores de un
  agente que usa su token, no de un programa malicioso local. En el servidor sí son una barrera.
- **Subir documentos**: `POST /api/subir` (JSON con el fichero en base64), en los dos modos. En el servidor solo documentos
  (PDF, Word, Markdown, texto, HTML, correos; imágenes solo con IA en la nube), 50 MB como mucho. Sin `resumir` solo se leen e
  indexan (sin IA); con `resumir` se hace el acta con la nube (permiso `ia`).

## Fases

1. `agentes.py`: tokens, permisos, filtro y lista de operaciones; gestión en Ajustes (escritorio) y Tu cuenta (servidor).
2. Manual `GET /utcp` generado de `OPS`; envoltorios en texto donde la API no sirve tal cual (preguntar, documento, documentos).
3. `POST /api/subir`; en el servidor, leer documentos sin IA.
4. Prueba de punta a punta con el cliente python-utcp contra una instancia servidor.

## Investigaciones

Documentos en Markdown de un proyecto (`investigacion.py`), escritos por una persona o por un agente, que se exportan a `.md` o a
Word con el estilo de organización del proyecto (títulos, negritas, listas, tablas con enlaces). Se ven y descargan en la pestaña
Informe. El agente puede pedir una guía de redacción opcional (`guia_investigacion`): estructura Problema (solo si se planteó antes
o es evidente) · Formas de resolverlo · Soluciones exploradas (riesgos solo si importan) · A tener en cuenta · Propuesta · Extras,
y estilo compacto (cada frase aporta un dato; secciones pequeñas con títulos que dicen de qué hablan).
