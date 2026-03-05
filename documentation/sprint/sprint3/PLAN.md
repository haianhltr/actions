# Sprint 3 — Ops UI (Health Overview + Actions)

**Goal:** Build a minimal Ops UI that displays entity health state from SSOT, surfaces action recommendations from the Actions API, and provides one-click remediation buttons with confirmation dialogs.

**Status:** Not Started
**Depends on:** Sprint 1 complete, Sprint 2 complete (for recommendations), Team 4 SSOT API (health_summary + ownership) — ALREADY LIVE

---

## Pre-Sprint State

- Actions API running at `http://192.168.1.210:31000` with:
  - `POST /actions` — execute restart/scale with RBAC + audit
  - `GET /actions` — list actions with filters
  - `GET /actions/{id}` — action detail
  - `GET /recommendations` — pending recommendations from Kafka events (Sprint 2)
  - Kafka consumer processing `health.transition.v1` events
  - Correlation: actions linked to triggering events
- SSOT API running at `http://192.168.1.210:30900` with:
  - `GET /entities` — list all entities
  - `GET /entities/{entity_id}` — entity detail
  - `GET /health_summary` — health summaries (with `?state=` filter)
  - `GET /health_summary/{entity_id}` — health summary for one entity
  - `GET /ownership/{entity_id}` — ownership info (team, tier, contact)

## Post-Sprint State

- Ops UI served by Nginx at `http://192.168.1.210:31080`
- **Health Overview page** — table of all entities with health state, type, owner, root cause, filters
- **Entity Detail page** — full health info, root cause, recommendations, action buttons, action history
- **Action Confirmation Dialog** — confirm before executing, reason field, shows result
- Auto-refresh every 30s
- Nginx reverse proxy to Actions API and SSOT API (eliminates CORS issues)
- Separate Kubernetes pod (Deployment + NodePort 31080)

---

## Milestones

### Milestone 1 — Create Ops UI project structure + Nginx config

**Status:** [ ] Not Started

Directory structure:
```
apps/ops-ui/
├── index.html          # Health Overview page
├── entity.html         # Entity Detail page
├── css/
│   └── styles.css      # All styles
├── js/
│   ├── config.js       # API URL configuration
│   ├── api.js          # API client (fetch wrappers)
│   └── app.js          # Main application logic
├── nginx.conf          # Nginx configuration
└── Dockerfile          # Nginx container image
```

