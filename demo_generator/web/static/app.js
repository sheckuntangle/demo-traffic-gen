const CATEGORY_DISPLAY = {
    app_control: "App Control",
    dns_filter: "DNS Filter",
    geo_ip: "Geo-IP",
    web_filter: "Web Filter",
    dynamic_blocklist: "Dynamic Blocklist",
    security: "Security",
    ip_reputation: "IP Reputation",
    url_reputation: "URL Reputation",
    legitimate: "Legitimate Traffic",
};

const CATEGORY_SCHEMAS = {
    app_control: [
        {key: "ssh_targets", label: "SSH Targets", fields: ["host", "port", "description", "expected"]},
        {key: "web_targets", label: "Web Targets", fields: ["url", "description", "expected"]},
    ],
    dns_filter: [
        {key: "targets", label: "Domains", fields: ["domain", "expected"]},
    ],
    web_filter: [
        {key: "targets", label: "URLs", fields: ["url", "category", "expected"]},
    ],
    dynamic_blocklist: [
        {key: "ip_targets", label: "IP Targets", fields: ["ip", "description", "expected"]},
        {key: "domain_targets", label: "Domain Targets", fields: ["domain", "description", "expected"]},
    ],
    security: [
        {key: "targets", label: "IP Targets", fields: ["ip", "description", "expected"]},
    ],
    ip_reputation: [
        {key: "targets", label: "Malicious IPs", fields: ["ip", "description", "expected"]},
    ],
    url_reputation: [
        {key: "targets", label: "High-Risk URLs", fields: ["url", "description", "expected"]},
    ],
};

const MAX_LOG_LINES = 1000;

