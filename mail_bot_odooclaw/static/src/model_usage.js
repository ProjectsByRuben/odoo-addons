/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registerPatch } from "@mail/model/model_core";
import { attr } from "@mail/model/model_field";
import { registerMessagingComponent } from "@mail/utils/messaging_component";

registerPatch({
    name: "Thread",
    fields: { odooclawUsageEnabled: attr({ default: false }) },
    modelMethods: {
        convertData(data) {
            const result = this._super(data);
            if ("odooclawUsageEnabled" in data) {
                result.odooclawUsageEnabled = data.odooclawUsageEnabled;
            }
            return result;
        },
    },
});

export class OdooClawModelUsage extends Component {
    setup() {
        this.orm = useService("orm");
        this.state = useState({ available: false, windows: [], loaded: false });
        this.alive = true;
        onMounted(() => this.refresh());
        onWillUnmount(() => {
            this.alive = false;
            clearTimeout(this.timer);
        });
    }

    async refresh() {
        try {
            const usage = await this.orm.call("mail.channel", "odooclaw_model_usage", [[this.props.channelId]]);
            if (this.alive) {
                this.state.available = Boolean(usage.available);
                this.state.windows = usage.windows || [];
            }
        } catch {
            if (this.alive) {
                this.state.available = false;
                this.state.windows = [];
            }
        } finally {
            if (this.alive) {
                this.state.loaded = true;
                this.timer = setTimeout(() => this.refresh(), 60000);
            }
        }
    }

    label(window) {
        const minutes = window.duration_minutes;
        if (minutes === 10080) { return "Semana"; }
        if (minutes >= 1440 && minutes % 1440 === 0) { return `${minutes / 1440} d`; }
        if (minutes >= 60 && minutes % 60 === 0) { return `${minutes / 60} h`; }
        return `${minutes} min`;
    }

    color(window) {
        return window.remaining <= 10 ? "low" : window.remaining <= 25 ? "warning" : "normal";
    }

    get title() {
        const heading = "Uso restante de la cuenta de Codex compartida por OdooClaw. Actualización cada minuto.";
        if (!this.state.available) { return `${heading}\nEl proveedor no ha devuelto el saldo. Se consultará de nuevo automáticamente.`; }
        return heading + "\n" + this.state.windows.map(window =>
            `${this.label(window)}: ${Math.floor(window.remaining)} % disponible. Se renueva ${new Date(window.resets_at * 1000).toLocaleString()}.`
        ).join("\n");
    }
}
OdooClawModelUsage.template = "mail_bot_odooclaw.ModelUsage";
OdooClawModelUsage.props = { channelId: Number };
registerMessagingComponent(OdooClawModelUsage);
