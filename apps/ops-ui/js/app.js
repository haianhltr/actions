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

function renderEntityInfo(entity, ownership) {
    const dl = document.getElementById('entity-metadata');
    const parts = (entity.entity_id || entity.id || '').split(':');
    dl.innerHTML = `
        <dt>Entity ID</dt><dd>${entity.entity_id || entity.id || ''}</dd>
        <dt>Name</dt><dd>${entity.name || parts[4] || ''}</dd>
        <dt>Type</dt><dd>${entity.type || parts[3] || ''}</dd>
        <dt>Namespace</dt><dd>${parts[2] || ''}</dd>
        <dt>Cluster</dt><dd>${parts[1] || ''}</dd>
        ${ownership ? `<dt>Owner</dt><dd>${ownership.team || '-'}</dd>
        <dt>Tier</dt><dd>${ownership.tier || '-'}</dd>
        <dt>Contact</dt><dd>${ownership.contact || '-'}</dd>` : ''}
    `;
}

function renderHealthInfo(health) {
    const div = document.getElementById('health-state-display');
    if (!health) { div.textContent = 'No health data available'; return; }
    const state = health.state || health.health_state || 'UNKNOWN';
    const cls = 'state-' + state.toLowerCase();
    div.innerHTML = `
        <span class="${cls}">${state}</span>
        ${health.reason ? `<p>${health.reason}</p>` : ''}
        ${health.confidence != null ? `<p>Confidence: ${(health.confidence * 100).toFixed(0)}%</p>` : ''}
        ${health.updated_at ? `<p>Last updated: ${new Date(health.updated_at).toLocaleString()}</p>` : ''}
    `;
}

function renderRootCause(health, entityId) {
    const div = document.getElementById('root-cause-display');
    if (!health || !health.root_cause_entity_id) {
        div.textContent = 'N/A';
        return;
    }
    if (health.root_cause_entity_id === entityId) {
        div.textContent = 'Self (this entity is the root cause)';
    } else {
        const name = health.root_cause_entity_id.split(':').pop();
        div.innerHTML = `<a href="entity.html?id=${encodeURIComponent(health.root_cause_entity_id)}">${name}</a>
            <span class="root-cause-id">(${health.root_cause_entity_id})</span>`;
    }
}

function renderRecommendation(rec) {
    const section = document.getElementById('recommendation');
    const div = document.getElementById('recommendation-display');
    if (!rec) { section.classList.add('hidden'); return; }
    section.classList.remove('hidden');
    div.innerHTML = `
        <p><strong>Recommended: ${rec.recommended_action}</strong></p>
        ${rec.reason ? `<p>Reason: ${rec.reason}</p>` : ''}
        <p>Health state: <span class="state-${(rec.health_state || '').toLowerCase()}">${rec.health_state || ''}</span></p>
        ${rec.since ? `<p>Since: ${new Date(rec.since).toLocaleString()}</p>` : ''}
    `;
}

function renderActionHistory(actions) {
    const tbody = document.getElementById('history-body');
    tbody.innerHTML = '';
    const list = Array.isArray(actions) ? actions : [];
    if (list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5">No actions recorded for this entity</td></tr>';
        return;
    }
    for (const a of list) {
        const row = document.createElement('tr');
        const statusCls = a.status === 'success' ? 'state-healthy' : a.status === 'failure' ? 'state-unhealthy' : '';
        row.innerHTML = `
            <td>${a.created_at ? new Date(a.created_at).toLocaleString() : '-'}</td>
            <td>${a.action_type || ''}</td>
            <td>${a.user_id || a.user || ''}</td>
            <td class="${statusCls}">${a.status || ''}</td>
            <td>${a.result_message || ''}</td>
        `;
        tbody.appendChild(row);
    }
}

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
