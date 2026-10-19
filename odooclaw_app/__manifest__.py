{
    "name": "OdooClaw",
    "version": "16.0.1.0.0",
    "summary": "Dedicated workspace for OdooClaw conversations",
    "category": "Productivity",
    "author": "ProjectsByRuben",
    "license": "AGPL-3",
    "depends": ["web", "mail_bot_odooclaw"],
    "data": ["data/security.xml", "views/odooclaw_menu.xml"],
    "assets": {
        "web.assets_backend": [
            ("remove", "mail_bot_odooclaw/static/src/conversations.js"),
            ("remove", "mail_bot_odooclaw/static/src/conversations.xml"),
            "odooclaw_app/static/src/workspace_service.js",
            "odooclaw_app/static/src/workspace.js",
            "odooclaw_app/static/src/workspace.xml",
            "odooclaw_app/static/src/workspace.scss",
        ],
    },
    "application": True,
    "installable": True,
}
