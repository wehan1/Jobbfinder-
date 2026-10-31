/*
 * Jarvis — Obsidian front door.
 *
 * This plugin holds NO memory of its own. It sends requests to the same Jarvis
 * server the web app uses, and that server reads/writes this vault's folder on
 * disk. Obsidian sees every note the server writes because they are just files
 * in the vault. On load we check the server's vault path matches this vault;
 * if it doesn't, the two front doors would have split memories, so we warn loudly.
 */
import {
  App, FileSystemAdapter, ItemView, Notice, Plugin, PluginSettingTab,
  Setting, WorkspaceLeaf, requestUrl,
} from "obsidian";

const VIEW_TYPE = "jarvis-chat";

interface JarvisSettings {
  serverUrl: string;
  token: string;
  speak: boolean;
}
const DEFAULTS: JarvisSettings = { serverUrl: "http://127.0.0.1:8765", token: "", speak: false };

interface JarvisResult {
  reply: string;
  tier: number;
  model: string;
  skill: string;
  escalated: boolean;
  latency_ms: number;
  route: { reason: string };
  sources: { path: string; date: string }[];
  saved: string[];
  audio_b64?: string | null;
}

export default class JarvisPlugin extends Plugin {
  settings: JarvisSettings = { ...DEFAULTS };
  vaultMismatch = "";

  async onload() {
    this.settings = { ...DEFAULTS, ...(await this.loadData()) };
    this.registerView(VIEW_TYPE, (leaf) => new JarvisView(leaf, this));
    this.addRibbonIcon("bot", "Open Jarvis", () => this.openView());
    this.addSettingTab(new JarvisSettingTab(this.app, this));

    this.addCommand({ id: "open", name: "Open chat", callback: () => this.openView() });
    this.addCommand({
      id: "ask-about-note", name: "Ask about the current note",
      checkCallback: (checking) => {
        const file = this.app.workspace.getActiveFile();
        if (!file) return false;
        if (!checking) this.openView().then((v) => v?.focusWithContext(file.path));
        return true;
      },
    });
    for (const skill of ["research", "repurpose", "qa"]) {
      this.addCommand({
        id: `skill-${skill}-selection`, name: `Run /${skill} on selection`,
        editorCallback: async (editor) => {
          const sel = editor.getSelection().trim();
          if (!sel) return new Notice("Select some text first");
          const view = await this.openView();
          view?.send(`/${skill} ${sel}`);
        },
      });
    }
    this.app.workspace.onLayoutReady(() => this.checkVault());
  }

  async openView(): Promise<JarvisView | null> {
    let leaf = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      const right = this.app.workspace.getRightLeaf(false);
      if (!right) return null;
      leaf = right;
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    this.app.workspace.revealLeaf(leaf);
    return leaf.view instanceof JarvisView ? leaf.view : null;
  }

  async api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
    const res = await requestUrl({
      url: this.settings.serverUrl.replace(/\/$/, "") + path,
      method,
      headers: {
        "Content-Type": "application/json",
        ...(this.settings.token ? { Authorization: `Bearer ${this.settings.token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      throw: false,
    });
    if (res.status >= 400) throw new Error(res.json?.error ?? `HTTP ${res.status}`);
    return res.json as T;
  }

  /** The non-negotiable invariant: one vault, one memory. */
  async checkVault() {
    try {
      const h = await this.api<{ vault: string }>("/api/health");
      const adapter = this.app.vault.adapter;
      const local = adapter instanceof FileSystemAdapter ? adapter.getBasePath() : "";
      const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
      this.vaultMismatch = local && norm(local) !== norm(h.vault)
        ? `Jarvis server is using a different vault (${h.vault}) than this one (${local}). ` +
          `Set JARVIS_VAULT="${local}" and restart the server, or the web app and Obsidian will have separate memories.`
        : "";
      if (this.vaultMismatch) new Notice(this.vaultMismatch, 15000);
    } catch (e) {
      this.vaultMismatch = `Can't reach Jarvis at ${this.settings.serverUrl}: ${(e as Error).message}`;
    }
    this.app.workspace.getLeavesOfType(VIEW_TYPE).forEach((l) => (l.view as JarvisView).renderWarning());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
}

class JarvisView extends ItemView {
  plugin: JarvisPlugin;
  log!: HTMLElement;
  input!: HTMLTextAreaElement;
  warn!: HTMLElement;
  contextPath: string | null = null;
  history: { role: string; content: string }[] = [];

  constructor(leaf: WorkspaceLeaf, plugin: JarvisPlugin) {
    super(leaf);
    this.plugin = plugin;
  }
  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "Jarvis"; }
  getIcon() { return "bot"; }

  async onOpen() {
    const root = this.contentEl;
    root.empty();
    root.addClass("jarvis-view");
    this.warn = root.createDiv({ cls: "jarvis-warn" });
    this.log = root.createDiv({ cls: "jarvis-log" });
    const bar = root.createDiv({ cls: "jarvis-input" });
    this.input = bar.createEl("textarea", { attr: { placeholder: "Ask Jarvis… (/research, /repurpose, /qa, /deep, /code)" } });
    const btn = bar.createEl("button", { text: "Send", cls: "mod-cta" });
    btn.onclick = () => this.send(this.input.value);
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(this.input.value); }
    });
    this.renderWarning();
  }

