from odoo import _, api, models
from odoo.exceptions import AccessError
from odoo.http import request
from odoo.osv import expression

_SCOPE = object()
_SCOPE_KEY = "odooclaw_app_verified_scope"


class ChannelAccess(models.Model):
    _inherit = "mail.channel"

    @api.model
    def _odooclaw_app_with_profile(self, profile, channel_id=None):
        if profile["user"].id != self.env.uid:
            raise AccessError(_("Perfil de otro usuario."))
        return self.with_context(
            **{
                _SCOPE_KEY: (
                    _SCOPE,
                    self.env.uid,
                    profile["employee"].id or 0,
                    channel_id,
                )
            }
        )

    @api.model
    def _odooclaw_app_delegated_scope(self, capability):
        if (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.app.enforce", "0")
            != "1"
        ):
            return {}
        if capability.user_id.id != self.env.uid:
            raise AccessError(_("Solicitud de otro usuario."))
        if capability.model != "mail.channel":
            return {}
        rows = self._odooclaw_app_protected_rows([capability.res_id])
        if not rows:
            return {}
        channel_id, employee_id, member = rows[0]
        if not member:
            raise AccessError(_("La solicitud no pertenece al usuario delegado."))
        employee = self._odooclaw_selected_employee(employee_id or None, required=True)
        return {_SCOPE_KEY: (_SCOPE, self.env.uid, employee.id or 0, channel_id)}

    @api.model
    def _odooclaw_app_clean_result(self, result):
        if isinstance(result, dict):
            return {
                key: self._odooclaw_app_clean_result(value)
                for key, value in result.items()
                if key != _SCOPE_KEY
            }
        if isinstance(result, list | tuple):
            return [self._odooclaw_app_clean_result(value) for value in result]
        return result

    @api.model
    def _odooclaw_app_protected_rows(self, ids=None):
        if ids is not None and not ids:
            return []
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        if not bot:
            return []
        self.flush_model(
            ["odooclaw_conversation", "odooclaw_employee_id", "channel_type"]
        )
        self.env["mail.channel.member"].flush_model(["channel_id", "partner_id"])
        query = """
            SELECT c.id, COALESCE(c.odooclaw_employee_id, 0),
                   EXISTS (SELECT 1 FROM mail_channel_member m
                           WHERE m.channel_id=c.id AND m.partner_id=%s)
              FROM mail_channel c
             WHERE (c.odooclaw_conversation OR
                    (c.channel_type='chat' AND EXISTS (
                        SELECT 1 FROM mail_channel_member b
                        WHERE b.channel_id=c.id AND b.partner_id=%s)))
        """
        params = [self.env.user.partner_id.id, bot.partner_id.id]
        if ids is not None:
            query += " AND c.id = ANY(%s)"
            params.append(list(ids))
        self.env.cr.execute(query, params)
        return self.env.cr.fetchall()

    @api.model
    def _odooclaw_app_blocked_channels(self, ids=None):
        if (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.app.enforce", "0")
            != "1"
        ):
            return []
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        if (bot and self.env.uid == bot.id) or (self.env.su and not request):
            return []
        scope = self.env.context.get(_SCOPE_KEY)
        trusted = (
            isinstance(scope, tuple)
            and len(scope) == 4
            and scope[0] is _SCOPE
            and scope[1] == self.env.uid
        )
        return [
            channel_id
            for channel_id, employee_id, member in self._odooclaw_app_protected_rows(
                ids
            )
            if not (
                trusted
                and member
                and scope[2] == employee_id
                and (not scope[3] or scope[3] == channel_id)
            )
        ]

    def _odooclaw_app_check_channels(self):
        if self._odooclaw_app_blocked_channels(self.ids):
            raise AccessError(
                _(
                    "Abre esta conversación desde la app OdooClaw "
                    "con tu perfil desbloqueado."
                )
            )

    def read(self, fields=None, load="_classic_read"):
        self._odooclaw_app_check_channels()
        return super().read(fields=fields, load=load)

    def _read(self, field_names):
        self._odooclaw_app_check_channels()
        return super()._read(field_names)

    @api.model
    def _where_calc(self, domain, active_test=True):
        blocked = self._odooclaw_app_blocked_channels()
        if blocked:
            domain = expression.AND([domain, [("id", "not in", blocked)]])
        return super()._where_calc(domain, active_test=active_test)

    @api.model_create_multi
    def create(self, values):
        channels = super().create(values)
        channels._odooclaw_app_check_channels()
        return channels

    def write(self, values):
        self._odooclaw_app_check_channels()
        result = super().write(values)
        self._odooclaw_app_check_channels()
        return result

    def unlink(self):
        self._odooclaw_app_check_channels()
        return super().unlink()

    @api.model
    def channel_get(self, partners_to, pin=True):
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False)
        enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.app.enforce", "0")
            == "1"
        )
        if enabled and bot and bot.partner_id.id in partners_to:
            raise AccessError(
                _("Usa la app OdooClaw para abrir un chat con el asistente.")
            )
        return super().channel_get(partners_to, pin=pin)

    def _notify_thread(self, message, msg_vals=False, **kwargs):
        enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.app.enforce", "0")
            == "1"
        )
        if enabled and self._odooclaw_app_protected_rows(self.ids):
            # Polling is profile-authorized. Native partner/channel bus topics
            # are shared by every browser logged into the generic account.
            return []
        return super()._notify_thread(message, msg_vals=msg_vals, **kwargs)

    def _message_update_content_after_hook(self, message):
        enabled = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.app.enforce", "0")
            == "1"
        )
        if enabled and self._odooclaw_app_protected_rows(self.ids):
            return None
        return super()._message_update_content_after_hook(message)


