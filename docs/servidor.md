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

Opcionales: `ACTAS_PORT` (8000), `ACTAS_HOST` (0.0.0.0), `ACTAS_NO_EMBED=0` para búsquedas semánticas con el modelo de embeddings (lo descarga la primera vez; con `1` se busca por vocabulario).

## Qué hay y qué no

- Todo pide sesión (o el token personal del escritorio). La sesión dura dos semanas; reiniciar el servidor obliga a entrar de nuevo.
- Todos ven todos los proyectos. El historial guarda quién hizo cada cambio.
- **Sin IA local:** procesar reuniones, Preguntar con LLM, poblar o redactar responden «En el servidor no hay IA local». Las reuniones se procesan en el escritorio.
- **Bloqueado en el servidor:** elegir ficheros o carpetas del disco, subir vídeos, grabar, carpetas vigiladas, modelos, compartir por OneDrive, descargas, MCP y Outlook. Los destinos «Carpeta» y «SFTP» tampoco (escriben en el disco del servidor o ejecutan comandos).
- Los secretos (claves de la nube, tokens de Jira, Planner…) se guardan en `/data/secretos.json` con permisos 600, en claro dentro del volumen: protege el volumen y sus copias.
- Cualquier usuario puede configurar webhooks y destinos HTTP; pueden llegar a la red interna del servidor. Da de alta solo a gente del equipo.

## Copias de seguridad

Basta con copiar el volumen `/data` (en Coolify: **Backups** del volumen, o un `tar` periódico). `registro.db` es SQLite: mejor copiarlo con la app parada o con `sqlite3 registro.db ".backup copia.db"`.
