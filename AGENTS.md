# Desarrollo del addon OdooClaw

Estas instrucciones son para agentes que modifican el código del addon.
Lee también el AGENTS.md del proyecto Doodba y scripts/odooclaw/WORKTREES.rst.

## Base consolidada

La rama estable es `16.0` en `odoo/custom/src/odooclaw-addons`.
Reúne modelos por conversación, contexto de registro, archivos elegidos y
utilidades locales del motor. La instancia de pruebas lee esta base estable.
El desarrollo está en `odoo/custom/worktrees/odooclaw/desarrollo`, rama
`dev/local` por componente. No montar worktrees en la instancia por accidente.
Ver `scripts/odooclaw/WORKTREES.rst` y `PROGRESS.md` del proyecto Doodba.

La nueva configuración está en models/model_settings.py y workspace*. Se persiste
por mail.channel y se valida contra el catálogo del CLI autenticado, manteniendo
la validación de perfil y permisos del usuario. Las opciones del mensaje viajan
como snapshot del webhook; no se modifica el proveedor global. Leer README.rst y
scripts/odooclaw/PROGRESS.md de la tarea. Se mantienen PIN, aislamiento, adjuntos,
progreso, cuota y permisos de negocio; no desactivar la protección de Discuss.

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

Contexto explícito en models/record_context.py; validar ACL/reglas/archivos sin sudo.
Al enviar, verificar de nuevo y copiar sólo los archivos elegidos al chat de ese
perfil. No capturar texto HTML de la página, credenciales ni campos en bloque.
El cliente conserva la referencia seleccionada hasta envío/cambio explícito,
la borra al cambiar de chat/perfil y descarta RPC tardíos. Ver README.rst.
