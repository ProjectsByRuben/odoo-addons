OdooClaw: aplicación propia
==========================

Aplicación OWL para Odoo 16. Lista lateral de conversaciones y dos vistas del
mismo estado: pantalla completa y ventana flotante accesible desde la barra
superior. La ventana se mantiene al navegar por Odoo. Los perfiles y las ventanas
no se sincronizan entre pestañas ni navegadores.

Identidad y permisos
-------------------

El usuario Odoo determina permisos, reglas y compañías. En cuentas compartidas,
se selecciona además un empleado permitido por la política departamental del
puente. Se verifica su PIN nativo ``hr.employee.pin``. Si está vacío, el operario
lo crea y confirma en su primer acceso (de 4 a 8 dígitos). Se guarda en su ficha y
los siguientes accesos lo solicitan. El alta se serializa con bloqueo de fila y
no permite sustituir un PIN existente, ni elegir empleados fuera de su ámbito.
El restablecimiento de un PIN olvidado corresponde a un responsable con permisos
nativos de Recursos Humanos. No se concede escritura general sobre empleados.
Las cuentas personales no necesitan un PIN adicional.

Cinco fallos bloquean los intentos durante cinco minutos. El bloqueo se guarda en
el empleado y se serializa en PostgreSQL, también entre terminales. Los perfiles
caducan a las ocho horas y quedan vinculados a usuario, sesión Odoo, empleado y
compañías seleccionadas (incluida la principal). El cambio de PIN invalida sus
credenciales. Al caducar el acceso se puede recargar Odoo para identificarse de
nuevo. La ficha del empleado conserva el comportamiento nativo del PIN utilizado
también por asistencias o punto de venta.

Las autorizaciones guardadas en ``res.users.odooclaw_app_profiles`` contienen sólo
hashes de credenciales aleatorias, metadatos y una huella HMAC del PIN. El token
se conserva únicamente en memoria del cliente; no aparece en URLs, almacenamiento
local, mensajes ni notificaciones. Los bloqueos de fila evitan que las pestañas
sobrescriban sus autorizaciones concurrentes. Los datos técnicos quedan
restringidos mediante grupos nativos. No se amplían permisos de negocio con sudo.

Datos y protección del acceso
----------------------------

Se reutilizan ``mail.channel``, ``mail.message``, ``ir.attachment`` y el campo
``odooclaw_employee_id``. No se duplica ni migra el historial. Cada API comprueba
el perfil y la pertenencia exacta de usuario/bot y empleado antes de leer, enviar,
renombrar, descargar o borrar. Los chats antiguos de cuentas compartidas que no
tienen empleado asignado no se reasignan automáticamente a alguien.

``odooclaw.app.enforce=1`` activa la protección del ORM. Las consultas, las
lecturas directas (también desde controladores que usan sudo), las agrupaciones
y las mutaciones de conversaciones, mensajes y adjuntos quedan acotadas al perfil
verificado. El contexto interno incluye un marcador que no se puede construir
por JSON/RPC. El acceso nativo al bot mediante Discuss se rechaza; sus canales
no se listan allí y no se difunde el cuerpo de los mensajes por el bus compartido.
El parámetro se configura al instalar el módulo; no desactivarlo en producción.

El transporte del motor conserva sus capacidades temporales: cada llamada MCP
sigue usando el UID real y sus compañías, con ``su=False``. La excepción interna
para leer documentos del chat se limita a la conversación de esa capacidad.
El contexto interno se elimina de los resultados devueltos al motor. Las
respuestas del bot mantienen su validación de transporte/capacidad original.

Funcionamiento
--------------

* Lista de las últimas 100 conversaciones del perfil, creación, renombrado y
  borrado con confirmación. El borrado conserva las operaciones de negocio.
* Historial por páginas de 60 mensajes, con HTML saneado de Odoo, progreso y
  tokens originales. Consulta cada cuatro segundos sólo mientras hay una vista
  activa; se comprueba la revisión antes de volver a descargar los cuerpos.
* Archivos de hasta 25 MB, hasta 20 por mensaje. El servidor valida el chat y la
  propiedad del adjunto. Las subidas/descargas usan POST y CSRF sin tokens en URLs.
  El puente transmite los mismos adjuntos al motor; sus lectores PDF/MSG y otros
  formatos no se sustituyen por esta aplicación.
* Cuota compartida del proveedor por ventanas de tiempo, consultada como máximo
  una vez por minuto durante la conversación. No es una inferencia al modelo.
