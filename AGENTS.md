# Desarrollo del addon OdooClaw

Estas instrucciones son para agentes que modifican el código del addon.
Lee también el AGENTS.md del proyecto Doodba y scripts/odooclaw/WORKTREES.rst.

## Estado estable

Código integrado en `/home/rubenfernandez/CMP/doodba-cmp/odoo/custom/src/odooclaw-addons`,
rama `16.0`. La instancia cmpslu utiliza esta carpeta estable; no queda worktree
activo de OdooClaw. No crear ramas ni comenzar tareas hasta que Rubén lo indique.
Para una nueva modificación, preparar una rama feature/<tema> o fix/<tema> y un
worktree bajo odoo/custom/worktrees/odooclaw/<tema>, conservando este repositorio.
Comprobar status, branch y worktree list antes de actuar. No desarrollar en estable.

El módulo `odooclaw_app` integra pantalla completa y flotante, historial, adjuntos,
progreso, tokens y perfiles independientes entre pestañas. Las cuentas compartidas
verifican el PIN nativo del empleado: vacío permite alta inicial confirmada por el
operario (4 a 8 dígitos), nunca sobrescritura de un PIN existente. Un responsable
restablece los olvidados con permisos nativos de RRHH. Cuentas personales sin PIN
adicional. Las operaciones de negocio conservan UID, ACL, reglas y compañías.
La app está instalada en cmpslu; no crear bases alternativas para esta tarea.

## Archivos principales

La interfaz activa está en `odooclaw_app/static/src/workspace*`; sus controladores
en `odooclaw_app/controllers/workspace.py` y la seguridad/perfil/conversaciones en
`odooclaw_app/models/`. Leer su README.rst. Los archivos conversations.js/xml del
puente son históricos y esta app los retira de los assets.

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

La aplicación propia protege APIs, ORM y difusión por bus. El acceso nativo al
bot desde Discuss se rechaza; no desactivar `odooclaw.app.enforce=1`. La interfaz no es
una barrera de autorización: valida en servidor pertenencia al canal y operario.
No concedas permisos de negocio con sudo para resolver un rechazo. Conserva las
ACL, reglas y compañías del usuario Odoo que envía cada solicitud.

El selector se completa con `hr.employee.pin` en servidor: cinco fallos bloquean
cinco minutos; perfiles de ocho horas ligados a UID, sesión y compañías. Un PIN
vacío requiere alta inicial confirmada (4–8 dígitos). No configurar PIN reales ni
usuarios adicionales para una prueba.
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
