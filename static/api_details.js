// API Details Page JavaScript

// Global variables
let apiData = null;
let userId = null;
let apiSlug = null;

// Initialize page
document.addEventListener('DOMContentLoaded', function() {
    // Get user ID and API slug from the page
    const userIdElement = document.querySelector('[data-user-id]');
    const apiSlugElement = document.querySelector('[data-api-slug]');
    
    if (userIdElement) userId = userIdElement.getAttribute('data-user-id');
    if (apiSlugElement) apiSlug = apiSlugElement.getAttribute('data-api-slug');
    
    console.log('=== PAGE INITIALIZATION ===');
    console.log('User ID:', userId);
    console.log('API Slug:', apiSlug);
    console.log('Full URL:', window.location.href);
    console.log('Data attributes found:', {
        userIdElement: !!userIdElement,
        apiSlugElement: !!apiSlugElement
    });
    
    if (!userId || !apiSlug) {
        console.error('❌ Missing userId or apiSlug');
        showError('Missing API information. Please navigate to this page from your API list.');
        return;
    }
    
    loadAPIDetails();
});

// Load API details
async function loadAPIDetails() {
    try {
        console.log(`Loading API details for: ${userId}/${apiSlug}`);
        const response = await fetch(`/api/${userId}/${apiSlug}/apidetails`);
        console.log('Response status:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            console.error('Error response:', errorText);
            try {
                const errorData = JSON.parse(errorText);
                showError(errorData.detail || 'Failed to load API details');
            } catch {
                showError(`HTTP ${response.status}: ${errorText}`);
            }
            return;
        }
        
        const text = await response.text();
        console.log('Response text length:', text.length);
        console.log('Response text preview:', text.substring(0, 200));
        
        let data;
        try {
            data = JSON.parse(text);
        } catch (parseError) {
            console.error('JSON parse error:', parseError);
            console.error('Response text:', text);
            showError('Invalid JSON response from server');
            return;
        }
        
        console.log('Parsed data:', data);
        apiData = data;
        
        try {
            populateAPIDetails(data);
            showMainContent();
        } catch (populateError) {
            console.error('Error populating API details:', populateError);
            showError('Failed to display API details: ' + populateError.message);
        }
    } catch (error) {
        console.error('Error loading API details:', error);
        showError('Network error: ' + error.message);
    }
}

// Populate page with API details
function populateAPIDetails(data) {
    try {
        // Header - with null checks
        const apiNameEl = document.getElementById('apiName');
        const apiDescEl = document.getElementById('apiDescription');
        const createdDateEl = document.getElementById('createdDate');
        
        // Extract API name from prompt if not already set
        const apiName = extractAPINameFromPrompt(data.prompt || '', data.api_name || `API ${apiSlug}`);
        if (apiNameEl) apiNameEl.textContent = apiName;
        // Parse description from prompt to show only clean description
        const cleanDescription = extractDescriptionFromPrompt(data.prompt || '');
        // Display full description without truncation for better readability
        if (apiDescEl) apiDescEl.textContent = cleanDescription;
        if (createdDateEl) createdDateEl.textContent = `Created: ${formatDate(data.created_at)}`;
        
        // Status
        const statusEl = document.getElementById('apiStatus');
        if (statusEl) {
            if (data.code_available) {
                statusEl.className = 'api-status-badge status-active';
                statusEl.innerHTML = '<div class="w-2 h-2 bg-current rounded-full mr-2"></div>Active';
            } else {
                statusEl.className = 'api-status-badge status-inactive';
                statusEl.innerHTML = '<div class="w-2 h-2 bg-current rounded-full mr-2"></div>Inactive';
            }
        }
        
        // Metrics - with null checks
        const fileSizeEl = document.getElementById('fileSize');
        const lastModifiedEl = document.getElementById('lastModified');
        
        if (fileSizeEl) fileSizeEl.textContent = formatFileSize(data.file_size || 0);
        if (lastModifiedEl) lastModifiedEl.textContent = data.last_modified ? formatRelativeTime(data.last_modified) : '--';
    
        // Overview tab - with null checks
        const endpointUrlEl = document.getElementById('endpointUrl');
        const originalPromptEl = document.getElementById('originalPrompt');
        const createdAtEl = document.getElementById('createdAt');
        const savedAtEl = document.getElementById('savedAt');
        
        if (endpointUrlEl) endpointUrlEl.textContent = data.endpoint_url || '--';
        // Extract cleaner version of original prompt
        if (originalPromptEl) {
            const cleanPrompt = extractOriginalUserRequest(data.prompt || '');
            originalPromptEl.textContent = cleanPrompt || data.prompt || 'No prompt available';
        }
        if (createdAtEl) createdAtEl.textContent = formatDateTime(data.created_at);
        if (savedAtEl) savedAtEl.textContent = data.saved_at ? formatDateTime(data.saved_at) : 'Not saved';
        
        // Test tab - display endpoint URL
        const endpointDisplayEl = document.getElementById('endpointDisplay');
        if (endpointDisplayEl) {
            endpointDisplayEl.textContent = data.endpoint_url || '--';
        }
        
        // Documentation tab - handle both old and new structure
        const documentationContent = document.getElementById('documentationContent');
        if (documentationContent && data.documentation) {
            documentationContent.innerHTML = formatMarkdown(data.documentation);
        }
        
        // cURL example - check if element exists
        const curlExample = document.getElementById('curlExample');
        if (curlExample) {
            curlExample.textContent = data.curl_example || 'No cURL example available';
        }
        
        // Load source code if available
        if (data.code_available) {
            loadSourceCode();
        }
        
        // Store database config status for later use
        window.apiHasDatabaseConfig = false;
        window.showDbUpgradeMessage = false;
        
        console.log('=== DATABASE CONFIGURATION CHECK ===');
        console.log('API Data:', data);
        console.log('Database Config Field:', data.database_config);
        console.log('Database Config Type:', typeof data.database_config);
        
        // Check if API has database configuration
        if (data.database_config) {
            console.log('✅ Database config exists');
            console.log('Database config details:', JSON.stringify(data.database_config, null, 2));
            console.log('Database enabled:', data.database_config.enabled);
            
            if (data.database_config.enabled) {
                window.apiHasDatabaseConfig = true;
                // Show database tab for APIs with enabled database
                const databaseTabButton = document.getElementById('databaseTabButton');
                if (databaseTabButton) {
                    databaseTabButton.style.display = 'block';
                    console.log('Database tab button shown');
                }
                
                // Populate database information
                populateDatabaseInfo(data.database_config);
            } else {
                console.log('Database config exists but is disabled');
            }
        } else {
            console.log('No database_config field found');
            // Check if this is an older API that might have database connection
            // by looking at the prompt or API name
            const prompt = (data.prompt || '').toLowerCase();
            const apiName = (data.api_name || '').toLowerCase();
            const hasDbKeywords = prompt.includes('database') || prompt.includes('postgres') || 
                                 prompt.includes('mongodb') || prompt.includes('mysql') ||
                                 apiName.includes('database') || apiName.includes('db') ||
                                 prompt.includes('sql') || prompt.includes('user') ||
                                 prompt.includes('collection') || prompt.includes('table');
            
            console.log('Checking for database keywords:', hasDbKeywords);
            
            if (hasDbKeywords) {
                // Show database tab with upgrade message
                const databaseTabButton = document.getElementById('databaseTabButton');
                if (databaseTabButton) {
                    databaseTabButton.style.display = 'block';
                    console.log('Database tab button shown for keyword match');
                }
                // Mark that we need to show upgrade message when tab is opened
                window.showDbUpgradeMessage = true;
            }
        }
        
    } catch (error) {
        console.error('Error populating API details:', error);
        showError('Failed to display API details: ' + error.message);
    }
}

