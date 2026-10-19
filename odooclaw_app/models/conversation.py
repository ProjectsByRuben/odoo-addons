import base64

from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class Channel(models.Model):
    _inherit = "mail.channel"

    @api.model
    def _odooclaw_app_channel(self, profile, channel_id):
        if (
            not isinstance(channel_id, int) or isinstance(channel_id, bool)
        ) or channel_id <= 0:
            raise AccessError(_("Conversación no válida."))
        channel = self.browse(channel_id).exists()
        if not channel:
            raise AccessError(_("Esta conversación ya no está disponible."))
        channel.check_access_rights("read")
        channel.check_access_rule("read")
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        if (
            not (channel.odooclaw_conversation or channel.channel_type == "chat")
            or set(channel.channel_partner_ids.ids)
            != {profile["user"].partner_id.id, bot.partner_id.id}
            or channel.odooclaw_employee_id.id != profile["employee"].id
        ):
            raise AccessError(_("La conversación no pertenece a tu perfil actual."))
        return channel

    @api.model
    def _odooclaw_app_conversations(self, profile):
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        channels = self.search(
            [
                ("channel_partner_ids", "in", [profile["user"].partner_id.id]),
                ("channel_partner_ids", "in", [bot.partner_id.id]),
                ("odooclaw_employee_id", "=", profile["employee"].id),
                "|",
                ("odooclaw_conversation", "=", True),
                ("channel_type", "=", "chat"),
            ],
            order="id desc",
            limit=100,
        )
        return [
            {"id": channel.id, "name": channel.name}
            for channel in channels
            if set(channel.channel_partner_ids.ids)
            == {profile["user"].partner_id.id, bot.partner_id.id}
        ]

    @api.model
    def _odooclaw_app_messages(self, profile, channel_id, before=None, revision=None):
        channel = self._odooclaw_app_channel(profile, channel_id)
        domain = [("model", "=", "mail.channel"), ("res_id", "=", channel.id)]
        if before is not None:
            if (not isinstance(before, int) or isinstance(before, bool)) or before <= 0:
                raise UserError(_("Página de mensajes no válida."))
            domain.append(("id", "<", before))
        messages = self.env["mail.message"].search(domain, order="id desc", limit=60)
        current_revision = ",".join(
            f"{message.id}:{message.write_date}" for message in messages
        )
        if before is None and revision == current_revision:
            return {"unchanged": True}
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        return {
            "revision": current_revision,
            "messages": [
                {
                    "id": message.id,
                    "body": str(message.body or ""),
                    "date": fields.Datetime.to_string(message.date),
                    "author": message.author_id.name or "OdooClaw",
                    "bot": message.author_id == bot.partner_id,
                    "attachments": [
                        {
                            "id": attachment.id,
                            "name": attachment.name,
                            "mimetype": attachment.mimetype,
                        }
                        for attachment in message.attachment_ids
                    ],
                }
                for message in reversed(messages)
            ],
            "has_more": len(messages) == 60,
        }

    @api.model
    def _odooclaw_app_send(self, profile, channel_id, body, attachment_ids=None):
        channel = self._odooclaw_app_channel(profile, channel_id)
        attachment_ids = attachment_ids or []
        if (
            not isinstance(attachment_ids, list)
            or len(attachment_ids) > 20
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in attachment_ids
            )
        ):
            raise UserError(_("Lista de adjuntos no válida."))
        attachments = self.env["ir.attachment"].browse(attachment_ids).exists()
        if len(attachments) != len(set(attachment_ids)) or any(
            attachment.res_model != "mail.channel" or attachment.res_id != channel.id
            for attachment in attachments
        ):
            raise AccessError(_("Los adjuntos no pertenecen a esta conversación."))
        attachments.check_access_rights("read")
        attachments.check_access_rule("read")
        if (
            not isinstance(body, str)
            or len(body) > 64000
            or not (body.strip() or attachments)
        ):
            raise UserError(_("Escribe un mensaje de hasta 64.000 caracteres."))
        message = channel.message_post(
            body=Markup("<p>")
            + escape(body.strip()).replace("\n", Markup("<br/>"))
            + Markup("</p>"),
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            author_id=profile["user"].partner_id.id,
            attachment_ids=attachments.ids,
        )
        return {"id": message.id}

    @api.model
    def _odooclaw_app_upload(self, profile, channel_id, name, content):
        channel = self._odooclaw_app_channel(profile, channel_id)
        if not isinstance(name, str) or not name.strip() or len(name) > 255:
            raise UserError(_("Nombre de archivo no válido."))
        if not isinstance(content, bytes) or len(content) > 25 * 1024 * 1024:
            raise UserError(_("Cada archivo puede ocupar hasta 25 MB."))
        attachment = self.env["ir.attachment"].create(
            {
                "name": name,
                "datas": base64.b64encode(content),
                "res_model": "mail.channel",
                "res_id": channel.id,
            }
        )
        return {"id": attachment.id, "name": attachment.name}

    @api.model
    def _odooclaw_app_attachment(self, profile, channel_id, attachment_id):
        channel = self._odooclaw_app_channel(profile, channel_id)
        if not isinstance(attachment_id, int) or isinstance(attachment_id, bool):
            raise AccessError(_("Adjunto no válido."))
        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if not attachment:
            raise AccessError(_("Adjunto no disponible."))
        attached = self.env["mail.message"].search_count(
            [
                ("model", "=", "mail.channel"),
                ("res_id", "=", channel.id),
                ("attachment_ids", "in", attachment.ids),
            ]
        )
        if not attached and not (
            attachment.res_model == "mail.channel"
            and attachment.res_id == channel.id
            and attachment.create_uid == profile["user"]
        ):
            raise AccessError(_("El adjunto no pertenece a esta conversación."))
        attachment.check_access_rights("read")
        attachment.check_access_rule("read")
        return attachment
