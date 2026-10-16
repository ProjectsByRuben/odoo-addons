/** @odoo-module **/

import { registerPatch } from "@mail/model/model_core";
import { attr } from "@mail/model/model_field";
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
    name: "Message",
    modelMethods: {
        async performRpcMessageFetch(route, params) {
            const original = this._super.bind(this);
            try {
                return await original(route, params);
            } catch (error) {
                // Duplicated tabs/old Discuss URLs can retain channels deleted
                // or no longer accessible to the current account. Keep the
                // server's membership check; discard only the stale local view.
                if (route !== "/mail/channel/messages" || !params.channel_id || !isGone(error)) {
                    throw error;
                }
                forgetChannel(this.messaging, params.channel_id);
                return [];
            }
        },
    },
});

registerPatch({
    name: "Thread",
    fields: {
        odooclaw_conversation: attr({ default: false }),
    },
    recordMethods: {
        async notifyFoldStateToServer(state) {
            // An Odoo account may be shared across operators and devices.
            // Their AI windows are local; native human chats still synchronize.
            if (this.odooclaw_conversation) {
                return;
            }
            return this._super(state);
        },
        _onServerFoldStateChanged() {
            // Ignore legacy/open-in-another-tab events, including remote closes
            // and minimizations of a window that is already open here.
            if (this.odooclaw_conversation) {
                return;
            }
            return this._super();
        },
        async pin() {
            if (this.odooclaw_conversation) {
                return;
            }
            return this._super();
        },
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
        discussSidebarCategoryItem: {
            compute() {
                if (this.odooclaw_conversation || (this.thread && this.thread.odooclaw_conversation)) {
                    return clear();
                }
                return this._super();
            },
        },
    },
});

registerPatch({
    name: "MessagingNotificationHandler",
    recordMethods: {
        async _handleNotificationChannelMessage(payload) {
            const original = this._super.bind(this);
            let channel = this.messaging.models["Channel"].findFromIdentifyingData({ id: payload.id });
            if ((!channel || !channel.channel_type) && !this.messaging.isCurrentUserGuest) {
                const data = await this.messaging.models["Thread"].performRpcChannelInfo({ ids: [payload.id] });
                if (!this.exists()) {
                    return;
                }
                channel = data[0] && data[0].channel;
            }
            if (channel && channel.thread && channel.thread.odooclaw_conversation) {
                const Message = this.messaging.models["Message"];
                const message = Message.insert(Message.convertData(payload.message));
                this._notifyThreadViewsMessageReceived(message);
                return;
            }
            return original(payload);
        },
        async _handleNotificationChannelDelete({ id }) {
            const original = this._super.bind(this);
            forgetChannel(this.messaging, id);
            return original({ id });
        },
    },
});

// Only an explicit action in this tab may open an AI window. Window state
// stays local even when the same account is used in other tabs or devices.
registerPatch({
    name: "ChatWindowManager",
    recordMethods: {
        openThread(thread, options = {}) {
            if (thread.odooclaw_conversation && !thread.chatWindow && !options.odooclawExplicit) {
                return;
            }
            return this._super(thread, thread.odooclaw_conversation
                ? { ...options, notifyServer: false } : options);
        },
    },
});