**`apps/ops-ui/nginx.conf`:**
```nginx
server {
    listen 80;
    server_name _;

    # Static files
    location / {
        root /usr/share/nginx/html;
        index index.html;
    }

    # Reverse proxy to Actions API (same namespace — short name works)
    location /proxy/actions/ {
        proxy_pass http://actions-api:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Reverse proxy to SSOT API (cross-namespace — use FQDN)
    location /proxy/ssot/ {
        proxy_pass http://ssot-api.ssot.svc.cluster.local:8080/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

**`apps/ops-ui/Dockerfile`:**
```dockerfile
FROM nginx:1.25-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/
COPY entity.html /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/
EXPOSE 80
```

**`apps/ops-ui/js/config.js`:**
```javascript
const CONFIG = {
    ACTIONS_API: '/proxy/actions',   // Reverse-proxied to actions-api:8080
    SSOT_API: '/proxy/ssot',         // Reverse-proxied to ssot-api.ssot:8080
    REFRESH_INTERVAL_MS: 30000,      // Auto-refresh every 30 seconds
};
```

**Files to create:**
- `apps/ops-ui/nginx.conf`
- `apps/ops-ui/Dockerfile`
- `apps/ops-ui/js/config.js`

---

### Milestone 2 — API client module

**Status:** [ ] Not Started

**`apps/ops-ui/js/api.js`:**
```javascript
const API = {
    // ── SSOT API calls ──

    async getEntities() {
        const res = await fetch(`${CONFIG.SSOT_API}/entities`);
        if (!res.ok) throw new Error(`Failed to fetch entities: ${res.status}`);
        return res.json();
    },

    async getEntity(entityId) {
        const res = await fetch(`${CONFIG.SSOT_API}/entities/${encodeURIComponent(entityId)}`);
        if (!res.ok) throw new Error(`Failed to fetch entity: ${res.status}`);
        return res.json();
    },

    async getHealthSummaries(state = null) {
        const params = state ? `?state=${state}` : '';
        const res = await fetch(`${CONFIG.SSOT_API}/health_summary${params}`);
        if (!res.ok) throw new Error(`Failed to fetch health summaries: ${res.status}`);
        return res.json();
    },

    async getHealthSummary(entityId) {
        const res = await fetch(
            `${CONFIG.SSOT_API}/health_summary/${encodeURIComponent(entityId)}`
        );
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`Failed to fetch health summary: ${res.status}`);
        return res.json();
    },

    async getOwnership(entityId) {
        const res = await fetch(
            `${CONFIG.SSOT_API}/ownership/${encodeURIComponent(entityId)}`
        );
        if (res.status === 404) return null;
        if (!res.ok) throw new Error(`Failed to fetch ownership: ${res.status}`);
        return res.json();
    },

    // ── Actions API calls ──

    async getRecommendations() {
        const res = await fetch(`${CONFIG.ACTIONS_API}/recommendations`);
        if (!res.ok) throw new Error(`Failed to fetch recommendations: ${res.status}`);
        return res.json();
    },

    async getActions(params = {}) {
        const query = new URLSearchParams(params).toString();
        const res = await fetch(`${CONFIG.ACTIONS_API}/actions?${query}`);
        if (!res.ok) throw new Error(`Failed to fetch actions: ${res.status}`);
        return res.json();
    },

    async executeAction(payload) {
        const res = await fetch(`${CONFIG.ACTIONS_API}/actions`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-User-Team': payload.team || 'app-team',
            },
            body: JSON.stringify({
                entity_id: payload.entity_id,
                action_type: payload.action_type,
                user: payload.user,
                reason: payload.reason || '',
                parameters: payload.parameters || {},
            }),
        });
        return { status: res.status, data: await res.json() };
    },
};
```

**Files to create:**
- `apps/ops-ui/js/api.js`

---

### Milestone 3 — Health Overview page (index.html)

**Status:** [ ] Not Started

**`apps/ops-ui/index.html`:**

Key structure:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ops Console — Health Overview</title>
    <link rel="stylesheet" href="css/styles.css">
</head>
<body>
    <header>
        <h1>Ops Console</h1>
        <div class="header-meta">
            <span id="last-updated">Loading...</span>
            <span id="auto-refresh-indicator" class="badge badge-green">Auto-refresh: ON</span>
        </div>
    </header>

    <div class="filters">
        <select id="filter-state">
            <option value="">All States</option>
            <option value="HEALTHY">HEALTHY</option>
            <option value="DEGRADED">DEGRADED</option>
            <option value="UNHEALTHY">UNHEALTHY</option>
            <option value="UNKNOWN">UNKNOWN</option>
        </select>
        <select id="filter-type">
            <option value="">All Types</option>
        </select>
        <select id="filter-team">
            <option value="">All Teams</option>
        </select>
    </div>

    <table id="health-table">
        <thead>
            <tr>
                <th>Entity</th>
                <th>Type</th>
                <th>Health</th>
                <th>Root Cause</th>
                <th>Owner</th>
                <th>Last Transition</th>
                <th></th>
            </tr>
        </thead>
        <tbody id="health-body">
            <!-- Populated by JavaScript -->
        </tbody>
    </table>

    <script src="js/config.js"></script>
    <script src="js/api.js"></script>
    <script src="js/app.js"></script>
</body>
</html>
```

