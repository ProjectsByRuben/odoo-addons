import logging
import requests
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.http import request

_logger = logging.getLogger(__name__)


class MailChannel(models.Model):
    _inherit = "mail.channel"

    odooclaw_conversation = fields.Boolean(copy=False, readonly=True)
    odooclaw_employee_id = fields.Many2one("hr.employee", string="Operario OdooClaw", copy=False, index=True)

    @api.model
    def _odooclaw_conversation_user(self):
        # A browser can only create/list conversations for its own session.
        # In particular, the delegation service cannot impersonate a user here.
        if request and request.session.uid != self.env.uid:
            raise AccessError(_("Usa tu propia sesión de Odoo para abrir conversaciones."))
        user = self.env.user
        if not user.active or user.share or user.id == 1:
            raise AccessError(_("Esta opción requiere un usuario interno conectado."))
        return user

    @api.model
    def odooclaw_get_available_employees(self):
        """Return employees assigned to the current shared user's department."""
        user = self._odooclaw_conversation_user()
        login = (user.login or "").lower().strip()

        dept_domain = []
        if login == "almacen":
            dept_domain = [("name", "ilike", "ALMACEN")]
        elif login in ("fabrica", "produccion", "cproduccion"):
            dept_domain = [("name", "in", [
                "PRODUCCION", "MONTAJE", "SOLDADURA Y PREPARACION",
                "CORTE Y PREPARACION", "CONFORMADO", "PINTURA Y PREPARACION",
                "REPASADO MANUAL", "FRESADO Y PREPARACION"
            ])]
        elif login == "calidad":
            dept_domain = [("name", "ilike", "CALIDAD")]
        elif login == "logistica":
            dept_domain = [("name", "ilike", "LOGISTICA")]
        elif login in ("otecnica", "delineacion"):
            dept_domain = [("name", "in", ["OT", "DELINEACION"])]
        else:
            # Individual user (admin, named office users) -> No employee selector needed
            return []

        depts = self.env["hr.department"].sudo().search(dept_domain)
        if not depts:
            return []

        employees = self.env["hr.employee"].sudo().search_read(
            [("department_id", "in", depts.ids), ("active", "=", True)],
            ["id", "name"],
            order="name asc",
            limit=150
        )
        return employees

    @api.model
    def odooclaw_new_conversation(self, employee_id=None):
        user = self._odooclaw_conversation_user()
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        if not bot or not bot.active:
            raise UserError(_("OdooClaw no está disponible. Contacta con informática."))
        stamp = fields.Datetime.context_timestamp(self, fields.Datetime.now())

        employee = None
        if employee_id:
            try:
                emp_rec = self.env["hr.employee"].sudo().browse(int(employee_id))
                if emp_rec.exists():
                    employee = emp_rec
            except (ValueError, TypeError):
                employee = None

        prefix = f"OdooClaw [{employee.name}]" if employee else "OdooClaw"
        channel = self.create({
            "name": f"{prefix} · {stamp.strftime('%d/%m/%Y %H:%M')}",
            "channel_type": "group",
            "channel_partner_ids": [(4, user.partner_id.id), (4, bot.partner_id.id)],
            "odooclaw_conversation": True,
            "odooclaw_employee_id": employee.id if employee else False,
        })
        channel.name += " · " + str(channel.id)

        welcome_title = (
            f"Conversación nueva de {employee.name} con OdooClaw."
            if employee else
            "Conversación nueva con OdooClaw."
        )
        channel.with_user(bot).message_post(
            body=_(f"<p><strong>{welcome_title}</strong></p>"
                   "<p>Escribe tu solicitud aquí. Esta conversación empieza sin el contexto "
                   "de tus chats anteriores y utiliza los permisos de tu usuario actual.</p>"
                   "<p>Para abrir otra o volver a las anteriores, usa el menú "
                   "<strong>OdooClaw</strong> de la barra superior. Allí encontrarás "
                   "<strong>Cómo usarlo</strong>.</p>"),
            message_type="comment", subtype_xmlid="mail.mt_comment",
        )
        channel._broadcast([user.partner_id.id, bot.partner_id.id])
        return channel.channel_info()[0]

    @api.model
    def odooclaw_list_conversations(self, employee_id=None):
        user = self._odooclaw_conversation_user()
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        if not bot:
            return []
        domain = [
            ("channel_partner_ids", "in", [user.partner_id.id]),
            ("channel_partner_ids", "in", [bot.partner_id.id]),
            "|", ("odooclaw_conversation", "=", True), ("channel_type", "=", "chat"),
        ]
        if employee_id:
            try:
                domain.append(("odooclaw_employee_id", "=", int(employee_id)))
            except (ValueError, TypeError):
                pass
        return self.search_read(domain, ["name", "odooclaw_employee_id"], order="id desc", limit=30)

    @api.model
    def odooclaw_accessible_channel_ids(self, channel_ids):
        """Reconcile browser windows using only the current user's membership."""
        user = self._odooclaw_conversation_user()
        if not isinstance(channel_ids, list) or len(channel_ids) > 200:
            raise UserError(_("Lista de conversaciones no válida."))
        if any(type(channel_id) is not int or channel_id <= 0 for channel_id in channel_ids):
            raise UserError(_("Identificador de conversación no válido."))
        return self.search([
            ("id", "in", channel_ids),
            ("channel_partner_ids", "in", [user.partner_id.id]),
        ]).ids

    def channel_info(self):
        infos = super().channel_info()
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        partner = self.env.user.partner_id
        for info in infos:
            channel = self.browse(info["id"])
            info["odooclawUsageEnabled"] = bool(
                bot and not self.env.user.share and
                partner in channel.channel_partner_ids and
                bot.partner_id in channel.channel_partner_ids
            )
        return infos

    def odooclaw_model_usage(self):
        """Only an internal member of this bot chat can read the shared quota."""
        self.ensure_one()
        user = self._odooclaw_conversation_user()
        self.check_access_rights("read")
        self.check_access_rule("read")
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        if (not self.exists() or not bot or
                user.partner_id not in self.channel_partner_ids or
                bot.partner_id not in self.channel_partner_ids):
            raise AccessError(_("El uso del modelo solo está disponible en tus chats con OdooClaw."))
        params = self.env["ir.config_parameter"].sudo()
        secret = params.get_param("odooclaw.webhook_token", "")
        if not secret:
            return {"available": False}
        url = params.get_param("odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo").rstrip("/") + "/system"
        try:
            response = requests.post(url, json={"event": "model_usage"},
                                     headers={"X-OdooClaw-Token": secret}, timeout=(2, 10))
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not data.get("available"):
                return {"available": False}
            # Expose only the public fields, even if the gateway changes later.
            windows = []
            for window in data.get("windows", [])[:2]:
                remaining = float(window["remaining"])
                duration = int(window["duration_minutes"])
                reset = int(window["resets_at"])
                if not 0 <= remaining <= 100 or duration <= 0 or reset <= 0:
                    continue
                windows.append({"remaining": remaining, "duration_minutes": duration, "resets_at": reset})
            return {"available": bool(windows), "scope": "shared_codex_account", "windows": windows}
        except (requests.RequestException, ValueError, TypeError, KeyError):
            return {"available": False}

    def odooclaw_delete_conversation(self):
        self.ensure_one()
        user = self._odooclaw_conversation_user()
        self.check_access_rights("write")
        self.check_access_rule("write")
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        # Membership, not a client-supplied owner or even administrator status,
        # authorizes this narrowly scoped deletion of a private bot chat.
        if (not self.exists() or
                not (self.odooclaw_conversation or self.channel_type == "chat") or
                set(self.channel_partner_ids.ids) != {user.partner_id.id, bot.partner_id.id}):
            raise AccessError(_("Solo puedes borrar tus chats privados con OdooClaw."))
        params = self.env["ir.config_parameter"].sudo()
        url = params.get_param("odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo").rstrip("/") + "/system"
        secret = params.get_param("odooclaw.webhook_token", "")
        if not secret:
            raise UserError(_("No está configurada la conexión segura con OdooClaw."))
        channel_id = self.id
        conversation_id = channel_id if self.odooclaw_conversation else 0
        identity = {"user_id": user.id, "channel_id": channel_id, "conversation_id": conversation_id}

        def restore_after_rollback():
            # An uncertain HTTP acknowledgement or a later transaction failure
            # must never leave a retained chat permanently blocked at the bot.
            try:
                requests.post(url, json={"event": "conversation_restore", **identity},
                              headers={"X-OdooClaw-Token": secret}, timeout=5)
            except requests.RequestException:
                _logger.warning("Could not restore OdooClaw conversation %s after rollback", channel_id)

        self.env.cr.postrollback.add(restore_after_rollback)
        with self.env.cr.savepoint():
            # Revoke only this chat's capabilities; rollback restores them if
            # the agent is busy or the context purge cannot be acknowledged.
            self.env["mail.odooclaw.reply.token"].sudo().search([
                ("model", "=", "mail.channel"), ("res_id", channel_id),
                ("used", "=", False),
            ]).write({"used": True})
            # Standard unlink handles this channel's messages, notifications,
            # followers and memberships. No global ACL is granted to the user.
            # Partner subscriptions survive channel removal. Notify every
            # member's open tabs, not only subscribers to the deleted channel.
            members = self.channel_partner_ids
            self.env['bus.bus']._sendmany([
                (partner, 'mail.channel/delete', {'id': channel_id}) for partner in members
            ])
            self.sudo().unlink()
            try:
                response = requests.post(url, json={"event": "conversation_delete", **identity},
                                         headers={"X-OdooClaw-Token": secret}, timeout=15)
                if response.status_code == 409:
                    raise UserError(_("OdooClaw está trabajando en este chat. Espera a que termine y vuelve a borrarlo."))
                response.raise_for_status()
            except requests.RequestException as e:
                _logger.warning("Could not purge OdooClaw conversation context for %s: %s", channel_id, e)
        return True
