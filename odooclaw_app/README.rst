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

La revisión se realiza en ``cmpslu`` por indicación de Rubén. El código permanece
en el worktree ``feature/odooclaw-app-propia``. El override del proyecto
``.docker/odooclaw-app-preview.yaml`` monta el repositorio de addons del worktree y
su ``addons.yaml`` en el servicio existente. No se copiaron fuentes sobre la rama
estable. Doodba reconstruye ``auto/addons`` al arrancar: no usar enlaces manuales
para este despliegue. Consultar WORKTREES.rst y PROGRESS.md del proyecto antes de
integrar o retirar el worktree. No se debe borrar un worktree aún montado.
