# Modo servidor (Coolify)

La misma aplicación, para todo el equipo desde el navegador. Decisiones y alcance: `docs/plan-equipos.md`, A7.

## Desplegar en Coolify

1. **New resource → Application →** este repositorio, rama que quieras desplegar, **Build pack: Dockerfile**.
2. **Port:** `8000`. Pon un dominio con HTTPS (Coolify lo gestiona con su proxy).
3. **Persistent storage:** un volumen montado en `/data` (proyectos, registro, usuarios, secretos). Sin volumen se pierde todo al redesplegar.
4. **Environment variables:**
   - `ACTAS_ADMIN`: nombre del primer administrador.
   - `ACTAS_ADMIN_CLAVE`: su contraseña (10 caracteres o más). Solo se usa si aún no hay usuarios; después puedes quitarla.
5. Despliega y entra en el dominio con ese usuario. En **Ajustes › Usuarios** das de alta al resto.

Opcionales: `ACTAS_PORT` (8000) y `ACTAS_HOST` (0.0.0.0).

**CPU baja siempre.** El servidor no corre modelos ni nada pesado: ni IA local (LLM, Whisper), ni embeddings (la búsqueda va por
vocabulario, también con `ACTAS_NO_EMBED=0`), ni OCR (las páginas escaneadas y las imágenes entran sin su texto), ni vídeo. La IA
solo con un modelo en la nube, que corre fuera; lo pesado se procesa en el escritorio y se envía al servidor.

## Qué hay y qué no

- Todo pide sesión (o el token personal del escritorio). La sesión dura dos semanas; reiniciar el servidor obliga a entrar de nuevo.
- Todos ven todos los proyectos. El historial guarda quién hizo cada cambio.
- **Sin IA local; sí en la nube:** el servidor nunca arranca modelos locales ni CLIs de IA. Preguntar, «Regenerar con IA», derivar, redactar informes, buscar a fondo y describir capturas funcionan si eliges un proveedor de la nube con clave (enlace «Modelos en la nube» en Preguntar o al añadir). La clave se guarda en el volumen (ver abajo). Las reuniones se transcriben y procesan en el escritorio.
- **Bloqueado en el servidor:** elegir ficheros o carpetas del disco, subir vídeos, grabar, carpetas vigiladas, modelos, compartir por OneDrive, descargas, MCP y Outlook. Los destinos «Carpeta» y «SFTP» tampoco (escriben en el disco del servidor o ejecutan comandos).
- Los secretos (claves de la nube, tokens de Jira, Planner…) se guardan en `/data/secretos.json` con permisos 600, en claro dentro del volumen: protege el volumen y sus copias.
- Cualquier usuario puede configurar webhooks y destinos HTTP; pueden llegar a la red interna del servidor. Da de alta solo a gente del equipo.

## Enviar desde el escritorio

1. En la web: Ajustes › Tu cuenta › Generar token.
2. En el escritorio: Ajustes › Equipo › Servidor de equipo: pega la dirección y el token y pulsa «Guardar y probar». El token se guarda en el llavero del sistema.
3. En cada proyecto: pestaña Ajustes › Compartir con el equipo › «Enviar al servidor de equipo».

Desde ahí se sincroniza solo cada minuto, en los dos sentidos:

- Viajan las tareas, decisiones y demás elementos, más las actas en zip ligero, sin vídeo.
- Las transcripciones solo viajan si marcas la casilla. Las actas que se anonimizan por defecto no se envían.
- Lo que el equipo cambia en la web vuelve al escritorio con su autor.

Un proyecto se comparte por carpeta (OneDrive) o por servidor, no por las dos vías a la vez.

## Agentes

Un agente (Claude, un script, un orquestador) puede usar la web en nombre de un usuario: en Ajustes › Agentes cada uno crea tokens
con permisos (leer, escribir, usar IA, borrar). El agente lee el manual UTCP en `/utcp` con ese token y llama a la API; lo que hace
sale en el historial como «Ana (agente: nombre)». Puede subir documentos (PDF, Word, Markdown, texto, HTML, correos; 50 MB): se
leen e indexan sin IA, o se resumen con la nube si el token tiene «usar IA». Detalle: `docs/plan-agentes.md`.

## Copias de seguridad

Basta con copiar el volumen `/data` (en Coolify: **Backups** del volumen, o un `tar` periódico). `registro.db` es SQLite: mejor copiarlo con la app parada o con `sqlite3 registro.db ".backup copia.db"`.
