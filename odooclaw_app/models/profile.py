import hashlib
import hmac
import secrets
import time
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

PROFILE_SECONDS = 8 * 60 * 60
MAX_ATTEMPTS = 5
LOCK_SECONDS = 5 * 60
PROFILE_FIELD = "odooclaw_app_profiles"


class Employee(models.Model):
    _inherit = "hr.employee"

    odooclaw_pin_failures = fields.Integer(
        groups="hr.group_hr_user",
        readonly=True,
        copy=False,
    )
    odooclaw_pin_locked_until = fields.Datetime(
        groups="hr.group_hr_user",
        readonly=True,
        copy=False,
    )


class User(models.Model):
    _inherit = "res.users"

    # Only hashes of random credentials; no PINs or bearer tokens are stored.
    # Database storage avoids lost session-file updates when tabs unlock at once.
    odooclaw_app_profiles = fields.Json(
        groups="base.group_system",
        readonly=True,
        copy=False,
    )


class Channel(models.Model):
    _inherit = "mail.channel"

    @api.model
    def _odooclaw_app_pin_secret(self):
        secret = self.env["ir.config_parameter"].sudo().get_param("database.secret")
        if not secret:
            raise UserError(
                _("No está configurada la clave de seguridad de la base de datos.")
            )
        return secret

    @api.model
    def _odooclaw_app_bootstrap(self):
        user = self._odooclaw_conversation_user()
        selector = self.odooclaw_employee_selector()
        if selector["required"]:
            employees = self.env["hr.employee"].sudo().browse(
                [item["id"] for item in selector["employees"]]
            )
            needs_pin = {employee.id: not bool(employee.pin) for employee in employees}
            selector["employees"] = [
                dict(item, pin_setup_required=needs_pin[item["id"]])
                for item in selector["employees"]
            ]
        return dict(selector, user={"id": user.id, "name": user.name})

    @api.model
    def _odooclaw_app_pin_version(self, employee, secret):
        # A keyed fingerprint revokes old profiles after PIN changes without
        # revealing a digest that could be brute-forced offline by the browser.
        pin = employee.pin or ""
        return hmac.new(secret.encode(), pin.encode(), hashlib.sha256).hexdigest()

    @api.model
    def _odooclaw_app_profile_store(self, lock=False):
        user = self._odooclaw_conversation_user().sudo()
        if lock:
            self.env.cr.execute(
                "SELECT id FROM res_users WHERE id = %s FOR UPDATE", [user.id]
            )
            user.invalidate_recordset([PROFILE_FIELD])
        return user

    @api.model
    def _odooclaw_app_session_digest(self, session):
        sid = getattr(session, "sid", None)
        if not sid:
            raise AccessError(_("No hay una sesión válida para desbloquear el perfil."))
        return hashlib.sha256(sid.encode()).hexdigest()

    @api.model
    def _odooclaw_app_setup_pin(self, employee_id, pin, confirmation, session):
        # This narrow self-service operation is only for an allowed employee
        # whose native PIN is still empty. It grants no general HR write access.
        if self._odooclaw_employee_domain() is None:
            raise AccessError(
                _("Esta cuenta no necesita configurar un PIN de operario.")
            )
        employee = self._odooclaw_selected_employee(employee_id, required=True)
        self._odooclaw_app_session_digest(session)
        self.env.cr.execute(
            "SELECT id FROM hr_employee WHERE id = %s FOR UPDATE", [employee.id]
        )
        employee.invalidate_recordset(["pin"])
        if employee.pin:
            return {
                "ok": False,
                "needs_setup": False,
                "error": _("Este operario ya tiene PIN. Introduce su PIN para entrar."),
            }
        if (
            not isinstance(pin, str)
            or not 4 <= len(pin) <= 8
            or not pin.isascii()
            or not pin.isdigit()
        ):
            return {"ok": False, "error": _("Elige un PIN de 4 a 8 números.")}
        if not isinstance(confirmation, str) or not secrets.compare_digest(
            pin.encode(), confirmation.encode()
        ):
            return {"ok": False, "error": _("Los dos PIN no coinciden.")}
        employee.write({"pin": pin})
        return self._odooclaw_app_unlock(employee.id, pin, session)

    @api.model
    def _odooclaw_app_unlock(self, employee_id, pin, session):
        user = self._odooclaw_conversation_user()
        required = self._odooclaw_employee_domain() is not None
        employee = self._odooclaw_selected_employee(employee_id, required=required)
        secret = self._odooclaw_app_pin_secret()
        if required:
            # Serialize attempts across browsers/workers. Failures are returned
            # normally (not raised) so the HTTP transaction commits the counter.
            self.env.cr.execute(
                "SELECT id FROM hr_employee WHERE id = %s FOR UPDATE", [employee.id]
            )
            employee.invalidate_recordset(
                [
                    "pin",
                    "odooclaw_pin_failures",
                    "odooclaw_pin_locked_until",
                ]
            )
            now = fields.Datetime.now()
            if (
                employee.odooclaw_pin_locked_until
                and employee.odooclaw_pin_locked_until > now
            ):
                return {
                    "ok": False,
                    "error": _(
                        "Demasiados intentos. Espera unos minutos "
                        "antes de volver a intentarlo."
                    ),
                }
            if not employee.pin:
                return {
                    "ok": False,
                    "needs_setup": True,
                    "error": _(
                        "Todavía no tienes PIN. Créalo y confírmalo para entrar."
                    ),
                }
            if not isinstance(pin, str) or not secrets.compare_digest(
                pin.encode(), employee.pin.encode()
            ):
                expired = bool(employee.odooclaw_pin_locked_until)
                failures = (0 if expired else employee.odooclaw_pin_failures) + 1
                employee.write(
                    {
                        "odooclaw_pin_failures": failures,
                        "odooclaw_pin_locked_until": (
                            now + timedelta(seconds=LOCK_SECONDS)
                            if failures >= MAX_ATTEMPTS
                            else False
                        ),
                    }
                )
                return {
                    "ok": False,
                    "error": _(
                        "No se ha podido desbloquear el perfil. Comprueba el PIN."
                    ),
                }
            employee.write(
                {"odooclaw_pin_failures": 0, "odooclaw_pin_locked_until": False}
            )

        claims = {
            "uid": user.id,
            "employee_id": employee.id if employee else False,
            "companies": self.env.companies.ids,
            "pin_version": self._odooclaw_app_pin_version(employee, secret)
            if employee
            else "",
            "expiry": time.time() + PROFILE_SECONDS,
            "session": self._odooclaw_app_session_digest(session),
        }
        store = self._odooclaw_app_profile_store(lock=True)
        profiles = {
            key: value
            for key, value in (store[PROFILE_FIELD] or {}).items()
            if value.get("expiry", 0) > time.time()
        }
        if len(profiles) >= 128:
            raise UserError(
                _(
                    "Hay demasiados perfiles abiertos. "
                    "Bloquea alguno o espera a que caduque."
                )
            )
        token = secrets.token_urlsafe(48)
        profiles[hashlib.sha256(token.encode()).hexdigest()] = claims
        store.write({PROFILE_FIELD: profiles})
        return {
            "ok": True,
            "token": token,
            "profile": {
                "employee_id": claims["employee_id"],
                "name": employee.name if employee else user.name,
            },
        }

    @api.model
    def _odooclaw_app_profile(self, token, session):
        user = self._odooclaw_conversation_user()
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise AccessError(_("Desbloquea tu perfil para usar OdooClaw."))
        secret = self._odooclaw_app_pin_secret()
        digest = hashlib.sha256(token.encode()).hexdigest()
        claims = (self._odooclaw_app_profile_store()[PROFILE_FIELD] or {}).get(
            digest, {}
        )
        if (
            claims.get("uid") != user.id
            or claims.get("session") != self._odooclaw_app_session_digest(session)
            or claims.get("expiry", 0) <= time.time()
            or claims.get("companies") != self.env.companies.ids
        ):
            raise AccessError(_("El perfil no es válido para esta sesión o compañías."))
        required = self._odooclaw_employee_domain() is not None
        employee = self._odooclaw_selected_employee(
            claims.get("employee_id"), required=required
        )
        if employee and (
            not employee.pin
            or not secrets.compare_digest(
                claims.get("pin_version", ""),
                self._odooclaw_app_pin_version(employee, secret),
            )
        ):
            raise AccessError(_("El PIN ha cambiado. Desbloquea de nuevo tu perfil."))
        return {"user": user, "employee": employee, "digest": digest}

    @api.model
    def _odooclaw_app_lock(self, token, session):
        profile = self._odooclaw_app_profile(token, session)
        store = self._odooclaw_app_profile_store(lock=True)
        profiles = dict(store[PROFILE_FIELD] or {})
        profiles.pop(profile["digest"], None)
        store.write({PROFILE_FIELD: profiles})
        return {"ok": True}