Features:
- Fetches entities from SSOT `GET /entities` and health summaries from `GET /health_summary`
- Merges data into a single table row per entity
- Color coding: green (`HEALTHY`), yellow (`DEGRADED`), red (`UNHEALTHY`), gray (`UNKNOWN`)
- Filter dropdowns for state, type, and owner team (populated dynamically from data)
- Each entity name links to `entity.html?id=<entity_id>`
- Recommendation badge (icon) on entities with pending recommendations
- Auto-refresh every 30s with "Last updated" timestamp

**Files to create:**
- `apps/ops-ui/index.html`

---

### Milestone 4 — Entity Detail page (entity.html)

**Status:** [ ] Not Started

**`apps/ops-ui/entity.html`:**

Key structure:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Entity Detail</title>
    <link rel="stylesheet" href="css/styles.css">
</head>
<body>
    <header>
        <a href="index.html" class="back-link">&larr; Back to Overview</a>
        <h1 id="entity-title">Entity Detail</h1>
    </header>

    <!-- Entity Metadata -->
    <section id="entity-info" class="card">
        <h2>Entity</h2>
        <dl id="entity-metadata"><!-- name, type, namespace, cluster --></dl>
    </section>

    <!-- Health State -->
    <section id="health-info" class="card">
        <h2>Health State</h2>
        <div id="health-state-display"><!-- state badge + reason + confidence --></div>
    </section>

    <!-- Root Cause -->
    <section id="root-cause" class="card">
        <h2>Root Cause</h2>
        <div id="root-cause-display">
            <!-- root_cause_entity_id link, or "Self" if same as entity -->
        </div>
    </section>

    <!-- Recommendation (if any) -->
    <section id="recommendation" class="card hidden">
        <h2>Recommended Action</h2>
        <div id="recommendation-display">
            <!-- recommended_action + reason from health.transition event -->
        </div>
    </section>

    <!-- Action Buttons -->
    <section id="actions" class="card">
        <h2>Actions</h2>
        <div class="action-buttons">
            <button onclick="confirmAction('restart_deployment')" class="btn btn-warning">
                Restart Deployment
            </button>
            <div class="scale-controls">
                <label for="scale-replicas">Replicas:</label>
                <input type="number" id="scale-replicas" min="0" max="10" value="1">
                <button onclick="confirmAction('scale_deployment')" class="btn btn-warning">
                    Scale Deployment
                </button>
            </div>
        </div>
    </section>

    <!-- Action History -->
    <section id="action-history" class="card">
        <h2>Action History</h2>
        <table id="history-table">
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Action</th>
                    <th>User</th>
                    <th>Status</th>
                    <th>Result</th>
                </tr>
            </thead>
            <tbody id="history-body"><!-- Populated by JS --></tbody>
        </table>
    </section>

    <!-- Confirmation Dialog (Modal) -->
    <div id="confirm-dialog" class="modal hidden">
        <div class="modal-overlay" onclick="cancelAction()"></div>
        <div class="modal-content">
            <h3 id="confirm-title">Confirm Action</h3>
            <p id="confirm-message"></p>
            <div class="form-group">
                <label for="confirm-reason">Reason (optional):</label>
                <input type="text" id="confirm-reason"
                       placeholder="Why are you performing this action?">
            </div>
            <div class="form-group">
                <label for="confirm-user">Your email:</label>
                <input type="text" id="confirm-user" value="engineer@team.com">
            </div>
            <div class="modal-buttons">
                <button onclick="cancelAction()" class="btn btn-cancel">Cancel</button>
                <button onclick="executeConfirmedAction()" class="btn btn-confirm">Confirm</button>
            </div>
            <div id="action-result" class="hidden"></div>
        </div>
    </div>

    <script src="js/config.js"></script>
    <script src="js/api.js"></script>
    <script src="js/app.js"></script>
