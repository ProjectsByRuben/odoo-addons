{
    "name": "OdooClaw AI Bot",
    "version": "16.0.1.6.5",
    "category": "Discuss",
    "summary": "Integrate OdooClaw AI agent via webhooks in Odoo Discuss",
    "description": """
OdooClaw AI Bot for Odoo Discuss.

Features:
- Bot user for Discuss channels and direct messages.
- Webhook bridge between Odoo and OdooClaw.
- Voice attachment support.
""",
    "author": "Nicolás Ramos",
    "license": "AGPL-3",
    "depends": ["mail", "hr"],
    "data": [
        "security/odooclaw_security.xml",
        "security/ir.model.access.csv",
        "data/odooclaw_bot_data.xml",
        "data/odooclaw_cron.xml",
    ],
    "installable": True,
    "assets": {
        "web.assets_backend": [
            "mail_bot_odooclaw/static/src/conversations.js",
            "mail_bot_odooclaw/static/src/conversation_lifecycle.js",
            "mail_bot_odooclaw/static/src/conversations.xml",
            "mail_bot_odooclaw/static/src/progress.scss",
            "mail_bot_odooclaw/static/src/model_usage.js",
            "mail_bot_odooclaw/static/src/model_usage.xml",
        ],
    },
    "application": False,
    "auto_install": False,
    "maintainer": "nicolasramos",
    "development_status": "Beta",
}
