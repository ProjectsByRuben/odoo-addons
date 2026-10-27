from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestProfile(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env["ir.config_parameter"].sudo().set_param("odooclaw.app.enforce", "0")
        self.shared = new_test_user(
            self.env(context=dict(self.env.context, no_reset_password=True)),
            login="oc_shared_" + uuid4().hex,
            groups="base.group_user",
        )
        self.employee = self.env["hr.employee"].create(
            {
                "name": "OdooClaw PIN fixture",
                "company_id": self.env.company.id,
            }
        )
        self.other_employee = self.env["hr.employee"].create(
            {
                "name": "OdooClaw excluded fixture",
                "company_id": self.env.company.id,
            }
        )
        self.channel = self.env["mail.channel"].with_user(self.shared)
        cls = type(self.channel)
        original = cls._odooclaw_employee_domain
        uid, employee_id = self.shared.id, self.employee.id

        def domain(recordset):
            if recordset.env.uid == uid:
                return [
                    ("id", "=", employee_id),
                    ("active", "=", True),
                    ("company_id", "in", recordset.env.companies.ids),
                ]
            return original(recordset)

        patched = patch.object(cls, "_odooclaw_employee_domain", domain)
        patched.start()
        self.addCleanup(patched.stop)
        self.session = type("BrowserSession", (dict,), {"sid": "test-session-one"})()

    def unlock(self, pin="1234"):
        return self.channel._odooclaw_app_unlock(self.employee.id, pin, self.session)

    def test_empty_pin_and_employee_scope(self):
        self.assertFalse(self.unlock()["ok"])
        self.assertFalse(self.session)
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_unlock(self.other_employee.id, "", self.session)
        with self.assertRaises(UserError):
            self.channel._odooclaw_app_unlock(None, "", self.session)

    def test_first_access_sets_native_pin_once_and_unlocks(self):
        result = self.channel._odooclaw_app_setup_pin(
            self.employee.id, "0427", "0427", self.session
        )
        self.assertTrue(result["ok"])
        self.assertEqual(self.employee.pin, "0427")
        self.assertEqual(
            self.channel._odooclaw_app_profile(result["token"], self.session)[
                "employee"
            ],
            self.employee,
        )
        repeat = self.channel._odooclaw_app_setup_pin(
            self.employee.id, "9999", "9999", self.session
        )
        self.assertFalse(repeat["ok"])
        self.assertFalse(repeat["needs_setup"])
        self.assertEqual(self.employee.pin, "0427")
        self.assertTrue(self.unlock("0427")["ok"])

    def test_pin_setup_validates_confirmation_format_and_employee_scope(self):
        for pin, confirmation in [
            ("123", "123"),
            ("123456789", "123456789"),
            ("abcd", "abcd"),
            ("１２３４", "１２３４"),
            ("1234", "5678"),
            (None, None),
        ]:
            self.assertFalse(
                self.channel._odooclaw_app_setup_pin(
                    self.employee.id, pin, confirmation, self.session
                )["ok"]
            )
            self.assertFalse(self.employee.pin)
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_setup_pin(
                self.other_employee.id, "1234", "1234", self.session
            )
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_setup_pin(self.employee.id, "1234", "1234", {})
        self.assertFalse(self.employee.pin)
        self.assertFalse(self.other_employee.pin)
        with self.assertRaises(AccessError):
            self.env["mail.channel"]._odooclaw_app_setup_pin(
                self.employee.id, "1234", "1234", self.session
            )

    def test_bootstrap_reports_pin_setup_without_exposing_pin(self):
        data = self.channel._odooclaw_app_bootstrap()
        self.assertTrue(data["employees"][0]["pin_setup_required"])
        self.assertNotIn("pin", data["employees"][0])
        self.employee.pin = "1234"
        data = self.channel._odooclaw_app_bootstrap()
        self.assertFalse(data["employees"][0]["pin_setup_required"])

    def test_model_settings_persist_per_chat_and_validate_capabilities(self):
        first = self.create_conversation(self.employee)
        second = self.create_conversation(self.employee)
        catalog = {
            "available": True,
            "models": [
                {
                    "id": "fixture-model",
                    "efforts": ["medium", "high"],
                    "tiers": ["default", "priority"],
                }
            ],
        }
        settings = {
            "model": "fixture-model",
            "reasoning_effort": "high",
            "service_tier": "priority",
        }
        with patch.object(
            type(first), "_odooclaw_app_model_catalog", return_value=catalog
        ):
            self.assertEqual(first._odooclaw_app_set_model_settings(settings), settings)
            self.assertEqual(
                second._odooclaw_app_model_settings(),
                {
                    "model": "gpt-6.1-sol",
                    "reasoning_effort": "medium",
                    "service_tier": "default",
                },
            )
            for key, value in [
                ("model", "missing"),
                ("reasoning_effort", "ultra"),
                ("service_tier", "other"),
            ]:
                with self.assertRaises(UserError):
                    first._odooclaw_app_set_model_settings(
                        dict(settings, **{key: value})
                    )
            self.assertEqual(first._odooclaw_app_model_settings(), settings)
        empty = {key: "" for key in settings}
        self.assertEqual(
            first._odooclaw_app_set_model_settings(empty),
            {
                "model": "gpt-6.1-sol",
                "reasoning_effort": "medium",
                "service_tier": "default",
            },
        )

    def test_model_settings_follow_operator_scope(self):
        mine = self.create_conversation(self.employee)
        other = self.create_conversation(self.other_employee)
        self.env["ir.config_parameter"].sudo().set_param("odooclaw.app.enforce", "1")
        profile = {"user": self.shared, "employee": self.employee}
        permitted = self.channel._odooclaw_app_with_profile(profile)
        self.assertEqual(permitted._odooclaw_app_channel(profile, mine.id).id, mine.id)
        with self.assertRaises(AccessError):
            permitted._odooclaw_app_channel(profile, other.id)
        with self.assertRaises(AccessError):
            permitted.browse(other.id)._odooclaw_app_set_model_settings(
                {
                    "model": "",
                    "reasoning_effort": "",
                    "service_tier": "",
                }
            )

    def test_attempt_limit_and_recovery(self):
        self.employee.pin = "1234"
        for _ in range(5):
            self.assertFalse(self.unlock("9999")["ok"])
        self.assertEqual(self.employee.odooclaw_pin_failures, 5)
        self.assertTrue(self.employee.odooclaw_pin_locked_until)
        self.assertFalse(self.unlock()["ok"])
        self.employee.odooclaw_pin_locked_until = fields.Datetime.now() - timedelta(
            seconds=1
        )
        self.assertTrue(self.unlock()["ok"])
        self.assertFalse(self.employee.odooclaw_pin_locked_until)
        self.assertEqual(self.employee.odooclaw_pin_failures, 0)

    def test_capability_bound_to_user_session_and_pin(self):
        self.employee.pin = "1234"
        token = self.unlock()["token"]
        profile = self.channel._odooclaw_app_profile(token, self.session)
        self.assertEqual(profile["employee"].id, self.employee.id)
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_profile(
                token, type("OtherSession", (dict,), {"sid": "test-session-two"})()
            )
        with self.assertRaises(AccessError):
            self.env["mail.channel"]._odooclaw_app_profile(token, self.session)
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_profile(token + "x", self.session)
        self.employee.pin = "5678"
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_profile(token, self.session)

    def test_tabs_have_independent_capabilities(self):
        self.employee.pin = "1234"
        first = self.unlock()["token"]
        second = self.unlock()["token"]
        self.channel._odooclaw_app_lock(first, self.session)
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_profile(first, self.session)
        self.assertEqual(
            self.channel._odooclaw_app_profile(second, self.session)["employee"].id,
            self.employee.id,
        )

    def test_personal_account_uses_authenticated_odoo_identity(self):
        user = new_test_user(
            self.env(context=dict(self.env.context, no_reset_password=True)),
            login="oc_personal_" + uuid4().hex,
            groups="base.group_user",
        )
        personal = self.env["mail.channel"].with_user(user)
        result = personal._odooclaw_app_unlock(None, "", self.session)
        self.assertTrue(result["ok"])
        profile = personal._odooclaw_app_profile(result["token"], self.session)
        self.assertEqual(profile["user"], user)
        self.assertFalse(profile["employee"])

    def test_employee_scope_rechecked(self):
        self.employee.pin = "1234"
        token = self.unlock()["token"]
        self.employee.active = False
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_profile(token, self.session)

    def test_expired_profile_denied(self):
        self.employee.pin = "1234"
        token = self.unlock()["token"]
        profiles = self.shared.sudo().odooclaw_app_profiles
        for claims in profiles.values():
            claims["expiry"] = 0
        self.shared.sudo().odooclaw_app_profiles = profiles
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_profile(token, self.session)

    def create_conversation(self, employee):
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        return self.channel.create(
            {
                "name": "OdooClaw fixture",
                "channel_type": "group",
                "odooclaw_conversation": True,
                "odooclaw_employee_id": employee.id,
                "channel_partner_ids": [
                    (4, self.shared.partner_id.id),
                    (4, bot.partner_id.id),
                ],
            }
        )

    def test_conversations_and_messages_exclude_other_operator(self):
        mine = self.create_conversation(self.employee)
        other = self.create_conversation(self.other_employee)
        profile = {"user": self.shared, "employee": self.employee}
        rows = self.channel._odooclaw_app_conversations(profile)
        self.assertIn(mine.id, [row["id"] for row in rows])
        self.assertNotIn(other.id, [row["id"] for row in rows])
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_messages(profile, other.id)
        with self.assertRaises(AccessError):
            self.channel._odooclaw_app_messages(profile, True)

    def test_message_poll_revision_and_safe_send(self):
        channel = self.create_conversation(self.employee)
        profile = {"user": self.shared, "employee": self.employee}
        # The live webhook must never run against fixtures on cmpslu.
        with patch("threading.Thread.start") as start:
            result = self.channel._odooclaw_app_send(
                profile, channel.id, "<script>alert(1)</script>"
            )
            start.assert_not_called()
            queued = [
                callback
                for callback in self.env.cr.postcommit._funcs
                if callback is start
            ]
            self.assertEqual(len(queued), 1)
            queued[0]()
            start.assert_called_once()
        message = self.env["mail.message"].browse(result["id"])
        self.assertNotIn("<script>", message.body)
        self.assertIn("&lt;script&gt;", message.body)
        token = (
            self.env["mail.odooclaw.reply.token"]
            .sudo()
            .search([("message_id", "=", message.id)])
        )
        self.assertEqual(token.user_id, self.shared)
        first = self.channel._odooclaw_app_messages(profile, channel.id)
        self.assertEqual(first["messages"][-1]["id"], message.id)
        self.assertTrue(
            self.channel._odooclaw_app_messages(
                profile, channel.id, revision=first["revision"]
            )["unchanged"]
        )

    def test_native_access_and_aggregations_cannot_bypass_profile(self):
        mine = self.create_conversation(self.employee)
        other = self.create_conversation(self.other_employee)
        profile = {"user": self.shared, "employee": self.employee}
        permitted = self.channel._odooclaw_app_with_profile(profile)
        with patch("threading.Thread.start"):
            message_id = permitted._odooclaw_app_send(
                profile, mine.id, "Private fixture"
            )["id"]
        attachment = permitted._odooclaw_app_upload(
            profile, mine.id, "fixture.msg", b"mail fixture"
        )
        self.env["ir.config_parameter"].sudo().set_param("odooclaw.app.enforce", "1")
        with patch("odoo.addons.odooclaw_app.models.access.request", True):
            for target, fields_to_read in [
                (self.channel.browse(mine.id), ["name"]),
                (
                    self.env["mail.message"].with_user(self.shared).browse(message_id),
                    ["body"],
                ),
                (
                    self.env["ir.attachment"]
                    .with_user(self.shared)
                    .browse(attachment["id"]),
                    ["datas"],
                ),
            ]:
                with self.assertRaises(AccessError):
                    target.read(fields_to_read)
                with self.assertRaises(AccessError):
                    target.sudo().read(fields_to_read)
                self.assertFalse(target.search([("id", "in", target.ids)]))
                self.assertFalse(
                    target.sudo().read_group(
                        [("id", "in", target.ids)], ["id:count"], ["create_uid"]
                    )
                )
            self.assertTrue(permitted.browse(mine.id).read(["name"]))
            with self.assertRaises(AccessError):
                permitted.browse(other.id).read(["name"])
            forged = self.channel.with_context(
                odooclaw_app_verified_scope=[
                    True,
                    self.shared.id,
                    self.employee.id,
                    mine.id,
                ]
            )
            with self.assertRaises(AccessError):
                forged.browse(mine.id).read(["name"])
            with self.assertRaises(AccessError):
                self.channel.channel_get(
                    [self.env.ref("mail_bot_odooclaw.odooclaw_bot").partner_id.id]
                )

    def test_attachment_scope_and_send(self):
        mine = self.create_conversation(self.employee)
        other = self.create_conversation(self.other_employee)
        profile = {"user": self.shared, "employee": self.employee}
        channel = self.channel._odooclaw_app_with_profile(profile)
        attachment = channel._odooclaw_app_upload(
            profile, mine.id, "fixture.msg", b"mail fixture"
        )
        self.assertEqual(
            channel._odooclaw_app_attachment(profile, mine.id, attachment["id"]).id,
            attachment["id"],
        )
        with self.assertRaises(AccessError):
            channel._odooclaw_app_attachment(profile, other.id, attachment["id"])
        with self.assertRaises(AccessError):
            channel._odooclaw_app_send(profile, other.id, "", [attachment["id"]])
        with patch("threading.Thread.start"):
            result = channel._odooclaw_app_send(
                profile, mine.id, "", [attachment["id"]]
            )
        self.assertEqual(
            self.env["mail.message"].browse(result["id"]).attachment_ids.ids,
            [attachment["id"]],
        )

    def test_delegated_scope_and_progress_bus(self):
        import json

        channel = self.create_conversation(self.employee)
        other = self.create_conversation(self.employee)
        profile = {"user": self.shared, "employee": self.employee}
        permitted = self.channel._odooclaw_app_with_profile(profile)
        self.env["ir.config_parameter"].sudo().set_param("odooclaw.app.enforce", "1")
        bot = self.env.ref("mail_bot_odooclaw.odooclaw_bot")
        with patch("odoo.addons.odooclaw_app.models.access.request", True), patch(
            "threading.Thread.start"
        ), patch.object(type(self.env["bus.bus"]), "_sendmany") as bus:
            result = permitted._odooclaw_app_send(
                profile, channel.id, "Private fixture no broadcast"
            )
            capability = (
                self.env["mail.odooclaw.reply.token"]
                .sudo()
                .search([("message_id", "=", result["id"])])
            )
            scope = self.channel._odooclaw_app_delegated_scope(capability)
            delegated = self.channel.with_context(**scope)
            self.assertTrue(delegated.browse(channel.id).read(["name"]))
            with self.assertRaises(AccessError):
                delegated.browse(other.id).read(["name"])
            clean = delegated._odooclaw_app_clean_result(
                {"context": dict(delegated.env.context)}
            )
            self.assertNotIn("odooclaw_app_verified_scope", json.dumps(clean))
            capability.with_user(bot).sudo()._update_progress(
                channel, bot, "Private progress no broadcast"
            )
            capability.with_user(bot).sudo()._update_progress(
                channel, bot, "Private updated no broadcast"
            )
            notifications = repr(bus.call_args_list)
            self.assertNotIn("Private fixture no broadcast", notifications)
            self.assertNotIn("Private progress no broadcast", notifications)
            self.assertNotIn("Private updated no broadcast", notifications)

    def test_company_scope_and_primary_company_bound_to_profile(self):
        company = self.env["res.company"].create({"name": "OdooClaw company fixture"})
        self.shared.company_ids = [(4, company.id)]
        self.employee.pin = "1234"
        channel = self.channel.with_context(
            allowed_company_ids=[self.env.company.id, company.id]
        )
        result = channel._odooclaw_app_unlock(self.employee.id, "1234", self.session)
        self.assertTrue(channel._odooclaw_app_profile(result["token"], self.session))
        with self.assertRaises(AccessError):
            channel.with_context(
                allowed_company_ids=[company.id, self.env.company.id]
            )._odooclaw_app_profile(result["token"], self.session)

    def test_two_operators_with_valid_pins_share_account_not_conversations(self):
        self.employee.pin = "1234"
        self.other_employee.pin = "5678"
        first_chat = self.create_conversation(self.employee)
        second_chat = self.create_conversation(self.other_employee)
        domain = [
            ("id", "in", [self.employee.id, self.other_employee.id]),
            ("company_id", "in", self.channel.env.companies.ids),
        ]
        with patch.object(
            type(self.channel), "_odooclaw_employee_domain", return_value=domain
        ):
            first = self.channel._odooclaw_app_unlock(
                self.employee.id, "1234", self.session
            )
            second = self.channel._odooclaw_app_unlock(
                self.other_employee.id, "5678", self.session
            )
            profile_one = self.channel._odooclaw_app_profile(
                first["token"], self.session
            )
            profile_two = self.channel._odooclaw_app_profile(
                second["token"], self.session
            )
            self.assertEqual(profile_one["employee"], self.employee)
            self.assertEqual(profile_two["employee"], self.other_employee)
            self.env["ir.config_parameter"].sudo().set_param(
                "odooclaw.app.enforce", "1"
            )
            channel_one = self.channel._odooclaw_app_with_profile(profile_one)
            channel_two = self.channel._odooclaw_app_with_profile(profile_two)
            self.assertIn(
                first_chat.id,
                [
                    item["id"]
                    for item in channel_one._odooclaw_app_conversations(profile_one)
                ],
            )
            self.assertNotIn(
                second_chat.id,
                [
                    item["id"]
                    for item in channel_one._odooclaw_app_conversations(profile_one)
                ],
            )
            with self.assertRaises(AccessError):
                channel_one._odooclaw_app_messages(profile_one, second_chat.id)
            self.assertIn(
                second_chat.id,
                [
                    item["id"]
                    for item in channel_two._odooclaw_app_conversations(profile_two)
                ],
            )
            self.channel._odooclaw_app_lock(first["token"], self.session)
            self.assertEqual(
                self.channel._odooclaw_app_profile(second["token"], self.session)[
                    "employee"
                ],
                self.other_employee,
            )

    def test_record_context_reference_and_selected_files(self):
        profile = {"user": self.shared, "employee": self.employee}
        mine = self.create_conversation(self.employee)
        channel = self.channel._odooclaw_app_with_profile(profile)
        partner = self.shared.partner_id
        source = self.env["ir.attachment"].create(
            {
                "name": "context-fixture.txt",
                "raw": b"selected document",
                "res_model": "res.partner",
                "res_id": partner.id,
            }
        )
        reference = {"model": "res.partner", "id": partner.id}
        info = channel._odooclaw_app_record_context(profile, mine.id, reference)
        self.assertEqual(info["name"], partner.display_name)
        self.assertIn(source.id, [f["id"] for f in info["attachments"]])
        self.assertNotIn("raw", str(info))
        text, ids = channel._odooclaw_prepare_record_context(
            profile, mine.id, reference, []
        )
        self.assertFalse(ids)
        self.assertIn("Modelo: res.partner", text)
        text, ids = channel._odooclaw_prepare_record_context(
            profile, mine.id, reference, [source.id]
        )
        copied = self.env["ir.attachment"].browse(ids)
        self.assertEqual(copied.raw, b"selected document")
        self.assertEqual(copied.res_model, "mail.channel")
        self.assertEqual(copied.res_id, mine.id)
        self.assertNotEqual(copied.id, source.id)
        self.assertEqual(source.res_model, "res.partner")
        self.assertEqual(source.res_id, partner.id)

    def test_record_context_rejects_tampering_rules_and_other_profiles(self):
        profile = {"user": self.shared, "employee": self.employee}
        mine = self.create_conversation(self.employee)
        other = self.create_conversation(self.other_employee)
        channel = self.channel._odooclaw_app_with_profile(profile)
        partner = self.shared.partner_id
        reference = {"model": "res.partner", "id": partner.id}
        for value, error in [
            (None, UserError),
            ({"model": "res.partner", "id": True}, AccessError),
            ({"model": "ir.config_parameter", "id": 1}, AccessError),
            ({"model": "mail.channel", "id": mine.id}, AccessError),
            ({"model": "res.partner", "id": partner.id, "name": "forged"}, UserError),
        ]:
            with self.assertRaises(error):
                channel._odooclaw_app_record_context(profile, mine.id, value)
        with self.assertRaises(AccessError):
            channel._odooclaw_app_record_context(profile, other.id, reference)
        foreign = self.env["res.partner"].create({"name": "Forbidden context fixture"})
        attachment = self.env["ir.attachment"].create(
            {
                "name": "other-record.txt",
                "raw": b"foreign record",
                "res_model": "res.partner",
                "res_id": foreign.id,
            }
        )
        with self.assertRaises(AccessError):
            channel._odooclaw_prepare_record_context(
                profile, mine.id, reference, [attachment.id]
            )
        self.env["ir.rule"].create(
            {
                "name": "Context fixture deny record",
                "model_id": self.env["ir.model"]._get_id("res.partner"),
                "domain_force": "[('id', '!=', %s)] if user.id == %s else []"
                % (foreign.id, self.shared.id),
            }
        )
        with self.assertRaises(AccessError):
            channel._odooclaw_app_record_context(
                profile, mine.id, {"model": "res.partner", "id": foreign.id}
            )
        with self.assertRaises(AccessError):
            channel._odooclaw_prepare_record_context(
                profile,
                mine.id,
                {"model": "res.partner", "id": foreign.id},
                [attachment.id],
            )

    def test_record_context_send_remains_escaped_and_no_automatic_business_action(self):
        profile = {"user": self.shared, "employee": self.employee}
        mine = self.create_conversation(self.employee)
        channel = self.channel._odooclaw_app_with_profile(profile)
        with patch("threading.Thread.start") as start:
            result = channel._odooclaw_app_send(
                profile,
                mine.id,
                "Resume este registro <script>",
                [],
                {"model": "res.partner", "id": self.shared.partner_id.id},
                [],
            )
            start.assert_not_called()
        message = self.env["mail.message"].browse(result["id"])
        self.assertIn("Modelo: res.partner", message.body)
        self.assertIn("&lt;script&gt;", message.body)
        self.assertFalse(message.attachment_ids)
