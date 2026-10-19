/** @odoo-module **/

import {
  Component,
  markup,
  onMounted,
  onPatched,
  onWillPatch,
  onWillStart,
  onWillUnmount,
  useRef,
  useState,
} from "@odoo/owl";
import {ConfirmationDialog} from "@web/core/confirmation_dialog/confirmation_dialog";
import {Dialog} from "@web/core/dialog/dialog";
import {registry} from "@web/core/registry";
import {useService} from "@web/core/utils/hooks";

class RenameDialog extends Component {
  setup() {
    this.state = useState({name: this.props.name, busy: false});
  }
  async save(event) {
    event.preventDefault();
    if (this.state.busy) return;
    this.state.busy = true;
    try {
      if (await this.props.save(this.state.name)) this.props.close();
    } finally {
      this.state.busy = false;
    }
  }
}
RenameDialog.template = "odooclaw_app.Rename";
RenameDialog.components = {Dialog};
RenameDialog.props = {name: String, save: Function, close: Function};

export class Workspace extends Component {
  setup() {
    this.workspace = useService("odooclaw_workspace");
    this.state = useState(this.workspace.state);
    this.user = useService("user");
    this.dialog = useService("dialog");
    this.view = useState({sidebar: false, pin: "", confirmation: ""});
    let detach = null;
    onMounted(() => {
      detach = this.workspace.attach();
    });
    onWillUnmount(() => {
      if (detach) detach();
    });
    const history = useRef("history");
    let scroll = null;
    let lastActive = null;
    onWillPatch(() => {
      const element = history.el;
      scroll = element
        ? {
            top: element.scrollTop,
            height: element.scrollHeight,
            bottom:
              element.scrollHeight - element.scrollTop - element.clientHeight < 100,
          }
        : null;
    });
    onPatched(() => {
      const element = history.el;
      if (element && (!scroll || scroll.bottom || lastActive !== this.state.activeId)) {
        element.scrollTop = element.scrollHeight;
      }
      lastActive = this.state.activeId;
    });
    onWillStart(() => this.workspace.initialize());
  }
  async onEmployeeChange(event) {
    this.view.pin = "";
    this.view.confirmation = "";
    this.state.draft = "";
    await this.workspace.selectEmployee(
      event.target.value ? Number(event.target.value) : ""
    );
  }
  async unlock(event) {
    event.preventDefault();
    const pin = this.view.pin;
    const confirmation = this.view.confirmation;
    this.view.pin = "";
    this.view.confirmation = "";
    await this.workspace.unlock(pin, confirmation);
  }
  html(body) {
    return markup(body);
  }
  onComposerKeydown(event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      this.send(event);
    }
  }
  async send(event) {
    event.preventDefault();
    const draft = this.state.draft;
    if ((await this.workspace.send(draft)) && this.state.draft === draft)
      this.state.draft = "";
  }
  async openConversation(id) {
    this.state.draft = "";
    this.view.sidebar = false;
    await this.workspace.openConversation(id);
  }
  async upload(event) {
    for (const file of event.target.files) await this.workspace.upload(file);
    event.target.value = "";
  }
  removeAttachment(id) {
    this.state.attachments = this.state.attachments.filter(
      (attachment) => attachment.id !== id
    );
  }
  rename(conversation) {
    this.dialog.add(RenameDialog, {
      name: conversation.name,
      save: (name) => this.workspace.renameConversation(conversation.id, name),
    });
  }
  deleteConversation(conversation) {
    this.dialog.add(ConfirmationDialog, {
      title: "Borrar conversación",
      body: `Se borrará «${conversation.name}» y su contexto de IA. Las operaciones realizadas en Odoo se conservan.`,
      confirmLabel: "Borrar conversación",
      confirm: () => this.workspace.deleteConversation(conversation.id),
    });
  }
  usageLabel(quota) {
    const duration = quota.duration_minutes;
    return duration === 10080
      ? "Semana"
      : duration % 60 === 0
      ? `${duration / 60} h`
      : `${duration} min`;
  }
}
Workspace.template = "odooclaw_app.Workspace";
Workspace.props = {floating: {type: Boolean, optional: true}};

export class WorkspaceAction extends Component {
  setup() {
    this.workspace = useService("odooclaw_workspace");
    onMounted(() => {
      this.workspace.state.fullViews++;
    });
    onWillUnmount(() => {
      this.workspace.state.fullViews--;
    });
  }
}
WorkspaceAction.template = "odooclaw_app.Action";
WorkspaceAction.components = {Workspace};
registry.category("actions").add("odooclaw_app.workspace", WorkspaceAction);

class FloatingWorkspace extends Component {
  setup() {
    this.workspace = useService("odooclaw_workspace");
    this.state = useState(this.workspace.state);
  }
}
FloatingWorkspace.template = "odooclaw_app.Floating";
FloatingWorkspace.components = {Workspace};
registry.category("main_components").add("odooclaw_app.Floating", {
  Component: FloatingWorkspace,
});

class WorkspaceLauncher extends Component {
  setup() {
    this.workspace = useService("odooclaw_workspace");
    this.state = useState(this.workspace.state);
  }
}
WorkspaceLauncher.template = "odooclaw_app.Launcher";
registry.category("systray").add(
  "odooclaw_app.Launcher",
  {
    Component: WorkspaceLauncher,
  },
  {sequence: 26}
);
