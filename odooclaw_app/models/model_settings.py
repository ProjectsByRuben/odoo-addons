import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class Channel(models.Model):
    _inherit = "mail.channel"

    odooclaw_model_settings = fields.Json(copy=False, readonly=True)

    def _odooclaw_app_model_settings(self):
        self.ensure_one()
        data = self.odooclaw_model_settings or {}
        if not any(data.values()):
            return {
                "model": "gpt-6.1-sol",
                "reasoning_effort": "medium",
                "service_tier": "default",
            }
        return {
            key: data.get(key, "")
            for key in ("model", "reasoning_effort", "service_tier")
        }

    @api.model
    def _odooclaw_app_model_catalog(self):
        self._odooclaw_conversation_user()
        params = self.env["ir.config_parameter"].sudo()
        secret = params.get_param("odooclaw.webhook_token", "")
        if not secret:
            return {"available": False, "models": []}
        url = (
            params.get_param(
                "odooclaw.webhook_url", "http://odooclaw:18790/webhook/odoo"
            ).rstrip("/")
            + "/system"
        )
        try:
            response = requests.post(
                url,
                json={"event": "model_catalog"},
                headers={"X-OdooClaw-Token": secret},
                timeout=(2, 16),
            )
            response.raise_for_status()
            data = response.json()
            choices = []
            for item in data.get("models", [])[:200]:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                    continue
                choices.append(
                    {
                        "id": item["id"],
                        "name": str(item.get("name") or item["id"]),
                        "is_default": bool(item.get("is_default")),
                        "default_reasoning": str(item.get("default_reasoning") or ""),
                        "efforts": [
                            v for v in item.get("efforts", []) if isinstance(v, str)
                        ],
                        "tiers": [
                            v for v in item.get("tiers", []) if isinstance(v, str)
                        ],
                    }
                )
            return {
                "available": bool(data.get("available") and choices),
                "models": choices,
            }
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            return {"available": False, "models": []}

    def _odooclaw_app_set_model_settings(self, settings):
        self.ensure_one()
        keys = {"model", "reasoning_effort", "service_tier"}
        if (
            not isinstance(settings, dict)
            or set(settings) != keys
            or any(not isinstance(v, str) or len(v) > 128 for v in settings.values())
        ):
            raise UserError(_("Ajustes de modelo no válidos."))
        if any(settings.values()):
            catalog = self._odooclaw_app_model_catalog()
            choice = next(
                (m for m in catalog["models"] if m["id"] == settings["model"]), None
            )
            if (
                not catalog["available"]
                or not choice
                or settings["reasoning_effort"] not in ["", *choice["efforts"]]
                or settings["service_tier"] not in ["", *choice["tiers"]]
            ):
                raise UserError(
                    _("Esa combinación no está disponible en la suscripción.")
                )
        self.write({"odooclaw_model_settings": dict(settings)})
        return self._odooclaw_app_model_settings()
