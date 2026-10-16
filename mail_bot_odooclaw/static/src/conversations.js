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
        this.employeeSelectionVersion = 0;
        const user = useService("user");
        this.employeeStorageKey = `odooclaw_selected_employee_id:${user.db.name}:${user.userId}`;

        let savedEmpId = "";
        try {
            const raw = sessionStorage.getItem(this.employeeStorageKey);
            if (raw) {
                savedEmpId = parseInt(raw, 10) || "";
            }
        } catch (_) {}

        this.state = useState({
            conversations: [],
            busy: false,
            switchingEmployee: false,
            employees: [],
            employeeRequired: false,
            employeesLoaded: false,
            selectedEmployeeId: savedEmpId,
        });

        onMounted(async () => {
            await this.loadEmployees();
            await this.reconcileOpenConversations();
            if (this.state.employeeRequired) {
                await this.closeOperatorConversations();
            }
        });
    }

    async loadEmployees() {
        try {
            const selector = await this.orm.call("mail.channel", "odooclaw_employee_selector", []);
            this.state.employees = selector.employees || [];
            this.state.employeeRequired = selector.required;
            this.state.employeesLoaded = true;
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
        if (this.state.selectedEmployeeId === val) {
            return;
        }
        const previous = this.state.selectedEmployeeId;
        const version = ++this.employeeSelectionVersion;
        this.state.selectedEmployeeId = val;
        this.state.conversations = [];
        this.state.switchingEmployee = true;
        try {
            try {
                await this.closeOperatorConversations();
            } catch (error) {
                if (version === this.employeeSelectionVersion) {
                    this.state.selectedEmployeeId = previous;
                }
                throw error;
            }
            if (version !== this.employeeSelectionVersion) {
                return;
            }
            try {
                if (val) {
                    sessionStorage.setItem(this.employeeStorageKey, String(val));
                } else {
                    sessionStorage.removeItem(this.employeeStorageKey);
                }
            } catch (_) {}
            await this.loadConversations();
        } finally {
            if (version === this.employeeSelectionVersion) {
                this.state.switchingEmployee = false;
            }
        }
    }

    async closeOperatorConversations() {
        await this.messagingService.modelManager.messagingCreatedPromise;
        const messaging = this.messagingService.modelManager.messaging;
        await messaging.initializedPromise;
        const windows = [...messaging.chatWindowManager.chatWindows];
        const ids = [...new Set(windows.map(window => window.thread)
            .filter(thread => thread && thread.model === "mail.channel")
            .map(thread => thread.id))];
        const aiIds = new Set(ids.length ? await this.orm.call(
            "mail.channel", "odooclaw_accessible_channel_ids", [ids], { odooclaw_only: true }
        ) : []);
        for (const window of windows) {
            const thread = window.thread;
            if (!thread || !(thread.odooclaw_conversation || aiIds.has(thread.id))) {
                continue;
            }
            // Restore missing metadata so delayed native notifications cannot reopen it.
            thread.update({ odooclaw_conversation: true });
            messaging.chatWindowManager.closeThread(thread, { notifyServer: false });
        }
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
        if (!this.state.employeesLoaded) {
            await this.loadEmployees();
        }
        const empId = this.state.selectedEmployeeId || null;
        const conversations = await this.orm.call(
            "mail.channel", "odooclaw_list_conversations", [empId]
        );
        // A slow response for the previous operator must not replace this list.
        if ((this.state.selectedEmployeeId || null) === empId) {
            this.state.conversations = conversations;
        }
    }

    async newConversation() {
        if (this.state.busy || this.state.switchingEmployee) {
            return;
        }
        if (!this.state.employeesLoaded) {
            await this.loadEmployees();
        }
        if (!this.state.employeesLoaded) {
            this.notification.add("No se ha podido comprobar el operario. Inténtalo de nuevo.", { type: "warning" });
            return;
        }
        if (this.state.employeeRequired && !this.state.selectedEmployeeId) {
            this.notification.add("Por favor, selecciona tu nombre de operario antes de abrir una nueva conversación.", { type: "warning" });
            return;
        }
        this.state.busy = true;
        const selectionVersion = this.employeeSelectionVersion;
        try {
            const empId = this.state.selectedEmployeeId || null;
            const channel = await this.orm.call("mail.channel", "odooclaw_new_conversation", [empId]);
            await this.openConversation(channel.id, channel, selectionVersion);
        } finally {
            this.state.busy = false;
        }
    }

    async openConversation(id, channelData, selectionVersion = this.employeeSelectionVersion) {
        if (this.state.switchingEmployee || selectionVersion !== this.employeeSelectionVersion) {
            return;
        }
        await this.messagingService.modelManager.messagingCreatedPromise;
        const messaging = this.messagingService.modelManager.messaging;
        await messaging.initializedPromise;
        // The employee is per tab, never a mutable shared user/server setting.
        const data = channelData || await this.orm.call(
            "mail.channel", "odooclaw_open_conversation", [[id], this.state.selectedEmployeeId || null]
        );
        if (!data) {
            this.forgetConversation(id);
            await this.loadConversations();
            this.notification.add("Esta conversación ya no está disponible.", { type: "info" });
            return;
        }
        if (this.state.switchingEmployee || selectionVersion !== this.employeeSelectionVersion) {
            return;
        }
        const Thread = messaging.models["Thread"];
        const thread = Thread.insert(Thread.convertData({ model: "mail.channel", ...data }));
        // Discuss suppresses floating windows. Leave it only when necessary;
        // opening from a business screen keeps that screen and its draft intact.
        if (messaging.discuss.discussView && !messaging.device.isSmall) {
            await this.action.doAction({ type: "ir.actions.client", tag: "menu" });
        }
        if (this.state.switchingEmployee || selectionVersion !== this.employeeSelectionVersion) {
            return;
        }
        messaging.chatWindowManager.openThread(thread, {
            odooclawExplicit: true,
            notifyServer: false,
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
