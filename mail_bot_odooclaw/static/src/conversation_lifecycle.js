/** @odoo-module **/

import { registerPatch } from "@mail/model/model_core";

function forgetChannel(messaging, id) {
    const thread = messaging.models["Thread"].findFromIdentifyingData({ model: "mail.channel", id });
    if (thread && thread.exists()) {
        // The channel has gone away: do not save fold state or issue another RPC.
        messaging.chatWindowManager.closeThread(thread, { notifyServer: false });
        if (thread.exists()) {
            thread.delete();
        }
    }
}

function isGone(error) {
    return error.code === 404 || error.exceptionName === "werkzeug.exceptions.NotFound";
}

registerPatch({
    name: "Thread",
    modelMethods: {
        async performRpcChannelSeen({ id, lastMessageId }) {
            const original = this._super.bind(this);
            try {
                return await original({ id, lastMessageId });
            } catch (error) {
                if (!isGone(error)) {
                    throw error;
                }
                forgetChannel(this.messaging, id);
            }
        },
        async performRpcChannelFold(id, state) {
            const original = this._super.bind(this);
            try {
                return await original(id, state);
            } catch (error) {
                if (!isGone(error) && error.exceptionName !== "odoo.exceptions.MissingError") {
                    throw error;
                }
                forgetChannel(this.messaging, id);
            }
        },
    },
});

registerPatch({
    name: "MessagingNotificationHandler",
    recordMethods: {
        async _handleNotificationChannelDelete({ id }) {
            const original = this._super.bind(this);
            forgetChannel(this.messaging, id);
            return original({ id });
        },
    },
});
