/**
 * Centralized application configuration.
 * 
 * All environment-specific values should be read from Vite env vars
 * (import.meta.env.VITE_*) and exposed through this module.
 * 
 * This ensures no hard-coded hostnames, ports, or tenant IDs exist in the codebase.
 */

export interface AppConfig {
  /** Base URL for backend API (without trailing slash) */
  apiBaseUrl: string;
}

/**
 * Get the API base URL from environment or derive a sensible default.
 * 
 * In development, defaults to window.location.origin if VITE_API_BASE_URL is not set.
 * In production, VITE_API_BASE_URL should always be configured.
 */
function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  
  if (envUrl) {
    // Remove trailing slashes
    return envUrl.replace(/\/+$/, '');
  }
  
  // Fallback: use backend URL (for Docker Compose setup)
  // Default backend runs on port 8081
  if (typeof window !== 'undefined') {
    const isDev = import.meta.env.DEV;
    // In development with Docker, backend is typically on localhost:8081
    const defaultBackendUrl = isDev ? 'http://localhost:8081/api' : '/api';
    
    if (isDev) {
      console.warn(
        'VITE_API_BASE_URL not set. Using default backend URL:',
        defaultBackendUrl
      );
    }
    return defaultBackendUrl;
  }
  
  // SSR fallback (shouldn't happen in this app, but type-safe)
  console.error('VITE_API_BASE_URL not set and window is undefined');
  return '/api';
}

/**
 * Application configuration object.
 * 
 * Import this in components/modules that need config values.
 */
export const config: AppConfig = {
  apiBaseUrl: getApiBaseUrl(),
};