// Load source code
async function loadSourceCode() {
    try {
        const response = await fetch(`/api/${userId}/${apiSlug}/code`);
        const data = await response.json();
        
        if (response.ok) {
            document.getElementById('sourceCode').textContent = data.code;
        } else {
            document.getElementById('sourceCode').textContent = 'Failed to load source code';
        }
    } catch (error) {
        document.getElementById('sourceCode').textContent = 'Error loading source code: ' + error.message;
    }
}

// Populate database information
function populateDatabaseInfo(dbConfig) {
    console.log('populateDatabaseInfo called with:', dbConfig);
    
    try {
        // Database type
        const dbTypeEl = document.getElementById('dbType');
        console.log('dbTypeEl:', dbTypeEl, 'db_type:', dbConfig.db_type);
        if (dbTypeEl && dbConfig.db_type) {
            dbTypeEl.textContent = dbConfig.db_type.toUpperCase();
            console.log('Set database type to:', dbConfig.db_type.toUpperCase());
        }
        
        // Database name
        const dbNameEl = document.getElementById('dbName');
        console.log('dbNameEl:', dbNameEl, 'database_name:', dbConfig.database_name);
        if (dbNameEl) {
            dbNameEl.textContent = dbConfig.database_name || '--';
            console.log('Set database name to:', dbConfig.database_name || '--');
        }
        
        // Host
        const dbHostEl = document.getElementById('dbHost');
        console.log('dbHostEl:', dbHostEl, 'host:', dbConfig.host);
        if (dbHostEl) {
            dbHostEl.textContent = dbConfig.host || '--';
            console.log('Set host to:', dbConfig.host || '--');
        }
        
        // Port
        const dbPortEl = document.getElementById('dbPort');
        console.log('dbPortEl:', dbPortEl, 'port:', dbConfig.port);
        if (dbPortEl) {
            dbPortEl.textContent = dbConfig.port || '--';
            console.log('Set port to:', dbConfig.port || '--');
        }
        
        // Username
        const dbUsernameEl = document.getElementById('dbUsername');
        console.log('dbUsernameEl:', dbUsernameEl, 'username:', dbConfig.username);
        if (dbUsernameEl) {
            dbUsernameEl.textContent = dbConfig.username || '--';
            console.log('Set username to:', dbConfig.username || '--');
        }
        
        // Connection string
        const dbConnectionStringEl = document.getElementById('dbConnectionString');
        if (dbConnectionStringEl && dbConfig.connection_string) {
            // Mask sensitive parts of connection string
            const maskedConnectionString = maskConnectionString(dbConfig.connection_string);
            dbConnectionStringEl.innerHTML = `<span class="text-white">${maskedConnectionString}</span>`;
            console.log('Set connection string (masked)');
        }
        
        console.log('✅ Database info populated successfully');
    } catch (error) {
        console.error('❌ Error populating database info:', error);
        console.error('Stack trace:', error.stack);
    }
}

// Mask sensitive information in connection string
function maskConnectionString(connectionString) {
    if (!connectionString) return '';
    
    // Mask password in connection string
    // Pattern: protocol://username:password@host:port/database
    const passwordPattern = /:\/\/([^:]+):([^@]+)@/;
    const masked = connectionString.replace(passwordPattern, (match, username, password) => {
        const maskedPassword = '*'.repeat(Math.min(password.length, 8));
        return `://${username}:${maskedPassword}@`;
    });
    
    return masked;
}

// Test database connection
async function testDatabaseConnection() {
    const testBtn = document.getElementById('testDbBtn');
    const statusBadge = document.getElementById('dbStatusBadge');
    const statusMessage = document.getElementById('dbStatusMessage');
    const connectionTimeEl = document.getElementById('dbConnectionTime');
    
    // Disable button and show loading state
    if (testBtn) {
        testBtn.disabled = true;
        testBtn.innerHTML = `
            <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
            </svg>
            Testing...
        `;
    }
    
    // Update status to testing
    if (statusBadge) {
        statusBadge.innerHTML = `
            <div class="w-2 h-2 bg-yellow-400 rounded-full animate-pulse"></div>
            <span class="text-sm text-yellow-300">Testing...</span>
        `;
    }
    
    if (statusMessage) {
        statusMessage.textContent = 'Connecting to database...';
        statusMessage.className = 'text-slate-400 text-sm';
    }
    
    try {
        const response = await fetch(`/api/${userId}/${apiSlug}/test-database-connection`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        // Update UI based on result
        if (result.success) {
            // Success state
            if (statusBadge) {
                statusBadge.innerHTML = `
                    <div class="w-2 h-2 bg-green-400 rounded-full"></div>
                    <span class="text-sm text-green-300">Connected</span>
                `;
                statusBadge.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-green-500/20 border border-green-500/30';
            }
            
            if (statusMessage) {
                statusMessage.textContent = result.message || 'Database connection successful!';
                statusMessage.className = 'text-green-300 text-sm';
            }
            
            // Show connection time
            if (connectionTimeEl && result.connection_time_ms) {
                connectionTimeEl.textContent = `Connection established in ${result.connection_time_ms.toFixed(2)}ms`;
                connectionTimeEl.className = 'mt-2 text-xs text-green-400';
                connectionTimeEl.classList.remove('hidden');
            }
        } else {
            // Error state
            if (statusBadge) {
                statusBadge.innerHTML = `
                    <div class="w-2 h-2 bg-red-400 rounded-full"></div>
                    <span class="text-sm text-red-300">Failed</span>
                `;
                statusBadge.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-red-500/20 border border-red-500/30';
            }
            
            if (statusMessage) {
                statusMessage.textContent = result.message || 'Failed to connect to database';
                statusMessage.className = 'text-red-300 text-sm';
            }
            
            if (connectionTimeEl) {
                connectionTimeEl.classList.add('hidden');
            }
        }
    } catch (error) {
        console.error('Error testing database connection:', error);
        
        // Error state
        if (statusBadge) {
            statusBadge.innerHTML = `
                <div class="w-2 h-2 bg-red-400 rounded-full"></div>
                <span class="text-sm text-red-300">Error</span>
            `;
            statusBadge.className = 'flex items-center gap-2 px-3 py-1 rounded-full bg-red-500/20 border border-red-500/30';
        }
        
        if (statusMessage) {
            statusMessage.textContent = `Error: ${error.message}`;
            statusMessage.className = 'text-red-300 text-sm';
        }
        
        if (connectionTimeEl) {
            connectionTimeEl.classList.add('hidden');
        }
    } finally {
        // Re-enable button
        if (testBtn) {
            testBtn.disabled = false;
            testBtn.innerHTML = `
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                Test Connection
            `;
        }
    }
}

// Show database upgrade message for old APIs
function showDatabaseUpgradeMessage() {
    const databaseTabContent = document.getElementById('databaseTab');
    if (!databaseTabContent) return;
    
    // Replace the content with an upgrade message
    databaseTabContent.innerHTML = `
        <div class="space-y-6">
            <div class="text-center py-12">
                <div class="w-20 h-20 bg-gradient-to-r from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center mx-auto mb-6">
                    <svg class="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"></path>
                    </svg>
                </div>
                <h3 class="text-2xl font-bold text-white mb-4">Database Configuration Not Available</h3>
                <p class="text-slate-300 text-lg mb-6 max-w-2xl mx-auto">
                    This API was created before database configuration tracking was added. 
                    You can add database connection details through our chat interface.
                </p>
                
                <div class="bg-blue-500/10 border border-blue-500/30 rounded-lg p-6 max-w-2xl mx-auto mb-6">
                    <div class="flex items-start gap-3 text-left">
                        <svg class="w-6 h-6 text-blue-400 flex-shrink-0 mt-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                        </svg>
                        <div class="text-sm text-blue-300">
                            <p class="font-medium mb-2">How to add database configuration:</p>
                            <ol class="list-decimal list-inside space-y-1 text-blue-200/80">
                                <li>Go to the chat interface</li>
                                <li>Tell the AI you want to add/update database connection for this API</li>
                                <li>Provide your database credentials (host, port, database name, etc.)</li>
                                <li>The API will be updated with database integration</li>
                            </ol>
                        </div>
                    </div>
                </div>
                
                <div class="flex flex-col sm:flex-row gap-4 justify-center items-center">
                    <button onclick="addDatabaseConfig()" class="action-btn btn-primary px-8 py-3 text-lg">
                        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"></path>
                        </svg>
                        Add Database Configuration
                    </button>
                    <button onclick="goBack()" class="action-btn btn-secondary px-6 py-3">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"></path>
                        </svg>
                        Go Back
                    </button>
                </div>
            </div>
        </div>
    `;
}

// Add database configuration for old APIs
function addDatabaseConfig() {
    // Redirect to chat with a pre-filled message about adding database config
    const message = encodeURIComponent(`I want to add database configuration to my existing API "${apiSlug}". Can you help me connect it to my database?`);
    window.location.href = `/chat?api_slug=${apiSlug}&message=${message}`;
}

// Modify database configuration
function modifyDatabaseConfig() {
    // Redirect to chat with a pre-filled message about modifying database config
    const message = encodeURIComponent(`I want to modify the database configuration for my API "${apiSlug}". Can you help me update the connection settings?`);
    window.location.href = `/chat?api_slug=${apiSlug}&message=${message}`;
}

// Tab switching
function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.add('hidden');
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(tabName + 'Tab').classList.remove('hidden');
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    
    // Load tab-specific data
    if (tabName === 'usage') {
        loadUsageData();
    } else if (tabName === 'versions') {
        loadVersions();
    } else if (tabName === 'domains') {
        loadDomains();
    } else if (tabName === 'database') {
        // Check if we need to show upgrade message for old APIs
        if (window.showDbUpgradeMessage && !window.apiHasDatabaseConfig) {
            showDatabaseUpgradeMessage();
            window.showDbUpgradeMessage = false; // Only show once
        }
    }
}

