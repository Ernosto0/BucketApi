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
    
    console.log('Initialized with userId:', userId, 'apiSlug:', apiSlug);
    
    if (!userId || !apiSlug) {
        console.error('Missing userId or apiSlug');
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
    
    // Load usage data when switching to usage tab
    if (tabName === 'usage') {
        loadUsageData();
    } else if (tabName === 'versions') {
        loadVersions();
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