</body>
</html>
```

Features:
- Reads `?id=<entity_id>` from URL query parameter
- Entity metadata parsed from entity_id format `k8s:{cluster}:{namespace}:{kind}:{name}`
- Health state with color-coded badge + reason text + confidence percentage
- Root cause: if `root_cause_entity_id` differs from `entity_id`, show as clickable link to that entity's detail page
- Recommendation section: shown only if a recommendation exists for this entity, displays recommended action type and reason
- Action buttons: Restart and Scale (with replicas input, bounded 0-10)
- Confirmation dialog: modal overlay with reason field, user email, confirm/cancel buttons
- After action execution: shows success (green) or failure (red) result in the dialog
- Action history: table of recent actions for this entity from `GET /actions?entity_id=X`

**Files to create:**
- `apps/ops-ui/entity.html`

---

### Milestone 5 — Styles + Application logic

**Status:** [ ] Not Started

**`apps/ops-ui/css/styles.css`:**
```css
/* -- Base -- */
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
    background: #1a1a2e;
    color: #e0e0e0;
    line-height: 1.6;
}

/* -- Header -- */
header {
    background: #16213e;
    padding: 1rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #0f3460;
}
header h1 { color: #e94560; font-size: 1.4rem; }
.header-meta { font-size: 0.85rem; color: #888; }

/* -- Health State Colors -- */
.state-healthy   { color: #2ecc71; font-weight: bold; }
.state-degraded  { color: #f39c12; font-weight: bold; }
.state-unhealthy { color: #e74c3c; font-weight: bold; }
.state-unknown   { color: #95a5a6; font-weight: bold; }

/* -- Table -- */
table { width: 100%; border-collapse: collapse; margin: 1rem 0; }
th { background: #16213e; padding: 0.75rem 1rem; text-align: left; font-size: 0.85rem; }
td { padding: 0.6rem 1rem; border-bottom: 1px solid #2a2a4a; font-size: 0.9rem; }
tr:hover { background: #1f1f3a; }
a { color: #53a8e2; text-decoration: none; }
a:hover { text-decoration: underline; }

/* -- Filters -- */
.filters { padding: 1rem 2rem; display: flex; gap: 1rem; }
.filters select {
    background: #16213e; color: #e0e0e0; border: 1px solid #0f3460;
    padding: 0.4rem 0.8rem; border-radius: 4px; font-size: 0.85rem;
}

/* -- Cards -- */
.card {
    background: #16213e; border: 1px solid #0f3460; border-radius: 8px;
    padding: 1.2rem; margin: 1rem 2rem;
}
.card h2 { font-size: 1rem; color: #e94560; margin-bottom: 0.8rem; }

/* -- Buttons -- */
.btn {
    padding: 0.5rem 1.2rem; border: none; border-radius: 4px;
    cursor: pointer; font-size: 0.85rem; font-weight: bold;
}
.btn-warning { background: #e94560; color: white; }
.btn-warning:hover { background: #c73e54; }
.btn-cancel  { background: #555; color: white; }
.btn-confirm { background: #2ecc71; color: white; }
.btn-confirm:hover { background: #27ae60; }

/* -- Modal -- */
.modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 1000; }
.modal-overlay { position: absolute; width: 100%; height: 100%; background: rgba(0,0,0,0.7); }
.modal-content {
    position: relative; background: #1a1a2e; border: 1px solid #0f3460;
    border-radius: 8px; padding: 2rem; max-width: 500px;
    margin: 10vh auto; z-index: 1001;
}
.modal-buttons { display: flex; gap: 1rem; margin-top: 1.5rem; justify-content: flex-end; }
.form-group { margin: 1rem 0; }
.form-group label { display: block; font-size: 0.85rem; margin-bottom: 0.3rem; }
.form-group input {
    width: 100%; padding: 0.5rem; background: #16213e; color: #e0e0e0;
    border: 1px solid #0f3460; border-radius: 4px;
}

/* -- Utilities -- */
.hidden { display: none !important; }
.badge { padding: 0.2rem 0.6rem; border-radius: 12px; font-size: 0.75rem; }
.badge-green { background: #2ecc71; color: black; }
.badge-red { background: #e74c3c; color: white; }
.action-result-success { border: 2px solid #2ecc71; padding: 1rem; border-radius: 4px; margin-top: 1rem; }
.action-result-failure { border: 2px solid #e74c3c; padding: 1rem; border-radius: 4px; margin-top: 1rem; }

/* -- Scale Controls -- */
.scale-controls { display: inline-flex; gap: 0.5rem; align-items: center; margin-left: 1rem; }
.scale-controls input[type=number] {
    width: 60px; padding: 0.4rem; background: #16213e; color: #e0e0e0;
    border: 1px solid #0f3460; border-radius: 4px; text-align: center;
}
.action-buttons { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; }
.recommendation-badge { color: #f39c12; font-weight: bold; margin-left: 0.5rem; }
.back-link { color: #53a8e2; text-decoration: none; font-size: 0.9rem; }
```

**`apps/ops-ui/js/app.js`:**
```javascript
// ── Health Overview Page ──

async function loadHealthOverview() {
    try {
        const [entities, healthSummaries, recommendations] = await Promise.all([
            API.getEntities(),
            API.getHealthSummaries(),
            API.getRecommendations(),
        ]);

        // Build recommendation lookup by entity_id
        const recsMap = {};
        for (const rec of recommendations) {
            recsMap[rec.entity_id] = rec;
        }

        // Build health lookup by entity_id
        const healthMap = {};
        for (const hs of healthSummaries) {
            healthMap[hs.entity_id] = hs;
        }

        renderHealthTable(entities, healthMap, recsMap);

        document.getElementById('last-updated').textContent =
            'Last updated: ' + new Date().toLocaleTimeString();
    } catch (err) {
        console.error('Failed to load health overview:', err);
    }
}

function renderHealthTable(entities, healthMap, recsMap) {
    const tbody = document.getElementById('health-body');
    const filterState = document.getElementById('filter-state').value;
    const filterType = document.getElementById('filter-type').value;
    const filterTeam = document.getElementById('filter-team').value;

    tbody.innerHTML = '';

    for (const entity of entities) {
        const eid = entity.entity_id || entity.id;
        const health = healthMap[eid] || {};
        const state = health.state || 'UNKNOWN';
        const rec = recsMap[eid];

        // Apply filters
        if (filterState && state !== filterState) continue;
        if (filterType && entity.type !== filterType) continue;
        if (filterTeam && health.owner_team !== filterTeam) continue;

        const stateClass = 'state-' + state.toLowerCase();
        const recBadge = rec ? '<span class="recommendation-badge" title="Recommendation available">[!]</span>' : '';

        const row = document.createElement('tr');
        row.innerHTML = `
            <td><a href="entity.html?id=${encodeURIComponent(eid)}">${entity.name || eid}</a>${recBadge}</td>
            <td>${entity.type || ''}</td>
            <td class="${stateClass}">${state}</td>
            <td>${health.root_cause_entity_id || '-'}</td>
            <td>${health.owner_team || '-'}</td>
            <td>${health.updated_at ? new Date(health.updated_at).toLocaleString() : '-'}</td>
            <td>${rec ? '<a href="entity.html?id=' + encodeURIComponent(eid) + '">Action</a>' : ''}</td>
        `;
        tbody.appendChild(row);
    }
}

// ── Entity Detail Page ──

async function loadEntityDetail(entityId) {
    try {
        const [entity, health, ownership, recommendations, actions] = await Promise.all([
            API.getEntity(entityId),
            API.getHealthSummary(entityId).catch(() => null),
            API.getOwnership(entityId).catch(() => null),
            API.getRecommendations(),
            API.getActions({ entity_id: entityId, limit: 20 }),
        ]);

        // Set page title
        document.getElementById('entity-title').textContent = entity.name || entityId;

        renderEntityInfo(entity, ownership);
        renderHealthInfo(health);
        renderRootCause(health, entityId);

        const rec = recommendations.find(r => r.entity_id === entityId);
        renderRecommendation(rec);

        renderActionHistory(actions);
    } catch (err) {
        console.error('Failed to load entity detail:', err);
    }
}

function renderEntityInfo(entity, ownership) { /* populate #entity-metadata dl */ }
function renderHealthInfo(health) { /* populate #health-state-display with state badge + reason */ }
function renderRootCause(health, entityId) { /* show root cause link or "Self" */ }
function renderRecommendation(rec) { /* show/hide #recommendation section */ }
function renderActionHistory(actions) { /* populate #history-body table */ }

// ── Confirmation Dialog ──

let pendingAction = null;

function confirmAction(actionType) {
    const entityId = new URLSearchParams(window.location.search).get('id');
    const parts = entityId.split(':');
    const name = parts[4] || entityId;
    const ns = parts[2] || '';

    let message = '';
    if (actionType === 'restart_deployment') {
        message = `Are you sure you want to restart Deployment ${name} in namespace ${ns}?`;
    } else if (actionType === 'scale_deployment') {
        const replicas = document.getElementById('scale-replicas').value;
        message = `Are you sure you want to scale Deployment ${name} in namespace ${ns} to ${replicas} replicas?`;
    }

    document.getElementById('confirm-title').textContent = 'Confirm: ' + actionType;
    document.getElementById('confirm-message').textContent = message;
    document.getElementById('action-result').classList.add('hidden');
    document.getElementById('confirm-dialog').classList.remove('hidden');

    pendingAction = { entityId, actionType };
}

function cancelAction() {
    document.getElementById('confirm-dialog').classList.add('hidden');
    pendingAction = null;
}

async function executeConfirmedAction() {
    if (!pendingAction) return;

    const reason = document.getElementById('confirm-reason').value;
    const user = document.getElementById('confirm-user').value;
    const params = {};

    if (pendingAction.actionType === 'scale_deployment') {
        params.replicas = parseInt(document.getElementById('scale-replicas').value, 10);
    }

    try {
        const result = await API.executeAction({
            entity_id: pendingAction.entityId,
            action_type: pendingAction.actionType,
            user: user,
            reason: reason,
            parameters: params,
        });

        const resultDiv = document.getElementById('action-result');
        resultDiv.classList.remove('hidden', 'action-result-success', 'action-result-failure');

        if (result.status === 200) {
            resultDiv.classList.add('action-result-success');
            resultDiv.textContent = 'Success: ' + (result.data.result_message || 'Action completed');
        } else {
            resultDiv.classList.add('action-result-failure');
            resultDiv.textContent = 'Failed: ' + (result.data.detail || JSON.stringify(result.data));
        }

        // Refresh action history
        loadEntityDetail(pendingAction.entityId);
    } catch (err) {
        console.error('Action execution failed:', err);
    }
}

// ── Auto-Refresh ──

let refreshInterval = null;

function startAutoRefresh() {
    refreshInterval = setInterval(() => {
        if (document.getElementById('health-table')) {
            loadHealthOverview();
        }
    }, CONFIG.REFRESH_INTERVAL_MS);
}

// ── Page Initialization ──

document.addEventListener('DOMContentLoaded', () => {
    const params = new URLSearchParams(window.location.search);
    const entityId = params.get('id');

    if (entityId) {
        // Entity detail page
        loadEntityDetail(entityId);
    } else if (document.getElementById('health-table')) {
        // Health overview page
        loadHealthOverview();
        startAutoRefresh();

        // Filter change handlers
        document.getElementById('filter-state').addEventListener('change', loadHealthOverview);
        document.getElementById('filter-type').addEventListener('change', loadHealthOverview);
        document.getElementById('filter-team').addEventListener('change', loadHealthOverview);
    }
});
```

**Files to create:**
- `apps/ops-ui/css/styles.css`
- `apps/ops-ui/js/app.js`

---

### Milestone 6 — Kubernetes deployment manifests

**Status:** [ ] Not Started

**`k8s/ops-ui/deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ops-ui
  namespace: actions
  labels:
    app: ops-ui
    service: ops-ui
    team: team6
    env: production
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ops-ui
  template:
    metadata:
      labels:
        app: ops-ui
        service: ops-ui
        team: team6
        env: production
    spec:
      containers:
        - name: ops-ui
          image: ghcr.io/haianhltr/ops-ui:latest
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /
              port: 80
            initialDelaySeconds: 10
            periodSeconds: 30
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 100m
              memory: 128Mi
```

**`k8s/ops-ui/service.yaml`:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: ops-ui
  namespace: actions
  labels:
    app: ops-ui
    service: ops-ui
    team: team6
spec:
  type: NodePort
  selector:
    app: ops-ui
  ports:
    - port: 80
      targetPort: 80
      nodePort: 31080
      protocol: TCP
```

**Files to create:**
- `k8s/ops-ui/deployment.yaml`
- `k8s/ops-ui/service.yaml`

---

### Milestone 7 — Build, deploy, and smoke test

**Status:** [ ] Not Started

```bash
# 1. Build Ops UI image
cd apps/ops-ui && docker build -t ghcr.io/haianhltr/ops-ui:latest .
docker push ghcr.io/haianhltr/ops-ui:latest

# 2. Deploy to k3s
ssh 5560 "sudo kubectl apply -f k8s/ops-ui/"

# 3. Verify pod is running
ssh 5560 "sudo kubectl get pods -n actions -l app=ops-ui"

# 4. Test UI loads
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.210:31080/
# Should return 200

# 5. Test static assets
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.210:31080/css/styles.css
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.210:31080/js/app.js
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.210:31080/js/config.js
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.210:31080/js/api.js
# All should return 200

# 6. Test reverse proxy to Actions API
curl -s http://192.168.1.210:31080/proxy/actions/health
# Should return Actions API health response

# 7. Test reverse proxy to SSOT API
curl -s http://192.168.1.210:31080/proxy/ssot/entities | python3 -m json.tool | head -20
# Should return SSOT entities list

# 8. Test entity detail page
curl -s -o /dev/null -w "%{http_code}" http://192.168.1.210:31080/entity.html
# Should return 200

# 9. Browser verification (manual):
#    - Navigate to http://192.168.1.210:31080/
#    - Verify: health overview table renders with entity data
#    - Verify: filter dropdowns work
#    - Click an entity → entity detail page loads
#    - Verify: health state, root cause, action buttons visible
#    - Click Restart → confirmation dialog appears
#    - Confirm → action executes → result shown (green = success)
#    - Verify: action appears in action history table
#    - Wait 30s → table auto-refreshes (check "Last updated" timestamp)
```

---

### Milestone 8 — Write E2E tests

**Status:** [ ] Not Started

**`tests/e2e/test_ops_ui.py`:**
```python
import pytest
import httpx

pytestmark = pytest.mark.sprint3

OPS_UI = "http://192.168.1.210:31080"


class TestOpsUIStaticFiles:
    """Verify Nginx serves all static files."""

    def test_index_page_loads(self):
        r = httpx.get(f"{OPS_UI}/")
        assert r.status_code == 200
        assert "Health Overview" in r.text

    def test_entity_page_loads(self):
        r = httpx.get(f"{OPS_UI}/entity.html")
        assert r.status_code == 200
        assert "Entity Detail" in r.text

    @pytest.mark.parametrize("path", [
        "/css/styles.css",
        "/js/config.js",
        "/js/api.js",
        "/js/app.js",
    ])
    def test_static_asset(self, path):
        r = httpx.get(f"{OPS_UI}{path}")
        assert r.status_code == 200, f"Failed to load {path}"


class TestOpsUIProxy:
    """Verify Nginx reverse proxy to backend APIs."""

    def test_proxy_actions_api(self):
        r = httpx.get(f"{OPS_UI}/proxy/actions/health")
        assert r.status_code == 200

    def test_proxy_actions_list(self):
        r = httpx.get(f"{OPS_UI}/proxy/actions/actions?limit=5")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_proxy_ssot_entities(self):
        r = httpx.get(f"{OPS_UI}/proxy/ssot/entities")
        assert r.status_code == 200

    def test_proxy_recommendations(self):
        r = httpx.get(f"{OPS_UI}/proxy/actions/recommendations")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
```

**Files to create:**
- `tests/e2e/test_ops_ui.py`

**Run tests:**
```bash
pytest tests/e2e/test_ops_ui.py -v
```

---

### Milestone 9 — Update docs + write sprint review

**Status:** [ ] Not Started

- Update `documentation/sprint/ROADMAP.md` — mark Sprint 3 as complete
- Write `documentation/sprint/sprint3/REVIEW.md`

**Files to modify:**
- `documentation/sprint/ROADMAP.md`

**Files to create:**
- `documentation/sprint/sprint3/REVIEW.md`

---

## Design Decisions

| Decision | Rationale | Why not X |
|----------|-----------|-----------|
| Vanilla HTML/CSS/JS (no framework) | No build step, no npm/node dependency. Simple to deploy. Sufficient for ops console with ~2 pages. | React/Vue: overkill, adds build complexity and dependency. htmx: viable but adds learning curve for a small project. |
| Nginx for static files + reverse proxy | Efficient static file serving. Reverse proxy eliminates CORS issues — all requests go to same origin. | FastAPI serving static files: conflates concerns, adds load to API pod. CORS headers: requires all upstream APIs to cooperate, more failure modes. |
| Dark theme | Standard for ops/monitoring consoles. Easier on eyes during incident response. Matches Grafana/Prometheus aesthetic. | Light theme: fine but unconventional for ops tooling. |
| Nginx reverse proxy (not CORS) | All browser requests go to the same origin (:31080). No CORS headers needed on SSOT or Actions API. Works regardless of upstream CORS config. | CORS: requires Actions API and SSOT API to set `Access-Control-Allow-Origin` headers. More fragile. |
| 30s polling (not WebSocket/SSE) | Simple, reliable. Health data changes on minute timescales, not seconds. Polling is adequate and trivial to implement. | WebSocket: complex, requires server-side changes, overkill for dashboard. SSE: same complexity. |
| Separate pod for UI (not served by Actions API) | Independent scaling and deployment lifecycle. Nginx is purpose-built for static files. Can update UI without restarting API. | Same pod as API: coupling — can't update UI without API restart. Sidecar: unnecessary complexity. |
| NodePort 31080 | Specified in ARCHITECTURE_DESIRED.md. Doesn't conflict with other team services (30000-31000 range). | Ingress controller: more complex, not needed for single-node k3s lab. |
| URL-based entity routing (`?id=`) | Simple, no client-side router needed. Works with vanilla JS. Bookmarkable entity URLs. | Hash routing (`#/entity/...`): works but breaks browser back button expectations. SPA framework: overkill. |

---

## Estimated New Files

| File | Purpose |
|------|---------|
| `apps/ops-ui/index.html` | Health Overview page |
| `apps/ops-ui/entity.html` | Entity Detail page |
| `apps/ops-ui/css/styles.css` | Ops console styles (dark theme) |
| `apps/ops-ui/js/config.js` | API URL configuration |
| `apps/ops-ui/js/api.js` | API client module (SSOT + Actions) |
| `apps/ops-ui/js/app.js` | Application logic (rendering, actions, auto-refresh) |
| `apps/ops-ui/nginx.conf` | Nginx configuration (static files + reverse proxy) |
| `apps/ops-ui/Dockerfile` | Nginx container image |
| `k8s/ops-ui/deployment.yaml` | Ops UI Deployment (1 replica, Nginx) |
| `k8s/ops-ui/service.yaml` | Ops UI Service (NodePort 31080) |
| `tests/e2e/test_ops_ui.py` | Sprint 3 E2E tests |
| `documentation/sprint/sprint3/REVIEW.md` | Sprint retrospective |