  renderWarning() {
    if (!this.warn) return;
    this.warn.setText(this.plugin.vaultMismatch);
  }

  focusWithContext(path: string) {
    this.contextPath = path;
    this.input.placeholder = `Ask about ${path}…`;
    this.input.focus();
  }

  private bubble(cls: string, text: string): HTMLElement {
    const el = this.log.createDiv({ cls: `jarvis-msg ${cls}`, text });
    el.scrollIntoView({ block: "end" });
    return el;
  }

  async send(raw: string) {
    const text = raw.trim();
    if (!text) return;
    this.input.value = "";
    this.bubble("you", text);
    const pending = this.bubble("jarvis", "…");
    try {
      const r = await this.plugin.api<JarvisResult>("/api/chat", "POST", {
        text, source: "obsidian", history: this.history.slice(-10),
        context_path: this.contextPath, speak: this.plugin.settings.speak,
      });
      pending.setText(r.reply);
      const meta = pending.createDiv({ cls: "jarvis-meta" });
      meta.appendText(`tier ${r.tier}${r.escalated ? " ↑" : ""} · ${r.model}${r.skill ? " · skill " + r.skill : ""} · ${r.route.reason} · ${r.latency_ms}ms`);
      const links = [...r.saved.map((p) => ["saved", p]), ...r.sources.map((s) => ["note", s.path])];
      for (const [kind, p] of links) {
        meta.createEl("br");
        const a = meta.createEl("a", { text: `${kind}: ${p}` });
        a.onclick = () => this.app.workspace.openLinkText(p, "", false);
      }
      if (r.audio_b64) new Audio(`data:audio/wav;base64,${r.audio_b64}`).play().catch(() => {});
      this.history.push({ role: "user", content: text }, { role: "assistant", content: r.reply });
    } catch (e) {
      pending.setText(`⚠ ${(e as Error).message}`);
    }
    this.contextPath = null;
    this.input.placeholder = "Ask Jarvis…";
  }
}

class JarvisSettingTab extends PluginSettingTab {
  plugin: JarvisPlugin;
  constructor(app: App, plugin: JarvisPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    new Setting(containerEl).setName("Server URL").setDesc("Where `python -m jarvis serve` is running.")
      .addText((t) => t.setValue(this.plugin.settings.serverUrl).onChange(async (v) => {
        this.plugin.settings.serverUrl = v.trim(); await this.plugin.saveSettings();
      }));
    new Setting(containerEl).setName("API token").setDesc("JARVIS_TOKEN, if the server requires one.")
      .addText((t) => { t.inputEl.type = "password"; t.setValue(this.plugin.settings.token).onChange(async (v) => {
        this.plugin.settings.token = v.trim(); await this.plugin.saveSettings();
      }); });
    new Setting(containerEl).setName("Speak replies").setDesc("Play replies with local Kokoro TTS.")
      .addToggle((t) => t.setValue(this.plugin.settings.speak).onChange(async (v) => {
        this.plugin.settings.speak = v; await this.plugin.saveSettings();
      }));
    new Setting(containerEl).setName("Check vault").setDesc("Verify the server uses this same vault.")
      .addButton((b) => b.setButtonText("Check").onClick(async () => {
        await this.plugin.checkVault();
        new Notice(this.plugin.vaultMismatch || "✓ Jarvis server is using this vault.");
      }));
  }
}
