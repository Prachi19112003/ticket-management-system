/**
 * Antigravity Ticket Management System — Dashboard Client Application
 * 
 * NOTE: This frontend application communicates directly with the local FastAPI
 * server backend via fetch() requests to http://127.0.0.1:8000/api/v1/.
 * For this demo tool context, no authorization header is required.
 */

const API_BASE = "http://127.0.0.1:8000/api/v1";

// Application State
let state = {
    tickets: [],
    selectedTicket: null,
    filters: {
        status: "drafted", // Default filter to show pending items
        category: "",
        sort: "desc"
    },
    reviewerName: "Human Reviewer"
};

// DOM References
const elements = {
    // Stats
    statTotalTickets: document.getElementById("stat-total-tickets"),
    statTokensToday: document.getElementById("stat-tokens-today"),
    statTokensAllTime: document.getElementById("stat-tokens-alltime"),
    statAvgTokens: document.getElementById("stat-avg-tokens"),
    
    // Filters
    filterStatus: document.getElementById("filter-status"),
    filterCategory: document.getElementById("filter-category"),
    sortPriority: document.getElementById("sort-priority"),
    
    // List & Detail Panel
    queueCount: document.getElementById("queue-count"),
    ticketList: document.getElementById("ticket-list"),
    detailPanel: document.getElementById("ticket-detail-panel"),
    
    // Toast Container
    toastContainer: document.getElementById("toast-container")
};

// Initialization
document.addEventListener("DOMContentLoaded", () => {
    // Set default select values in UI
    elements.filterStatus.value = state.filters.status;
    elements.filterCategory.value = state.filters.category;
    elements.sortPriority.value = state.filters.sort;
    
    // Register Filter Listeners
    elements.filterStatus.addEventListener("change", (e) => {
        state.filters.status = e.target.value;
        loadTickets();
    });
    
    elements.filterCategory.addEventListener("change", (e) => {
        state.filters.category = e.target.value;
        renderTicketsList();
    });
    
    elements.sortPriority.addEventListener("change", (e) => {
        state.filters.sort = e.target.value;
        renderTicketsList();
    });

    // Initial Load
    refreshAll();
});

