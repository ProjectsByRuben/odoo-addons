from odoo import http, SUPERUSER_ID, fields, api
from odoo.exceptions import AccessError, UserError, ValidationError, MissingError
from werkzeug.exceptions import HTTPException
from odoo.http import request
import json
from psycopg2 import OperationalError
from odoo.service.model import PG_CONCURRENCY_ERRORS_TO_RETRY
from markupsafe import Markup

from ..utils.markdown_html import markdown_to_safe_html
from ..utils.token_usage import token_usage_footer
from . import security


def _raise_retryable_database_error(error):
    # Let Odoo's request-level retrying() roll back and rerun the transaction.
    # Converting these exceptions into HTTP 500 suppresses the native retry.
    if isinstance(error, OperationalError) and error.pgcode in PG_CONCURRENCY_ERRORS_TO_RETRY:
        raise error


class OdooClawController(http.Controller):
    @http.route(
        "/odooclaw/reply", type="http", auth="public", methods=["POST"], csrf=False
    )
    def odooclaw_reply(self, **kwargs):
        """
        Endpoint for OdooClaw to send messages back to an Odoo discussion/thread.
        Supports text messages and voice attachments (voice notes).

        Expected payload:
        {
            "model": "mail.channel",
            "res_id": 123,
            "message": "Hello!",
            "attachment_ids": [456, 457],
            "voice_metadata_ids": [789]
        }
        """
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            model_name = payload.get("model")
            res_id = payload.get("res_id")
            message_body = payload.get("message", "")
            attachment_ids = payload.get("attachment_ids", [])
            voice_metadata_ids = payload.get("voice_metadata_ids", [])
            reply_token = payload.get("reply_token", "")
            progress = payload.get("progress") is True

            if not model_name or not res_id:
                return security.error_response("Missing parameters")

            if not message_body and not attachment_ids:
                return security.error_response("Missing message or attachments")

            # Validate reply token — ensures this reply was solicited by a human message
            if not reply_token:
                return request.make_json_response(
                    {"status": "error", "reason": "Missing reply_token"},
                    status=401
                )
            token_valid = (
                request.env["mail.odooclaw.reply.token"]
                .sudo()
                ._validate(reply_token, model_name, res_id, consume=not progress)
            )
            if not token_valid:
                return request.make_json_response(
                    {"status": "error", "reason": "Invalid or expired reply_token"},
                    status=403
                )

            bot_user = (
                request.env["res.users"]
                .sudo()
                .search([("login", "=", "odooclaw_bot")], limit=1)
            )
            if not bot_user:
                return security.error_response("OdooClaw bot user not found")

            token_valid = token_valid.with_user(bot_user).sudo()
            message_html = markdown_to_safe_html(message_body)
            if not progress:
                message_html = Markup(message_html) + token_usage_footer(payload.get("token_usage"))

            post_values = {
                "body": Markup(message_html),
                "author_id": bot_user.partner_id.id,
                "message_type": "comment",
            }

            if attachment_ids:
                post_values["attachment_ids"] = [(6, 0, attachment_ids)]

            if voice_metadata_ids:
                post_values["voice_ids"] = [(6, 0, voice_metadata_ids)]

            record = request.env[model_name].sudo().browse(res_id)
            if record.exists():
                if progress:
                    token_valid.progress_count += 1
                    token_valid._update_progress(record, bot_user, message_body)
                else:
                    token_valid.finished_at = fields.Datetime.now()
                    token_valid._update_progress(record, bot_user, "Finalizada", finished=True)
                    record.with_user(bot_user).sudo().message_post(**post_values)

                if model_name == "mail.channel" and not progress:
                    channel_partner = request.env["mail.channel.member"].sudo().search(
                        [
                            ("channel_id", "=", record.id),
                            ("partner_id", "=", bot_user.partner_id.id),
                        ],
                        limit=1,
                    )
                    if channel_partner:
                        channel_partner._notify_typing(is_typing=False)

                return request.make_json_response({"status": "ok"})

            return security.error_response("Record not found")
        except Exception as e:
            _raise_retryable_database_error(e)
            if isinstance(e, (http.Response, HTTPException)):
                raise
            request.env.cr.rollback()
            return security.log_exception(security._logger, "odooclaw_reply error")

    @http.route(
        "/odooclaw/call_kw_as_user",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def call_kw_as_user(self, **kwargs):
        """
        Executes an ORM method on behalf of a specific user.
        Payload:
        {
            "user_id": 5,
            "model": "sale.order",
            "method": "create",
            "args": [[{...}]],
            "kwargs": {}
        }
        """
        try:
            security.authorize()

            payload = json.loads(request.httprequest.data)
            user_id = payload.get("user_id")
            model = payload.get("model")
            method = payload.get("method")
            args = payload.get("args", [])
            kwargs_dict = payload.get("kwargs", {})
            context_dict = payload.get("context") or {}

            if (
                not isinstance(model, str) or not isinstance(method, str)
                or not isinstance(args, list) or not isinstance(kwargs_dict, dict)
                or not isinstance(context_dict, dict)
            ):
                return security.error_response("Invalid delegated RPC payload")
            if method.startswith("_") or method in (
                "init", "sudo", "with_user", "with_env", "with_context", "with_company",
            ):
                return security.error_response("Permission denied: unsafe RPC method", status=403)

            if not user_id or not model or not method:
                return security.error_response("Missing user_id, model, or method")

            if not request.session.uid:
                return security.error_response(
                    "Unauthorized. Must be logged in via session.",
                    status=401,
                )

            caller = request.env.user
            odooclaw_bot = request.env.ref(
                "mail_bot_odooclaw.odooclaw_bot", raise_if_not_found=False
            )
            if not (
                (odooclaw_bot and caller.id == odooclaw_bot.id)
                or caller.has_group("mail_bot_odooclaw.group_odooclaw_delegator")
                or caller.has_group("base.group_system")
            ):
                return security.error_response(
                    "Unauthorized. Delegated RPC permission required.",
                    status=401,
                )

            try:
                user_id = int(user_id)
            except (TypeError, ValueError):
                return security.error_response("Invalid user_id")

            target_user = request.env["res.users"].sudo().browse(user_id)
            if (user_id in (SUPERUSER_ID, caller.id) or not target_user.exists()
                    or not target_user.active or target_user.share):
                return security.error_response("Invalid delegated user")

            # Bind every RPC to the user of a real, unexpired incoming message.
            capability = request.env["mail.odooclaw.reply.token"].sudo().search([
                ("token", "=", payload.get("request_token") or ""),
                ("user_id", "=", user_id), ("used", "=", False),
                ("expiry", ">", __import__("odoo").fields.Datetime.now()),
            ], limit=1)
            if capability:
                request.env.cr.execute("SELECT id FROM mail_odooclaw_reply_token WHERE id = %s FOR UPDATE", [capability.id])
                capability.invalidate_recordset(["used"])
            if not capability or capability.used:
                return security.error_response("Permission denied: invalid request identity", status=403)

            if model == "mail.odooclaw.reply.token" or (model == "ir.config_parameter" and not (
                method == "get_param" and args and args[0] in (
                    "odooclaw.extra_allowed_models", "odooclaw.denied_models",
                )
            )):
                return security.error_response("Permission denied: secrets are not available through the bot", status=403)

            # Use the delegated user's defaults, never the service account's companies.
            merged_context = dict(target_user.with_user(user_id).context_get())
            merged_context["allowed_company_ids"] = json.loads(capability.allowed_company_ids_json or "[]")
            merged_context.update(context_dict)
            nested_context = kwargs_dict.pop("context", {})
            if not isinstance(nested_context, dict):
                return security.error_response("Invalid RPC context")
            merged_context.update(nested_context)
            for key in ("uid", "user", "su", "sudo"):
                merged_context.pop(key, None)
            allowed = merged_context.get("allowed_company_ids", [target_user.company_id.id])
            if (not isinstance(allowed, list) or not allowed
                    or any(type(cid) is not int for cid in allowed)
                    or not set(allowed).issubset(set(target_user.company_ids.ids))
                    or not set(allowed).issubset(set(json.loads(capability.allowed_company_ids_json or "[]")))):
                return security.error_response("Permission denied: unauthorized company", status=403)
            for key in ("company_id", "force_company"):
                if key in merged_context and merged_context[key] not in allowed:
                    return security.error_response("Permission denied: unauthorized company", status=403)
            merged_context["allowed_company_ids"] = allowed
            # Environment.__call__ preserves uid_origin from the service session.
            # Native one2many commands use that origin for child mutations, so
            # construct a fresh environment bound entirely to the human user.
            safe_env = api.Environment(request.env.cr, user_id, merged_context, su=False, uid_origin=user_id)
            scope_provider = getattr(safe_env["mail.channel"], "_odooclaw_app_delegated_scope", None)
            app_scope = scope_provider(capability) if scope_provider else {}
            if app_scope:
                merged_context.update(app_scope)
                safe_env = api.Environment(request.env.cr, user_id, merged_context, su=False, uid_origin=user_id)

            try:
                recs = safe_env[model]
                rpc_args = list(args)
                operation = {
                    "create": "create", "copy": "create", "write": "write", "unlink": "unlink",
                    "read": "read", "search": "read", "search_read": "read",
                    "search_count": "read", "read_group": "read", "name_search": "read",
                }.get(method)
                if args and (
                    isinstance(args[0], int)
                    or (
                        isinstance(args[0], list)
                        and (not args[0] or isinstance(args[0][0], int))
                    )
                ):
                    if method not in (
                        "search",
                        "create",
                        "search_read",
                        "search_count",
                        "fields_get",
                    ):
                        recs = recs.browse(args.pop(0))

                # Do not use permissive child ACLs to bypass a sales/purchase header.
                if model in ("sale.order.line", "purchase.order.line") and operation in ("create", "write", "unlink"):
                    parent_model = "sale.order" if model == "sale.order.line" else "purchase.order"
                    parents = safe_env[parent_model]
                    parents.check_access_rights("write")
                    parent_ids = recs.mapped("order_id").ids if recs.ids else []
                    values = args[0] if args else {}
                    entries = values if isinstance(values, list) else [values]
                    parent_ids += [value["order_id"] for value in entries if isinstance(value, dict) and type(value.get("order_id")) is int]
                    parents.browse(parent_ids).check_access_rule("write")
                with request.env.cr.savepoint():
                    # api.call_kw rebuilds the record context from kwargs.
                    # Pass the validated context explicitly, including companies.
                    kwargs_dict["context"] = merged_context
                    result = api.call_kw(safe_env[model], method, rpc_args, kwargs_dict)
                    if hasattr(result, "_name") and hasattr(result, "ids"):
                        if method in ("create", "message_post") and len(result.ids) == 1:
                            result = result.ids[0]
                        else:
                            result = result.ids
                    if app_scope:
                        result = safe_env["mail.channel"]._odooclaw_app_clean_result(result)
                    return request.make_json_response({"status": "ok", "result": result})
            except AccessError:
                return security.error_response(
                    "Permission denied: the active Odoo user is not allowed to perform this operation.",
                    status=403,
                )
            except (UserError, ValidationError, MissingError) as business_error:
                return security.error_response(str(business_error), status=422)
            except Exception as orm_error:
                _raise_retryable_database_error(orm_error)
                return security.error_response("Odoo ORM error", status=500)

        except Exception as e:
            _raise_retryable_database_error(e)
            if isinstance(e, (http.Response, HTTPException)):
                raise
            return security.log_exception(security._logger, "call_kw_as_user error")