// Domain Management Functions

// Make loadDomains globally accessible for debugging
window.loadDomains = loadDomains;
window.debugDomains = function() {
    console.log('=== DOMAIN DEBUG INFO ===');
    console.log('userId:', userId);
    console.log('apiSlug:', apiSlug);
    console.log('Current URL:', window.location.href);
    loadDomains();
};

async function loadDomains() {
    const domainsList = document.getElementById('domainsList');
    if (!domainsList) {
        console.warn('domainsList element not found');
        return;
    }
    
    domainsList.innerHTML = '<div class="text-center py-8 text-slate-400">Loading domains...</div>';
    
    try {
        console.log(`Loading domains for API: ${apiSlug}, User: ${userId}`);
        
        // Try with api_slug filter first
        let response = await fetch(`/api/domains?api_slug=${apiSlug}`);
        
        if (!response.ok) {
            console.error(`Domains API returned status ${response.status}`);
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        let result = await response.json();
        console.log('Domains API response (filtered by api_slug):', result);
        console.log('Number of domains found:', result.domains ? result.domains.length : 0);
        
        // If no domains found with filter, try without filter to see all user domains
        if (result.success && (!result.domains || result.domains.length === 0)) {
            console.log('No domains found with api_slug filter, trying without filter...');
            response = await fetch(`/api/domains`);
            if (response.ok) {
                result = await response.json();
                console.log('Domains API response (all user domains):', result);
                console.log('Total user domains found:', result.domains ? result.domains.length : 0);
            }
        }
        
        if (!result.success) {
            console.error('Domains API returned success=false:', result);
            throw new Error(result.detail || result.message || 'Failed to load domains');
        }
        
        if (!result.domains || result.domains.length === 0) {
            console.log('❌ No domains found to display');
            domainsList.innerHTML = `
                <div class="text-center py-8 text-slate-400">
                    <div class="w-16 h-16 bg-slate-700/50 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg class="w-8 h-8 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9"></path>
                        </svg>
                    </div>
                    <p class="text-lg font-medium text-slate-300 mb-2">No Custom Domains</p>
                    <p class="text-sm">Add a custom domain to access your API via your own domain name.</p>
                    <button onclick="window.debugDomains()" class="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-sm">
                        🔍 Debug Domains
                    </button>
                </div>
            `;
            return;
        }
        
        console.log(`Loading ${result.domains.length} domain(s)`);
        
        const html = result.domains.map(domain => {
            let statusBadge = '';
            let actionButton = '';
            
            // Status Badge
            switch (domain.status) {
                case 'active':
                    statusBadge = '<span class="px-2 py-1 bg-green-500/20 text-green-300 rounded text-xs border border-green-500/30">Active</span>';
                    break;
                case 'verified':
                    statusBadge = '<span class="px-2 py-1 bg-blue-500/20 text-blue-300 rounded text-xs border border-blue-500/30">Verified</span>';
                    break;
                case 'verifying':
                    statusBadge = '<span class="px-2 py-1 bg-yellow-500/20 text-yellow-300 rounded text-xs border border-yellow-500/30">Verifying...</span>';
                    break;
                case 'failed':
                    statusBadge = '<span class="px-2 py-1 bg-red-500/20 text-red-300 rounded text-xs border border-red-500/30">Failed</span>';
                    break;
                default:
                    statusBadge = '<span class="px-2 py-1 bg-slate-500/20 text-slate-300 rounded text-xs border border-slate-500/30">Pending</span>';
            }
            
            // Action Button
            if (domain.status === 'pending' || domain.status === 'failed') {
                actionButton = `
                    <button onclick="openVerifyDomainModal('${domain.id}', '${domain.domain}', '${domain.verification_token}')" 
                            class="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-medium transition-colors">
                        Verify
                    </button>
                `;
            }
            
            // SSL Status
            let sslStatus = '';
            if (domain.ssl_certificate_status === 'issued') {
                sslStatus = '<span class="text-green-400 text-xs flex items-center gap-1"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path></svg> SSL Active</span>';
            }
            
            return `
                <div class="glass-card p-4 rounded-xl border border-slate-700/50 flex justify-between items-center hover:border-slate-600 transition-colors">
                    <div>
                        <div class="flex items-center space-x-3 mb-1">
                            <span class="text-lg font-semibold text-white">${domain.domain}</span>
                            ${statusBadge}
                        </div>
                        <div class="flex items-center gap-4 text-xs text-slate-400">
                            <span>Added: ${new Date(domain.created_at).toLocaleDateString()}</span>
                            ${sslStatus}
                        </div>
                        ${domain.error_message ? `<div class="text-red-400 text-xs mt-1">${domain.error_message}</div>` : ''}
                    </div>
                    <div class="flex items-center gap-3">
                        ${actionButton}
                        <button onclick="deleteDomain('${domain.id}')" class="text-slate-400 hover:text-red-400 transition-colors p-1">
                            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                            </svg>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
        
        domainsList.innerHTML = html;
        
    } catch (error) {
        console.error('Error loading domains:', error);
        domainsList.innerHTML = `<div class="text-center py-8 text-red-400">Error loading domains: ${error.message}</div>`;
    }
}

// Domain Modal Functions
function openAddDomainModal() {
    document.getElementById('addDomainModal').classList.remove('hidden');
    document.getElementById('addDomainModal').classList.add('flex');
}

function closeAddDomainModal() {
    document.getElementById('addDomainModal').classList.add('hidden');
    document.getElementById('addDomainModal').classList.remove('flex');
    document.getElementById('addDomainForm').reset();
}

async function handleAddDomain(event) {
    event.preventDefault();
    
    const domainInput = document.getElementById('domainInput');
    const domain = domainInput.value.trim();
    
    if (!domain) return;
    
    try {
        const submitBtn = event.target.querySelector('button[type="submit"]');
        const originalText = submitBtn.textContent;
        submitBtn.disabled = true;
        submitBtn.textContent = 'Adding...';
        
        console.log('Adding domain:', domain);
        console.log('For API slug:', apiSlug);
        console.log('User ID:', userId);
        
        const requestBody = {
            domain: domain,
            api_slug: apiSlug,
            verification_method: 'dns_txt'
        };
        console.log('Request body:', requestBody);
        
        const response = await fetch('/api/domains', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // Show appropriate message based on whether it's a new domain or existing one
            const message = result.message || 'Domain added successfully';
            showNotification(message, result.message && result.message.includes('previously registered') ? 'info' : 'success');
            closeAddDomainModal();
            loadDomains();
            
            // Open verification modal
            if (result.domain) {
                openVerifyDomainModal(result.domain.id, result.domain.domain, result.domain.verification_token);
            }
        } else {
            const errorMessage = result.detail || result.message || 'Failed to add domain';
            showNotification(errorMessage, 'error');
            
            // If the error is about domain already being verified/active, refresh the domains list
            // so the user can see it
            if (errorMessage.includes('already') && (errorMessage.includes('verified') || errorMessage.includes('active'))) {
                console.log('Domain already exists and is verified/active, refreshing domains list...');
                closeAddDomainModal();
                loadDomains();
            }
        }
        
    } catch (error) {
        showNotification('Error adding domain: ' + error.message, 'error');
    } finally {
        const submitBtn = event.target.querySelector('button[type="submit"]');
        submitBtn.disabled = false;
        submitBtn.textContent = 'Add Domain';
    }
}

function openVerifyDomainModal(domainId, domain, token) {
    const modal = document.getElementById('verifyDomainModal');
    const dnsHostDisplay = document.getElementById('dnsHostDisplay');
    const dnsValueDisplay = document.getElementById('dnsValueDisplay');
    const dnsHostDisplayInline = document.getElementById('dnsHostDisplayInline');
    const dnsSubdomainDisplayInline = document.getElementById('dnsSubdomainDisplayInline');
    const dnsValueDisplayInline = document.getElementById('dnsValueDisplayInline');
    const verifyBtn = document.getElementById('verifyBtn');
    const statusDiv = document.getElementById('verificationStatus');
    
    // Set data attributes for verify function
    modal.dataset.domainId = domainId;
    
    // Set display values
    // For subdomain: _bucketapi-verify.sub
    // For root: _bucketapi-verify
    const isSubdomain = domain.split('.').length > 2;
    const hostPrefix = '_bucketapi-verify';
    const hostDisplay = isSubdomain ? `${hostPrefix}.${domain}` : `${hostPrefix}.${domain}`;
    
    dnsHostDisplay.textContent = hostDisplay;
    dnsValueDisplay.textContent = token;
    
    // Also set inline display values for instructions
    if (dnsHostDisplayInline) {
        dnsHostDisplayInline.textContent = hostDisplay;
    }
    // Extract just the subdomain part (for providers like Dynadot)
    if (dnsSubdomainDisplayInline) {
        // Extract the subdomain part: _bucketapi-verify from _bucketapi-verify.loopfeedback.dev
        const subdomainPart = hostDisplay.split('.')[0];
        dnsSubdomainDisplayInline.textContent = subdomainPart;
    }
    if (dnsValueDisplayInline) {
        dnsValueDisplayInline.textContent = token;
    }
    
    // Reset UI state
    statusDiv.className = 'hidden p-4 rounded-lg text-sm';
    verifyBtn.disabled = false;
    verifyBtn.textContent = 'Verify Now';
    
    modal.classList.remove('hidden');
    modal.classList.add('flex');
}

function closeVerifyDomainModal() {
    document.getElementById('verifyDomainModal').classList.add('hidden');
    document.getElementById('verifyDomainModal').classList.remove('flex');
}

async function verifyDomain() {
    const modal = document.getElementById('verifyDomainModal');
    const domainId = modal.dataset.domainId;
    const verifyBtn = document.getElementById('verifyBtn');
    const statusDiv = document.getElementById('verificationStatus');
    
    if (!domainId) return;
    
    try {
        verifyBtn.disabled = true;
        verifyBtn.innerHTML = '<svg class="w-4 h-4 animate-spin inline mr-2" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Verifying...';
        
        const response = await fetch(`/api/domains/${domainId}/verify`, {
            method: 'POST'
        });
        
        const result = await response.json();
        
        statusDiv.classList.remove('hidden', 'bg-red-500/20', 'text-red-300', 'bg-green-500/20', 'text-green-300', 'bg-yellow-500/20', 'text-yellow-300');
        
        // Check if verification was successful (status can be 'verified' or 'VERIFIED')
        const isVerified = result.success && (result.status === 'verified' || result.status === 'VERIFIED');
        
        if (isVerified) {
            statusDiv.classList.add('bg-green-500/20', 'text-green-300');
            statusDiv.innerHTML = `
                <div class="flex items-center gap-2">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
                    Domain verified successfully!
                </div>
            `;
            
            // Refresh domains list immediately
            loadDomains();
            
            setTimeout(() => {
                closeVerifyDomainModal();
                // Switch to domains tab and refresh to ensure UI is updated
                switchTab('domains');
            }, 2000);
        } else {
            const statusStr = result.status?.toLowerCase() || '';
            const isPending = statusStr === 'pending' || statusStr === 'verifying';
            statusDiv.classList.add(isPending ? 'bg-yellow-500/20' : 'bg-red-500/20', isPending ? 'text-yellow-300' : 'text-red-300');
            statusDiv.textContent = result.message || 'Verification failed. Please check your DNS records and try again.';
            
            // Still refresh domains list to show updated status
            loadDomains();
        }
        
    } catch (error) {
        statusDiv.classList.remove('hidden');
        statusDiv.classList.add('bg-red-500/20', 'text-red-300');
        statusDiv.textContent = 'Error verifying domain: ' + error.message;
    } finally {
        verifyBtn.disabled = false;
        verifyBtn.textContent = 'Verify Now';
    }
}

async function deleteDomain(domainId) {
    if (!confirm('Are you sure you want to remove this domain? This will stop all traffic to your API via this domain.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/domains/${domainId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showNotification('Domain removed successfully');
            loadDomains();
        } else {
            const result = await response.json();
            showNotification(result.detail || 'Failed to remove domain', 'error');
        }
    } catch (error) {
        showNotification('Error removing domain: ' + error.message, 'error');
    }
}

function copyText(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        navigator.clipboard.writeText(element.textContent);
        showNotification('Copied to clipboard!');
    }
}

// Action functions
function goBack() {
    window.history.back();
}

function testAPI() {
    switchTab('test');
}

function viewDocs() {
    window.open(`/api/${userId}/${apiSlug}/docs`, '_blank');
}

function modifyAPI() {
    if (!apiSlug || !userId) {
        showNotification('Unable to modify API - missing API identifier', 'error');
        return;
    }
    // Navigate to the main chat page (/) with the modify parameter and user_id
    window.location.href = `/?modify=${apiSlug}&user_id=${userId}`;
}

function quickPreview() {
    const previewSection = document.getElementById('quickPreviewSection');
    const isHidden = previewSection.classList.contains('hidden');
    
    if (isHidden) {
        previewSection.classList.remove('hidden');
        // Scroll to the preview section
        previewSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else {
        previewSection.classList.add('hidden');
    }
}

async function runAPITestDetails() {
    const testInput = document.getElementById('testInput').value;
    const testStatusEl = document.getElementById('testStatus');
    const testStatusTextEl = document.getElementById('testStatusText');
    const runTestBtn = document.getElementById('runTestBtn');
    const responseBodyEl = document.getElementById('responseBody');
    const responseHeadersEl = document.getElementById('responseHeadersContent');
    const responseStatusEl = document.getElementById('responseStatus');
    const responseTimeEl = document.getElementById('responseTime');
    const testResultsDiv = document.getElementById('testResults');

    // Safety check - ensure button exists before proceeding
    if (!runTestBtn) {
        console.error('Test button not found');
        return;
    }

    // Update UI to show testing in progress
    runTestBtn.disabled = true;
    runTestBtn.innerHTML = `
        <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
        </svg>
        <span>Testing...</span>
    `;
    
    if (testStatusEl) {
        testStatusEl.className = 'w-3 h-3 bg-yellow-500 rounded-full animate-pulse';
    }
    if (testStatusTextEl) {
        testStatusTextEl.textContent = 'Running test...';
        testStatusTextEl.className = 'text-sm text-yellow-400';
    }

    const startTime = Date.now();

    try {
        // Prepare request data for the backend test endpoint
        const testData = {
            user_id: userId,
            api_slug: apiSlug,
            test_type: 'manual'
        };

        // Add test data if provided
        const testInputValue = testInput.trim();
        if (testInputValue) {
            try {
                // Validate JSON if provided
                const parsedData = JSON.parse(testInputValue);
                testData.test_data = parsedData;
            } catch (jsonError) {
                throw new Error('Invalid JSON format in test input');
            }
        }

        // Call the backend test endpoint
        const response = await fetch('/test-api', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(testData)
        });

        const endTime = Date.now();
        const requestTime = endTime - startTime;

        // Get response data
        const testResult = await response.json();

        // Update UI with results
        testResultsDiv.classList.remove('hidden');

        // Response status - use the actual API status from the test result
        const actualStatusCode = testResult.status_code || response.status;
        const actualStatusText = testResult.success ? 'OK' : (testResult.error ? 'Error' : response.statusText);

        responseStatusEl.textContent = `${actualStatusCode} ${actualStatusText}`;
        responseStatusEl.className = testResult.success ? 
            'px-2 py-1 bg-green-600/20 text-green-300 rounded text-xs font-mono' :
            'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';

        // Use execution time from the test result if available, otherwise use request time
        const executionTimeMs = testResult.execution_time ? Math.round(testResult.execution_time * 1000) : requestTime;
        responseTimeEl.textContent = `${executionTimeMs}ms`;
        
        // Display pricing information if available
        if (testResult.response_headers) {
            const costPerCall = testResult.response_headers['x-cost-per-call-cents'];
            const tokensPerCall = testResult.response_headers['x-internal-tokens-per-call'];
            const aiModel = testResult.response_headers['x-ai-model-used'];
            
            if (costPerCall && tokensPerCall) {
                // Create or update pricing display
                let pricingEl = document.getElementById('api-pricing-info');
                if (!pricingEl) {
                    pricingEl = document.createElement('div');
                    pricingEl.id = 'api-pricing-info';
                    pricingEl.className = 'mt-4 p-3 bg-blue-900/30 border border-blue-500/30 rounded-lg';
                    testResultsDiv.appendChild(pricingEl);
                }
                
                const isFirstTimeAnalysis = testResult.response_headers['x-first-time-analysis'] === 'true';
                const analysisNote = isFirstTimeAnalysis ? 
                    '<div class="text-xs text-blue-300 mt-1"><strong>Note:</strong> Pricing calculated by analyzing your API code</div>' : '';
                
                pricingEl.innerHTML = `
                    <div class="text-sm font-medium text-blue-200 mb-2"><strong>API Pricing Information</strong></div>
                    <div class="grid grid-cols-2 gap-4 text-xs">
                        <div>
                            <span class="text-gray-400">Cost per call:</span>
                            <span class="text-green-300 font-mono ml-2">${costPerCall}$</span>
                        </div>
                        <div>
                            <span class="text-gray-400">Tokens per call:</span>
                            <span class="text-blue-300 font-mono ml-2">${tokensPerCall}</span>
                        </div>
                        <div>
                            <span class="text-gray-400">AI Model:</span>
                            <span class="text-purple-300 font-mono ml-2">${aiModel || 'none'}</span>
                        </div>
                        <div>
                            <span class="text-gray-400">Processing:</span>
                            <span class="text-yellow-300 font-mono ml-2">${aiModel === 'none' ? 'Free' : 'AI-Powered'}</span>
                        </div>
                    </div>
                    ${analysisNote}
                `;
            }
        }

        // Response body - show the actual API response or error
        let displayData;
        if (testResult.success && testResult.response_data) {
            displayData = testResult.response_data;
        } else if (testResult.error) {
            displayData = { error: testResult.error };
        } else {
            displayData = testResult;
        }

        // Handle binary data specially
        if (displayData && displayData.result_type === 'binary') {
            responseBodyEl.innerHTML = `
                <div class="space-y-2">
                    <div class="text-blue-300">
                        <div class="text-sm font-semibold mb-2">📦 Binary Data Response</div>
                        <div class="text-xs space-y-1">
                            <div>Type: <span class="text-green-300">${displayData.content_type || 'application/octet-stream'}</span></div>
                            <div>Size: <span class="text-green-300">${displayData.size_bytes} bytes</span></div>
                            <div class="text-slate-400">${displayData.message || 'Binary data returned successfully'}</div>
                        </div>
                    </div>
                    ${displayData.data_base64 && displayData.data_base64.startsWith('iVBORw') ? `
                        <div class="mt-3">
                            <div class="text-xs text-slate-400 mb-2">Preview (PNG Image):</div>
                            <img src="data:image/png;base64,${displayData.data_base64}" 
                                 alt="API Response Image" 
                                 class="max-w-full h-auto rounded border border-slate-600"
                                 style="max-height: 300px;">
                        </div>
                    ` : ''}
                    <div class="mt-2">
                        <button onclick="downloadBinaryResponseDetails('${displayData.data_base64}', '${displayData.content_type}')" 
                                class="px-3 py-1 bg-blue-600/20 text-blue-300 border border-blue-500/30 rounded text-xs hover:bg-blue-600/30 transition-all duration-200">
                            💾 Download Binary Data
                        </button>
                    </div>
                </div>
            `;
        } else {
            responseBodyEl.textContent = typeof displayData === 'object' ? 
                JSON.stringify(displayData, null, 2) : String(displayData);
        }

        // Response headers - use headers from test result
        const headers = testResult.response_headers || {};
        responseHeadersEl.textContent = JSON.stringify(headers, null, 2);

        // Update status based on test result
        if (testResult.success) {
            testStatusEl.className = 'w-3 h-3 bg-green-500 rounded-full';
            testStatusTextEl.textContent = 'Test successful';
            testStatusTextEl.className = 'text-sm text-green-400';
        } else {
            testStatusEl.className = 'w-3 h-3 bg-red-500 rounded-full';
            testStatusTextEl.textContent = 'Test failed';
            testStatusTextEl.className = 'text-sm text-red-400';
        }

    } catch (error) {
        // Handle errors
        testResultsDiv.classList.remove('hidden');

        responseStatusEl.textContent = 'Error';
        responseStatusEl.className = 'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';

        responseTimeEl.textContent = `${Date.now() - startTime}ms`;
        responseBodyEl.textContent = `Error: ${error.message}`;
        responseHeadersEl.textContent = 'No headers (request failed)';

        testStatusEl.className = 'w-3 h-3 bg-red-500 rounded-full';
        testStatusTextEl.textContent = 'Test error';
        testStatusTextEl.className = 'text-sm text-red-400';
    } finally {
        // Reset button - with safety checks
        if (runTestBtn) {
            runTestBtn.disabled = false;
            runTestBtn.innerHTML = `
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1m4 0h1m-6 4h1m4 0h1m6-10V7a3 3 0 11-6 0V4h6zM4 7v10a2 2 0 002 2h12a2 2 0 002-2V7"></path>
                </svg>
                <span>Run Test</span>
            `;
        }
    }
}

async function quickTest() {
    // Switch to test tab and load example data (without auto-running test)
    switchTab('test');
    
    // Load example data
    loadExample();
    
    // Optional: Show a message that user can now run the test manually
    // The test will not run automatically anymore
}

function clearTestData() {
    document.getElementById('testInput').value = '';
    document.getElementById('testResults').classList.add('hidden');
}

function loadExample() {
    // Load example based on API type
    const exampleData = {
        "message": "Hello World",
        "data": "sample input",
        "timestamp": new Date().toISOString()
    };
    document.getElementById('testInput').value = JSON.stringify(exampleData, null, 2);
}

function copyEndpoint() {
    navigator.clipboard.writeText(apiData.endpoint_url);
    showNotification('Endpoint URL copied to clipboard!');
}

function copyCurl() {
    const curlElement = document.getElementById('curlExample');
    const curlText = curlElement ? curlElement.textContent : (apiData?.curl_example || 'No cURL example available');
    
    navigator.clipboard.writeText(curlText).then(() => {
        showNotification('cURL command copied to clipboard!');
    }).catch(() => {
        showNotification('Failed to copy cURL command', 'error');
    });
}

function downloadCode() {
    if (!apiData?.code_available) {
        showNotification('Source code not available', 'error');
        return;
    }
    
    const element = document.createElement('a');
    const code = document.getElementById('sourceCode').textContent;
    const file = new Blob([code], {type: 'text/plain'});
    element.href = URL.createObjectURL(file);
    element.download = `${apiSlug}.py`;
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
}

function sharableLink() {
    const url = window.location.href;
    navigator.clipboard.writeText(url);
    showNotification('Sharable link copied to clipboard!');
}

async function deleteAPI() {
    if (!confirm('Are you sure you want to delete this API? This action cannot be undone.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/${userId}/${apiSlug}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            showNotification('API deleted successfully');
            setTimeout(() => {
                window.location.href = '/profile';
            }, 2000);
        } else {
            const error = await response.json();
            showNotification(error.detail || 'Failed to delete API', 'error');
        }
    } catch (error) {
        showNotification('Error deleting API: ' + error.message, 'error');
    }
}

// Utility functions
function showMainContent() {
    document.getElementById('loadingState').classList.add('hidden');
    document.getElementById('mainContent').classList.remove('hidden');
}

function showError(message) {
    document.getElementById('loadingState').innerHTML = `
        <div class="glass-card rounded-2xl p-8 text-center">
            <div class="w-16 h-16 bg-red-600 rounded-xl flex items-center justify-center mx-auto mb-4">
                <svg class="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"></path>
                </svg>
            </div>
            <h2 class="text-xl font-bold text-white mb-2">Error Loading API</h2>
            <p class="text-slate-400">${message}</p>
            <button onclick="goBack()" class="action-btn btn-secondary mt-4">Go Back</button>
        </div>
    `;
}

function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    notification.className = `notification ${type}`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

function formatDate(dateString) {
    if (!dateString) return '--';
    return new Date(dateString).toLocaleDateString();
}

function formatDateTime(dateString) {
    if (!dateString) return '--';
    return new Date(dateString).toLocaleString();
}

function formatRelativeTime(dateString) {
    if (!dateString) return '--';
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    return formatDate(dateString);
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substr(0, maxLength) + '...';
}

function formatMarkdown(text) {
    return text
        .replace(/\n/g, '<br>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/`(.*?)`/g, '<code class="bg-slate-700/50 px-1 py-0.5 rounded text-xs font-mono">$1</code>');
}

function formatTestInput() {
    const input = document.getElementById('testInput').value;
    try {
        const formatted = JSON.stringify(JSON.parse(input), null, 2);
        document.getElementById('testInput').value = formatted;
        showNotification('Input data formatted!');
    } catch (e) {
        showNotification('Invalid JSON input. Please enter a valid JSON object.', 'error');
    }
}

function extractAPINameFromPrompt(promptText, fallbackName) {
    if (!promptText || typeof promptText !== 'string') return fallbackName;
    
    // Try to extract API name from structured prompt
    // Pattern: "API Name: ..." or "Name: ..."
    const nameMatch = promptText.match(/(?:API Name|Name):\s*([^\n]+)/i);
    if (nameMatch && nameMatch[1]) {
        return nameMatch[1].trim();
    }
    
    // Try to extract from prompt that starts with name
    const inlineMatch = promptText.match(/^([^\n:]+?)(?:\s+Description:)/i);
    if (inlineMatch && inlineMatch[1]) {
        return inlineMatch[1].trim();
    }
    
    // Return the fallback name
    return fallbackName;
}

function extractOriginalUserRequest(promptText) {
    if (!promptText || typeof promptText !== 'string') return null;
    
    // Try to extract "Original User Request:" section if present
    const originalRequestMatch = promptText.match(/Original User Request:\s*(.+)$/i);
    if (originalRequestMatch && originalRequestMatch[1]) {
        return originalRequestMatch[1].trim();
    }
    
    // If prompt starts with simple user request (not "Build an API with these specifications:")
    if (!promptText.match(/^Build an API with these specifications:/i) && promptText.length < 500) {
        // Looks like a simple user request, return it
        return promptText.trim();
    }
    
    return null;
}

function extractDescriptionFromPrompt(promptText) {
    if (!promptText || typeof promptText !== 'string') return 'No description available';
    
    // Try to extract description from structured prompt
    // Pattern: "Description: ..." followed by potential continuation lines until next section
    const descMatch = promptText.match(/Description:\s*([^\n]+(?:\n(?!\s*(?:Functionality:|Endpoints:|Input Format:|Output Format:|API Name:))[^\n]*)*)/i);
    if (descMatch && descMatch[1]) {
        let description = descMatch[1].trim();
        // Clean up description - remove any remaining headers
        description = description.replace(/^\s*(API Name:|Name:|Functionality:).*$/gmi, '');
        description = description.replace(/\n\s*(Functionality:|Endpoints:|Input Format:|Output Format:).*/i, '');
        return description.trim();
    }
    
    // If no structured format, try to extract from common patterns
    // Remove common prefixes like "Build an API with these specifications:"
    let cleaned = promptText.replace(/^Build an API with these specifications:\s*/i, '');
    
    // Remove "API Name: ..." if present
    cleaned = cleaned.replace(/API Name:\s*[^\n]+\n?\s*/i, '');
    
    // If it starts with "Description:", extract it
    const descMatch2 = cleaned.match(/^Description:\s*((?:.|\n)+?)(?:\n\s*(?:Functionality:|Endpoints:|Input Format:|Output Format:)|$)/i);
    if (descMatch2) {
        return descMatch2[1].trim();
    }
    
    // If the prompt looks like "Name: X Description: Y", extract description
    const simpleDescMatch = cleaned.match(/Description:\s*(.+?)(?:\n|$)/is);
    if (simpleDescMatch && simpleDescMatch[1].trim()) {
        return simpleDescMatch[1].trim();
    }
    
    // If no Description: found, try to extract any meaningful text after removing boilerplate
    cleaned = cleaned.replace(/^(API Name:.*?\n)?/i, '');
    if (cleaned && cleaned.trim() && cleaned.length > 10) {
        // Return cleaned text, but only up to first major section
        const firstSection = cleaned.split(/\n\s*(?:Functionality:|Endpoints:|Input Format:|Output Format:)/i)[0];
        return firstSection.trim();
    }
    
    // Fallback: return the prompt itself
    return promptText;
}

// Usage Data Loading Functions
async function loadUsageData() {
    try {
        showUsageLoading();
        
        const response = await fetch(`/api/${userId}/${apiSlug}/usage-stats?days=30`);
        const data = await response.json();
        
        if (response.ok) {
            populateUsageData(data);
        } else {
            showUsageError(data.detail || 'Failed to load usage data');
        }
    } catch (error) {
        console.error('Error loading usage data:', error);
        showUsageError('Network error: ' + error.message);
    }
}

function populateUsageData(data) {
    try {
        // Update overview metrics
        if (data.usage_stats) {
            const stats = data.usage_stats;
            document.getElementById('totalExecutions').textContent = stats.total_executions || 0;
            document.getElementById('successfulExecutions').textContent = stats.successful_executions || 0;
            document.getElementById('failedExecutions').textContent = stats.failed_executions || 0;
            
            // Update token usage
            document.getElementById('avgTokens').textContent = stats.avg_total_tokens ? Math.round(stats.avg_total_tokens) : '--';
            document.getElementById('maxTokens').textContent = stats.max_tokens_used || '--';
            document.getElementById('minTokens').textContent = stats.min_tokens_used || '--';
            document.getElementById('primaryModel').textContent = stats.primary_model_used || 'none';
            
            // Update cost analysis
            const avgCostCents = stats.avg_cost_per_call_cents || 0;
            const totalCostCents = stats.total_cost_cents || 0;
            const maxCostCents = stats.max_cost_per_call_cents || 0;
            
            document.getElementById('avgCost').textContent = avgCostCents > 0 ? `${avgCostCents.toFixed(4)}$` : 'Free';
            document.getElementById('totalCost').textContent = totalCostCents > 0 ? `${totalCostCents.toFixed(2)}$` : 'Free';
            document.getElementById('maxCost').textContent = maxCostCents > 0 ? `${maxCostCents.toFixed(4)}$` : 'Free';
            document.getElementById('processingType').textContent = stats.primary_model_used && stats.primary_model_used !== 'none' ? 'AI-Powered' : 'Free';
        } else {
            // No usage data available
            document.getElementById('totalExecutions').textContent = '0';
            document.getElementById('successfulExecutions').textContent = '0';
            document.getElementById('failedExecutions').textContent = '0';
            document.getElementById('avgTokens').textContent = '--';
            document.getElementById('maxTokens').textContent = '--';
            document.getElementById('minTokens').textContent = '--';
            document.getElementById('primaryModel').textContent = 'none';
            document.getElementById('avgCost').textContent = 'Free';
            document.getElementById('totalCost').textContent = 'Free';
            document.getElementById('maxCost').textContent = 'Free';
            document.getElementById('processingType').textContent = 'Free';
        }
        
        // Update recent executions
        populateRecentExecutions(data.recent_executions || []);
        
        // Update usage timeline
        populateUsageTimeline(data);
        
    } catch (error) {
        console.error('Error populating usage data:', error);
        showUsageError('Failed to display usage data: ' + error.message);
    }
}

function populateRecentExecutions(executions) {
    const container = document.getElementById('recentExecutions');
    
    if (!executions || executions.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8 text-slate-400">
                No recent executions found
            </div>
        `;
        return;
    }
    
    const executionHtml = executions.map(execution => {
        const statusClass = execution.success ? 'text-green-400' : 'text-red-400';
        const statusIcon = execution.success ? 'Success' : 'Failed';
        const date = new Date(execution.created_at).toLocaleString();
        
        return `
            <div class="flex items-center justify-between p-3 bg-slate-800/30 rounded-lg border border-slate-600/30">
                <div class="flex items-center space-x-3">
                    <span class="${statusClass} font-mono text-lg">${statusIcon}</span>
                    <div>
                        <div class="text-white text-sm font-medium">${execution.api_slug}</div>
                        <div class="text-slate-400 text-xs">${date}</div>
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-slate-300 text-sm">${execution.execution_time_ms}ms</div>
                    <div class="text-slate-400 text-xs">
                        ${formatBytes(execution.input_data_size + execution.output_data_size)}
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = executionHtml;
}

function populateUsageTimeline(data) {
    const container = document.getElementById('usageTimeline');
    
    if (!data.has_usage_data) {
        container.innerHTML = `
            <div class="text-center py-8 text-slate-400">
                No usage data available for the selected period
            </div>
        `;
        return;
    }
    
    // Simple timeline representation
    const stats = data.usage_stats;
    const timelineHtml = `
        <div class="space-y-4">
            <div class="flex items-center justify-between p-4 bg-slate-800/30 rounded-lg border border-slate-600/30">
                <div>
                    <div class="text-white font-medium">First Execution</div>
                    <div class="text-slate-400 text-sm">${new Date(stats.first_execution).toLocaleDateString()}</div>
                </div>
                <div class="text-right">
                    <div class="text-blue-400 font-mono">${stats.total_executions} calls</div>
                    <div class="text-slate-400 text-sm">Total</div>
                </div>
            </div>
            <div class="flex items-center justify-between p-4 bg-slate-800/30 rounded-lg border border-slate-600/30">
                <div>
                    <div class="text-white font-medium">Last Execution</div>
                    <div class="text-slate-400 text-sm">${new Date(stats.last_execution).toLocaleDateString()}</div>
                </div>
                <div class="text-right">
                    <div class="text-green-400 font-mono">${((stats.successful_executions / stats.total_executions) * 100).toFixed(1)}%</div>
                    <div class="text-slate-400 text-sm">Success Rate</div>
                </div>
            </div>
        </div>
    `;
    
    container.innerHTML = timelineHtml;
}

function showUsageLoading() {
    // Show loading state for all usage elements
    const loadingText = 'Loading...';
    document.getElementById('totalExecutions').textContent = loadingText;
    document.getElementById('successfulExecutions').textContent = loadingText;
    document.getElementById('failedExecutions').textContent = loadingText;
    document.getElementById('avgTokens').textContent = loadingText;
    document.getElementById('maxTokens').textContent = loadingText;
    document.getElementById('minTokens').textContent = loadingText;
    document.getElementById('primaryModel').textContent = loadingText;
    document.getElementById('avgCost').textContent = loadingText;
    document.getElementById('totalCost').textContent = loadingText;
    document.getElementById('maxCost').textContent = loadingText;
    document.getElementById('processingType').textContent = loadingText;
    
    document.getElementById('recentExecutions').innerHTML = `
        <div class="text-center py-8 text-slate-400">
            Loading usage data...
        </div>
    `;
}

function showUsageError(message) {
    document.getElementById('recentExecutions').innerHTML = `
        <div class="text-center py-8 text-red-400">
            Error: ${message}
        </div>
    `;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Function to download binary response data
function downloadBinaryResponseDetails(base64Data, contentType) {
    try {
        // Convert base64 to blob
        const byteCharacters = atob(base64Data);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], { type: contentType || 'application/octet-stream' });
        
        // Create download link
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        
        // Determine file extension from content type
        let extension = 'bin';
        if (contentType) {
            if (contentType.includes('image/png')) extension = 'png';
            else if (contentType.includes('image/jpeg')) extension = 'jpg';
            else if (contentType.includes('image/gif')) extension = 'gif';
            else if (contentType.includes('application/pdf')) extension = 'pdf';
        }
        
        a.download = `api-response.${extension}`;
        document.body.appendChild(a);
        a.click();
        
        // Cleanup
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
        
        // Show success message
        console.log('Binary data downloaded successfully');
    } catch (error) {
        console.error('Failed to download binary data:', error);
        alert('Failed to download binary data');
    }
}

// Version management functions

async function loadVersions() {
    const versionsList = document.getElementById('versionsList');
    
    if (!versionsList) return;
    
    versionsList.innerHTML = '<div class="text-center py-8 text-slate-400">Loading versions...</div>';
    
    try {
        const response = await fetch(`/api/${userId}/${apiSlug}/versions`);
        const versions = await response.json();
        
        if (!response.ok) {
            throw new Error(versions.detail || 'Failed to load versions');
        }
        
        if (versions.length === 0) {
            versionsList.innerHTML = '<div class="text-center py-8 text-slate-400">No version history available</div>';
            return;
        }
        
        // Sort versions descending
        versions.sort((a, b) => b.version - a.version);
        
        const html = versions.map(v => `
            <div class="glass-card p-4 rounded-xl border border-slate-700/50 flex justify-between items-center hover:border-slate-600 transition-colors">
                <div>
                    <div class="flex items-center space-x-3 mb-1">
                        <span class="text-lg font-semibold text-white">Version ${v.version}</span>
                        <span class="text-xs text-slate-500">${new Date(v.created_at).toLocaleString()}</span>
                    </div>
                    <div class="text-slate-400 text-sm italic mb-2">
                        "${v.commit_message || 'No description'}"
                    </div>
                    <div class="text-xs text-slate-500">
                        Prompt: ${truncateText(v.prompt, 100)}
                    </div>
                </div>
                <div class="flex space-x-2">
                    <button onclick="restoreVersion(${v.version})" class="action-btn-compact btn-secondary hover:bg-blue-600/20 hover:text-blue-300 transition-colors">
                        <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                        </svg>
                        Restore
                    </button>
                </div>
            </div>
        `).join('');
        
        versionsList.innerHTML = html;
        
    } catch (error) {
        versionsList.innerHTML = `<div class="text-center py-8 text-red-400">Error: ${error.message}</div>`;
    }
}

async function restoreVersion(version) {
    if (!confirm(`Are you sure you want to restore Version ${version}? Current changes will be overwritten.`)) {
        return;
    }
    
    try {
        showNotification('Restoring version...', 'info');
        const response = await fetch(`/api/${userId}/${apiSlug}/restore/${version}`, {
            method: 'POST'
        });
        const result = await response.json();
        
        if (response.ok) {
            showNotification(`Restored Version ${version} successfully`);
            // Reload details to update code view etc
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            showNotification(result.detail || 'Failed to restore version', 'error');
        }
    } catch (error) {
        showNotification('Error restoring version: ' + error.message, 'error');
    }
}

// ==================== Report Modal Functions ====================

// Make functions globally accessible for inline onclick handlers
window.openReportModal = function() {
    const modal = document.getElementById('reportModal');
    const reportApiName = document.getElementById('reportApiName');
    const reportEndpoint = document.getElementById('reportEndpoint');
    
    if (!modal) {
        console.error('Report modal not found in DOM');
        return;
    }
    
    // Populate API information
    if (apiData) {
        if (reportApiName) reportApiName.textContent = apiData.api_slug || 'Unknown';
        if (reportEndpoint) reportEndpoint.textContent = apiData.endpoint_url || 'Unknown';
    }
    
    // Reset form
    const reportForm = document.getElementById('reportForm');
    if (reportForm) {
        reportForm.reset();
    }
    
    const reportError = document.getElementById('reportError');
    const reportSuccess = document.getElementById('reportSuccess');
    const charCount = document.getElementById('charCount');
    
    if (reportError) reportError.classList.add('hidden');
    if (reportSuccess) reportSuccess.classList.add('hidden');
    if (charCount) charCount.textContent = '0 / 2000';
    
    // Show modal
    modal.classList.add('show');
};

window.closeReportModal = function() {
    const modal = document.getElementById('reportModal');
    if (modal) {
        modal.classList.remove('show');
    }
};

// Character count for description
document.addEventListener('DOMContentLoaded', function() {
    const descriptionField = document.getElementById('reportDescription');
    const charCount = document.getElementById('charCount');
    
    if (descriptionField && charCount) {
        descriptionField.addEventListener('input', function() {
            const length = this.value.length;
            charCount.textContent = `${length} / 2000`;
            
            // Change color based on length
            if (length < 10) {
                charCount.classList.add('text-red-400');
                charCount.classList.remove('text-slate-400', 'text-green-400');
            } else if (length > 1900) {
                charCount.classList.add('text-orange-400');
                charCount.classList.remove('text-slate-400', 'text-green-400');
            } else {
                charCount.classList.add('text-green-400');
                charCount.classList.remove('text-slate-400', 'text-red-400', 'text-orange-400');
            }
        });
    }
    
    // Handle form submission
    const reportForm = document.getElementById('reportForm');
    if (reportForm) {
        reportForm.addEventListener('submit', handleReportSubmit);
    }
    
    // Close modal on outside click
    const modal = document.getElementById('reportModal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeReportModal();
            }
        });
    }
});

async function handleReportSubmit(e) {
    e.preventDefault();
    
    const submitBtn = document.getElementById('submitReportBtn');
    const errorDiv = document.getElementById('reportError');
    const errorText = document.getElementById('reportErrorText');
    const successDiv = document.getElementById('reportSuccess');
    
    // Hide previous messages
    errorDiv.classList.add('hidden');
    successDiv.classList.add('hidden');
    
    // Get form values
    const category = document.getElementById('reportCategory').value;
    const severity = document.querySelector('input[name="severity"]:checked')?.value;
    const description = document.getElementById('reportDescription').value;
    
    // Validate
    if (!category || !severity || !description || description.length < 10) {
        errorText.textContent = 'Please fill in all required fields correctly.';
        errorDiv.classList.remove('hidden');
        return;
    }
    
    // Disable submit button
    submitBtn.disabled = true;
    submitBtn.innerHTML = `
        <svg class="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
        </svg>
        Submitting...
    `;
    
    try {
        const response = await fetch('/api/reports', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                api_user_id: userId,
                api_slug: apiSlug,
                category: category,
                severity: severity,
                description: description,
                endpoint_url: apiData?.endpoint_url || ''
            })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // Show success message
            successDiv.classList.remove('hidden');
            
            // Reset form
            document.getElementById('reportForm').reset();
            
            // Show notification
            showNotification('Report submitted successfully!', 'success');
            
            // Close modal after 2 seconds
            setTimeout(() => {
                closeReportModal();
            }, 2000);
        } else {
            errorText.textContent = result.message || 'Failed to submit report. Please try again.';
            errorDiv.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error submitting report:', error);
        errorText.textContent = 'Network error. Please check your connection and try again.';
        errorDiv.classList.remove('hidden');
    } finally {
        // Re-enable submit button
        submitBtn.disabled = false;
        submitBtn.innerHTML = `
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path>
            </svg>
            Submit Report
        `;
    }
}
