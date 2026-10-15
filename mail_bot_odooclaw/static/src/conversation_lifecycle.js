/** @odoo-module **/

import { registerPatch } from "@mail/model/model_core";
import { attr, one } from "@mail/model/model_field";
import { clear } from "@mail/model/model_field_command";

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
    fields: {
        odooclaw_conversation: attr({ default: false }),
    },
    modelMethods: {
        convertData(data) {
            const result = this._super(data);
            if ("odooclaw_conversation" in data) {
                result.odooclaw_conversation = Boolean(data.odooclaw_conversation);
            }
            return result;
        },
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
    name: "Channel",
    fields: {
        odooclaw_conversation: attr({
            compute() {
                return Boolean(this.thread && this.thread.odooclaw_conversation);
            },
            default: false,
        }),
        discussSidebarCategoryItem: one('DiscussSidebarCategoryItem', {
            compute() {
                // If it is an OdooClaw AI conversation, NEVER show it in the Discuss sidebar categories
                if (this.odooclaw_conversation || (this.thread && this.thread.odooclaw_conversation)) {
                    return clear();
                }
                if (!this.thread) {
                    return clear();
                }
                if (!this.thread.isPinned) {
                    return clear();
                }
                if (!this.discussSidebarCategory) {
                    return clear();
                }
                return { category: this.discussSidebarCategory };
            },
            inverse: 'channel',
        }),
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
