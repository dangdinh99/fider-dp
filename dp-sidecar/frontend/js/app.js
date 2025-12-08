/**
 * Main Application Logic for DP Dashboard
 * Handles UI updates, data fetching, and user interactions
 */

// State
let posts = [];
let autoRefreshEnabled = true;
let autoRefreshInterval = null;
let lastUpdateTime = null;

// Configuration
const AUTO_REFRESH_SECONDS = 30;
const TRACKED_POST_IDS = [1, 2, 3, 4, 5]; // Posts to track - adjust as needed

/**
 * Initialize the application
 */
async function init() {
    console.log('🚀 Initializing DP Dashboard...');
    
    // Set up event listeners
    setupEventListeners();
    
    // Load data
    await loadData();
    
    // Start auto-refresh if enabled
    if (autoRefreshEnabled) {
        startAutoRefresh();
    }
    
    console.log('✅ Dashboard initialized');
}

/**
 * Set up event listeners
 */
function setupEventListeners() {
    // Refresh button
    document.getElementById('refreshBtn').addEventListener('click', handleRefresh);
    
    // Auto-refresh toggle
    const toggle = document.getElementById('autoRefreshToggle');
    toggle.addEventListener('change', (e) => {
        autoRefreshEnabled = e.target.checked;
        if (autoRefreshEnabled) {
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });
    
    // Learn more modal
    document.getElementById('learnMoreBtn').addEventListener('click', openModal);
    document.getElementById('closeModalBtn').addEventListener('click', closeModal);
    document.getElementById('aboutLink').addEventListener('click', (e) => {
        e.preventDefault();
        openModal();
    });
    
    // Close modal when clicking outside
    document.getElementById('learnMoreModal').addEventListener('click', (e) => {
        if (e.target.id === 'learnMoreModal') {
            closeModal();
        }
    });
}

/**
 * Load all data
 */
async function loadData() {
    showLoading();
    
    try {
        // Check API health first
        await dpApi.healthCheck();
        
        // Load posts with DP counts
        await loadPosts();
        
        // Render UI
        renderPosts();
        updateStats();
        updateLastUpdated();
        
        hideLoading();
        
    } catch (error) {
        console.error('Failed to load data:', error);
        showError(error.message);
    }
}

/**
 * Load posts with DP counts
 */
async function loadPosts() {
    posts = [];
    
    try {
        // Try to get posts list from API (with real titles)
        const response = await fetch(`${dpApi.baseUrl}/api/posts`);
        
        if (response.ok) {
            const data = await response.json();
            console.log(`📊 Found ${data.total} tracked posts from API`);
            
            // For each post, get DP count and budget
            for (const postInfo of data.posts) {
                try {
                    const dpData = await dpApi.getDPCount(postInfo.id);
                    const budgetData = await dpApi.getBudgetInfo(postInfo.id);
                    
                    // Only include if has been published
                    if (dpData.noisy_count !== null || dpData.meets_threshold) {
                        posts.push({
                            id: postInfo.id,
                            title: postInfo.title,
                            description: postInfo.description,
                            slug: postInfo.slug,
                            dpData: dpData,
                            budgetData: budgetData
                        });
                        
                        console.log(`✓ Loaded post ${postInfo.id}: ${postInfo.title}`);
                    }
                } catch (error) {
                    console.warn(`Skipping post ${postInfo.id}:`, error.message);
                }
            }
        } else {
            // Fallback to manual IDs if /api/posts doesn't exist
            console.log('⚠️ /api/posts not available, using fallback');
            await loadPostsFallback();
        }
        
    } catch (error) {
        console.error('Error loading posts:', error);
        // Fallback if API call fails
        await loadPostsFallback();
    }
    
    console.log(`📊 Total posts loaded: ${posts.length}`);
}

/**
 * Fallback: Load posts using hardcoded IDs
 */
async function loadPostsFallback() {
    const TRACKED_POST_IDS = [1, 2, 3, 4, 5];
    
    for (const postId of TRACKED_POST_IDS) {
        try {
            const dpData = await dpApi.getDPCount(postId);
            const budgetData = await dpApi.getBudgetInfo(postId);
            
            if (dpData.meets_threshold || dpData.noisy_count !== null) {
                posts.push({
                    id: postId,
                    title: `Feature Request #${postId}`,
                    description: null,
                    slug: `post-${postId}`,
                    dpData: dpData,
                    budgetData: budgetData
                });
            }
        } catch (error) {
            console.warn(`Skipping post ${postId}:`, error.message);
        }
    }
}

/**
 * Get post title (placeholder - in real app would fetch from Fider)
 */
function getPostTitle(postId) {
    const titles = {
        1: 'Mobile App Support',
        2: 'Email Notifications',
        3: 'Dark Mode Feature',
        4: 'API Keys Management',
        5: 'Export Data Feature'
    };
    return titles[postId] || `Feature Request #${postId}`;
}

/**
 * Render posts to the DOM
 */
function renderPosts() {
    const container = document.getElementById('postsContainer');
    
    if (posts.length === 0) {
        container.innerHTML = '';
        document.getElementById('emptyState').style.display = 'block';
        return;
    }
    
    document.getElementById('emptyState').style.display = 'none';
    
    container.innerHTML = posts.map(post => createPostCard(post)).join('');
}

/**
 * Create HTML for a single post card
 */
function createPostCard(post) {
    const { dpData, budgetData } = post;
    
    // Format noisy count
    const noisyCount = dpData.noisy_count !== null 
        ? Math.round(dpData.noisy_count) 
        : null;
    
    // Format confidence interval
    const ci = dpData.confidence_interval;
    const ciText = ci 
        ? `${Math.max(0, Math.round(ci.lower))}-${Math.round(ci.upper)} range`
        : 'Pending';
    
    // Determine status
    const isLocked = dpData.is_locked || budgetData.is_locked;
    const statusClass = isLocked ? 'locked' : 'active';
    const statusText = isLocked ? '🔒 Locked' : '✓ Active';
    
    // Budget calculations
    const budgetPercent = budgetData.budget_percent_used || 0;
    const budgetRemaining = 100 - budgetPercent;
    const budgetClass = getBudgetClass(budgetRemaining);
    
    // Message
    const message = dpData.message || '';
    const isStale = dpData.is_stale;
    
    return `
        <div class="post-card ${statusClass}">
            <div class="post-header">
                <h2 class="post-title">${escapeHtml(post.title)}</h2>
                <span class="post-status ${statusClass}">${statusText}</span>
            </div>
            
            <div class="post-votes">
                ${noisyCount !== null ? `
                    <div class="vote-count">~${noisyCount} votes</div>
                    <div class="vote-range">(${ciText})</div>
                    ${isStale ? '<span class="confidence-badge">⏳ Pending update</span>' : ''}
                ` : `
                    <div class="vote-count" style="font-size: 1.25rem; color: var(--text-muted);">
                        ${message}
                    </div>
                `}
            </div>
            
            ${!isLocked && budgetData.epsilon_remaining !== null ? `
                <div class="budget-section">
                    <div class="budget-header">
                        <span class="budget-label">Privacy Budget</span>
                        <span class="budget-value">${budgetRemaining.toFixed(0)}% remaining</span>
                    </div>
                    <div class="budget-bar-container">
                        <div class="budget-bar ${budgetClass}" style="width: ${budgetRemaining}%"></div>
                    </div>
                    <div class="budget-details">
                        <span>${budgetData.queries_remaining || 0} updates remaining</span>
                        <span>${budgetData.num_noise_generations || 0} updates used</span>
                    </div>
                </div>
            ` : isLocked ? `
                <div class="budget-section">
                    <div class="budget-header">
                        <span class="budget-label">Privacy Budget</span>
                        <span class="budget-value" style="color: var(--locked-color);">
                            🔒 Exhausted
                        </span>
                    </div>
                    <div class="budget-bar-container">
                        <div class="budget-bar exhausted" style="width: 100%"></div>
                    </div>
                    <div class="budget-details">
                        <span>Final result (no more updates)</span>
                        <span>${budgetData.num_noise_generations || 0} total updates</span>
                    </div>
                </div>
            ` : ''}
            
            <div class="post-actions">
                <a href="${FIDER_BASE}" target="_blank" class="btn-secondary">
                    View in Fider →
                </a>
                ${dpData.noisy_count !== null ? `
                    <button class="btn-secondary" onclick="showPostDetails(${post.id})">
                        Budget Details
                    </button>
                ` : ''}
            </div>
        </div>
    `;
}

/**
 * Get budget bar color class based on remaining percentage
 */
function getBudgetClass(remaining) {
    if (remaining > 70) return 'high';
    if (remaining > 30) return 'medium';
    if (remaining > 0) return 'low';
    return 'exhausted';
}

/**
 * Update statistics in the header
 */
function updateStats() {
    const total = posts.length;
    const active = posts.filter(p => !p.dpData.is_locked && !p.budgetData.is_locked).length;
    const locked = posts.filter(p => p.dpData.is_locked || p.budgetData.is_locked).length;
    
    document.getElementById('totalPosts').textContent = total;
    document.getElementById('activePosts').textContent = active;
    document.getElementById('lockedPosts').textContent = locked;
}

/**
 * Update last updated timestamp
 */
function updateLastUpdated() {
    lastUpdateTime = new Date();
    updateLastUpdatedDisplay();
}

/**
 * Update the display of last updated time
 */
function updateLastUpdatedDisplay() {
    if (!lastUpdateTime) return;
    
    const now = new Date();
    const diff = Math.floor((now - lastUpdateTime) / 1000);
    
    let text;
    if (diff < 60) {
        text = `Last updated: ${diff}s ago`;
    } else if (diff < 3600) {
        text = `Last updated: ${Math.floor(diff / 60)}m ago`;
    } else {
        text = `Last updated: ${Math.floor(diff / 3600)}h ago`;
    }
    
    document.getElementById('lastUpdated').textContent = text;
}

/**
 * Handle manual refresh
 */
async function handleRefresh() {
    console.log('🔄 Manual refresh triggered');
    const btn = document.getElementById('refreshBtn');
    btn.disabled = true;
    btn.style.opacity = '0.6';
    
    await loadData();
    
    btn.disabled = false;
    btn.style.opacity = '1';
}

/**
 * Start auto-refresh timer
 */
function startAutoRefresh() {
    console.log(`⏰ Auto-refresh enabled (every ${AUTO_REFRESH_SECONDS}s)`);
    stopAutoRefresh(); // Clear any existing interval
    
    autoRefreshInterval = setInterval(async () => {
        console.log('🔄 Auto-refresh triggered');
        await loadData();
    }, AUTO_REFRESH_SECONDS * 1000);
    
    // Also update the "time ago" display every second
    setInterval(updateLastUpdatedDisplay, 1000);
}

/**
 * Stop auto-refresh timer
 */
function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
        console.log('⏹️ Auto-refresh disabled');
    }
}

