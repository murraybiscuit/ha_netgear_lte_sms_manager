if (!customElements.get("netgear-sms-panel")) {
  class NetgearSMSPanel extends HTMLElement {
    constructor() {
      super();
      this._hass = null;
      this._config = {};
      this._messages = [];
      this._contacts = [];
      this._inboxCount = "?";
      this._available = true;
      this._selected = new Set();
      this._sortCol = null;
      this._sortDir = "asc";
      this._trustedSelected = new Set();
      this._trustedSortCol = null;
      this._trustedSortDir = "asc";
      this._contactForm = null;
      this._editingId = null;
      this._editValues = null;
      this._simNumber = "";
      this._loading = false;
      this._refreshing = false;
      this._status = null;
      this._entityMissing = false;
      this._lastStateKey = undefined;
      this._blurPending = false;
      this._commands = [];
      this._commandForm = null; // null | {name,keywords,entityId,service,replyOk,replyFail,editingId}
    }

    set panel(panel) {
      this._config = panel.config || {};
      if (this._hass) this._applyHass(this._hass);
    }

    set hass(hass) {
      this._hass = hass;
      this._applyHass(hass);
    }

    _applyHass(hass) {
      const entity = this._config.entity;
      if (!entity) return;
      const s = hass.states[entity];

      // Only re-render when our entity actually changes, not on every HA state push
      const stateKey = s ? `${s.state}|${s.last_updated}` : null;
      if (stateKey === this._lastStateKey) return;
      this._lastStateKey = stateKey;

      if (!s) {
        this._entityMissing = true;
        this._render();
        return;
      }
      this._entityMissing = false;
      const msgs = s?.attributes?.messages || [];
      const ids = new Set(msgs.map((m) => m.id));
      this._selected = new Set([...this._selected].filter((id) => ids.has(id)));
      this._messages = msgs;

      const contacts = s?.attributes?.contacts || [];
      const cids = new Set(contacts.map((c) => c.uuid));
      this._trustedSelected = new Set([...this._trustedSelected].filter((id) => cids.has(id)));
      if (this._editingId && !cids.has(this._editingId)) {
        this._editingId = null;
        this._editValues = null;
      }
      this._contacts = contacts;
      this._commands = s?.attributes?.commands || [];
      this._inboxCount = s?.state ?? "?";
      this._available = s?.state !== "unavailable";
      this._simNumber = s?.attributes?.sim_number || "";
      this._render();
    }

    // ── number helpers ───────────────────────────────────────────────────────

    _normalizeNumber(n) { return (n || "").replace(/\D/g, ""); }

    _formatNumber(n) {
      const d = this._normalizeNumber(n);
      if (d.length === 10) return `(${d.slice(0,3)}) ${d.slice(3,6)}-${d.slice(6)}`;
      if (d.length === 11 && d[0] === "1") return `+1 (${d.slice(1,4)}) ${d.slice(4,7)}-${d.slice(7)}`;
      return n || "";
    }

    _isDuplicateNumber(number, excludeUuid = null) {
      const norm = this._normalizeNumber(number);
      if (!norm) return false;
      return this._contacts.some(
        (c) => c.uuid !== excludeUuid && this._normalizeNumber(c.number) === norm
      );
    }

    // ── sorting ──────────────────────────────────────────────────────────────

    _sorted(list, col, dir) {
      if (!col) return [...list];
      return [...list].sort((a, b) => {
        const va = a[col] ?? "", vb = b[col] ?? "";
        if (col === "id") return dir === "asc" ? +va - +vb : +vb - +va;
        const cmp = String(va).toLowerCase().localeCompare(String(vb).toLowerCase());
        return dir === "asc" ? cmp : -cmp;
      });
    }

    _sortIcon(activeCol, col, dir) {
      if (activeCol !== col) return " ⇅";
      return dir === "asc" ? " ↑" : " ↓";
    }

    // ── render ───────────────────────────────────────────────────────────────

    _render() {
      if (!this._hass) return;
      const root = this.shadowRoot || this.attachShadow({ mode: "open" });

      // Don't wipe the DOM while the user is typing — defer until focus leaves
      // Exclude checkboxes: they're instant-state, not text entry, and must render immediately
      const focused = root.activeElement;
      if (focused && (focused.tagName === "TEXTAREA" || (focused.tagName === "INPUT" && focused.type !== "checkbox"))) {
        if (!this._blurPending) {
          this._blurPending = true;
          focused.addEventListener("blur", () => { this._blurPending = false; this._render(); }, { once: true });
        }
        return;
      }
      this._blurPending = false;

      root.innerHTML = "";

      const style = document.createElement("style");
      style.textContent = `
        :host {
          display: block;
          background: var(--primary-background-color);
          min-height: 100%;
        }
        .panel-header {
          background: var(--app-header-background-color, var(--primary-color));
          color: var(--app-header-text-color, white);
          padding: 0 8px 0 0;
          height: 56px;
          display: flex;
          align-items: center;
          font-size: 20px;
          font-weight: 400;
          letter-spacing: 0.01em;
          box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        .panel-header-title {
          flex: 1;
          padding-left: 8px;
        }
        .panel-header ha-menu-button {
          color: var(--app-header-text-color, white);
          display: none;
        }
        @media (max-width: 870px) {
          .panel-header ha-menu-button {
            display: block;
          }
        }
        .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        .panel-content {
          max-width: 1100px;
          margin: 0 auto;
          padding: 24px 20px;
          box-sizing: border-box;
        }
        @media (max-width: 899px) {
          .section { margin-bottom: 16px; }
        }
        @media (min-width: 900px) {
          .panel-content { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: start; }
          .status-bar { grid-column: 1 / -1; }
        }
        .section {
          background: var(--card-background-color);
          border-radius: 8px;
          padding: 16px;
          box-shadow: var(--ha-card-box-shadow, 0 2px 6px rgba(0,0,0,0.1));
        }
        .section-title { font-size: 14px; font-weight: 600; margin-bottom: 4px; color: var(--primary-text-color); }
        .section-desc { font-size: 12px; color: var(--secondary-text-color); margin-bottom: 10px; }

        .action-bar {
          display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
          padding: 4px 0 10px; border-bottom: 1px solid var(--divider-color); margin-bottom: 12px;
        }
        .action-count { font-size: 12px; color: var(--secondary-text-color); flex: 1; min-width: 60px; }

        .status {
          padding: 10px 14px; border-radius: 6px; font-size: 13px;
          display: flex; align-items: center; gap: 8px;
          background: var(--secondary-background-color);
        }
        .status.success { background: var(--success-color, #4caf50); color: white; }
        .status.error   { background: var(--error-color); color: white; }
        .status-text { flex: 1; }
        .status-close {
          background: none; border: none; cursor: pointer; font-size: 16px; line-height: 1;
          color: inherit; opacity: 0.8; padding: 0 2px; flex-shrink: 0;
        }
        .status-close:hover { opacity: 1; }

        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 6px 6px; border-bottom: 1px solid var(--divider-color); }
        th {
          font-weight: 600; font-size: 12px;
          background: var(--table-row-background-color, var(--secondary-background-color));
          user-select: none;
        }
        th.sort { cursor: pointer; }
        th.sort:hover { color: var(--primary-color); }
        th.check { width: 28px; }
        td { user-select: text; }
        td.number { font-weight: 500; font-family: monospace; white-space: nowrap; }
        td.message { color: var(--secondary-text-color); word-break: break-word; }
        td.time { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap; }
        td.check { width: 28px; }
        td.edit-actions { white-space: nowrap; width: 1%; }
        input[type="checkbox"] { cursor: pointer; width: 15px; height: 15px; }
        tr:hover td { background: var(--table-row-alternative-background-color, transparent); }
        tr.editing td { background: var(--secondary-background-color) !important; }
        .unavailable { color: var(--error-color); padding: 12px 0; }
        .no-messages { text-align: center; color: var(--secondary-text-color); padding: 20px; }

        button.cb {
          background: none; border: 1px solid var(--primary-color); border-radius: 4px;
          color: var(--primary-color); cursor: pointer; font-size: 11px; font-weight: 500;
          letter-spacing: 0.05em; text-transform: uppercase; padding: 3px 9px;
          white-space: nowrap; font-family: inherit; line-height: 1.6;
          transition: background 0.15s;
        }
        button.cb:hover:not(:disabled) { background: rgba(var(--rgb-primary-color, 3,169,244), 0.08); }
        button.cb:disabled {
          cursor: default;
          border-color: var(--disabled-text-color, #888);
          color: var(--disabled-text-color, #888);
        }

        .edit-input {
          font-size: 13px; padding: 4px 6px; border: 1px solid var(--primary-color);
          border-radius: 4px; background: var(--card-background-color);
          color: var(--primary-text-color); width: 100%; box-sizing: border-box; min-width: 80px;
        }
        .edit-input.warn { border-color: var(--warning-color, orange); }
        .edit-btns { display: flex; gap: 4px; }

        .contact-form {
          display: flex; gap: 8px; flex-wrap: wrap; align-items: flex-end;
          padding: 10px; margin-bottom: 12px;
          background: var(--secondary-background-color); border-radius: 6px;
        }
        .contact-form label { font-size: 12px; color: var(--secondary-text-color); display: block; margin-bottom: 3px; }
        .contact-form input[type="text"] {
          font-size: 13px; padding: 6px 8px; border: 1px solid var(--divider-color);
          border-radius: 4px; background: var(--card-background-color);
          color: var(--primary-text-color); width: 140px;
        }
        .contact-form input[type="text"]:focus { outline: 1px solid var(--primary-color); }
        .contact-form input[type="text"].warn { border-color: var(--warning-color, orange); }
        .contact-form .welcome-row { display: flex; align-items: center; gap: 6px; font-size: 13px; padding-bottom: 2px; }
        .contact-form .btn-row { display: flex; gap: 6px; align-items: center; padding-bottom: 2px; }
        .dup-warn { font-size: 11px; color: var(--warning-color, orange); margin-top: 2px; }

        .full-width { grid-column: 1 / -1; }

        .command-form {
          display: grid; grid-template-columns: 1fr 1fr; gap: 10px;
          padding: 12px; margin-bottom: 12px;
          background: var(--secondary-background-color); border-radius: 6px;
        }
        .command-form .full { grid-column: 1 / -1; }
        .command-form label { font-size: 12px; color: var(--secondary-text-color); display: block; margin-bottom: 3px; }
        .command-form input, .command-form select {
          width: 100%; box-sizing: border-box; font-size: 13px; padding: 6px 8px;
          border: 1px solid var(--divider-color); border-radius: 4px;
          background: var(--card-background-color); color: var(--primary-text-color);
          font-family: inherit;
        }
        .command-form input:focus, .command-form select:focus { outline: 1px solid var(--primary-color); border-color: var(--primary-color); }
        .command-form .hint { font-size: 11px; color: var(--secondary-text-color); margin-top: 2px; }
        .command-form .entity-name { font-size: 11px; color: var(--primary-color); margin-top: 2px; font-style: italic; }
        .command-form .btn-row { display: flex; gap: 6px; align-items: center; }

        td.cmd-keywords { font-size: 12px; color: var(--secondary-text-color); max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        td.cmd-action { font-family: monospace; font-size: 12px; }
        td.cmd-reply { font-size: 12px; color: var(--secondary-text-color); max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        tr.cmd-disabled td { opacity: 0.45; }
        tr.cmd-disabled td.cmd-toggle { opacity: 1; }
        td.cmd-toggle { width: 32px; text-align: center; }
      `;

      const wrapper = document.createElement("div");

      const header = document.createElement("div");
      header.className = "panel-header";
      const menuBtn = document.createElement("ha-menu-button");
      menuBtn.hass = this._hass;
      menuBtn.narrow = true;
      header.appendChild(menuBtn);
      const headerTitle = document.createElement("span");
      headerTitle.className = "panel-header-title";
      headerTitle.textContent = "Netgear LTE SMS Manager";
      header.appendChild(headerTitle);
      wrapper.appendChild(header);

      const content = document.createElement("div");
      content.className = "panel-content";

      if (this._entityMissing) {
        const bar = document.createElement("div");
        bar.className = "status-bar";
        const s = document.createElement("div");
        s.className = "status error";
        s.innerHTML = `<span class="status-text">Integration not configured — go to Settings › Devices &amp; services › Add Integration › Netgear LTE SMS Manager to set it up.</span>`;
        bar.appendChild(s);
        content.appendChild(bar);
      }

      if (this._status) {
        const bar = document.createElement("div");
        bar.className = "status-bar";
        const s = document.createElement("div");
        s.className = `status ${this._status.cls}`;
        const txt = document.createElement("span");
        txt.className = "status-text";
        txt.textContent = this._status.text;
        s.appendChild(txt);
        const x = document.createElement("button");
        x.className = "status-close";
        x.textContent = "✕";
        x.setAttribute("aria-label", "Dismiss");
        x.onclick = () => { this._status = null; this._render(); };
        s.appendChild(x);
        bar.appendChild(s);
        content.appendChild(bar);
      }

      content.appendChild(this._makeInboxSection());
      content.appendChild(this._makeTrustedSendersSection());

      const cmdSection = this._makeCommandsSection();
      cmdSection.classList.add("full-width");
      content.appendChild(cmdSection);

      wrapper.appendChild(content);
      root.appendChild(style);
      root.appendChild(wrapper);
    }

    // ── inbox section ────────────────────────────────────────────────────────

    _makeInboxSection() {
      const section = document.createElement("div");
      section.className = "section";

      const title = document.createElement("div");
      title.className = "section-title";
      title.textContent = `Inbox (${this._inboxCount})`;
      section.appendChild(title);

      section.appendChild(this._makeActionBar({
        selCount: this._selected.size,
        buttons: [
          {
            label: (n) => n > 0 ? `Delete (${n})` : "Delete",
            disabled: (n) => n === 0 || this._loading,
            onclick: () => this._deleteSelected(),
          },
          {
            label: () => "Add as contact",
            disabled: (n) => n === 0 || this._loading,
            onclick: () => this._openContactFormFromInbox(),
          },
          {
            label: () => this._refreshing ? "Refreshing…" : "↻ Refresh",
            disabled: () => this._loading || this._refreshing,
            onclick: () => this._refresh(),
          },
        ],
      }));

      if (!this._available) {
        const u = document.createElement("div");
        u.className = "unavailable";
        u.textContent = "Modem unavailable — check HA logs";
        section.appendChild(u);
      } else if (this._messages.length === 0) {
        const e = document.createElement("div");
        e.className = "no-messages";
        e.textContent = "Inbox is empty";
        section.appendChild(e);
      } else {
        const inboxWrap = document.createElement("div");
        inboxWrap.className = "table-wrap";
        inboxWrap.appendChild(this._makeInboxTable());
        section.appendChild(inboxWrap);
      }

      return section;
    }

    // ── trusted senders section ──────────────────────────────────────────────

    _makeTrustedSendersSection() {
      const section = document.createElement("div");
      section.className = "section";

      const title = document.createElement("div");
      title.className = "section-title";
      title.textContent = "Trusted senders";
      section.appendChild(title);

      const desc = document.createElement("div");
      desc.className = "section-desc";
      const simLabel = this._simNumber ? this._formatNumber(this._simNumber) : "the modem";
      desc.textContent = `Manage users who can trigger automations via SMS to ${simLabel}. To edit the welcome message: Settings \u203a Devices & services \u203a Integrations \u203a SMS Manager (Configure).`;
      section.appendChild(desc);

      section.appendChild(this._makeActionBar({
        selCount: this._trustedSelected.size,
        buttons: [
          {
            label: () => "+ Add contact",
            disabled: () => this._loading,
            onclick: () => {
              this._editingId = null;
              this._editValues = null;
              this._contactForm = { name: "", number: "", sendWelcome: true };
              this._render();
            },
          },
          {
            label: (n) => n > 0 ? `Send welcome (${n})` : "Send welcome",
            disabled: (n) => n === 0 || this._loading,
            onclick: () => this._sendWelcomeSelected(),
          },
          {
            label: (n) => n > 0 ? `Remove (${n})` : "Remove",
            disabled: (n) => n === 0 || this._loading,
            onclick: () => this._removeSelected(),
          },
        ],
      }));

      if (this._contactForm !== null) section.appendChild(this._makeContactForm());

      if (this._contacts.length === 0 && this._contactForm === null) {
        const empty = document.createElement("div");
        empty.className = "no-messages";
        empty.textContent = "No trusted senders configured";
        section.appendChild(empty);
      } else if (this._contacts.length > 0) {
        const trustedWrap = document.createElement("div");
        trustedWrap.className = "table-wrap";
        trustedWrap.appendChild(this._makeTrustedTable());
        section.appendChild(trustedWrap);
      }

      return section;
    }

    // ── shared action bar ────────────────────────────────────────────────────

    _makeActionBar({ selCount, buttons }) {
      const bar = document.createElement("div");
      bar.className = "action-bar";
      const label = document.createElement("span");
      label.className = "action-count";
      label.textContent = selCount > 0 ? `${selCount} selected` : "Select items";
      bar.appendChild(label);
      for (const btn of buttons) {
        const el = document.createElement("button");
        el.className = "cb";
        el.textContent = typeof btn.label === "function" ? btn.label(selCount) : btn.label;
        el.disabled = typeof btn.disabled === "function" ? btn.disabled(selCount) : btn.disabled;
        el.onclick = btn.onclick;
        bar.appendChild(el);
      }
      return bar;
    }

    // ── inbox table ──────────────────────────────────────────────────────────

    _makeInboxTable() {
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const hr = document.createElement("tr");

      const checkTh = document.createElement("th");
      checkTh.className = "check";
      checkTh.appendChild(this._makeHeaderCheckbox(
        this._messages, this._selected, "id",
        (s) => { this._selected = s; this._render(); }
      ));
      hr.appendChild(checkTh);

      for (const { label, key } of [
        { label: "ID", key: "id" },
        { label: "Sender", key: "sender" },
        { label: "Message", key: "message" },
        { label: "Time", key: "timestamp" },
      ]) {
        const th = document.createElement("th");
        th.className = "sort";
        th.textContent = label + this._sortIcon(this._sortCol, key, this._sortDir);
        th.onclick = () => {
          if (this._sortCol === key) this._sortDir = this._sortDir === "asc" ? "desc" : "asc";
          else { this._sortCol = key; this._sortDir = "asc"; }
          this._render();
        };
        hr.appendChild(th);
      }
      thead.appendChild(hr);
      table.appendChild(thead);

      const tbody = document.createElement("tbody");
      for (const msg of this._sorted(this._messages, this._sortCol, this._sortDir)) {
        const tr = document.createElement("tr");
        const checkTd = document.createElement("td");
        checkTd.className = "check";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = this._selected.has(msg.id);
        cb.onchange = (e) => {
          e.target.checked ? this._selected.add(msg.id) : this._selected.delete(msg.id);
          this._render();
        };
        checkTd.appendChild(cb);
        tr.appendChild(checkTd);
        for (const { text, cls } of [
          { text: String(msg.id), cls: null },
          { text: this._formatNumber(msg.sender) || "(unknown)", cls: "number" },
          { text: msg.message || "(no content)", cls: "message" },
          { text: msg.timestamp ? this._fmtTime(msg.timestamp) : "—", cls: "time" },
        ]) {
          const td = document.createElement("td");
          if (cls) td.className = cls;
          td.textContent = text;
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      return table;
    }

    // ── trusted senders table ────────────────────────────────────────────────

    _makeTrustedTable() {
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const hr = document.createElement("tr");

      const checkTh = document.createElement("th");
      checkTh.className = "check";
      checkTh.appendChild(this._makeHeaderCheckbox(
        this._contacts, this._trustedSelected, "uuid",
        (s) => { this._trustedSelected = s; this._render(); }
      ));
      hr.appendChild(checkTh);

      for (const { label, key } of [
        { label: "Name", key: "name" },
        { label: "Number", key: "number" },
      ]) {
        const th = document.createElement("th");
        th.className = "sort";
        th.textContent = label + this._sortIcon(this._trustedSortCol, key, this._trustedSortDir);
        th.onclick = () => {
          if (this._trustedSortCol === key) this._trustedSortDir = this._trustedSortDir === "asc" ? "desc" : "asc";
          else { this._trustedSortCol = key; this._trustedSortDir = "asc"; }
          this._render();
        };
        hr.appendChild(th);
      }
      hr.appendChild(document.createElement("th"));
      thead.appendChild(hr);
      table.appendChild(thead);

      const tbody = document.createElement("tbody");
      for (const contact of this._sorted(this._contacts, this._trustedSortCol, this._trustedSortDir)) {
        tbody.appendChild(this._makeTrustedRow(contact));
      }
      table.appendChild(tbody);
      return table;
    }

    _makeTrustedRow(contact) {
      const isEditing = this._editingId === contact.uuid;
      const tr = document.createElement("tr");
      if (isEditing) tr.className = "editing";

      const checkTd = document.createElement("td");
      checkTd.className = "check";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = this._trustedSelected.has(contact.uuid);
      cb.disabled = isEditing;
      cb.onchange = (e) => {
        e.target.checked
          ? this._trustedSelected.add(contact.uuid)
          : this._trustedSelected.delete(contact.uuid);
        this._render();
      };
      checkTd.appendChild(cb);
      tr.appendChild(checkTd);

      if (isEditing) {
        const nameTd = document.createElement("td");
        const nameInput = document.createElement("input");
        nameInput.className = "edit-input";
        nameInput.value = this._editValues.name;
        nameInput.placeholder = "Contact name";
        nameInput.oninput = (e) => { this._editValues.name = e.target.value; };
        nameTd.appendChild(nameInput);
        tr.appendChild(nameTd);

        const numTd = document.createElement("td");
        const numInput = document.createElement("input");
        numInput.className = "edit-input";
        numInput.value = this._editValues.number;
        numInput.placeholder = "(111) 111-1111";
        const isDup = this._isDuplicateNumber(this._editValues.number, contact.uuid);
        if (isDup) numInput.classList.add("warn");
        numInput.oninput = (e) => {
          this._editValues.number = e.target.value;
          e.target.classList.toggle("warn", this._isDuplicateNumber(e.target.value, contact.uuid));
        };
        numTd.appendChild(numInput);
        tr.appendChild(numTd);

        const actTd = document.createElement("td");
        actTd.className = "edit-actions";
        const btns = document.createElement("div");
        btns.className = "edit-btns";
        const saveBtn = document.createElement("button");
        saveBtn.className = "cb";
        saveBtn.textContent = "Save";
        saveBtn.disabled = this._loading;
        saveBtn.onclick = () => this._saveEdit(contact.uuid, nameInput, numInput);
        btns.appendChild(saveBtn);
        const cancelBtn = document.createElement("button");
        cancelBtn.className = "cb";
        cancelBtn.textContent = "Cancel";
        cancelBtn.onclick = () => { this._editingId = null; this._editValues = null; this._render(); };
        btns.appendChild(cancelBtn);
        actTd.appendChild(btns);
        tr.appendChild(actTd);
      } else {
        const nameTd = document.createElement("td");
        nameTd.style.fontWeight = "500";
        nameTd.textContent = contact.name;
        tr.appendChild(nameTd);

        const numTd = document.createElement("td");
        numTd.className = "number";
        numTd.textContent = this._formatNumber(contact.number);
        tr.appendChild(numTd);

        const actTd = document.createElement("td");
        actTd.className = "edit-actions";
        const editBtn = document.createElement("button");
        editBtn.className = "cb";
        editBtn.textContent = "Edit";
        editBtn.disabled = this._loading;
        editBtn.onclick = () => {
          this._editingId = contact.uuid;
          this._editValues = { name: contact.name, number: this._formatNumber(contact.number) };
          this._contactForm = null;
          this._render();
        };
        actTd.appendChild(editBtn);
        tr.appendChild(actTd);
      }
      return tr;
    }

    // ── add contact form ─────────────────────────────────────────────────────

    _makeContactForm() {
      const form = document.createElement("div");
      form.className = "contact-form";

      const nameWrap = document.createElement("div");
      const nameLabel = document.createElement("label");
      nameLabel.textContent = "Name";
      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.placeholder = "Contact name";
      nameInput.value = this._contactForm.name;
      nameInput.oninput = (e) => { this._contactForm.name = e.target.value; };
      nameWrap.appendChild(nameLabel);
      nameWrap.appendChild(nameInput);
      form.appendChild(nameWrap);

      const numWrap = document.createElement("div");
      const numLabel = document.createElement("label");
      numLabel.textContent = "Number";
      const numInput = document.createElement("input");
      numInput.type = "text";
      numInput.placeholder = "(111) 111-1111";
      numInput.value = this._contactForm.number;
      const isDup = this._isDuplicateNumber(this._contactForm.number);
      if (isDup) numInput.classList.add("warn");
      numInput.oninput = (e) => {
        this._contactForm.number = e.target.value;
        const dup = this._isDuplicateNumber(e.target.value);
        e.target.classList.toggle("warn", dup);
        const warn = numWrap.querySelector(".dup-warn");
        if (dup && !warn) {
          const w = document.createElement("div");
          w.className = "dup-warn";
          w.textContent = "Number already in trusted senders";
          numWrap.appendChild(w);
        } else if (!dup && warn) warn.remove();
      };
      numWrap.appendChild(numLabel);
      numWrap.appendChild(numInput);
      if (isDup) {
        const warn = document.createElement("div");
        warn.className = "dup-warn";
        warn.textContent = "Number already in trusted senders";
        numWrap.appendChild(warn);
      }
      form.appendChild(numWrap);

      const welcomeRow = document.createElement("div");
      welcomeRow.className = "welcome-row";
      const welcomeCb = document.createElement("input");
      welcomeCb.type = "checkbox";
      welcomeCb.checked = this._contactForm.sendWelcome;
      welcomeCb.onchange = (e) => { this._contactForm.sendWelcome = e.target.checked; };
      const welcomeLabel = document.createElement("label");
      welcomeLabel.textContent = "Send welcome message";
      welcomeRow.appendChild(welcomeCb);
      welcomeRow.appendChild(welcomeLabel);
      form.appendChild(welcomeRow);

      const btnRow = document.createElement("div");
      btnRow.className = "btn-row";
      const saveBtn = document.createElement("button");
      saveBtn.className = "cb";
      saveBtn.textContent = "Save";
      saveBtn.disabled = this._loading || isDup;
      saveBtn.onclick = () => this._saveContact();
      btnRow.appendChild(saveBtn);
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "cb";
      cancelBtn.textContent = "Cancel";
      cancelBtn.onclick = () => { this._contactForm = null; this._render(); };
      btnRow.appendChild(cancelBtn);
      form.appendChild(btnRow);

      return form;
    }

    // ── shared header checkbox ───────────────────────────────────────────────

    _makeHeaderCheckbox(items, selected, idKey, onchange) {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      const total = items.length, sel = selected.size;
      cb.checked = total > 0 && sel === total;
      cb.indeterminate = sel > 0 && sel < total;
      cb.onchange = () => {
        onchange(selected.size === items.length ? new Set() : new Set(items.map((m) => m[idKey])));
      };
      return cb;
    }

    _fmtTime(ts) {
      try { return new Date(ts).toLocaleString(); } catch { return ts; }
    }

    // ── service calls ────────────────────────────────────────────────────────

    _openContactFormFromInbox() {
      const selectedMsgs = this._messages.filter((m) => this._selected.has(m.id));
      const rawNumber = selectedMsgs.length > 0 ? (selectedMsgs[0].sender || "") : "";
      this._editingId = null;
      this._editValues = null;
      this._contactForm = { name: "", number: this._normalizeNumber(rawNumber), sendWelcome: true };
      this._render();
    }

    async _deleteSelected() {
      const ids = [...this._selected];
      if (ids.length === 0) return;
      if (!confirm(`Delete ${ids.length} message(s)?`)) return;
      this._loading = true;
      this._status = { text: `Deleting ${ids.length} message(s)…`, cls: "loading" };
      this._render();
      try {
        await this._hass.callService("netgear_lte_sms_manager", "delete_sms", {
          host: this._config.host || undefined, sms_id: ids,
        });
        this._selected = new Set();
        this._status = { text: "Deleted. Refreshing inbox…", cls: "loading" };
        this._render();
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
        this._status = { text: `Deleted ${ids.length} message(s).`, cls: "success" };
      } catch (err) {
        this._status = { text: `Error: ${err.message}`, cls: "error" };
      }
      this._loading = false;
      this._render();
    }

    async _refresh() {
      this._refreshing = true;
      this._render();
      try {
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
      } catch (err) {
        this._status = { text: `Refresh error: ${err.message}`, cls: "error" };
      }
      this._refreshing = false;
      this._render();
    }

    async _saveContact() {
      const { name, number, sendWelcome } = this._contactForm;
      const digits = this._normalizeNumber(number);
      if (!name.trim()) { this._status = { text: "Name is required.", cls: "error" }; this._render(); return; }
      if (!digits) { this._status = { text: "Phone number contains no digits.", cls: "error" }; this._render(); return; }
      if (this._isDuplicateNumber(number)) { this._status = { text: "That number is already a trusted sender.", cls: "error" }; this._render(); return; }
      this._loading = true;
      this._status = { text: `Adding ${name.trim()}…`, cls: "loading" };
      this._render();
      try {
        await this._hass.callService("netgear_lte_sms_manager", "add_contact", {
          name: name.trim(), number: digits,
          send_welcome: sendWelcome, host: this._config.host || undefined,
        });
        this._contactForm = null;
        this._status = { text: `Added ${name.trim()}.${sendWelcome ? " Welcome message sent." : ""}`, cls: "success" };
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
      } catch (err) {
        this._status = { text: `Error: ${err.message}`, cls: "error" };
      }
      this._loading = false;
      this._render();
    }

    async _saveEdit(uuid, nameInput, numInput) {
      const name = nameInput.value.trim();
      const digits = this._normalizeNumber(numInput.value);
      if (!name) { this._status = { text: "Name is required.", cls: "error" }; this._render(); return; }
      if (!digits) { this._status = { text: "Phone number contains no digits.", cls: "error" }; this._render(); return; }
      if (this._isDuplicateNumber(numInput.value, uuid)) { this._status = { text: "Another contact already uses that number.", cls: "error" }; this._render(); return; }
      this._loading = true;
      this._status = { text: `Saving ${name}…`, cls: "loading" };
      this._render();
      try {
        await this._hass.callService("netgear_lte_sms_manager", "update_contact", { contact_id: uuid, name, number: digits });
        this._editingId = null;
        this._editValues = null;
        this._status = { text: `Saved ${name}.`, cls: "success" };
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
      } catch (err) {
        this._status = { text: `Error: ${err.message}`, cls: "error" };
      }
      this._loading = false;
      this._render();
    }

    async _sendWelcomeSelected() {
      const selected = this._contacts.filter((c) => this._trustedSelected.has(c.uuid));
      if (selected.length === 0) return;
      if (!confirm(`Send welcome message to ${selected.map((c) => c.name).join(", ")}?`)) return;
      this._loading = true;
      this._status = { text: `Sending welcome to ${selected.length} contact(s)…`, cls: "loading" };
      this._render();
      const errors = [];
      for (const contact of selected) {
        try {
          await this._hass.callService("netgear_lte_sms_manager", "send_welcome", {
            number: contact.number, host: this._config.host || undefined,
          });
        } catch (err) { errors.push(`${contact.name}: ${err.message}`); }
      }
      this._status = errors.length > 0
        ? { text: `Some failed: ${errors.join("; ")}`, cls: "error" }
        : { text: `Welcome sent to ${selected.length} contact(s).`, cls: "success" };
      this._loading = false;
      this._render();
    }

    // ── commands section ─────────────────────────────────────────────────────

    _makeCommandsSection() {
      const section = document.createElement("div");
      section.className = "section";

      const title = document.createElement("div");
      title.className = "section-title";
      title.textContent = `SMS Commands (${this._commands.length})`;
      section.appendChild(title);

      const desc = document.createElement("div");
      desc.className = "section-desc";
      desc.textContent = "Define keywords that trusted senders can SMS to trigger Home Assistant actions. Commands are matched in order — put more specific keywords first.";
      section.appendChild(desc);

      const bar = document.createElement("div");
      bar.className = "action-bar";
      const spacer = document.createElement("span");
      spacer.className = "action-count";
      spacer.textContent = "";
      bar.appendChild(spacer);
      const addBtn = document.createElement("button");
      addBtn.className = "cb";
      addBtn.textContent = "+ Add command";
      addBtn.disabled = this._loading || this._commandForm !== null;
      addBtn.onclick = () => {
        this._commandForm = { name: "", keywords: "", entityId: "", service: "", replyOk: "", replyFail: "", editingId: null };
        this._render();
      };
      bar.appendChild(addBtn);
      section.appendChild(bar);

      if (this._commandForm !== null) section.appendChild(this._makeCommandForm());

      if (this._commands.length === 0 && this._commandForm === null) {
        const empty = document.createElement("div");
        empty.className = "no-messages";
        empty.textContent = "No commands configured";
        section.appendChild(empty);
      } else if (this._commands.length > 0) {
        const cmdWrap = document.createElement("div");
        cmdWrap.className = "table-wrap";
        cmdWrap.appendChild(this._makeCommandsTable());
        section.appendChild(cmdWrap);
      }

      return section;
    }

    _makeCommandForm() {
      const f = this._commandForm;
      const isEdit = !!f.editingId;

      // Derive available services for the current entity's domain
      const domain = f.entityId ? f.entityId.split(".")[0] : "";
      const domainSvcs = domain && this._hass.services?.[domain]
        ? Object.keys(this._hass.services[domain]).map((s) => `${domain}.${s}`)
        : [];

      // Friendly name of selected entity
      const entityState = f.entityId && this._hass.states?.[f.entityId];
      const friendlyName = entityState?.attributes?.friendly_name;

      const form = document.createElement("div");
      form.className = "command-form";

      // Name
      const nameWrap = document.createElement("div");
      nameWrap.className = "full";
      const nameLabel = document.createElement("label");
      nameLabel.textContent = "Command name";
      const nameInput = document.createElement("input");
      nameInput.type = "text";
      nameInput.placeholder = "e.g. Lock the front door";
      nameInput.value = f.name;
      const nameHint = document.createElement("div");
      nameHint.className = "hint";
      nameHint.textContent = "Describe the outcome as a short phrase (verb + subject). This appears in HELP replies and is used for AI matching — \u201cLock the front door\u201d is better than \u201clock\u201d.";
      const nameWarn = document.createElement("div");
      nameWarn.className = "hint";
      nameWarn.style.color = "var(--warning-color, orange)";
      nameWarn.style.display = f.name.trim() && !f.name.trim().includes(" ") ? "block" : "none";
      nameWarn.textContent = "Single-word names are harder to match \u2014 try \u201cLock the front door\u201d instead.";
      nameInput.oninput = (e) => {
        this._commandForm.name = e.target.value;
        const v = e.target.value.trim();
        nameWarn.style.display = v && !v.includes(" ") ? "block" : "none";
      };
      nameWrap.appendChild(nameLabel);
      nameWrap.appendChild(nameInput);
      nameWrap.appendChild(nameHint);
      nameWrap.appendChild(nameWarn);
      form.appendChild(nameWrap);

      // Keywords
      const kwWrap = document.createElement("div");
      kwWrap.className = "full";
      const kwLabel = document.createElement("label");
      kwLabel.textContent = "Keywords";
      const kwInput = document.createElement("input");
      kwInput.type = "text";
      kwInput.placeholder = "lock, lock door, lock up";
      kwInput.value = f.keywords;
      kwInput.oninput = (e) => { this._commandForm.keywords = e.target.value; };
      const kwHint = document.createElement("div");
      kwHint.className = "hint";
      kwHint.textContent = "Comma-separated. SMS must contain one of these words/phrases.";
      kwWrap.appendChild(kwLabel);
      kwWrap.appendChild(kwInput);
      kwWrap.appendChild(kwHint);
      form.appendChild(kwWrap);

      // Entity picker
      const entityWrap = document.createElement("div");
      const entityLabel = document.createElement("label");
      entityLabel.textContent = "Entity";
      const entityInput = document.createElement("input");
      entityInput.type = "text";
      entityInput.placeholder = "lock.front_door_smart_lock";
      entityInput.value = f.entityId;
      entityInput.setAttribute("list", "cmd-entity-list");
      entityInput.oninput = (e) => { this._commandForm.entityId = e.target.value; };
      entityInput.onchange = (e) => {
        const newDomain = e.target.value.split(".")[0];
        const oldDomain = (this._commandForm.service || "").split(".")[0];
        if (newDomain !== oldDomain) this._commandForm.service = "";
        this._commandForm.entityId = e.target.value;
        this._render();
      };
      // Datalist of all HA entities
      const dl = document.createElement("datalist");
      dl.id = "cmd-entity-list";
      for (const [eid, state] of Object.entries(this._hass.states || {}).sort()) {
        const opt = document.createElement("option");
        opt.value = eid;
        opt.textContent = state.attributes?.friendly_name || eid;
        dl.appendChild(opt);
      }
      entityWrap.appendChild(entityLabel);
      entityWrap.appendChild(entityInput);
      entityWrap.appendChild(dl);
      if (friendlyName) {
        const fn = document.createElement("div");
        fn.className = "entity-name";
        fn.textContent = friendlyName;
        entityWrap.appendChild(fn);
      }
      form.appendChild(entityWrap);

      // Service/action picker
      const svcWrap = document.createElement("div");
      const svcLabel = document.createElement("label");
      svcLabel.textContent = "Action";
      svcWrap.appendChild(svcLabel);

      if (domainSvcs.length > 0) {
        const svcSelect = document.createElement("select");
        const placeholder = document.createElement("option");
        placeholder.value = "";
        placeholder.textContent = "— select action —";
        svcSelect.appendChild(placeholder);
        for (const svc of domainSvcs) {
          const opt = document.createElement("option");
          opt.value = svc;
          opt.textContent = svc;
          if (svc === f.service) opt.selected = true;
          svcSelect.appendChild(opt);
        }
        svcSelect.onchange = (e) => { this._commandForm.service = e.target.value; };
        svcWrap.appendChild(svcSelect);
      } else {
        const svcInput = document.createElement("input");
        svcInput.type = "text";
        svcInput.placeholder = domain ? `${domain}.???` : "lock.lock";
        svcInput.value = f.service;
        svcInput.oninput = (e) => { this._commandForm.service = e.target.value; };
        const svcHint = document.createElement("div");
        svcHint.className = "hint";
        svcHint.textContent = domain ? `No actions found for domain "${domain}"` : "Select an entity first to see available actions.";
        svcWrap.appendChild(svcInput);
        svcWrap.appendChild(svcHint);
      }
      form.appendChild(svcWrap);

      // Reply OK
      const replyOkWrap = document.createElement("div");
      const replyOkLabel = document.createElement("label");
      replyOkLabel.textContent = "Reply on success";
      const replyOkInput = document.createElement("input");
      replyOkInput.type = "text";
      replyOkInput.placeholder = "Front door locked.";
      replyOkInput.value = f.replyOk;
      replyOkInput.oninput = (e) => { this._commandForm.replyOk = e.target.value; };
      replyOkWrap.appendChild(replyOkLabel);
      replyOkWrap.appendChild(replyOkInput);
      form.appendChild(replyOkWrap);

      // Reply fail
      const replyFailWrap = document.createElement("div");
      const replyFailLabel = document.createElement("label");
      replyFailLabel.textContent = "Reply on failure";
      const replyFailInput = document.createElement("input");
      replyFailInput.type = "text";
      replyFailInput.placeholder = "Failed to lock front door.";
      replyFailInput.value = f.replyFail;
      replyFailInput.oninput = (e) => { this._commandForm.replyFail = e.target.value; };
      replyFailWrap.appendChild(replyFailLabel);
      replyFailWrap.appendChild(replyFailInput);
      form.appendChild(replyFailWrap);

      // Buttons
      const btnRow = document.createElement("div");
      btnRow.className = "full btn-row";
      const saveBtn = document.createElement("button");
      saveBtn.className = "cb";
      saveBtn.textContent = isEdit ? "Save changes" : "Add command";
      saveBtn.disabled = this._loading;
      saveBtn.onclick = () => this._saveCommand(nameInput, kwInput, entityInput, svcWrap);
      btnRow.appendChild(saveBtn);
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "cb";
      cancelBtn.textContent = "Cancel";
      cancelBtn.onclick = () => { this._commandForm = null; this._render(); };
      btnRow.appendChild(cancelBtn);
      form.appendChild(btnRow);

      return form;
    }

    _makeCommandsTable() {
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const hr = document.createElement("tr");
      for (const label of ["On", "Name", "Keywords", "Action", "Reply OK", ""]) {
        const th = document.createElement("th");
        th.textContent = label;
        hr.appendChild(th);
      }
      thead.appendChild(hr);
      table.appendChild(thead);

      const tbody = document.createElement("tbody");
      for (const cmd of this._commands) {
        const enabled = cmd.enabled !== false;
        const tr = document.createElement("tr");
        if (!enabled) tr.classList.add("cmd-disabled");

        const toggleTd = document.createElement("td");
        toggleTd.className = "cmd-toggle";
        const toggleCb = document.createElement("input");
        toggleCb.type = "checkbox";
        toggleCb.checked = enabled;
        toggleCb.disabled = this._loading;
        toggleCb.title = enabled ? "Disable command" : "Enable command";
        toggleCb.onchange = () => this._toggleCommand(cmd);
        toggleTd.appendChild(toggleCb);
        tr.appendChild(toggleTd);

        const nameTd = document.createElement("td");
        nameTd.style.fontWeight = "500";
        nameTd.textContent = cmd.name;
        tr.appendChild(nameTd);

        const kwTd = document.createElement("td");
        kwTd.className = "cmd-keywords";
        kwTd.title = (cmd.keywords || []).join(", ");
        kwTd.textContent = (cmd.keywords || []).join(", ");
        tr.appendChild(kwTd);

        const actTd = document.createElement("td");
        actTd.className = "cmd-action";
        actTd.textContent = `${cmd.service} → ${cmd.entity_id}`;
        tr.appendChild(actTd);

        const replyTd = document.createElement("td");
        replyTd.className = "cmd-reply";
        replyTd.title = cmd.reply_ok || "—";
        replyTd.textContent = cmd.reply_ok || "—";
        tr.appendChild(replyTd);

        const actionsTd = document.createElement("td");
        actionsTd.className = "edit-actions";
        const btnWrap = document.createElement("div");
        btnWrap.className = "edit-btns";

        const testBtn = document.createElement("button");
        testBtn.className = "cb";
        testBtn.textContent = "Test";
        testBtn.title = "Run this command now from the first trusted contact";
        testBtn.disabled = this._loading || this._contacts.length === 0;
        testBtn.onclick = () => this._testCommand(cmd);
        btnWrap.appendChild(testBtn);

        const editBtn = document.createElement("button");
        editBtn.className = "cb";
        editBtn.textContent = "Edit";
        editBtn.disabled = this._loading || this._commandForm !== null;
        editBtn.onclick = () => {
          this._commandForm = {
            name: cmd.name,
            keywords: (cmd.keywords || []).join(", "),
            entityId: cmd.entity_id || "",
            service: cmd.service || "",
            replyOk: cmd.reply_ok || "",
            replyFail: cmd.reply_fail || "",
            editingId: cmd.uuid,
          };
          this._render();
        };
        btnWrap.appendChild(editBtn);

        const delBtn = document.createElement("button");
        delBtn.className = "cb";
        delBtn.textContent = "Delete";
        delBtn.disabled = this._loading;
        delBtn.onclick = () => this._deleteCommand(cmd.uuid, cmd.name);
        btnWrap.appendChild(delBtn);

        actionsTd.appendChild(btnWrap);
        tr.appendChild(actionsTd);
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      return table;
    }

    async _saveCommand(nameInput, kwInput, entityInput, svcWrap) {
      const f = this._commandForm;
      // Read latest input values (in case blur-defer hasn't flushed yet)
      const name = nameInput.value.trim();
      const keywords = kwInput.value.split(",").map((k) => k.trim().toLowerCase()).filter(Boolean);
      const entityId = entityInput.value.trim();
      const svcEl = svcWrap.querySelector("select") || svcWrap.querySelector("input[type=text]");
      const service = svcEl ? svcEl.value.trim() : f.service;

      if (!name) { this._status = { text: "Command name is required.", cls: "error" }; this._render(); return; }
      if (keywords.length === 0) { this._status = { text: "At least one keyword is required.", cls: "error" }; this._render(); return; }
      if (!entityId) { this._status = { text: "Entity is required.", cls: "error" }; this._render(); return; }
      if (!service || !service.includes(".")) { this._status = { text: "A valid action is required (e.g. lock.lock).", cls: "error" }; this._render(); return; }

      this._loading = true;
      this._status = { text: f.editingId ? `Saving "${name}"…` : `Adding "${name}"…`, cls: "loading" };
      this._render();

      try {
        if (f.editingId) {
          await this._hass.callService("netgear_lte_sms_manager", "update_command", {
            command_id: f.editingId,
            name, keywords, service, entity_id: entityId,
            reply_ok: f.replyOk || "", reply_fail: f.replyFail || "",
          });
        } else {
          await this._hass.callService("netgear_lte_sms_manager", "add_command", {
            name, keywords, service, entity_id: entityId,
            reply_ok: f.replyOk || "", reply_fail: f.replyFail || "",
          });
        }
        this._commandForm = null;
        this._status = { text: f.editingId ? `Saved "${name}".` : `Added "${name}".`, cls: "success" };
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
      } catch (err) {
        this._status = { text: `Error: ${err.message}`, cls: "error" };
      }
      this._loading = false;
      this._render();
    }

    async _deleteCommand(uuid, name) {
      if (!confirm(`Delete command "${name}"?`)) return;
      this._loading = true;
      this._status = { text: `Deleting "${name}"…`, cls: "loading" };
      this._render();
      try {
        await this._hass.callService("netgear_lte_sms_manager", "remove_command", { command_id: uuid });
        this._status = { text: `Deleted "${name}".`, cls: "success" };
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
      } catch (err) {
        this._status = { text: `Error: ${err.message}`, cls: "error" };
      }
      this._loading = false;
      this._render();
    }

    async _testCommand(cmd) {
      const sender = this._contacts[0]?.number;
      if (!sender) { this._status = { text: "No trusted contacts — add one first.", cls: "error" }; this._render(); return; }
      const keyword = cmd.keywords?.[0] || cmd.name;
      this._loading = true;
      this._status = { text: `Testing "${cmd.name}" with message "${keyword}"…`, cls: "loading" };
      this._render();
      try {
        await this._hass.callService("netgear_lte_sms_manager", "test_command", {
          message: keyword, sender, send_reply: false,
        });
        this._status = { text: `"${cmd.name}" executed successfully.`, cls: "success" };
      } catch (err) {
        this._status = { text: `Test failed: ${err.message}`, cls: "error" };
      }
      this._loading = false;
      this._render();
    }

    async _toggleCommand(cmd) {
      const currentEnabled = cmd.enabled !== false;
      const newEnabled = !currentEnabled;
      this._loading = true;
      this._render();
      try {
        await this._hass.callService("netgear_lte_sms_manager", "update_command", {
          command_id: cmd.uuid,
          name: cmd.name,
          keywords: cmd.keywords || [],
          service: cmd.service,
          entity_id: cmd.entity_id,
          reply_ok: cmd.reply_ok || "",
          reply_fail: cmd.reply_fail || "",
          enabled: newEnabled,
        });
        this._status = { text: `"${cmd.name}" ${newEnabled ? "enabled" : "disabled"}.`, cls: "success" };
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
      } catch (err) {
        this._status = { text: `Error: ${err.message}`, cls: "error" };
      }
      this._loading = false;
      this._render();
    }

    async _removeSelected() {
      const selected = this._contacts.filter((c) => this._trustedSelected.has(c.uuid));
      if (selected.length === 0) return;
      if (!confirm(`Remove ${selected.map((c) => c.name).join(", ")} from trusted senders?`)) return;
      this._loading = true;
      this._status = { text: `Removing ${selected.length} contact(s)…`, cls: "loading" };
      this._render();
      const errors = [];
      for (const contact of selected) {
        try {
          await this._hass.callService("netgear_lte_sms_manager", "remove_contact", { contact_id: contact.uuid });
        } catch (err) { errors.push(`${contact.name}: ${err.message}`); }
      }
      if (errors.length === 0) this._trustedSelected = new Set();
      this._status = errors.length > 0
        ? { text: `Some failed: ${errors.join("; ")}`, cls: "error" }
        : { text: `Removed ${selected.length} contact(s).`, cls: "success" };
      try {
        await this._hass.callService("homeassistant", "update_entity", { entity_id: this._config.entity });
      } catch (_) {}
      this._loading = false;
      this._render();
    }
  }

  customElements.define("netgear-sms-panel", NetgearSMSPanel);
  console.log("netgear-sms-panel registered");
}