// Toast Notifications Helper
function showToast(message, type = "success") {
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    elements.toastContainer.appendChild(toast);
    
    // Remove toast after animation completes
    setTimeout(() => {
        toast.style.animation = "slideIn 0.3s cubic-bezier(0,0,0.2,1) reverse forwards";
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Fetch stats and update header widgets
async function loadStats() {
    try {
        const response = await fetch(`${API_BASE}/dashboard/stats`);
        if (!response.ok) throw new Error("Failed to load dashboard statistics");
        
        const stats = await response.json();
        
        elements.statTotalTickets.textContent = Object.values(stats.tickets_by_status).reduce((a, b) => a + b, 0);
        elements.statTokensToday.textContent = stats.tokens_used.today.toLocaleString();
        elements.statTokensAllTime.textContent = stats.tokens_used.all_time.toLocaleString();
        elements.statAvgTokens.textContent = stats.average_tokens_per_draft.toLocaleString();
    } catch (error) {
        console.error("Error loading stats:", error);
        showToast("Error updating stats panel", "error");
    }
}

// Fetch tickets from database
async function loadTickets() {
    elements.ticketList.innerHTML = '<div class="loading-state">Loading tickets...</div>';
    
    try {
        let url = `${API_BASE}/dashboard/tickets`;
        if (state.filters.status) {
            url += `?status=${encodeURIComponent(state.filters.status)}`;
        }
        
        const response = await fetch(url);
        if (!response.ok) throw new Error("Failed to fetch tickets");
        
        state.tickets = await response.json();
        renderTicketsList();
    } catch (error) {
        console.error("Error fetching tickets:", error);
        elements.ticketList.innerHTML = '<div class="loading-state">Failed to load queue.</div>';
        showToast("Failed to load ticket queue", "error");
    }
}

// Filter, Sort, and Render current tickets to the queue list
function renderTicketsList() {
    // 1. Apply category filter locally
    let filtered = [...state.tickets];
    if (state.filters.category) {
        filtered = filtered.filter(t => t.category === state.filters.category);
    }
    
    // 2. Sort by priority score
    filtered.sort((a, b) => {
        if (state.filters.sort === "asc") {
            return a.priority_score - b.priority_score;
        } else {
            return b.priority_score - a.priority_score;
        }
    });
    
    elements.queueCount.textContent = `${filtered.length} Ticket${filtered.length === 1 ? '' : 's'}`;
    
    if (filtered.length === 0) {
        elements.ticketList.innerHTML = '<div class="loading-state">No tickets matched criteria.</div>';
        return;
    }
    
    elements.ticketList.innerHTML = "";
    filtered.forEach(ticket => {
        const card = document.createElement("div");
        card.className = `ticket-card ${state.selectedTicket?.ticket_id === ticket.ticket_id ? 'selected' : ''}`;
        
        // Priority styling helper
        let priorityClass = "priority-low";
        if (ticket.priority_score >= 70) priorityClass = "priority-high";
        else if (ticket.priority_score >= 40) priorityClass = "priority-medium";
        
        // Guardrail alert badge
        const hasGuardrails = ticket.guardrail_flags && ticket.guardrail_flags.length > 0;
        const flagNames = hasGuardrails 
            ? ticket.guardrail_flags.map(f => typeof f === 'object' && f ? f.type : String(f)).join(', ')
            : "";
        const guardrailBadge = hasGuardrails 
            ? `<span class="guardrail-warning-badge" title="${flagNames}">Guardrail Alert</span>` 
            : "";
            
        card.innerHTML = `
            <div class="ticket-card-header">
                <span class="category-label">${ticket.category || 'General'}</span>
                <span class="ticket-card-priority ${priorityClass}">Score: ${ticket.priority_score}</span>
            </div>
            <div class="ticket-card-title">${ticket.raw_subject || '(No Subject)'}</div>
            <div class="ticket-card-body">${ticket.cleaned_body || '(No Content)'}</div>
            <div class="ticket-card-footer">
                <span class="status-badge status-${ticket.status}">${ticket.status}</span>
                ${guardrailBadge}
            </div>
        `;
        
        card.addEventListener("click", () => selectTicket(ticket.ticket_id));
        elements.ticketList.appendChild(card);
    });
}

// Fetch single ticket details and update right details panel
async function selectTicket(ticketId) {
    // Select styling update instantly
    const cards = elements.ticketList.querySelectorAll(".ticket-card");
    cards.forEach(c => c.classList.remove("selected"));
    
    try {
        const response = await fetch(`${API_BASE}/dashboard/tickets/${ticketId}`);
        if (!response.ok) throw new Error("Failed to load ticket details");
        
        const ticket = await response.json();
        state.selectedTicket = ticket;
        
        // Render selected ticket in detail queue list
        renderTicketsList();
        
        // Render detailed panel content
        renderTicketDetailView(ticket);
    } catch (error) {
        console.error("Error loading ticket detail:", error);
        showToast("Error retrieving ticket details", "error");
    }
}

// Render the detailed panel content
function renderTicketDetailView(ticket) {
    let priorityClass = "priority-low";
    if (ticket.priority_score >= 70) priorityClass = "priority-high";
    else if (ticket.priority_score >= 40) priorityClass = "priority-medium";

    // Build Guardrail Warning Header if flags exist
    const hasFlags = ticket.guardrail_flags && ticket.guardrail_flags.length > 0;
    let guardrailHTML = "";
    if (hasFlags) {
        const flagItems = ticket.guardrail_flags.map(f => {
            if (typeof f === 'object' && f) {
                const textDetail = f.matched_text ? ` (Matched text: "${f.matched_text}")` : "";
                return `<li><strong>${f.type}</strong>: ${f.reason}${textDetail}</li>`;
            }
            return `<li>${f}</li>`;
        }).join("");
        guardrailHTML = `
            <div class="guardrail-alert" style="display: block;">
                <div style="font-weight: bold; margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                    <span>⚠️ Guardrail Triggers:</span>
                </div>
                <ul style="padding-left: 20px; font-size: 13px; line-height: 1.5; margin: 0;">
                    ${flagItems}
                </ul>
            </div>
        `;
    }

    // Build CC list view
    const ccList = (ticket.draft_json && ticket.draft_json.cc_list) ? ticket.draft_json.cc_list.join(", ") : "None";
    const confidenceScore = (ticket.draft_json && ticket.draft_json.confidence_score) ? ticket.draft_json.confidence_score : "N/A";
    
    // Tokens calculations
    const tokenLogs = ticket.llm_usage_logs || [];
    const totalTokens = tokenLogs.reduce((acc, log) => acc + log.total_tokens, 0);
    const inputTokens = tokenLogs.reduce((acc, log) => acc + log.input_tokens, 0);
    const outputTokens = tokenLogs.reduce((acc, log) => acc + log.output_tokens, 0);

    // Build RAG context references
    let ragRefsHTML = "";
    if (ticket.references && ticket.references.length > 0) {
        ticket.references.forEach((ref, index) => {
            ragRefsHTML += `
                <div class="rag-reference-item">
                    <div class="rag-ref-header">Reference #${index + 1}: ${ref.subject || 'Similar Inquiry'}</div>
                    <div class="rag-ref-body">${ref.cleaned_body}</div>
                    <div class="rag-ref-resolution"><strong>Resolution:</strong> ${ref.resolution}</div>
                </div>
            `;
        });
    } else {
        ragRefsHTML = '<p style="font-size: 13px; color: var(--text-muted);">No reference matches found in database.</p>';
    }

    // Draft response draft
    const draftText = (ticket.draft_json && ticket.draft_json.draft_reply) ? ticket.draft_json.draft_reply : "";

    elements.detailPanel.innerHTML = `
        <div class="detail-scroll-container">
            <!-- Header section -->
            <div class="detail-header">
                <div class="detail-title-group">
                    <h2>${ticket.raw_subject || '(No Subject)'}</h2>
                    <div class="detail-meta-row">
                        <span class="detail-meta-item">Status: <span class="status-badge status-${ticket.status}">${ticket.status}</span></span>
                        <span class="detail-meta-item">Category: <strong>${ticket.category || 'General'}</strong></span>
                        <span class="detail-meta-item">Priority Score: <span class="ticket-card-priority ${priorityClass}">${ticket.priority_score}</span></span>
                    </div>
                </div>
                <div class="detail-meta-item">
                    Ticket ID: <span style="font-family: 'Fira Code', monospace; font-size:11px;">${ticket.ticket_id}</span>
                </div>
            </div>

            <!-- Guardrails -->
            ${guardrailHTML}

            <!-- Original Incoming Email -->
            <div class="detail-card">
                <h3>Original Customer Query</h3>
                <div class="email-body-content">${ticket.cleaned_body || '(Empty)'}</div>
            </div>

            <!-- RAG Reference Matches -->
            <div class="detail-card">
                <h3>Similar Knowledge Matches (RAG Context)</h3>
                <div class="rag-references-list">
                    ${ragRefsHTML}
                </div>
            </div>

            <!-- Edit/Submit Reply Draft -->
            <div class="detail-card">
                <h3>Generated Reply Draft</h3>
                <div class="textarea-container">
                    <textarea class="draft-textarea" id="draft-textarea-input" ${ticket.status === 'sent' || ticket.status === 'approved' ? 'disabled' : ''}>${draftText}</textarea>
                </div>
            </div>

            <!-- Metadata & Token Log metrics -->
            <div class="metadata-panel">
                <div class="meta-column">
                    <span>Draft CC List: <strong>${ccList}</strong></span>
                    <span>Draft Confidence: <strong>${confidenceScore}</strong></span>
                </div>
                <div class="meta-column" style="text-align: right;">
                    <span>Input Tokens: <strong class="meta-tokens">${inputTokens}</strong></span>
                    <span>Output Tokens: <strong class="meta-tokens">${outputTokens}</strong></span>
                    <span>Total Tokens: <strong class="meta-tokens" style="font-size: 14px; text-decoration: underline;">${totalTokens}</strong></span>
                </div>
            </div>
        </div>

        <!-- Action Panel -->
        <div class="action-bar">
            <div class="reviewer-input-group">
                <label for="reviewer-name-field">Reviewer Name</label>
                <input type="text" id="reviewer-name-field" value="${state.reviewerName}" placeholder="Your Name" />
            </div>
            
            <div class="action-buttons">
                ${ticket.status !== 'sent' && ticket.status !== 'approved' && ticket.status !== 'rejected' ? `
                    <button class="btn btn-reject" id="btn-action-reject">Reject</button>
                    <button class="btn btn-edit" id="btn-action-edit">Edit & Send</button>
                    <button class="btn btn-approve" id="btn-action-approve">Approve & Send</button>
                ` : `
                    <span style="font-size: 13px; color: var(--text-muted); font-weight: 500;">Review complete (Read-Only)</span>
                `}
            </div>
        </div>
    `;

    // Bind Button Action events
    const rejectBtn = document.getElementById("btn-action-reject");
    const editBtn = document.getElementById("btn-action-edit");
    const approveBtn = document.getElementById("btn-action-approve");
    const reviewerField = document.getElementById("reviewer-name-field");

    if (reviewerField) {
        reviewerField.addEventListener("input", (e) => {
            state.reviewerName = e.target.value || "Human Reviewer";
        });
    }

    if (rejectBtn) rejectBtn.addEventListener("click", () => executeReviewAction("reject"));
    if (editBtn) editBtn.addEventListener("click", () => executeReviewAction("edit"));
    if (approveBtn) approveBtn.addEventListener("click", () => executeReviewAction("approve"));
}

// Post review actions to API
async function executeReviewAction(actionType) {
    if (!state.selectedTicket) return;
    const ticketId = state.selectedTicket.ticket_id;
    const reviewer = state.reviewerName || "Human Reviewer";
    
    let url = `${API_BASE}/review/${ticketId}/${actionType}`;
    let body = { reviewed_by: reviewer };
    
    if (actionType === "edit") {
        const textarea = document.getElementById("draft-textarea-input");
        if (!textarea) return;
        body.revised_reply = textarea.value;
    }

    showToast(`Submitting ${actionType} request...`, "info");

    try {
        const response = await fetch(url, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(body)
        });

        const result = await response.json();
        
        if (response.ok) {
            showToast(result.message || `Action '${actionType}' completed successfully!`, "success");
            
            // Reload statistics, list queue and ticket details to reflect state changes on-the-fly
            await loadStats();
            await loadTickets();
            await selectTicket(ticketId);
        } else {
            throw new Error(result.detail || `Server returned error status ${response.status}`);
        }
    } catch (error) {
        console.error(`Error performing ${actionType} action:`, error);
        showToast(error.message || `Failed to perform ${actionType} action.`, "error");
    }
}

// Helper function to reload stats and tickets queue
function refreshAll() {
    loadStats();
    loadTickets();
}
