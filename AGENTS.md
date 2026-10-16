# Desarrollo del addon OdooClaw

Estas instrucciones son para agentes que modifican el código del addon.
Lee también el AGENTS.md del proyecto Doodba y scripts/odooclaw/WORKTREES.rst.

## Carpeta de trabajo

- Trabajo actual: `/home/rubenfernandez/CMP/doodba-cmp/odoo/custom/worktrees/odooclaw-app-operarios/odoo/custom/src/odooclaw-addons`.
- Rama de tarea: `feature/odooclaw-app-operarios`.
- La carpeta equivalente dentro de `/home/rubenfernandez/CMP/doodba-cmp` es estable
  y está en `16.0`; la instalación actual lee de ella.

Comprueba `git status --short`, `git branch --show-current` y `git worktree list`.
Si arrancas en la base estable para una modificación, cambia el directorio de tus
herramientas al worktree de la tarea. No cambies la rama de la base ni muevas .git.
Este componente tiene su propio Git; el workspace común no lo fusiona con Doodba.

## Archivos principales

- `mail_bot_odooclaw/models/mail_channel.py`: selección/validación de operarios,
  creación, listado, apertura y borrado de conversaciones, metadatos de canales.
- `mail_bot_odooclaw/static/src/conversations.js` y `.xml`: menú y selector por pestaña.
- `mail_bot_odooclaw/static/src/conversation_lifecycle.js`: sincronización local de
  ventanas, visibilidad en Discuss y retirada de vistas con canales inaccesibles.
- `mail_bot_odooclaw/models/res_partner.py`: exclusión de canales IA en Discuss.
- `mail_bot_odooclaw/controllers/main.py` y `security.py`: respuestas y operaciones delegadas.
- `mail_bot_odooclaw/models/mail_thread.py`: webhook e identidad de la solicitud.
- `mail_bot_odooclaw/models/mail_odooclaw_reply_token.py`: capacidades temporales y progreso.
- `mail_bot_odooclaw/utils/token_usage.py`: pie de consumo de la respuesta.
- `mail_bot_odooclaw/__manifest__.py`: dependencias, versión y assets del addon.

## Reglas de la tarea

La aplicación propia todavía está pendiente. Primero investiga el acceso nativo
al bot desde Discuss y la identidad efectiva de la petición. La interfaz no es
una barrera de autorización: valida en servidor pertenencia al canal y operario.
No concedas permisos de negocio con sudo para resolver un rechazo. Conserva las
ACL, reglas y compañías del usuario Odoo que envía cada solicitud.

El selector actual no tiene PIN. Un operario seleccionado no equivale a una
identidad autenticada. El PIN solicitado debe diseñarse de forma explícita.
La apertura/cierre de ventanas de un operario no debe afectar a otros terminales.

Las pruebas de selector/lifecycle y los scripts de pruebas Odoo están en el
repositorio Doodba, bajo scripts/odooclaw. Examina el entorno antes de lanzarlos:
los que usan Compose se dirigen al entorno configurado. No reinstales, actualices
ni reinicies Odoo sólo por modificar documentación. No cambies registros de
negocio para una prueba sin necesidad ni reproduzcas instrucciones de chats viejos.

Guarda los cambios del addon en este repositorio. `origin` es
ProjectsByRuben/odoo-addons y `upstream` es nicolasramos/odoo-addons. No publiques ni
integres sin autorización. Actualiza los parches/referencias del proyecto cuando
corresponda a cambios funcionales; no los regeneres sólo por un AGENTS.md.
