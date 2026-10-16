# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError, AccessError
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class MailChannel(models.Model):
    _inherit = "mail.channel"

    odooclaw_conversation = fields.Boolean(
        string="Conversación de OdooClaw",
        default=False,
        index=True,
        help="Marca los canales creados como conversaciones independientes con el asistente OdooClaw.",
    )
    odooclaw_employee_id = fields.Many2one(
        "hr.employee",
        string="Operario / Empleado",
        index=True,
        help="Operario identificado para esta conversación cuando se comparte el usuario de Odoo.",
    )

    def _odooclaw_conversation_user(self):
        user = self.env.user
        if not user.exists() or not user.active or user.share:
            raise AccessError(_("Solo los usuarios internos pueden usar OdooClaw."))
        return user

    def _odooclaw_employee_domain(self):
        """Department scope is selected by the account, never by RPC arguments."""
        user = self._odooclaw_conversation_user()
        departments = {
            "almacen": ["ALMACEN"],
            "fabrica": ["PRODUCCION", "MONTAJE", "SOLDADURA Y PREPARACION",
                        "CORTE Y PREPARACION", "CONFORMADO", "PINTURA Y PREPARACION",
                        "REPASADO MANUAL", "FRESADO Y PREPARACION"],
            "calidad": ["CALIDAD"], "logistica": ["LOGISTICA"],
            "otecnica": ["OT", "DELINEACION"], "delineacion": ["OT", "DELINEACION"],
        }
        login = (user.login or "").lower().strip()
        names = departments.get("fabrica" if login in ("produccion", "cproduccion") else login)
        if names is None:
            return None
        return [("active", "=", True), ("department_id.name", "in", names),
                ("company_id", "in", self.env.companies.ids)]

    @api.model
    def odooclaw_get_available_employees(self):
        domain = self._odooclaw_employee_domain()
        if domain is None:
            return []
        # Shared accounts need names for this selector, never private HR fields.
        employees = self.env["hr.employee"].sudo().search(domain, order="name, id")
        return [{"id": employee.id, "name": employee.name} for employee in employees]

    @api.model
    def odooclaw_employee_selector(self):
        return {"required": self._odooclaw_employee_domain() is not None,
                "employees": self.odooclaw_get_available_employees()}

    def _odooclaw_selected_employee(self, employee_id, required=False):
        domain = self._odooclaw_employee_domain()
        if employee_id is None or employee_id is False:
            if required and domain is not None:
                raise UserError(_("Selecciona tu nombre de operario antes de abrir una conversación."))
            return self.env["hr.employee"]
        if type(employee_id) is not int or employee_id <= 0 or domain is None:
            raise UserError(_("Operario no válido para esta cuenta."))
        employee = self.env["hr.employee"].sudo().search(domain + [("id", "=", employee_id)], limit=1)
        if not employee:
            raise AccessError(_("El operario no pertenece a los departamentos y compañías permitidos."))
        return employee

    @api.model
    def odooclaw_new_conversation(self, employee_id=None):
        user = self._odooclaw_conversation_user()
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        if not bot or not bot.active:
            raise UserError(_("OdooClaw no está disponible. Contacta con informática."))
        stamp = fields.Datetime.context_timestamp(self, fields.Datetime.now())

        employee = self._odooclaw_selected_employee(employee_id, required=True)

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
            body=Markup("<p><strong>%s</strong></p>") % welcome_title + Markup(_(""
                   "<p>Escribe tu solicitud aquí. Esta conversación empieza sin el contexto "
                   "de tus chats anteriores y utiliza los permisos de tu usuario actual.</p>"
                   "<p>Para abrir otra o volver a las anteriores, usa el menú "
                   "<strong>OdooClaw</strong> de la barra superior. Allí encontrarás "
                   "<strong>Cómo usarlo</strong>.</p>")),
            message_type="comment", subtype_xmlid="mail.mt_comment",
        )
        # Ensure channel is never pinned in the general Discuss sidebar
        self.env["mail.channel.member"].sudo().search([
            ("channel_id", "=", channel.id),
        ]).write({"is_pinned": False})
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
        employee = self._odooclaw_selected_employee(employee_id)
        if self._odooclaw_employee_domain() is not None:
            if not employee:
                return []
            domain.append(("odooclaw_employee_id", "=", employee.id))
        return self.search_read(domain, ["name", "odooclaw_employee_id"], order="id desc", limit=30)

    def odooclaw_open_conversation(self, employee_id=None):
        """Validate the tab's employee without changing shared account state."""
        self.ensure_one()
        user = self._odooclaw_conversation_user()
        self.check_access_rights("read")
        self.check_access_rule("read")
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        if (not self.exists() or not bot or
                not (self.odooclaw_conversation or self.channel_type == "chat") or
                user.partner_id not in self.channel_partner_ids or
                bot.partner_id not in self.channel_partner_ids):
            raise AccessError(_("Esta conversación no está disponible."))
        employee = self._odooclaw_selected_employee(employee_id, required=True)
        if self._odooclaw_employee_domain() is not None and self.odooclaw_employee_id != employee:
            raise AccessError(_("Esta conversación pertenece a otro operario. Selecciona su nombre para abrirla."))
        return self.channel_info()[0]

    @api.model
    def odooclaw_accessible_channel_ids(self, channel_ids, odooclaw_only=False):
        """Reconcile browser windows using only the current user's membership."""
        user = self._odooclaw_conversation_user()
        if not isinstance(channel_ids, list) or len(channel_ids) > 200:
            raise UserError(_("Lista de conversaciones no válida."))
        if any(type(channel_id) is not int or channel_id <= 0 for channel_id in channel_ids):
            raise UserError(_("Identificador de conversación no válido."))
        domain = [
            ("id", "in", channel_ids),
            ("channel_partner_ids", "in", [user.partner_id.id]),
        ]
        if odooclaw_only:
            bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
            if not bot:
                return []
            domain += [
                ("channel_partner_ids", "in", [bot.partner_id.id]),
                "|", ("odooclaw_conversation", "=", True), ("channel_type", "=", "chat"),
            ]
        return self.search(domain).ids

    @api.returns('mail.message', lambda value: value.id)
    def message_post(self, *, message_type='notification', **kwargs):
        """Override to prevent auto-pinning OdooClaw conversations in Discuss when messages are posted."""
        res = super().message_post(message_type=message_type, **kwargs)
        odooclaw_channels = self.filtered(lambda c: c.odooclaw_conversation)
        if odooclaw_channels:
            odooclaw_channels.mapped('channel_member_ids').sudo().write({'is_pinned': False})
        return res

    def channel_info(self):
        infos = super().channel_info()
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        partner = self.env.user.partner_id
        for info in infos:
            channel = self.browse(info["id"])
            if channel.odooclaw_conversation:
                info["is_pinned"] = False
                info["odooclaw_conversation"] = True
                if "channel" in info and isinstance(info["channel"], dict):
                    info["channel"]["is_pinned"] = False
                    info["channel"]["odooclaw_conversation"] = True
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
                ("model", "=", "mail.channel"), ("res_id", "=", channel_id),
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
