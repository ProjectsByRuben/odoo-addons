/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { Dialog } from "@web/core/dialog/dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

class OdooClawHelp extends Component {}
OdooClawHelp.template = "mail_bot_odooclaw.ConversationHelp";
OdooClawHelp.components = { Dialog };
OdooClawHelp.props = { close: Function };

class OdooClawConversations extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.messagingService = useService("messaging");

        let savedEmpId = "";
        try {
            const raw = localStorage.getItem("odooclaw_selected_employee_id");
            if (raw) {
                savedEmpId = parseInt(raw, 10) || "";
            }
        } catch (_) {}

        this.state = useState({
            conversations: [],
            busy: false,
            employees: [],
            selectedEmployeeId: savedEmpId,
        });

        onMounted(async () => {
            await this.loadEmployees();
            await this.reconcileOpenConversations();
        });
    }

    async loadEmployees() {
        try {
            const emps = await this.orm.call("mail.channel", "odooclaw_get_available_employees", []);
            this.state.employees = emps || [];
            if (this.state.employees.length > 0) {
                const exists = this.state.employees.some(e => e.id === this.state.selectedEmployeeId);
                if (!exists) {
                    this.state.selectedEmployeeId = "";
                }
            } else {
                this.state.selectedEmployeeId = "";
            }
        } catch (e) {
            console.warn("Could not load odooclaw employees", e);
        }
    }

    async onEmployeeChange(ev) {
        const val = ev.target.value ? parseInt(ev.target.value, 10) : "";
        this.state.selectedEmployeeId = val;
        try {
            if (val) {
                localStorage.setItem("odooclaw_selected_employee_id", String(val));
            } else {
                localStorage.removeItem("odooclaw_selected_employee_id");
            }
        } catch (_) {}
        await this.loadConversations();
    }

    forgetConversation(id) {
        const messaging = this.messagingService.modelManager.messaging;
        const thread = messaging.models["Thread"].findFromIdentifyingData({ model: "mail.channel", id });
        if (thread && thread.exists()) {
            messaging.chatWindowManager.closeThread(thread, { notifyServer: false });
            if (thread.exists()) {
                thread.delete();
            }
        }
    }

    async reconcileOpenConversations() {
        await this.messagingService.modelManager.messagingCreatedPromise;
        const messaging = this.messagingService.modelManager.messaging;
        await messaging.initializedPromise;
        const ids = [...new Set(messaging.chatWindowManager.chatWindows
            .map(window => window.thread)
            .filter(thread => thread && thread.model === "mail.channel")
            .map(thread => thread.id))];
        if (!ids.length) {
            return;
        }
        const accessible = new Set(await this.orm.call("mail.channel", "odooclaw_accessible_channel_ids", [ids]));
        for (const id of ids) {
            if (!accessible.has(id)) {
                this.forgetConversation(id);
            }
        }
    }

    async loadConversations() {
        const empId = this.state.selectedEmployeeId || null;
        this.state.conversations = await this.orm.call(
            "mail.channel", "odooclaw_list_conversations", [empId]
        );
    }

    async newConversation() {
        if (this.state.busy) {
            return;
        }
        if (this.state.employees.length > 0 && !this.state.selectedEmployeeId) {
            this.notification.add("Por favor, selecciona tu nombre de operario antes de abrir una nueva conversación.", { type: "warning" });
            return;
        }
        this.state.busy = true;
        try {
            const empId = this.state.selectedEmployeeId || null;
            const channel = await this.orm.call("mail.channel", "odooclaw_new_conversation", [empId]);
            await this.openConversation(channel.id, channel);
        } finally {
            this.state.busy = false;
        }
    }

    async openConversation(id, channelData) {
        await this.messagingService.modelManager.messagingCreatedPromise;
        const messaging = this.messagingService.modelManager.messaging;
        await messaging.initializedPromise;
        const data = channelData || (await this.orm.call("mail.channel", "channel_info", [[id]]))[0];
        if (!data) {
            this.forgetConversation(id);
            await this.loadConversations();
            this.notification.add("Esta conversación ya no está disponible.", { type: "info" });
            return;
        }
        const Thread = messaging.models["Thread"];
        const thread = Thread.insert(Thread.convertData({ model: "mail.channel", ...data }));
        // Discuss suppresses floating windows. Leave it only when necessary;
        // opening from a business screen keeps that screen and its draft intact.
        if (messaging.discuss.discussView && !messaging.device.isSmall) {
            await this.action.doAction({ type: "ir.actions.client", tag: "menu" });
        }
        messaging.chatWindowManager.openThread(thread, {
            makeActive: true,
            isFolded: false,
            focus: true,
        });
    }

    showHelp() {
        this.dialog.add(OdooClawHelp);
    }

    deleteConversation(conversation) {
        if (this.state.busy) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: "Borrar conversación",
            body: `¿Borrar «${conversation.name}» y su contexto de IA? Se eliminarán los mensajes de este chat. Esta acción no borra ni deshace pedidos, contactos u otros registros creados desde él.`,
            confirmLabel: "Borrar conversación",
            cancelLabel: "Cancelar",
            cancel: () => {},
            confirm: async () => {
                this.state.busy = true;
                const dismiss = this.notification.add("Borrando la conversación y su contexto… Puede tardar si tiene muchos mensajes o adjuntos.", { sticky: true });
                try {
                    await this.orm.call("mail.channel", "odooclaw_delete_conversation", [[conversation.id]]);
                    this.forgetConversation(conversation.id);
                    await this.loadConversations();
                    this.notification.add("Conversación borrada.", { type: "success" });
                } finally {
                    dismiss();
                    this.state.busy = false;
                }
            },
        });
    }
}
OdooClawConversations.template = "mail_bot_odooclaw.Conversations";
OdooClawConversations.components = { Dropdown, DropdownItem };
registry.category("systray").add("mail_bot_odooclaw.conversations", {
    Component: OdooClawConversations,
}, { sequence: 25 });