const App = {
    ws: null,
    wsRetryDelay: 1000,
    config: {},
    stats: {},
    running: false,
    startTime: null,
    elapsedInterval: null,
    logCount: 0,

    init() {
        this.connectWS();
        this.loadConfig();
        this.loadCategories();
        this.startElapsedTimer();
    },

    // --- WebSocket ---

    connectWS() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        this.ws = new WebSocket(`${proto}//${location.host}/ws`);
        this.ws.onopen = () => {
            this.wsRetryDelay = 1000;
            document.getElementById("disconnect-banner").style.display = "none";
        };
        this.ws.onmessage = (e) => this.handleMessage(JSON.parse(e.data));
        this.ws.onclose = () => this.reconnectWS();
        this.ws.onerror = () => {};
    },

    reconnectWS() {
        document.getElementById("disconnect-banner").style.display = "block";
        setTimeout(() => {
            this.wsRetryDelay = Math.min(this.wsRetryDelay * 1.5, 30000);
            this.connectWS();
        }, this.wsRetryDelay);
    },

    handleMessage(msg) {
        if (msg.type === "log") this.appendLog(msg.data);
        else if (msg.type === "status") this.updateStatus(msg.data);
        else if (msg.type === "stats") this.updateStats(msg.data);
        else if (msg.type === "round_start") this.updateRound(msg.data.round_num);
        else if (msg.type === "round_complete") {
            this.updateRound(msg.data.round_num);
            this.fetchStats();
        }
    },

    // --- Controls ---

    async start() {
        const mode = document.getElementById("mode-select").value;
        await fetch("/api/start", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({mode}),
        });
    },

    async stop() {
        await fetch("/api/stop", {method: "POST"});
    },

    async runCategory(name) {
        const btn = document.querySelector(`[data-run="${name}"]`);
        if (btn) { btn.disabled = true; btn.textContent = "Running..."; }
        try {
            await fetch(`/api/run/${name}`, {method: "POST"});
            this.fetchStats();
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = "Run Now"; }
        }
    },

    // --- Status ---

    updateStatus(data) {
        this.running = data.running;
        this.startTime = data.start_time ? new Date(data.start_time) : null;

        const badge = document.getElementById("status-badge");
        badge.textContent = data.running ? "Running" : "Stopped";
        badge.className = "badge status-badge " + (data.running ? "status-running" : "status-stopped");

        const modeInfo = document.getElementById("mode-info");
        if (data.running && data.mode) {
            const labels = {full: "Full Run", triggers: "Triggers Only", legit: "Legitimate Only"};
            modeInfo.textContent = "Mode: " + (labels[data.mode] || data.mode);
        } else {
            modeInfo.textContent = "";
        }

        document.getElementById("start-btn").disabled = data.running;
        document.getElementById("stop-btn").disabled = !data.running;
        document.getElementById("mode-select").disabled = data.running;

        if (data.round) this.updateRound(data.round);
    },

    updateRound(num) {
        document.getElementById("round-display").textContent = `Round ${num}`;
    },

    startElapsedTimer() {
        this.elapsedInterval = setInterval(() => {
            if (!this.running || !this.startTime) {
                document.getElementById("elapsed-display").textContent = "00:00:00";
                return;
            }
            const secs = Math.floor((Date.now() - this.startTime.getTime()) / 1000);
            const h = String(Math.floor(secs / 3600)).padStart(2, "0");
            const m = String(Math.floor((secs % 3600) / 60)).padStart(2, "0");
            const s = String(secs % 60).padStart(2, "0");
            document.getElementById("elapsed-display").textContent = `${h}:${m}:${s}`;
        }, 1000);
    },

    // --- Log ---

    appendLog(entry) {
        const panel = document.getElementById("log-panel");
        const div = document.createElement("div");
        div.className = "log-line";

        const statusClass = entry.status === "PASS" ? "log-pass" : entry.status === "FAIL" ? "log-fail" : "log-info";
        const client = entry.client_name ? `[${entry.client_name}] ` : "";
        const ts = entry.timestamp || "";
        div.innerHTML = `<span class="text-muted">${this.esc(ts)}</span> `
            + `<span class="log-info">${this.esc(client)}</span>`
            + `<span class="log-info">${this.esc(entry.category || "")}</span> | `
            + `${this.esc(entry.target || "")} | `
            + `<span class="${statusClass}">${this.esc(entry.status || "")}</span> `
            + this.esc(entry.message || "");
        panel.appendChild(div);

        this.logCount++;
        while (this.logCount > MAX_LOG_LINES) {
            panel.removeChild(panel.firstChild);
            this.logCount--;
        }

        if (document.getElementById("autoscroll-toggle").checked) {
            panel.scrollTop = panel.scrollHeight;
        }
    },

    clearLog() {
        document.getElementById("log-panel").innerHTML = "";
        this.logCount = 0;
    },

    // --- Stats ---

    async fetchStats() {
        const res = await fetch("/api/stats");
        const data = await res.json();
        this.updateStats(data);
    },

    updateStats(data) {
        this.stats = data;
        const grid = document.getElementById("stats-grid");
        const cats = data.categories || {};

        const allNames = Object.keys(CATEGORY_DISPLAY);
        let html = "";
        for (const name of allNames) {
            const s = cats[name] || {pass: 0, fail: 0};
            const total = s.pass + s.fail;
            const display = CATEGORY_DISPLAY[name] || name;
            const runBtn = `<button class="btn btn-sm btn-outline-light mt-2" data-run="${name}" onclick="App.runCategory('${name}')">Run Now</button>`;

            html += `<div class="card stat-card">
                <div class="card-body text-center p-2">
                    <div class="small text-muted mb-1">${this.esc(display)}</div>
                    <span class="pass-count">${s.pass}</span>
                    <span class="text-muted mx-1">/</span>
                    <span class="fail-count">${s.fail}</span>
                    <div class="total-count small">${total} total</div>
                    ${runBtn}
                </div>
            </div>`;
        }
        grid.innerHTML = html;
    },

    // --- Config ---

    async loadConfig() {
        const res = await fetch("/api/config");
        this.config = await res.json();
        this.renderGeneratorSettings();
        this.loadNetworkInterfaces();
        this.renderClientProfiles();
        this.renderCategoryConfigs();
        this.renderLegitConfig();
    },

    async loadCategories() {
        await this.fetchStats();
    },

    renderGeneratorSettings() {
        const gen = this.config.generator || {};
        const fields = [
            {key: "round_interval_seconds", label: "Trigger Round Interval (seconds)", type: "number"},
            {key: "legitimate_interval_seconds", label: "Legitimate Traffic Interval (seconds)", type: "number"},
            {key: "max_rounds", label: "Max Rounds (0 = unlimited)", type: "number"},
            {key: "client_count", label: "Client Count", type: "number"},
            {key: "dns_sample_range", label: "DNS Queries per Round (min-max)", type: "range"},
            {key: "web_sample_range", label: "Web Requests per Round (min-max)", type: "range"},
            {key: "ping_sample_range", label: "Pings per Round (min-max)", type: "range"},
        ];

        let html = "";
        for (const f of fields) {
            const val = gen[f.key];
            if (f.type === "range") {
                const lo = Array.isArray(val) ? val[0] : 0;
                const hi = Array.isArray(val) ? val[1] : 0;
                html += `<div class="col-md-4">
                    <label class="form-label small">${f.label}</label>
                    <div class="d-flex gap-2">
                        <input type="number" class="form-control form-control-sm" data-gen="${f.key}" data-idx="0" value="${lo}">
                        <input type="number" class="form-control form-control-sm" data-gen="${f.key}" data-idx="1" value="${hi}">
                    </div>
                </div>`;
            } else {
                html += `<div class="col-md-4">
                    <label class="form-label small">${f.label}</label>
                    <input type="number" class="form-control form-control-sm" data-gen="${f.key}" value="${val || 0}">
                </div>`;
            }
        }
        document.getElementById("generator-settings").innerHTML = html;
    },

    async saveGenerator() {
        const data = {...this.config.generator};
        document.querySelectorAll("[data-gen]").forEach(el => {
            const key = el.dataset.gen;
            const idx = el.dataset.idx;
            if (idx !== undefined) {
                if (!Array.isArray(data[key])) data[key] = [0, 0];
                data[key][parseInt(idx)] = parseInt(el.value) || 0;
            } else {
                data[key] = parseInt(el.value) || 0;
            }
        });
        await fetch("/api/config/generator", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(data),
        });
        this.config.generator = data;
        this.showToast("Generator settings saved");
    },

    async loadNetworkInterfaces() {
        const res = await fetch("/api/network/interfaces");
        const interfaces = await res.json();
        this.interfaces = interfaces;

        const container = document.getElementById("network-interfaces");
        const ifaceSelect = document.getElementById("add-ip-iface");

        ifaceSelect.innerHTML = "";
        let html = "";

        for (const iface of interfaces) {
            ifaceSelect.innerHTML += `<option value="${this.esc(iface.name)}">${this.esc(iface.name)}</option>`;

            html += `<div class="mb-2"><strong>${this.esc(iface.name)}</strong>`;
            if (iface.addresses.length === 0) {
                html += ` <span class="text-muted small">no IPv4 addresses</span>`;
            } else {
                html += `<div class="d-flex flex-wrap gap-2 mt-1">`;
                for (const addr of iface.addresses) {
                    const isPrimary = iface.addresses.indexOf(addr) === 0;
                    const badge = isPrimary ? "bg-primary" : "bg-info";
                    const removeBtn = isPrimary ? ""
                        : ` <button class="btn btn-sm btn-link text-danger p-0 ms-1" onclick="App.removeIpAlias('${this.esc(iface.name)}', '${this.esc(addr.ip)}', ${addr.prefix})" title="Remove">&times;</button>`;
                    html += `<span class="badge ${badge}">${this.esc(addr.ip)}/${addr.prefix}${removeBtn}</span>`;
                }
                html += `</div>`;
            }
            html += `</div>`;
        }
        container.innerHTML = html;
    },

    parseIpInput(input) {
        input = input.trim();
        const rangeMatch = input.match(/^(\d{1,3}\.\d{1,3}\.\d{1,3}\.)(\d{1,3})-(\d{1,3})$/);
        if (rangeMatch) {
            const base = rangeMatch[1];
            const start = parseInt(rangeMatch[2]);
            const end = parseInt(rangeMatch[3]);
            if (start > end || start < 0 || end > 255) return [];
            const ips = [];
            for (let i = start; i <= end; i++) ips.push(base + i);
            return ips;
        }
        if (/^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(input)) return [input];
        return [];
    },

    async addIpAlias() {
        const iface = document.getElementById("add-ip-iface").value;
        const input = document.getElementById("add-ip-addr").value.trim();
        const prefix = parseInt(document.getElementById("add-ip-prefix").value) || 24;
        if (!input) return;

        const ips = this.parseIpInput(input);
        if (ips.length === 0) {
            this.showToast("Invalid IP or range format");
            return;
        }

        let added = 0;
        let lastErr = "";
        for (const ip of ips) {
            const res = await fetch("/api/network/add-ip", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({interface: iface, ip, prefix}),
            });
            if (res.ok) {
                added++;
            } else {
                const err = await res.json();
                lastErr = err.detail || "Failed";
            }
        }

        document.getElementById("add-ip-addr").value = "";
        if (added === ips.length) {
            this.showToast(`Added ${added} IP${added > 1 ? "s" : ""} to ${iface}`);
        } else if (added > 0) {
            this.showToast(`Added ${added}/${ips.length} IPs (last error: ${lastErr})`);
        } else {
            this.showToast(`Error: ${lastErr}`);
        }
        this.loadNetworkInterfaces();
    },

    async removeIpAlias(iface, ip, prefix) {
        const res = await fetch("/api/network/remove-ip", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({interface: iface, ip, prefix}),
        });
        if (res.ok) {
            this.showToast(`Removed ${ip} from ${iface}`);
            this.loadNetworkInterfaces();
        } else {
            const err = await res.json();
            this.showToast(`Error: ${err.detail || "Failed"}`);
        }
    },

    renderClientProfiles() {
        const profiles = this.config.client_profiles || [];
        const container = document.getElementById("client-profiles-config");
        let html = container.querySelector("p").outerHTML;

        html += `<table class="table table-sm target-table" id="table-client-profiles">
            <thead><tr>
                <th>Name</th><th>User Agent</th><th>Viewport</th><th>Timezone</th><th>Source IP</th><th></th>
            </tr></thead><tbody>`;

        for (const p of profiles) {
            const vp = p.viewport ? `${p.viewport.width}x${p.viewport.height}` : "";
            html += `<tr>
                <td><input type="text" class="form-control form-control-sm" data-field="name" value="${this.esc(p.name || "")}"></td>
                <td><input type="text" class="form-control form-control-sm" data-field="user_agent" value="${this.esc(p.user_agent || "")}"></td>
                <td><input type="text" class="form-control form-control-sm" data-field="viewport" value="${this.esc(vp)}" placeholder="1920x1080"></td>
                <td><input type="text" class="form-control form-control-sm" data-field="timezone" value="${this.esc(p.timezone || "")}"></td>
                <td><input type="text" class="form-control form-control-sm" data-field="source_ip" value="${this.esc(p.source_ip || "")}" placeholder="e.g. 10.0.1.101"></td>
                <td><button class="btn btn-sm btn-outline-danger" onclick="this.closest('tr').remove()">X</button></td>
            </tr>`;
        }

        html += `</tbody></table>`;
        html += `<button class="btn btn-sm btn-outline-light mb-2" onclick="App.addClientProfile()">+ Add Profile</button> `;
        html += `<button class="btn btn-primary btn-sm mb-2" onclick="App.saveClientProfiles()">Save Client Profiles</button>`;
        container.innerHTML = html;
    },

    addClientProfile() {
        const tbody = document.querySelector("#table-client-profiles tbody");
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td><input type="text" class="form-control form-control-sm" data-field="name" value=""></td>
            <td><input type="text" class="form-control form-control-sm" data-field="user_agent" value=""></td>
            <td><input type="text" class="form-control form-control-sm" data-field="viewport" value="1920x1080" placeholder="1920x1080"></td>
            <td><input type="text" class="form-control form-control-sm" data-field="timezone" value="America/New_York"></td>
            <td><input type="text" class="form-control form-control-sm" data-field="source_ip" value="" placeholder="e.g. 10.0.1.101"></td>
            <td><button class="btn btn-sm btn-outline-danger" onclick="this.closest('tr').remove()">X</button></td>`;
        tbody.appendChild(tr);
    },

    async saveClientProfiles() {
        const rows = document.querySelectorAll("#table-client-profiles tbody tr");
        const profiles = [];
        rows.forEach(row => {
            const get = (f) => row.querySelector(`[data-field="${f}"]`).value.trim();
            const name = get("name");
            if (!name) return;
            const vpStr = get("viewport");
            const vpParts = vpStr.split("x");
            const viewport = vpParts.length === 2
                ? {width: parseInt(vpParts[0]) || 1920, height: parseInt(vpParts[1]) || 1080}
                : {width: 1920, height: 1080};
            profiles.push({
                name: name,
                user_agent: get("user_agent"),
                viewport: viewport,
                timezone: get("timezone") || "America/New_York",
                locale: "en-US",
                source_ip: get("source_ip") || null,
            });
        });
        await fetch("/api/config/clients", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(profiles),
        });
        this.config.client_profiles = profiles;
        this.showToast("Client profiles saved");
    },

    renderCategoryConfigs() {
        const accordion = document.getElementById("category-accordion");
        const order = ["ip_reputation", "url_reputation", "app_control", "dns_filter", "geo_ip", "web_filter", "dynamic_blocklist", "security"];
        let html = "";

        for (const name of order) {
            const catConfig = this.config.categories?.[name];
            if (!catConfig) continue;
            const display = CATEGORY_DISPLAY[name] || name;
            const schema = CATEGORY_SCHEMAS[name];

            html += `<div class="accordion-item">
                <h2 class="accordion-header">
                    <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#cfg-${name}">
                        ${this.esc(display)}
                        <span class="ms-2 badge ${catConfig.enabled ? 'bg-success' : 'bg-secondary'}">${catConfig.enabled ? 'ON' : 'OFF'}</span>
                    </button>
                </h2>
                <div id="cfg-${name}" class="accordion-collapse collapse">
                    <div class="accordion-body">
                        <div class="form-check mb-3">
                            <input class="form-check-input" type="checkbox" id="enable-${name}" ${catConfig.enabled ? 'checked' : ''}>
                            <label class="form-check-label" for="enable-${name}">Enabled</label>
                        </div>`;

            if (name === "geo_ip") {
                html += this.renderGeoIpConfig(catConfig);
            } else if (schema) {
                for (const section of schema) {
                    const items = catConfig[section.key] || [];
                    html += `<h6>${section.label}</h6>`;
                    html += this.renderTargetTable(name, section.key, section.fields, items);
                }
            }

            html += `<button class="btn btn-primary btn-sm mt-2" onclick="App.saveCategory('${name}')">Save</button>
                    </div>
                </div>
            </div>`;
        }
        accordion.innerHTML = html;
    },

    renderGeoIpConfig(catConfig) {
        const countries = catConfig.countries || {};
        let html = "";
        for (const [country, data] of Object.entries(countries)) {
            html += `<h6>${country.charAt(0).toUpperCase() + country.slice(1)} (${data.expected || ""})</h6>`;
            html += this.renderTargetTable("geo_ip", `countries.${country}.targets`, ["ip", "description"], data.targets || []);
        }
        return html;
    },

    renderTargetTable(catName, sectionKey, fields, items) {
        const tableId = `table-${catName}-${sectionKey.replace(/\./g, '-')}`;
        let html = `<table class="table table-sm target-table mb-2" id="${tableId}">
            <thead><tr>`;
        for (const f of fields) html += `<th>${f}</th>`;
        html += `<th></th></tr></thead><tbody>`;

        for (let i = 0; i < items.length; i++) {
            html += "<tr>";
            for (const f of fields) {
                const val = items[i][f] || "";
                html += `<td><input type="text" class="form-control form-control-sm" data-field="${f}" value="${this.esc(String(val))}"></td>`;
            }
            html += `<td><button class="btn btn-sm btn-outline-danger" onclick="this.closest('tr').remove()">X</button></td></tr>`;
        }

        html += `</tbody></table>`;
        html += `<button class="btn btn-sm btn-outline-light mb-3" onclick="App.addRow('${tableId}', ${JSON.stringify(fields)})">+ Add</button>`;
        return html;
    },

    addRow(tableId, fields) {
        const tbody = document.querySelector(`#${tableId} tbody`);
        let tr = document.createElement("tr");
        for (const f of fields) {
            tr.innerHTML += `<td><input type="text" class="form-control form-control-sm" data-field="${f}" value=""></td>`;
        }
        tr.innerHTML += `<td><button class="btn btn-sm btn-outline-danger" onclick="this.closest('tr').remove()">X</button></td>`;
        tbody.appendChild(tr);
    },

    async saveCategory(name) {
        const catConfig = {...this.config.categories[name]};
        catConfig.enabled = document.getElementById(`enable-${name}`).checked;

        const schema = CATEGORY_SCHEMAS[name];
        if (name === "geo_ip") {
            for (const [country, data] of Object.entries(catConfig.countries || {})) {
                const tableId = `table-geo_ip-countries-${country}-targets`;
                catConfig.countries[country].targets = this.readTable(tableId);
            }
        } else if (schema) {
            for (const section of schema) {
                const tableId = `table-${name}-${section.key.replace(/\./g, '-')}`;
                catConfig[section.key] = this.readTable(tableId);
            }
        }

        await fetch(`/api/config/categories/${name}`, {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(catConfig),
        });
        this.config.categories[name] = catConfig;
        this.showToast(`${CATEGORY_DISPLAY[name]} config saved`);
    },

    readTable(tableId) {
        const table = document.getElementById(tableId);
        if (!table) return [];
        const rows = table.querySelectorAll("tbody tr");
        const items = [];
        rows.forEach(row => {
            const item = {};
            row.querySelectorAll("[data-field]").forEach(input => {
                let val = input.value.trim();
                if (input.dataset.field === "port" && val) val = parseInt(val) || val;
                item[input.dataset.field] = val;
            });
            const hasValue = Object.values(item).some(v => v !== "");
            if (hasValue) items.push(item);
        });
        return items;
    },

    renderLegitConfig() {
        const legit = this.config.legitimate_traffic || {};
        let html = "";

        html += `<h6>DNS Domains (${(legit.dns_domains || []).length})</h6>`;
        html += `<textarea class="form-control form-control-sm mb-2" id="legit-dns" rows="4">${(legit.dns_domains || []).join("\n")}</textarea>`;

        html += `<h6>Web URLs (${(legit.web_urls || []).length})</h6>`;
        html += `<textarea class="form-control form-control-sm mb-2" id="legit-web" rows="4">${(legit.web_urls || []).join("\n")}</textarea>`;

        html += `<h6>Ping Targets</h6>`;
        html += this.renderTargetTable("legit", "ping_targets", ["name", "ip"], legit.ping_targets || []);

        html += `<button class="btn btn-primary btn-sm" onclick="App.saveLegitimate()">Save Legitimate Traffic</button>`;
        document.getElementById("legit-config").innerHTML = html;
    },

    async saveLegitimate() {
        const dns = document.getElementById("legit-dns").value.split("\n").map(s => s.trim()).filter(Boolean);
        const web = document.getElementById("legit-web").value.split("\n").map(s => s.trim()).filter(Boolean);
        const pings = this.readTable("table-legit-ping_targets");

        const data = {dns_domains: dns, web_urls: web, ping_targets: pings};
        await fetch("/api/config/legitimate", {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(data),
        });
        this.config.legitimate_traffic = data;
        this.showToast("Legitimate traffic config saved");
    },

    // --- Utilities ---

    esc(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    },

    showToast(msg) {
        let toast = document.getElementById("save-toast");
        if (!toast) {
            toast = document.createElement("div");
            toast.id = "save-toast";
            toast.style.cssText = "position:fixed;bottom:20px;right:20px;background:#238636;color:#fff;padding:10px 20px;border-radius:6px;z-index:9999;transition:opacity 0.3s";
            document.body.appendChild(toast);
        }
        toast.textContent = msg;
        toast.style.opacity = "1";
        setTimeout(() => { toast.style.opacity = "0"; }, 2000);
    },
};

document.addEventListener("DOMContentLoaded", () => App.init());
