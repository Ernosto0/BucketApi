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
    
    loadAPIDetails();
});

// Load API details
async function loadAPIDetails() {
    try {
        const response = await fetch(`/api/${userId}/${apiSlug}/apidetails`);
        const data = await response.json();
        
        if (response.ok) {
            apiData = data;
            populateAPIDetails(data);
            showMainContent();
        } else {
            showError(data.detail || 'Failed to load API details');
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
        
        if (apiNameEl) apiNameEl.textContent = data.api_name || `API ${apiSlug}`;
        if (apiDescEl) apiDescEl.textContent = truncateText(data.prompt || 'No description available', 120);
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
        if (originalPromptEl) originalPromptEl.textContent = data.prompt || 'No prompt available';
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

        // Response body - show the actual API response or error
        let displayData;
        if (testResult.success && testResult.response_data) {
            displayData = testResult.response_data;
        } else if (testResult.error) {
            displayData = { error: testResult.error };
        } else {
            displayData = testResult;
        }

        responseBodyEl.textContent = typeof displayData === 'object' ? 
            JSON.stringify(displayData, null, 2) : String(displayData);

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

