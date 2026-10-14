import uuid
import json
from markupsafe import Markup
from datetime import timedelta
from odoo import models, fields, api


class MailOdooClawReplyToken(models.Model):
    _name = "mail.odooclaw.reply.token"
    _description = "OdooClaw Reply Token"
    _rec_name = "token"

    token = fields.Char(required=True, index=True, readonly=True)
    model = fields.Char(required=True, readonly=True)
    res_id = fields.Integer(required=True, readonly=True)
    message_id = fields.Many2one("mail.message", ondelete="cascade", readonly=True)
    expiry = fields.Datetime(required=True, readonly=True)
    used = fields.Boolean(default=False)
    allowed_company_ids_json = fields.Text(readonly=True)
    user_id = fields.Many2one("res.users", required=True, readonly=True)
    progress_count = fields.Integer(default=0)
    progress_message_id = fields.Many2one("mail.message", ondelete="set null", readonly=True)
    finished_at = fields.Datetime(readonly=True)
    progress_history_json = fields.Text(default="[]", readonly=True)

    def _progress_body(self, activity, finished=False):
        """Render only escaped activity text, with an indeterminate activity bar."""
        self.ensure_one()
        elapsed = max(0, int(((self.finished_at or fields.Datetime.now()) - self.create_date).total_seconds()))
        duration = f"{elapsed // 60} min {elapsed % 60:02d} s" if elapsed >= 60 else f"{elapsed} s"
        timing = f"Finalizada en {duration}" if finished else f"{duration} transcurridos"
        estimate = ""
        if not finished:
            history = self.search([
                ("user_id", "=", self.user_id.id),
                ("model", "=", self.model),
                ("finished_at", "!=", False),
            ], order="finished_at desc", limit=20)
            durations = [(t.finished_at - t.create_date).total_seconds() for t in history]
            durations = [d for d in durations if 0 < d <= 900]
            if len(durations) >= 5:
                durations.sort()
                low = max(5, int(durations[len(durations) // 5]))
                high = max(10, int(durations[min(len(durations) - 1, len(durations) * 4 // 5)]))
                if high > low * 4:
                    estimate = ""
                elif elapsed < high:
                    estimate = f"Tiempo restante orientativo: {max(0, low - elapsed)}–{high - elapsed} s (según solicitudes anteriores)."
                else:
                    estimate = "Está tardando más de lo habitual. La solicitud sigue en curso."
        status = "Finalizada" if finished else activity[:180]
        history = json.loads(self.progress_history_json or "[]")
        previous = history[-3:] if finished else history[:-1][-2:]
        steps = Markup("").join(Markup('<div class="o_odooclaw_progress_step"><span class="o_odooclaw_step_dot"></span><span>{}</span></div>').format(step) for step in previous)
        estimate_html = Markup('<div class="o_odooclaw_progress_estimate">{}</div>').format(estimate) if estimate else Markup("")
        return Markup('<div class="o_odooclaw_progress {}" role="status">'
                      '<div class="o_odooclaw_progress_header"><span class="o_odooclaw_progress_brand">'
                      '<i class="fa fa-bolt" aria-hidden="true"></i> OdooClaw</span>'
                      '<span class="o_odooclaw_progress_badge"><span></span>{}</span></div>'
                      '<div class="o_odooclaw_progress_steps">{}</div>'
                      '<div class="o_odooclaw_progress_current"><strong>{}</strong></div>'
                      '<div class="o_odooclaw_progress_track" role="progressbar" aria-label="{}"><span></span></div>'
                      '<div class="o_odooclaw_progress_footer"><i class="fa fa-clock-o" aria-hidden="true"></i> {}</div>{}</div>').format(
            "o_odooclaw_progress_done" if finished else "",
            "Finalizada" if finished else "En curso", steps, status,
            "Solicitud finalizada" if finished else "Solicitud en curso", timing, estimate_html)

    def _update_progress(self, record, bot_user, activity, finished=False):
        self.ensure_one()
        # The token fixes both the destination and this request's status message.
        message = self.progress_message_id.exists()
        if not finished:
            history = json.loads(self.progress_history_json or "[]")
            activity = " ".join(activity.split())[:180]
            generic = {"Solicitud recibida · En cola", "Analizando tu solicitud",
                       "Revisando los resultados y preparando la respuesta"}
            if not history or history[-1] != activity:
                # Keep meaningful steps visible when the next model call starts.
                if activity not in generic:
                    history = [step for step in history if step not in generic]
                elif any(step not in generic for step in history):
                    history = [step for step in history if step not in generic]
                history.append(activity)
                self.progress_history_json = json.dumps(history[-3:], ensure_ascii=False)
        body = self._progress_body(activity, finished=finished)
        target = record.with_user(bot_user).sudo()
        if message:
            if (message.model != self.model or message.res_id != self.res_id
                    or message.author_id != bot_user.partner_id):
                raise ValueError("Invalid progress message destination")
            target._message_update_content(message, body)
        elif not finished:
            self.progress_message_id = target.with_context(mail_create_nosubscribe=True).message_post(
                body=body, author_id=bot_user.partner_id.id, message_type="comment")

    @api.model
    def _generate(self, model, res_id, message_id, user_id=None, allowed_company_ids=None):
        """Generate a single-use reply token for the given record."""
        ttl = int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("odooclaw.reply_token_ttl", "900")
        )
        return self.create({
            "token": str(uuid.uuid4()),
            "model": model,
            "res_id": res_id,
            "message_id": message_id,
            "user_id": user_id or self.env.uid,
            "allowed_company_ids_json": json.dumps(allowed_company_ids or self.env["res.users"].browse(user_id or self.env.uid).company_ids.ids),
            "expiry": fields.Datetime.now() + timedelta(seconds=ttl),
        })

    @api.model
    def _validate(self, token_str, model, res_id, consume=True):
        """
        Validate a reply token and mark it as used (single-use).
        Returns the token record if valid (truthy), empty recordset otherwise (falsy).
        """
        self.env.cr.execute("SELECT id FROM mail_odooclaw_reply_token WHERE token = %s FOR UPDATE", [token_str])
        record = self.sudo().search([
            ("token", "=", token_str),
            ("used", "=", False),
            ("expiry", ">", fields.Datetime.now()),
            ("model", "=", model),
            ("res_id", "=", res_id),
        ], limit=1)
        if record and consume:
            record.used = True
        return record

    @api.model
    def _cleanup_expired(self):
        """Keep completed timings seven days; capabilities remain single-use."""
        now = fields.Datetime.now()
        self.sudo().search([
            "|", "&", ("finished_at", "=", False),
            "|", ("expiry", "<", now), ("used", "=", True),
            ("finished_at", "<", now - timedelta(days=7)),
        ]).unlink()
