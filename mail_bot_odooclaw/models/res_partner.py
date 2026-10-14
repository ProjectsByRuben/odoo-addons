from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _compute_im_status(self):
        # Set im_status to 'online' for the OdooClaw bot (shown in chatter as online)
        odooclaw_user = self.env.ref(
            "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
        )
        if odooclaw_user:
            odooclaw_partner = odooclaw_user.partner_id
            if odooclaw_partner in self:
                odooclaw_partner.im_status = "online"

        to_process = self.filtered(
            lambda r: not odooclaw_user or r != odooclaw_user.partner_id
        )
        if not to_process:
            return
        return super(ResPartner, to_process)._compute_im_status()

    def _get_channels_as_member(self):
        channels = super()._get_channels_as_member()
        # Hide OdooClaw private AI conversations from the main Discuss app
        # so Discuss remains clean for internal human communication and
        # users cannot view or delete other operators' AI chats through Discuss.
        return channels.filtered(lambda c: not c.odooclaw_conversation)
