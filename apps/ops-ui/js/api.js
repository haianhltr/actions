const API = {
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