class MessageAccess(models.Model):
    _inherit = "mail.message"

    def _odooclaw_app_check_messages(self):
        if not self.ids:
            return
        self.flush_model(["model", "res_id"])
        self.env.cr.execute(
            "SELECT DISTINCT res_id FROM mail_message "
            "WHERE id=ANY(%s) AND model='mail.channel'",
            [self.ids],
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        self.env["mail.channel"].browse(ids)._odooclaw_app_check_channels()

    def read(self, fields=None, load="_classic_read"):
        self._odooclaw_app_check_messages()
        return super().read(fields=fields, load=load)

    def _read(self, field_names):
        self._odooclaw_app_check_messages()
        return super()._read(field_names)

    @api.model
    def _where_calc(self, domain, active_test=True):
        blocked = self.env["mail.channel"]._odooclaw_app_blocked_channels()
        if blocked:
            domain = expression.AND(
                [
                    domain,
                    [
                        "|",
                        ("model", "!=", "mail.channel"),
                        ("res_id", "not in", blocked),
                    ],
                ]
            )
        return super()._where_calc(domain, active_test=active_test)

    @api.model_create_multi
    def create(self, values):
        ids = [
            value.get("res_id")
            for value in values
            if value.get("model") == "mail.channel"
        ]
        self.env["mail.channel"].browse(
            [value for value in ids if value]
        )._odooclaw_app_check_channels()
        records = super().create(values)
        records._odooclaw_app_check_messages()
        return records

    def write(self, values):
        self._odooclaw_app_check_messages()
        if values.get("model") == "mail.channel" and values.get("res_id"):
            self.env["mail.channel"].browse(
                values["res_id"]
            )._odooclaw_app_check_channels()
        result = super().write(values)
        self._odooclaw_app_check_messages()
        return result

    def unlink(self):
        self._odooclaw_app_check_messages()
        return super().unlink()


class AttachmentAccess(models.Model):
    _inherit = "ir.attachment"

    @api.model
    def _odooclaw_app_blocked_attachments(self, ids=None):
        blocked = self.env["mail.channel"]._odooclaw_app_blocked_channels()
        if not blocked or (ids is not None and not ids):
            return []
        self.flush_model(["res_model", "res_id"])
        query = """
            SELECT a.id FROM ir_attachment a
             WHERE ((a.res_model='mail.channel' AND a.res_id=ANY(%s))
                OR (a.res_model='mail.message' AND a.res_id IN (
                    SELECT id FROM mail_message
                    WHERE model='mail.channel' AND res_id=ANY(%s)))
                OR ((a.res_model IS NULL
                     OR a.res_model IN ('mail.compose.message', '')) AND EXISTS (
                    SELECT 1 FROM message_attachment_rel rel
                    JOIN mail_message m ON m.id=rel.message_id
                    WHERE rel.attachment_id=a.id
                      AND m.model='mail.channel' AND m.res_id=ANY(%s))))
        """
        params = [blocked, blocked, blocked]
        if ids is not None:
            query += " AND a.id=ANY(%s)"
            params.append(list(ids))
        self.env.cr.execute(query, params)
        return [row[0] for row in self.env.cr.fetchall()]

    def _odooclaw_app_check_attachments(self):
        if self._odooclaw_app_blocked_attachments(self.ids):
            raise AccessError(_("Accede al adjunto desde tu conversación de OdooClaw."))

    def read(self, fields=None, load="_classic_read"):
        self._odooclaw_app_check_attachments()
        return super().read(fields=fields, load=load)

    def _read(self, field_names):
        self._odooclaw_app_check_attachments()
        return super()._read(field_names)

    @api.model
    def _where_calc(self, domain, active_test=True):
        blocked = self._odooclaw_app_blocked_attachments()
        if blocked:
            domain = expression.AND([domain, [("id", "not in", blocked)]])
        return super()._where_calc(domain, active_test=active_test)

    @api.model_create_multi
    def create(self, values):
        ids = [
            value.get("res_id")
            for value in values
            if value.get("res_model") == "mail.channel"
        ]
        self.env["mail.channel"].browse(
            [value for value in ids if value]
        )._odooclaw_app_check_channels()
        records = super().create(values)
        records._odooclaw_app_check_attachments()
        return records

    def write(self, values):
        self._odooclaw_app_check_attachments()
        if values.get("res_model") == "mail.channel" and values.get("res_id"):
            self.env["mail.channel"].browse(
                values["res_id"]
            )._odooclaw_app_check_channels()
        result = super().write(values)
        self._odooclaw_app_check_attachments()
        return result

    def unlink(self):
        self._odooclaw_app_check_attachments()
        return super().unlink()