* El webhook se inicia después del commit: un rollback o reintento de Odoo no
  debe disparar dos operaciones de negocio ni publicar una capacidad sin guardar.

Modelo por conversación
-----------------------

El desplegable del chat permite elegir modelo, razonamiento y rapidez de la
cuenta Codex autenticada. El catálogo viene de model/list del app-server del CLI;
no se inventa una lista de modelos ni se hace una inferencia para consultarlo.
Se conserva en caché cinco minutos en Go (fallos, treinta segundos). Sólo se
publican identificadores, nombres y capacidades; sin identidad ni credenciales.

mail.channel.odooclaw_model_settings conserva las tres preferencias del chat.
Las rutas /models y /model_settings verifican perfil y pertenencia. El servidor
rechaza combinaciones ajenas al catálogo; Go vuelve a validarlas antes de llamar
al CLI. Los ajustes se incluyen como snapshot en el webhook y se transmiten por
contexto de esa solicitud, nunca cambiando agent.Model ni config.toml global.
CLI recibe -m y -c por proceso; otras conversaciones mantienen sus ajustes.
Los chats sin elección propia usan GPT-6.1-Sol, razonamiento medium y tier default
(estándar). Restaurar Predeterminado devuelve esa combinación. Las selecciones
explícitas de otras conversaciones se conservan. Los selectores OWL usan t-model
para sincronizar valor visual y estado; un fallo de guardado restaura la última
selección confirmada por servidor.
Los cambios se aplican a próximos mensajes, no al trabajo ya iniciado. Durante
el guardado se bloquea el envío para evitar usar los ajustes anteriores por una
carrera. Puede restaurarse Predeterminado del sistema sin alterar otros chats.
La opción rápida sólo aparece si se anuncia para ese modelo y puede consumir
más cuota. Si no hay catálogo, se conservan los ajustes y se permite reintentar.

Mapa del código
---------------

* ``__manifest__.py``: dependencias ``web`` y ``mail_bot_odooclaw``, assets propios
  y retirada del selector antiguo. ``data/security.xml`` activa la protección.
* ``views/odooclaw_menu.xml``: aplicación y acción de cliente.
* ``models/profile.py``: PIN, intentos, bloqueo, autorizaciones, usuario y compañías.
* ``models/conversation.py``: pertenencia al chat, listado, mensajes y archivos.
* ``models/access.py``: protección ORM/bus y contexto limitado del motor delegado.
* ``controllers/workspace.py``: rutas autenticadas, selección de compañías y CSRF.
* ``static/src/workspace_service.js``: estado por cliente, solicitudes, respuestas
  tardías, revisión del historial, ventana, cuota y transferencia de archivos.
* ``static/src/workspace.js``: componentes, formularios, diálogos y scroll.
* ``static/src/workspace.xml`` y ``workspace.scss``: interfaz adaptable.
* ``tests/test_profile.py``: permisos, PIN, sesiones, compañías, adjuntos, contexto
  delegado y notificaciones. Las fixtures se revierten; no se usa el modelo real.

Cambios mínimos del puente: ``controllers/main.py`` conserva identidad/capacidad
al aplicar el ámbito del chat y al publicar progreso; ``models/res_partner.py``
filtra los canales sin leer primero sus datos protegidos; ``models/mail_thread.py``
encola el webhook tras commit. El motor Go, su modelo, configuración y catálogo
MCP permanecen sin cambios.

Entorno de esta rama
-------------------

Tarea feature/odooclaw-modelos-chat en los tres repositorios, bajo
odoo/custom/worktrees/odooclaw/modelos-chat. Preview activa en cmpslu mediante
.docker/odooclaw-models-preview.yaml del worktree: monta este addon y addons.yaml.
El motor usa cmp-odooclaw-codex:modelos-chat, con nuevo binario Go sobre la imagen
anterior. Se conservan CLI, MCP y autenticación. El .env estable referencia el
override; no mover ni retirar el worktree mientras esté montado. No se integró
ni publicó esta tarea. Consultar PROGRESS.md del proyecto.


Preguntas rápidas
-----------------

En cada chat abierto, pantalla completa y flotante comparten dos accesos sobre
el cuadro de escritura: Mi sesión (usuario, perfil, permisos y empresa) y
Modelo y ajustes (modelo, razonamiento y servicio). Cada botón envía directamente una pregunta predefinida usando
el servicio de envío y el perfil actuales. Sus textos están en QUICK_QUESTIONS,
en static/src/workspace.js; presentación en workspace.xml/workspace.scss.

