import logging
import requests
import json
import threading
from odoo import models, api, tools, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _odooclaw_sender_user(self):
        """Use the authenticated session, never the audit author, for permissions."""
        # impersonate_login deliberately attributes messages to the original
        # administrator. The active session UID is the impersonated user.
        sender_uid = request.session.uid if request and request.session.uid else self.env.uid
        return self.env["res.users"].sudo().browse(sender_uid)

    @api.model
    def odooclaw_session_info(self):
        """Describe only the effective user's identity and model ACLs."""
        user = self.env.user
        permissions = {}
        for model in (
            "res.partner", "sale.order", "sale.order.line", "purchase.order",
            "mrp.production", "mrp.workorder", "stock.picking", "account.move",
            "contract.contract", "contract.line", "quality.alert", "res.users",
            "res.groups", "ir.model.access", "ir.rule", "ir.attachment",
        ):
            available = model in self.env.registry.models
            permissions[model] = {"available": available}
            for operation in ("read", "create", "write", "unlink"):
                permissions[model][operation] = bool(
                    available and self.env[model].check_access_rights(
                        operation, raise_exception=False
                    )
                )
        return {
            "user": {
                "id": user.id, "name": user.name, "login": user.login,
                "company_id": self.env.company.id,
                "company_name": self.env.company.name,
                "allowed_company_ids": self.env.companies.ids,
            },
            "model_permissions": permissions,
            "record_rules": "Model ACLs do not override record rules; Odoo checks every operation.",
        }

    def _resolve_private_reply_channel(self, author_partner, bot_partner):
        Channel = self.env["mail.channel"].sudo()
        existing = Channel.search(
            [
                ("channel_type", "=", "chat"),
                ("channel_partner_ids", "in", [author_partner.id]),
                ("channel_partner_ids", "in", [bot_partner.id]),
            ],
            limit=1,
        )
        if existing:
            return existing

        return Channel.create(
            {
                "name": _("Chat with OdooClaw"),
                "channel_type": "chat",
                "channel_partner_ids": [(6, 0, [author_partner.id, bot_partner.id])],
            }
        )

    @api.returns("mail.message", lambda value: value.id)
    def message_post(self, **kwargs):
        message = super(MailThread, self).message_post(**kwargs)

        # Determine if OdooClaw is mentioned or it's a direct message to OdooClaw
        odooclaw_user = self.env.ref(
            "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
        )
        if not odooclaw_user:
            return message

        # Prevent infinite loops (don't reply to ourselves)
        if message.author_id == odooclaw_user.partner_id:
            return message

        odooclaw_partner_id = odooclaw_user.partner_id.id
        is_mentioned = odooclaw_partner_id in message.partner_ids.ids

        # If it's a channel, check if it's a DM with OdooClaw
        is_dm = False
        if message.model == "mail.channel":
            channel = self.env["mail.channel"].browse(message.res_id)
            if (
                (channel.channel_type == "chat" or channel.odooclaw_conversation)
                and odooclaw_partner_id
                in channel.channel_member_ids.mapped("partner_id").ids
            ):
                is_dm = True

        if is_mentioned or is_dm:
            # We must clean the text (remove html tags usually added by odoo)
            body_text = tools.html2plaintext(message.body)

            # Process attachments - include voice messages and invoices info
            voice_attachments = []
            invoice_attachments = []
            other_attachments = []

            if message.attachment_ids:
                for att in message.attachment_ids:
                    mimetype = (att.mimetype or "").lower()
                    name = (att.name or "").lower()

                    # Check if it's a voice attachment
                    if hasattr(att, "voice_ids") and att.voice_ids:
                        voice_attachments.append(
                            {"id": att.id, "name": att.name, "mimetype": att.mimetype}
                        )
                        body_text += f"\n🎤 [Nota de voz: {att.name} (ID: {att.id})]\n"
                    # Check if it's a PDF or image (potential invoice)
                    elif (
                        mimetype == "application/pdf"
                        or mimetype.startswith("image/")
                        or name.endswith((".pdf", ".jpg", ".jpeg", ".png", ".webp"))
                    ):
                        invoice_attachments.append(
                            {"id": att.id, "name": att.name, "mimetype": att.mimetype}
                        )
                        body_text += (
                            f"\n🧾 [Factura/Documento: {att.name} (ID: {att.id})]\n"
                        )
                    else:
                        other_attachments.append(
                            {"id": att.id, "name": att.name, "mimetype": att.mimetype}
                        )
                        body_text += f"\n[Adjunto: {att.name} (ID: {att.id})]\n"

            # Resolve permissions from the authenticated user, not mail audit data.
            sender_user = self._odooclaw_sender_user()
            if not sender_user.exists() or not sender_user.active or sender_user.share:
                _logger.warning("OdooClaw ignored message without an active internal user")
                return message
            session_info = self.with_user(sender_user).odooclaw_session_info()

            author_display_name = sender_user.name
            if channel and getattr(channel, 'odooclaw_employee_id', False):
                author_display_name = f"{channel.odooclaw_employee_id.name} ({sender_user.name})"

            # Send webhook asynchronously
            payload = {
                "message_id": message.id,
                "model": message.model,
                "res_id": message.res_id,
                "reply_model": message.model,
                "reply_res_id": message.res_id,
                "author_id": sender_user.partner_id.id,
                "author_user_id": sender_user.id,
                "author_name": author_display_name,
                "employee_id": channel.odooclaw_employee_id.id if channel and getattr(channel, 'odooclaw_employee_id', False) else 0,
                "employee_name": channel.odooclaw_employee_id.name if channel and getattr(channel, 'odooclaw_employee_id', False) else "",
                "session_info": session_info,
                "body": body_text,
                "is_dm": is_dm,
                "conversation_id": (
                    channel.id if is_dm and channel.odooclaw_conversation else 0
                ),
                "company_id": session_info["user"]["company_id"],
                "allowed_company_ids": session_info["user"]["allowed_company_ids"],
                "voice_attachments": voice_attachments,
                "invoice_attachments": invoice_attachments,
                "attachments": other_attachments,
            }

            if not is_dm and message.model == "mail.channel":
                channel = self.env["mail.channel"].browse(message.res_id)
                if channel.channel_type == "chat":
                    # Existing 1-to-1 chat: keep private reply behaviour
                    private_channel = self._resolve_private_reply_channel(
                        sender_user.partner_id, odooclaw_user.partner_id
                    )
                    payload["reply_model"] = "mail.channel"
                    payload["reply_res_id"] = private_channel.id
                # else: group channel → reply in the same channel (reply_model/res_id unchanged)

            # Build chatter context: read messages in reverse chronological order,
            # stopping at the last OdooClaw intervention. This gives OdooClaw
            # visibility into what happened between its last reply and now.
            chatter_context = []
            if not is_dm and payload["reply_model"] != "mail.channel":
                for ctx_msg in self.env["mail.message"].with_user(sender_user).search([
                    ("model", "=", payload["reply_model"]),
                    ("res_id", "=", payload["reply_res_id"]),
                    ("message_type", "in", ["comment", "email"]),
                    ("id", "!=", message.id),
                ], order="date desc", limit=10):
                    if ctx_msg.author_id == odooclaw_user.partner_id:
                        break
                    chatter_context.append({
                        "date": ctx_msg.date.isoformat(),
                        "author": ctx_msg.author_id.name,
                        "body": tools.html2plaintext(ctx_msg.body),
                    })
                chatter_context.reverse()
            payload["chatter_context"] = chatter_context

            # We use threading to not block the current transaction

            # Generate reply token — allows OdooClaw to identify solicited replies
            reply_token_rec = self.env["mail.odooclaw.reply.token"].sudo()._generate(
                model=payload["reply_model"],
                res_id=payload["reply_res_id"],
                message_id=message.id,
                user_id=sender_user.id,
                allowed_company_ids=session_info["user"]["allowed_company_ids"],
            )
            payload["reply_token"] = reply_token_rec.token

            webhook_url = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo")
            )
            webhook_token = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("odooclaw.webhook_token", "")
            )
            webhook_headers = {}
            if webhook_token:
                webhook_headers["X-OdooClaw-Token"] = webhook_token

            def send_webhook():
                try:
                    _logger.info("Sending webhook to OdooClaw: %s", webhook_url)
                    res = requests.post(
                        webhook_url, json=payload, headers=webhook_headers, timeout=10
                    )
                    _logger.info("OdooClaw response: %s", res.text)
                except Exception:
                    _logger.exception("Failed to send webhook to OdooClaw")

            threading.Thread(target=send_webhook).start()

            # Trigger "typing..." indicator if it's a mail channel
            if message.model == "mail.channel":
                channel = self.env["mail.channel"].browse(message.res_id)
                # In Odoo 16, channel_partner_ids is a many2many to res.partner
                # We need to find the mail.channel.member record for the bot
                channel_partner = self.env["mail.channel.member"].search(
                    [
                        ("channel_id", "=", channel.id),
                        ("partner_id", "=", odooclaw_partner_id),
                    ],
                    limit=1,
                )
                if channel_partner:
                    channel_partner._notify_typing(is_typing=True)

        return message
