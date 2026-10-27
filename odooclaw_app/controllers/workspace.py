import json

from odoo import http
from odoo.exceptions import AccessError, UserError
from odoo.http import request


class WorkspaceController(http.Controller):
    def _channel(self, company_ids=None):
        channel = request.env["mail.channel"]
        user = channel._odooclaw_conversation_user()
        if isinstance(company_ids, str):
            try:
                company_ids = json.loads(company_ids)
            except ValueError:
                raise AccessError("Compañías no válidas.") from None
        if company_ids is None:
            company_ids = channel.env.companies.ids
        if (
            not isinstance(company_ids, list)
            or not company_ids
            or any(
                not isinstance(value, int) or isinstance(value, bool)
                for value in company_ids
            )
            or not set(company_ids).issubset(user.company_ids.ids)
        ):
            raise AccessError("Compañías no permitidas para este usuario.")
        return channel.with_context(allowed_company_ids=company_ids)

    @http.route("/odooclaw/app/bootstrap", type="json", auth="user", methods=["POST"])
    def bootstrap(self, company_ids=None):
        return self._channel(company_ids)._odooclaw_app_bootstrap()

    @http.route("/odooclaw/app/unlock", type="json", auth="user", methods=["POST"])
    def unlock(self, employee_id=None, pin="", company_ids=None):
        return self._channel(company_ids)._odooclaw_app_unlock(
            employee_id, pin, request.session
        )

    @http.route("/odooclaw/app/setup_pin", type="json", auth="user", methods=["POST"])
    def setup_pin(self, employee_id=None, pin="", confirmation="", company_ids=None):
        return self._channel(company_ids)._odooclaw_app_setup_pin(
            employee_id, pin, confirmation, request.session
        )

    @http.route("/odooclaw/app/lock", type="json", auth="user", methods=["POST"])
    def lock(self, token=None, company_ids=None):
        return self._channel(company_ids)._odooclaw_app_lock(token, request.session)

    def _profile(self, token, company_ids=None):
        channel = self._channel(company_ids)
        profile = channel._odooclaw_app_profile(token, request.session)
        return channel._odooclaw_app_with_profile(profile), profile

    @http.route(
        "/odooclaw/app/conversations", type="json", auth="user", methods=["POST"]
    )
    def conversations(self, token=None, company_ids=None):
        channel, profile = self._profile(token, company_ids)
        return channel._odooclaw_app_conversations(profile)

    @http.route("/odooclaw/app/new", type="json", auth="user", methods=["POST"])
    def new(self, token=None, company_ids=None):
        channel, profile = self._profile(token, company_ids)
        data = channel.odooclaw_new_conversation(profile["employee"].id or None)
        return {"id": data["id"], "name": data.get("name", "OdooClaw")}

    @http.route("/odooclaw/app/messages", type="json", auth="user", methods=["POST"])
    def messages(
        self, token=None, channel_id=None, before=None, revision=None, company_ids=None
    ):
        channel, profile = self._profile(token, company_ids)
        return channel._odooclaw_app_messages(profile, channel_id, before, revision)

    @http.route("/odooclaw/app/send", type="json", auth="user", methods=["POST"])
    def send(
        self,
        token=None,
        channel_id=None,
        body="",
        attachment_ids=None,
        company_ids=None,
        record_context=None,
        record_attachment_ids=None,
    ):
        channel, profile = self._profile(token, company_ids)
        return channel._odooclaw_app_send(
            profile,
            channel_id,
            body,
            attachment_ids,
            record_context,
            record_attachment_ids,
        )

    @http.route(
        "/odooclaw/app/record_context", type="json", auth="user", methods=["POST"]
    )
    def record_context(
        self, token=None, channel_id=None, reference=None, company_ids=None
    ):
        channel, profile = self._profile(token, company_ids)
        return channel._odooclaw_app_record_context(profile, channel_id, reference)

    @http.route("/odooclaw/app/rename", type="json", auth="user", methods=["POST"])
    def rename(self, token=None, channel_id=None, name="", company_ids=None):
        channel, profile = self._profile(token, company_ids)
        record = channel._odooclaw_app_channel(profile, channel_id)
        if not isinstance(name, str) or not name.strip() or len(name) > 160:
            raise UserError("Escribe un nombre de hasta 160 caracteres.")
        record.write({"name": name.strip()})
        return {"ok": True}

    @http.route("/odooclaw/app/delete", type="json", auth="user", methods=["POST"])
    def delete(self, token=None, channel_id=None, company_ids=None):
        channel, profile = self._profile(token, company_ids)
        return channel._odooclaw_app_channel(
            profile, channel_id
        ).odooclaw_delete_conversation()

    @http.route(
        "/odooclaw/app/upload", type="http", auth="user", methods=["POST"], csrf=True
    )
    def upload(self, token=None, channel_id=None, company_ids=None, **kwargs):
        channel, profile = self._profile(token, company_ids)
        files = request.httprequest.files.getlist("file")
        if len(files) != 1:
            raise UserError("Selecciona un archivo.")
        try:
            channel_id = int(channel_id)
        except (ValueError, TypeError):
            raise AccessError("Conversación no válida.") from None
        result = channel._odooclaw_app_upload(
            profile, channel_id, files[0].filename, files[0].read(25 * 1024 * 1024 + 1)
        )
        return request.make_json_response(result)

    @http.route(
        "/odooclaw/app/download", type="http", auth="user", methods=["POST"], csrf=True
    )
    def download(
        self,
        token=None,
        channel_id=None,
        attachment_id=None,
        company_ids=None,
        **kwargs,
    ):
        channel, profile = self._profile(token, company_ids)
        try:
            channel_id, attachment_id = int(channel_id), int(attachment_id)
        except (ValueError, TypeError):
            raise AccessError("Adjunto no válido.") from None
        attachment = channel._odooclaw_app_attachment(
            profile, channel_id, attachment_id
        )
        stream = request.env["ir.binary"]._get_stream_from(attachment, "raw")
        return stream.get_response(as_attachment=True)

    @http.route("/odooclaw/app/usage", type="json", auth="user", methods=["POST"])
    def usage(self, token=None, channel_id=None, company_ids=None):
        channel, profile = self._profile(token, company_ids)
        return channel._odooclaw_app_channel(profile, channel_id).odooclaw_model_usage()

    @http.route("/odooclaw/app/models", type="json", auth="user", methods=["POST"])
    def models(self, token=None, channel_id=None, company_ids=None):
        channel, profile = self._profile(token, company_ids)
        record = channel._odooclaw_app_channel(profile, channel_id)
        return {
            "catalog": channel._odooclaw_app_model_catalog(),
            "settings": record._odooclaw_app_model_settings(),
        }

    @http.route(
        "/odooclaw/app/model_settings", type="json", auth="user", methods=["POST"]
    )
    def model_settings(
        self, token=None, channel_id=None, settings=None, company_ids=None
    ):
        channel, profile = self._profile(token, company_ids)
        return channel._odooclaw_app_channel(
            profile, channel_id
        )._odooclaw_app_set_model_settings(settings)
