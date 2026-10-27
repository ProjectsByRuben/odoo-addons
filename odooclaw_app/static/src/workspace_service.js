/** @odoo-module **/

import {reactive} from "@odoo/owl";
import {registry} from "@web/core/registry";

// Profile credentials live only in this client instance, never in browser
// storage, bus notifications, URLs or the native mail window state.
export const workspaceService = {
  dependencies: ["action", "rpc", "user", "company", "router"],
  start(env, {action, rpc: baseRpc, user, router}) {
    const companyIds = () => user?.context.allowed_company_ids;
    const rpc = (route, params) =>
      baseRpc(route, {...params, company_ids: companyIds()});
    const state = reactive({
      recordContext: null,
      recordContextBusy: false,
      contextFilesOpen: false,
      selectedContextFiles: [],
      screenRevision: 0,
      attachments: [],
      uploading: false,
      usage: null,
      draft: "",
      floating: false,
      minimized: false,
      fullViews: 0,
      conversations: [],
      messages: [],
      activeId: null,
      activeName: "",
      loadingMessages: false,
      sending: false,
      hasMore: false,
      ready: false,
      loading: false,
      required: false,
      employees: [],
      employeeId: "",
      profile: null,
      error: "",
      pinBusy: false,
      pinSetup: false,
      modelCatalog: [],
      modelSettings: null,
      modelsAvailable: false,
      modelsLoading: false,
      modelSaving: false,
    });
    // The action manager emits before the router's debounced pushState commits.
    // Invalidate after that commit so OWL reads the new form, not the old URL.
    let screenTimer = null;
    env.bus?.addEventListener("ACTION_MANAGER:UI-UPDATED", () => {
      clearTimeout(screenTimer);
      screenTimer = setTimeout(() => state.screenRevision++, 0);
    });
    env.bus?.addEventListener("ROUTE_CHANGE", () => state.screenRevision++);
    let contextRequest = 0;
    let token = null;
    let revision = null;
    let views = 0;
    let timer = null;
    let polling = false;
    let lastUsage = 0;
    let conversationGeneration = 0;
    let generation = 0;
    let initialization = null;
    let confirmedModelSettings = null;
    const clearProfile = () => {
      generation++;
      contextRequest++;
      state.recordContext = null;
      state.recordContextBusy = false;
      state.selectedContextFiles = [];
      state.contextFilesOpen = false;
      const previous = token;
      token = null;
      state.profile = null;
      state.modelCatalog = [];
      state.modelSettings = null;
      confirmedModelSettings = null;
      state.modelsAvailable = false;
      state.modelsLoading = false;
      state.modelSaving = false;
      state.draft = "";
      state.attachments = [];
      state.uploading = false;
      state.usage = null;
      state.conversations = [];
      state.messages = [];
      state.activeId = null;
      state.activeName = "";
      state.loadingMessages = false;
      state.sending = false;
      conversationGeneration++;
      revision = null;
      state.error = "";
      state.pinBusy = false;
      return previous;
    };
    const revoke = async (previous) => {
      if (previous) {
        try {
          await rpc("/odooclaw/app/lock", {token: previous});
        } catch (_) {
          // An expired/revoked credential is already unusable. Local state was
          // cleared first so no late response can reopen the previous profile.
        }
      }
    };
    const mergeMessages = (result, older) => {
      const messages = new Map(state.messages.map((message) => [message.id, message]));
      for (const message of result.messages) messages.set(message.id, message);
      state.messages = [...messages.values()].sort((a, b) => a.id - b.id);
      if (older || !revision) state.hasMore = result.has_more;
      if (!older) revision = result.revision;
    };
    const service = {
      state,
      currentRecordReference() {
        const controller = action.currentController;
        const hash = router?.current?.hash || {};
        const model = controller?.props?.resModel || controller?.action?.res_model;
        const id = Number(hash.id);
        if (controller?.action?.type !== "ir.actions.act_window" ||
            hash.view_type !== "form" || hash.model !== model ||
            !Number.isSafeInteger(id) || id <= 0) return null;
        return {model, id};
      },
      removeRecordContext() {
        contextRequest++;
        state.recordContext = null;
        state.recordContextBusy = false;
        state.selectedContextFiles = [];
        state.contextFilesOpen = false;
      },
      async addCurrentRecord() {
        const reference = service.currentRecordReference();
        if (!token || !state.activeId || !reference || state.sending || state.recordContextBusy) return;
        const current = generation, conversation = conversationGeneration;
        const requestId = ++contextRequest;
        state.recordContextBusy = true;
        state.error = "";
        try {
          const result = await rpc("/odooclaw/app/record_context", {
            token, channel_id: state.activeId, reference,
          });
          if (current !== generation || conversation !== conversationGeneration || requestId !== contextRequest) return;
          const sameRecord = state.recordContext?.model === result.model &&
            state.recordContext?.id === result.id;
          state.selectedContextFiles = sameRecord
            ? state.selectedContextFiles.filter(id => result.attachments.some(file => file.id === id))
            : [];
          state.contextFilesOpen = sameRecord && result.attachments.length > 0 && state.contextFilesOpen;
          state.recordContext = result;
        } catch (_) {
          if (current === generation && conversation === conversationGeneration && requestId === contextRequest)
            state.error = "No se puede añadir ese registro. Comprueba que está guardado y que tienes acceso.";
        } finally {
          if (requestId === contextRequest) state.recordContextBusy = false;
        }
      },
      toggleContextFile(id) {
        if (state.sending || !state.recordContext?.attachments.some(file => file.id === id)) return;
        const selected = state.selectedContextFiles;
        if (selected.includes(id)) state.selectedContextFiles = selected.filter(value => value !== id);
        else if (selected.length + state.attachments.length < 20) state.selectedContextFiles = [...selected, id];
      },
      async initialize() {
        if (state.ready) return;
        if (initialization) return initialization;
        state.loading = true;
        initialization = (async () => {
          try {
            const data = await rpc("/odooclaw/app/bootstrap", {});
            state.required = data.required;
            state.employees = data.employees;
            state.ready = true;
            if (!state.required) await service.unlock("");
          } catch (_) {
            state.error = "No se ha podido cargar tu perfil. Vuelve a abrir OdooClaw.";
          } finally {
            state.loading = false;
            initialization = null;
          }
        })();
        return initialization;
      },
      async selectEmployee(employeeId) {
        const previous = clearProfile();
        state.employeeId = employeeId;
        state.pinSetup = Boolean(
          state.employees.find((employee) => employee.id === employeeId)
            ?.pin_setup_required
        );
        await revoke(previous);
      },
      async unlock(pin, confirmation = null) {
        if (state.pinBusy) return;
        const current = generation;
        state.pinBusy = true;
        state.error = "";
        try {
          const setup = state.required && state.pinSetup;
          const result = await rpc(
            setup ? "/odooclaw/app/setup_pin" : "/odooclaw/app/unlock",
            {
              employee_id: state.required ? Number(state.employeeId) || null : null,
              pin,
              ...(setup ? {confirmation} : {}),
            }
          );
          if (current !== generation) {
            if (result.ok) await revoke(result.token);
            return;
          }
          if (!result.ok) {
            state.error = result.error;
            if (typeof result.needs_setup === "boolean")
              state.pinSetup = result.needs_setup;
            return;
          }
          token = result.token;
          state.pinSetup = false;
          const employee = state.employees.find((item) => item.id === state.employeeId);
          if (employee) employee.pin_setup_required = false;
          state.profile = result.profile;
          await service.refreshConversations();
        } catch (_) {
          if (current === generation)
            state.error =
              "No se ha podido desbloquear el perfil. Comprueba el operario e inténtalo de nuevo.";
        } finally {
          if (current === generation) state.pinBusy = false;
        }
      },
      attach() {
        views++;
        if (!timer)
          timer = setInterval(async () => {
            if (
              polling ||
              !token ||
              !state.activeId ||
              document.hidden ||
              (state.minimized && !state.fullViews)
            )
              return;
            polling = true;
            try {
              await service.loadMessages();
            } finally {
              polling = false;
            }
          }, 4000);
        return () => {
          if (--views === 0) {
            clearInterval(timer);
            timer = null;
          }
        };
      },
      async refreshConversations() {
        const current = generation;
        const data = await rpc("/odooclaw/app/conversations", {token});
        if (current === generation) state.conversations = data;
      },
      async openConversation(id, {preserveDraft = false} = {}) {
        conversationGeneration++;
        service.removeRecordContext();
        revision = null;
        state.activeId = id;
        state.modelSettings = null;
        confirmedModelSettings = null;
        state.modelCatalog = [];
        state.modelsAvailable = false;
        state.modelsLoading = false;
        state.modelSaving = false;
        if (!preserveDraft) state.draft = "";
        state.attachments = [];
        lastUsage = 0;
        state.activeName =
          state.conversations.find((item) => item.id === id)?.name || "OdooClaw";
        state.messages = [];
        state.hasMore = false;
        state.error = "";
        state.loadingMessages = true;
        await Promise.all([service.loadMessages(), service.loadModels()]);
      },
      async loadModels() {
        const current = generation;
        const id = state.activeId;
        if (!token || !id) return;
        state.modelsLoading = true;
        try {
          const data = await rpc("/odooclaw/app/models", {token, channel_id: id});
          if (current !== generation || id !== state.activeId) return;
          state.modelCatalog = data.catalog.models || [];
          state.modelsAvailable = Boolean(data.catalog.available);
          state.modelSettings = data.settings;
          confirmedModelSettings = {...data.settings};
        } catch (_) {
          if (current === generation && id === state.activeId)
            state.modelsAvailable = false;
        } finally {
          if (current === generation && id === state.activeId)
            state.modelsLoading = false;
        }
      },
      async changeModelSetting(key, value) {
        if (state.modelSaving || !state.modelSettings || !state.modelsAvailable) return;
        const current = generation;
        const id = state.activeId;
        const settings = {...state.modelSettings, [key]: value};
        if (key === "model" && !value) {
          settings.reasoning_effort = "";
          settings.service_tier = "";
        } else {
          const model =
            state.modelCatalog.find((item) => item.id === settings.model) ||
            state.modelCatalog.find((item) => item.is_default);
          if (!model) return;
          settings.model = model.id;
          if (key === "model") {
            settings.reasoning_effort = model.default_reasoning;
            settings.service_tier = "default";
          }
        }
        state.modelSaving = true;
        state.error = "";
        try {
          const saved = await rpc("/odooclaw/app/model_settings", {
            token,
            channel_id: id,
            settings,
          });
          if (current === generation && id === state.activeId) {
            state.modelSettings = saved;
            confirmedModelSettings = {...saved};
          }
        } catch (_) {
          if (current === generation && id === state.activeId) {
            if (confirmedModelSettings)
              state.modelSettings = {...confirmedModelSettings};
            state.error =
              "No se han guardado los ajustes. Comprueba las opciones disponibles e inténtalo de nuevo.";
          }
        } finally {
          if (current === generation && id === state.activeId)
            state.modelSaving = false;
        }
      },
      async loadMessages(older = false) {
        if (!token || !state.activeId) return;
        const current = generation;
        const conversation = conversationGeneration;
        const id = state.activeId;
        try {
          const result = await rpc("/odooclaw/app/messages", {
            token,
            channel_id: id,
            before: older ? state.messages[0]?.id : null,
            revision: older ? null : revision,
          });
          if (current !== generation || conversation !== conversationGeneration) return;
          if (!result.unchanged) mergeMessages(result, older);
          if (Date.now() - lastUsage > 60000) await service.refreshUsage();
        } catch (_) {
          if (current === generation && conversation === conversationGeneration) {
            state.error =
              "No se ha podido cargar el chat. Comprueba tu perfil o vuelve a abrir la conversación.";
          }
        } finally {
          if (current === generation && conversation === conversationGeneration)
            state.loadingMessages = false;
        }
      },
      async newConversation() {
        if (!token || state.loadingMessages || state.sending) return;
        const current = generation;
        state.loadingMessages = true;
        try {
          const item = await rpc("/odooclaw/app/new", {token});
          if (current !== generation) return;
          await service.refreshConversations();
          if (current === generation) await service.openConversation(item.id);
        } catch (_) {
          if (current === generation)
            state.error = "No se ha podido crear la conversación.";
        } finally {
          if (current === generation) state.loadingMessages = false;
        }
      },
      async refreshUsage() {
        const current = generation;
        const id = state.activeId;
        lastUsage = Date.now();
        try {
          const result = await rpc("/odooclaw/app/usage", {token, channel_id: id});
          if (current === generation && id === state.activeId) state.usage = result;
        } catch (_) {
          /* Quota availability does not block the conversation. */
        }
      },
      async upload(file) {
        if (!token || !state.activeId || state.uploading) return;
        if (state.attachments.length >= 20) {
          state.error = "Puedes adjuntar hasta 20 archivos por mensaje.";
          return;
        }
        const current = generation;
        const conversation = conversationGeneration;
        const id = state.activeId;
        if (file.size > 25 * 1024 * 1024) {
          state.error = "Cada archivo puede ocupar hasta 25 MB.";
          return;
        }
        state.uploading = true;
        try {
          const data = new FormData();
          data.set("csrf_token", odoo.csrf_token);
          data.set("company_ids", JSON.stringify(companyIds()));
          data.set("token", token);
          data.set("channel_id", String(id));
          data.set("file", file);
          const response = await fetch("/odooclaw/app/upload", {
            method: "POST",
            body: data,
          });
          if (!response.ok) throw new Error("Upload failed");
          const attachment = await response.json();
          if (current === generation && conversation === conversationGeneration)
            state.attachments.push(attachment);
        } catch (_) {
          if (current === generation)
            state.error =
              "No se ha podido adjuntar el archivo. Comprueba tu perfil y vuelve a intentarlo.";
        } finally {
          if (current === generation) state.uploading = false;
        }
      },
      async download(attachment) {
        if (!token || !state.activeId) return;
        const current = generation;
        const conversation = conversationGeneration;
        try {
          const data = new FormData();
          data.set("csrf_token", odoo.csrf_token);
          data.set("company_ids", JSON.stringify(companyIds()));
          data.set("token", token);
          data.set("channel_id", String(state.activeId));
          data.set("attachment_id", String(attachment.id));
          const response = await fetch("/odooclaw/app/download", {
            method: "POST",
            body: data,
          });
          if (!response.ok) throw new Error("Download failed");
          const blob = await response.blob();
          if (current !== generation || conversation !== conversationGeneration) return;
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = attachment.name;
          link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (_) {
          state.error =
            "No se ha podido descargar el archivo. Comprueba tu perfil y vuelve a intentarlo.";
        }
      },
      async renameConversation(id, name) {
        const current = generation;
        try {
          await rpc("/odooclaw/app/rename", {token, channel_id: id, name});
          if (current === generation) {
            await service.refreshConversations();
            if (state.activeId === id) state.activeName = name;
          }
          return true;
        } catch (_) {
          state.error = "No se ha podido cambiar el nombre de la conversación.";
          return false;
        }
      },
      async deleteConversation(id) {
        const current = generation;
        try {
          await rpc("/odooclaw/app/delete", {token, channel_id: id});
          if (current !== generation) return;
          if (state.activeId === id) {
            conversationGeneration++;
            state.activeId = null;
            state.messages = [];
            state.draft = "";
            state.attachments = [];
          }
          await service.refreshConversations();
        } catch (_) {
          if (current === generation)
            state.error =
              "No se ha podido borrar el chat. Si el agente está trabajando, espera a que termine.";
        }
      },
      async send(body) {
        if (
          !token ||
          (!state.activeId && state.loadingMessages) ||
          state.sending ||
          state.modelSaving ||
          state.uploading ||
          state.recordContextBusy ||
          !(body.trim() || state.attachments.length)
        )
          return false;
        const current = generation;
        let conversation = conversationGeneration;
        state.sending = true;
        state.error = "";
        let requestStarted = false;
        try {
          if (!state.activeId) {
            const item = await rpc("/odooclaw/app/new", {token});
            if (current !== generation || conversation !== conversationGeneration) return false;
            state.conversations = [item, ...state.conversations.filter(chat => chat.id !== item.id)];
            const nextConversation = conversation + 1;
            await service.openConversation(item.id, {preserveDraft: true});
            if (current !== generation || nextConversation !== conversationGeneration || state.activeId !== item.id) return false;
            conversation = nextConversation;
          }
          const recordContext = state.recordContext;
          const contextFiles = [...state.selectedContextFiles];
          requestStarted = true;
          await rpc("/odooclaw/app/send", {
            token,
            channel_id: state.activeId,
            body,
            attachment_ids: state.attachments.map((attachment) => attachment.id),
            record_context: recordContext ? {model: recordContext.model, id: recordContext.id} : null,
            record_attachment_ids: contextFiles,
          });
          if (current === generation && conversation === conversationGeneration)
            state.attachments = [];
          if (current === generation && conversation === conversationGeneration && state.recordContext === recordContext)
            service.removeRecordContext();
          if (current === generation && conversation === conversationGeneration)
            await service.loadMessages();
          return current === generation && conversation === conversationGeneration;
        } catch (_) {
          if (current === generation && conversation === conversationGeneration)
            state.error = requestStarted
              ? "No se ha podido confirmar el envío. Revisa el historial antes de repetirlo."
              : "No se ha podido preparar la conversación. Tu borrador se conserva; vuelve a intentarlo.";
          return false;
        } finally {
          if (current === generation) state.sending = false;
        }
      },
      async lock() {
        await revoke(clearProfile());
      },
      openFloating() {
        state.floating = true;
        state.minimized = false;
      },
      closeFloating() {
        state.floating = false;
        state.minimized = false;
      },
      toggleMinimized() {
        state.minimized = !state.minimized;
      },
      async openApp() {
        await action.doAction("odooclaw_app.action_workspace");
        state.floating = false;
        state.minimized = false;
      },
    };
    return service;
  },
};

registry.category("services").add("odooclaw_workspace", workspaceService);