/**
 * Show loading state
 */
function showLoading() {
    document.getElementById('loadingState').style.display = 'block';
    document.getElementById('errorState').style.display = 'none';
    document.getElementById('postsContainer').style.display = 'none';
    document.getElementById('emptyState').style.display = 'none';
}

/**
 * Hide loading state
 */
function hideLoading() {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('postsContainer').style.display = 'block';
}

/**
 * Show error state
 */
function showError(message) {
    document.getElementById('loadingState').style.display = 'none';
    document.getElementById('postsContainer').style.display = 'none';
    document.getElementById('errorState').style.display = 'block';
    document.getElementById('errorMessage').textContent = message;
}

/**
 * Open modal
 */
function openModal() {
    document.getElementById('learnMoreModal').classList.add('show');
    document.body.style.overflow = 'hidden';
}

/**
 * Close modal
 */
function closeModal() {
    document.getElementById('learnMoreModal').classList.remove('show');
    document.body.style.overflow = 'auto';
}

/**
 * Show post details (budget info)
 */
async function showPostDetails(postId) {
    try {
        const budgetData = await dpApi.getBudgetInfo(postId);
        const debugData = await dpApi.getDebugInfo(postId);
        
        alert(`
Budget Details for Post ${postId}:

Lifetime Cap: ${budgetData.lifetime_cap}
Total Used: ${budgetData.total_epsilon_used}
Remaining: ${budgetData.epsilon_remaining}
Updates: ${budgetData.num_noise_generations}
Queries Remaining: ${budgetData.queries_remaining}
Status: ${budgetData.message}

True Count: ${debugData.current_true_count_from_fider}
Noisy Count: ${debugData.published_release?.noisy_count?.toFixed(2) || 'N/A'}
        `.trim());
    } catch (error) {
        alert('Failed to load budget details: ' + error.message);
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', init);

// Handle page visibility (pause auto-refresh when tab is hidden)
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopAutoRefresh();
    } else if (autoRefreshEnabled) {
        startAutoRefresh();
        loadData(); // Refresh immediately when tab becomes visible
    }
});