Los accesos se bloquean si hay borrador, adjuntos, subida, guardado del modelo o
un envío en curso; tampoco envían sin perfil/chat activo. No añaden, descartan ni
incluyen documentos pendientes. Se conserva el envío normal y la validación en
servidor. El motor responde con sus datos de sesión sin inferencia si están
completos; las frases se corresponden con odoo_session_questions.go del motor.


Prueba: contexto del registro abierto
------------------------------------

Rama feature/odooclaw-contexto-registro. Desde un formulario guardado de Odoo,
abre la ventana flotante y un chat: Añadir registro actual incorpora una tarjeta
con nombre, tipo e ID. Puedes quitarla o sustituirla explícitamente. Cambiar de
pantalla no cambia el contexto seleccionado; al cambiar de chat u operario se
vacía. La tarjeta también se conserva al abrir ese chat en la aplicación grande.
Los registros nuevos sin guardar, listas y asistentes no se capturan.

Archivos del registro permite seleccionar los adjuntos binarios asociados al
registro (no binarios de campos internos ni enlaces). Se muestran hasta 100
archivos recientes. Nada se copia al elegir el registro: sólo al enviar se copian
los archivos marcados al chat privado. Máximo 20 archivos por mensaje, 25 MB por
archivo de contexto y 50 MB en la selección del registro. No se alteran originales.
Escribe una solicitud para enviar: Resume este registro, Revisa sus líneas,
Lee el PDF seleccionado, etc. Seleccionar un contexto no ejecuta acciones de IA.

El servidor comprueba perfil, conversación, ACL y reglas del registro y de sus
archivos, incluidas las compañías de la sesión. Las validaciones se repiten al
enviar. No se usa sudo. Los adjuntos del registro deben pertenecer exactamente
a ese modelo/ID; no basta con proporcionar un ID de archivo. Se añade al mensaje
sólo una referencia de Odoo validada y sus archivos seleccionados; el agente
consulta el resto cuando lo requiere la solicitud, usando su transporte habitual.
La referencia no concede permisos ni autoriza por sí sola modificaciones.

Código: models/record_context.py valida referencias, lista adjuntos y prepara
copias; models/conversation.py y controllers/workspace.py integran el envío;
workspace_service.js detecta la vista y aísla las solicitudes y el estado;
workspace.js/xml/scss presentan el botón, la tarjeta y la selección. Los botones
rápidos de sesión se desactivan con contexto para no prometer inferencia cero en
una petición que ya contiene referencias de negocio.

Detección del registro y archivos
--------------------------------

«Añadir registro actual» se habilita al entrar en un formulario guardado, también
con un chat ya abierto. La detección espera la actualización del router de Odoo.
El botón conserva el borrador y los adjuntos propios; al capturar de nuevo el
mismo registro conserva los archivos seleccionados que siguen disponibles.
La navegación por sí sola no sustituye el contexto elegido. Si no hay archivos
accesibles, la tarjeta muestra un aviso sin desplegable. La barra de conversaciones
incluye un botón propio para cerrarla en la aplicación y en la ventana flotante.

Primer mensaje
--------------

Con el perfil desbloqueado se puede escribir sin seleccionar una conversación.
El primer envío crea el chat con ese perfil y envía el texto; escribir por sí
solo no crea canales. En cuentas compartidas es obligatorio seleccionar y
verificar primero al operario. El borrador se conserva ante errores y se descarta
el envío pendiente si cambia el perfil o se elige otra conversación durante la
creación. Los archivos se adjuntan cuando ya hay una conversación abierta.

Consultas sencillas sin IA
-------------------------

El motor responde de forma determinista a consultas completas de hora y fecha,
cálculos básicos, porcentajes, conversiones de unidades, agradecimientos y ayuda.
La hora usa reglas IANA y horario de verano; sin lugar explícito usa la zona del
usuario de Odoo si existe. Los países con varios husos requieren ciudad.
Estas respuestas conservan historial y muestran consumo real de cero tokens.
Las peticiones con adjuntos, contexto de registros o instrucciones adicionales
siguen usando el agente normal. El permiso del usuario no cambia.


Historial de versiones
=====================

16.0.1.1.0 (2026-10-27)
----------------------

Consolida selección de modelo, razonamiento y rapidez por conversación,
contexto explícito del registro y adjuntos seleccionados, creación del primer
chat y utilidades deterministas sin inferencia. Conserva PIN nativo, perfiles
independientes, historial, cuota y permisos nativos de Odoo. Las pruebas de
servidor usan fixtures revertidas, sin red ni GC de filestore.
