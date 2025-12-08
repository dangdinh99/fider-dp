/**
 * API Client for DP Sidecar Backend
 * Handles all HTTP requests to the FastAPI backend
 */

const API_BASE = 'http://localhost:8000';
const FIDER_BASE = 'http://localhost:3000';

/**
 * API Client class
 */
class DPApiClient {
    constructor(baseUrl = API_BASE) {
        this.baseUrl = baseUrl;
    }

    /**
     * Generic fetch wrapper with error handling
     */
    async fetch(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers,
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API Error [${endpoint}]:`, error);
            throw error;
        }
    }

    /**
     * Get DP-protected count for a specific post
     * @param {number} postId - The post ID
     * @returns {Promise<Object>} DP count response
     */
    async getDPCount(postId) {
        return this.fetch(`/api/counts/${postId}`);
    }

    /**
     * Get budget information for a specific post
     * @param {number} postId - The post ID
     * @returns {Promise<Object>} Budget information
     */
    async getBudgetInfo(postId) {
        return this.fetch(`/api/admin/budget/${postId}`);
    }

    /**
     * Get debug information for a specific post (development only)
     * @param {number} postId - The post ID
     * @returns {Promise<Object>} Debug information
     */
    async getDebugInfo(postId) {
        return this.fetch(`/api/debug/post/${postId}`);
    }

    /**
     * Health check
     * @returns {Promise<Object>} API status
     */
    async healthCheck() {
        return this.fetch('/');
    }
}

/**
 * Fider API Client
 * For fetching posts from Fider (if needed)
 */
class FiderApiClient {
    constructor(baseUrl = FIDER_BASE) {
        this.baseUrl = baseUrl;
    }

    /**
     * Get all posts from Fider
     * Note: This is a simplified version. Fider's actual API might differ.
     * For now, we'll use a workaround by tracking posts through DP queries.
     */
    async getPosts() {
        // Fider doesn't expose a public API by default
        // We'll work around this in app.js by tracking posts through DP queries
        console.warn('Fider API not directly accessible. Using tracked posts instead.');
        return [];
    }
}

// Export instances
const dpApi = new DPApiClient();
const fiderApi = new FiderApiClient();