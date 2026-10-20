const API = (window.location.protocol === "file:" || window.location.port === "5500" || window.location.port === "3000")
    ? "http://127.0.0.1:8000"
    : "/api";

async function fetchWithAuth(url, options = {}) {
    const token = localStorage.getItem("token");
    if (!token) {
        window.location.href = "login.html";
        return null;
    }

    const headers = {
        "Content-Type": "application/json",
        ...options.headers,
        "Authorization": `Bearer ${token}`,
    };

    try {
        const response = await fetch(url, { ...options, headers });
        if (response.status === 401) {
            localStorage.clear();
            window.location.href = "login.html";
            return null;
        }
        return response;
    } catch (error) {
        console.error("Erro de conexão:", error);
        return null;
    }
}

function formatDateTime(value) {
    if (!value) return "N/A";
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return "N/A";
    return dt.toLocaleString("pt-BR");
}

function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

let incidentsCache = [];

function setIncidentsState(message, type = "info") {
    const box = document.getElementById("incidentsList");
    if (!box) return;
    box.innerHTML = `<div class="ui-state ui-state-${escapeHtml(type)}">${escapeHtml(message)}</div>`;
}

function renderIncidents(items) {
    const box = document.getElementById("incidentsList");
    if (!box) return;

    if (!items.length) {
        setIncidentsState("Nenhum incidente encontrado.", "empty");
        return;
    }

    box.innerHTML = items.map((inc) => {
        const isClosed = String(inc.status || "").toUpperCase() === "CLOSED";
        const stateClass = isClosed ? "incident-closed" : "incident-open";
        const statusLabel = isClosed ? "Fechado" : "Aberto";
        const durationFormatted = inc.duration
            ? `${Math.max(1, Math.round(inc.duration / 60))} min`
            : "Em andamento";
        return `
        <div class="incident-row ${stateClass}">
            <div class="incident-row-main">
                <strong>${escapeHtml(inc.host_name || "Host")}</strong>
                <small class="incident-status-tag ${stateClass}">${statusLabel} • ${escapeHtml(inc.incident_type || "GENERIC")}</small>
            </div>
            <div class="incident-row-meta">
                <small>Início: ${escapeHtml(formatDateTime(inc.started_time))}</small>
                <small>Fim: ${escapeHtml(formatDateTime(inc.ended_time))}</small>
                <small>Duração: ${escapeHtml(durationFormatted)}</small>
            </div>
            <div class="incident-row-reason">${escapeHtml(inc.reason_text || inc.reason || "Sem descrição")}</div>
        </div>
    `}).join("");
}

function applySearch() {
    const term = String(document.getElementById("incidentsSearch")?.value || "").toLowerCase().trim();
    if (!term) {
        renderIncidents(incidentsCache);
        return;
    }
    const filtered = incidentsCache.filter((inc) =>
        String(inc.host_name || "").toLowerCase().includes(term)
    );
    renderIncidents(filtered);
}

async function loadIncidents(silent = false) {
    const refreshBtn = document.getElementById("refreshIncidentsBtn");
    const refreshIcon = refreshBtn?.querySelector(".refresh-icon");
    if (refreshIcon) refreshIcon.classList.add("spin");

    if (!silent) {
        setIncidentsState("Carregando incidentes...", "info");
    }

    try {
        const res = await fetchWithAuth(`${API}/incidents/latest`);
        if (!res || !res.ok) {
            if (!silent) {
                setIncidentsState("Não foi possível carregar os incidentes.", "error");
            }
            return;
        }
        const data = await res.json();
        incidentsCache = Array.isArray(data) ? data : [];
        applySearch();
    } finally {
        if (refreshIcon) {
            setTimeout(() => refreshIcon.classList.remove("spin"), 400);
        }
    }
}

window.addEventListener("DOMContentLoaded", async () => {
    const searchInput = document.getElementById("incidentsSearch");
    if (searchInput) searchInput.addEventListener("input", applySearch);

    const refreshBtn = document.getElementById("refreshIncidentsBtn");
    if (refreshBtn) {
        refreshBtn.addEventListener("click", () => loadIncidents(false));
    }

    await loadIncidents();

    // Auto-refresh leve a cada 20 segundos em segundo plano (se a aba estiver visível)
    setInterval(() => {
        if (!document.hidden) {
            loadIncidents(true);
        }
    }, 20000);
});

/* ==========================================================================
   THEME TOGGLER MANAGER (LIGHT / DARK THEME)
   ========================================================================== */
(function initThemeManager() {
    const themeToggleBtn = document.getElementById("themeToggleBtn");
    
    // Ler o estado atual do tema
    const savedTheme = localStorage.getItem("theme");
    const isDark = savedTheme === "dark";
    
    // Atualizar o ícone de carregamento inicial
    updateThemeIcon(isDark);
    
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener("click", () => {
            const currentIsDark = document.documentElement.classList.toggle("dark-theme");
            localStorage.setItem("theme", currentIsDark ? "dark" : "light");
            updateThemeIcon(currentIsDark);
        });
    }
    
    function updateThemeIcon(isDarkState) {
        const icon = document.getElementById("themeToggleIcon");
        if (!icon) return;
        if (isDarkState) {
            icon.innerHTML = `<path d="M12 3a9 9 0 109 9 9.75 9.75 0 00-.67-3.4 6.78 6.78 0 01-7.93-7.93A9.75 9.75 0 0012 3z" fill="currentColor"/>`;
            icon.removeAttribute("stroke");
        } else {
            icon.innerHTML = `<circle cx="12" cy="12" r="4" fill="#f9ab00"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="#f9ab00" stroke-width="2" stroke-linecap="round"/>`;
        }
    }
})();
