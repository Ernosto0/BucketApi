// Global variables
let apiData = {
    base_url: "",
    user_id: "",
    api_slug: ""
};

let openApiSpec = null;
let swaggerUI = null;

// Initialize page
document.addEventListener('DOMContentLoaded', function() {
    // Get values from data attributes
    const container = document.querySelector('.docs-container');
    if (container) {
        apiData = {
            base_url: container.getAttribute('data-base-url') || "",
            user_id: container.getAttribute('data-user-id') || "",
            api_slug: container.getAttribute('data-api-slug') || ""
        };
    }
    
    // Validate that we have the required data
    if (!apiData.user_id || !apiData.api_slug) {
        console.error('Missing user_id or api_slug in data attributes');
        return;
    }
    
    loadAPIData();
    parseAndDistributeDocumentation();
    setupInteractiveTest();
    setupSmoothScrolling();
    loadOpenAPISpec();
    processMarkdownContent();
});

// Parse and distribute documentation content to appropriate sections
async function parseAndDistributeDocumentation() {
    try {
        const response = await fetch(`/api/${apiData.user_id}/${apiData.api_slug}/apidetails`);
        const data = await response.json();
        
        // Update API name from prompt
        if (response.ok) {
            updateAPIName(data);
        }
        
        if (response.ok && data.documentation && data.documentation !== 'Documentation not available') {
            const documentation = data.documentation;
            console.log('Documentation content:', documentation.substring(0, 200) + '...');
            
            // Check if this is structured markdown documentation or API proposal data
            if (documentation.includes('### Overview') || documentation.includes('## Documentation') || documentation.includes('### Endpoints')) {
                console.log('Detected structured markdown documentation');
                // This is structured AI-generated documentation
                const sections = parseDocumentationSections(documentation);
                populateDocumentationSections(sections);
            } else {
                console.log('Detected proposal data, extracting clean information');
                // This might be API proposal data, extract relevant information
                const cleanedSections = extractFromProposalData(data);
                populateDocumentationSections(cleanedSections);
            }
        } else {
            console.log('No documentation available, using basic overview');
            // No documentation available, show basic info
            const basicSections = createBasicOverview(data);
            populateDocumentationSections(basicSections);
        }
    } catch (error) {
        console.error('Failed to load and parse documentation:', error);
        // Show fallback content
        const fallbackSections = createFallbackOverview();
        populateDocumentationSections(fallbackSections);
    }
}

// Parse documentation into sections
function parseDocumentationSections(documentation) {
    console.log('Parsing documentation sections from:', documentation.substring(0, 300) + '...');
    
    const sections = {
        overview: '',
        authentication: '',
        endpoints: '',
        requestFormat: '',
        responseFormat: '',
        errorCodes: '',
        usageNotes: '',
        codeExamples: ''
    };
    
    // First try to split by ### sections (direct subsection format)
    const subsections = documentation.split(/^###\s+/m);
    
    if (subsections.length > 1) {
        console.log('Found ### subsections:', subsections.length);
        
        for (let subsection of subsections) {
            subsection = subsection.trim();
            if (!subsection) continue;
            
            console.log('Processing subsection:', subsection.substring(0, 50) + '...');
            
            if (subsection.startsWith('Overview')) {
                sections.overview = subsection.replace(/^Overview\s*/, '').trim();
                console.log('Found overview section');
            } else if (subsection.startsWith('Endpoints')) {
                sections.endpoints = subsection.replace(/^Endpoints\s*/, '').trim();
                console.log('Found endpoints section:', sections.endpoints.substring(0, 100) + '...');
            } else if (subsection.startsWith('Request Format')) {
                sections.requestFormat = subsection.replace(/^Request Format\s*/, '').trim();
                console.log('Found request format section');
            } else if (subsection.startsWith('Response Format')) {
                sections.responseFormat = subsection.replace(/^Response Format\s*/, '').trim();
                console.log('Found response format section');
            } else if (subsection.startsWith('Error Codes')) {
                sections.errorCodes = subsection.replace(/^Error Codes\s*/, '').trim();
                console.log('Found error codes section');
            } else if (subsection.startsWith('Usage Notes')) {
                sections.usageNotes = subsection.replace(/^Usage Notes\s*/, '').trim();
                console.log('Found usage notes section');
            } else if (subsection.startsWith('Code Examples')) {
                sections.codeExamples = subsection.replace(/^Code Examples\s*/, '').trim();
                console.log('Found code examples section');
            }
        }
    } else {
        // Fallback: try to split by ## sections (wrapped in Documentation)
        const docSections = documentation.split(/^##\s+/m);
        
        for (let section of docSections) {
            section = section.trim();
            if (!section) continue;
            
            // Check if this is the Documentation section
            if (section.startsWith('Documentation')) {
                const docContent = section.replace(/^Documentation\s*/, '');
                
                // Parse subsections within Documentation
                const innerSubsections = docContent.split(/^###\s+/m);
                
                for (let subsection of innerSubsections) {
                    subsection = subsection.trim();
                    if (!subsection) continue;
                    
                    if (subsection.startsWith('Overview')) {
                        sections.overview = subsection.replace(/^Overview\s*/, '').trim();
                    } else if (subsection.startsWith('Endpoints')) {
                        sections.endpoints = subsection.replace(/^Endpoints\s*/, '').trim();
                    } else if (subsection.startsWith('Request Format')) {
                        sections.requestFormat = subsection.replace(/^Request Format\s*/, '').trim();
                    } else if (subsection.startsWith('Response Format')) {
                        sections.responseFormat = subsection.replace(/^Response Format\s*/, '').trim();
                    } else if (subsection.startsWith('Error Codes')) {
                        sections.errorCodes = subsection.replace(/^Error Codes\s*/, '').trim();
                    } else if (subsection.startsWith('Usage Notes')) {
                        sections.usageNotes = subsection.replace(/^Usage Notes\s*/, '').trim();
                    } else if (subsection.startsWith('Code Examples')) {
                        sections.codeExamples = subsection.replace(/^Code Examples\s*/, '').trim();
                    }
                }
            }
        }
    }
    
    console.log('Parsed sections:', Object.keys(sections).filter(key => sections[key]));
    return sections;
}

// Populate documentation sections in the UI
function populateDocumentationSections(sections) {
    console.log('Populating documentation sections:', sections);
    
    // Overview - always populate even if empty to clear loading placeholder
    const overviewContent = document.getElementById('overview-content');
    if (overviewContent) {
        console.log('Setting overview content:', sections.overview);
        if (sections.overview) {
            overviewContent.innerHTML = parseMarkdown(sections.overview);
        } else {
            overviewContent.innerHTML = '<p class="text-slate-300">No overview available.</p>';
        }
    } else {
        console.error('Overview content element not found');
    }
    
    // Endpoints
    if (sections.endpoints) {
        const endpointsContent = document.getElementById('endpoints-content');
        if (endpointsContent) {
            // Hide raw endpoints markdown to avoid duplicating the styled endpoint card below
            endpointsContent.innerHTML = '';
            const proseContainer = endpointsContent.closest('.prose');
            if (proseContainer) {
                proseContainer.style.display = 'none';
            }
        }
    }
    
    // Request Format
    if (sections.requestFormat) {
        const requestFormatContent = document.getElementById('request-format-content');
        if (requestFormatContent) {
            requestFormatContent.innerHTML = parseMarkdown(sections.requestFormat);
        }
    }
    
    // Response Format
    if (sections.responseFormat) {
        const responseFormatContent = document.getElementById('response-format-content');
        if (responseFormatContent) {
            responseFormatContent.innerHTML = parseMarkdown(sections.responseFormat);
        }
    }
    
    // Error Codes
    if (sections.errorCodes) {
        const errorCodesContent = document.getElementById('error-codes-content');
        if (errorCodesContent) {
            errorCodesContent.innerHTML = parseMarkdown(sections.errorCodes);
        }
    }
    
    // Usage Notes
    if (sections.usageNotes) {
        const usageNotesContent = document.getElementById('usage-notes-content');
        const usageNotesSection = document.getElementById('usage-notes');
        if (usageNotesContent && usageNotesSection) {
            usageNotesContent.innerHTML = parseMarkdown(sections.usageNotes);
            usageNotesSection.style.display = 'block'; // Show the section
        }
    }
}

// Extract clean information from API proposal data
function extractFromProposalData(data) {
    console.log('Extracting from proposal data:', data);
    
    const sections = {
        overview: '',
        authentication: '',
        endpoints: '',
        requestFormat: '',
        responseFormat: '',
        errorCodes: '',
        usageNotes: '',
        codeExamples: ''
    };
    
    // Try to parse the documentation as potential proposal data
    let proposalData = null;
    try {
        // Check if documentation contains structured data
        if (data.documentation.includes('API Name:') || data.documentation.includes('Description:')) {
            console.log('Found proposal-style documentation, parsing...');
            proposalData = parseProposalText(data.documentation);
            console.log('Parsed proposal data:', proposalData);
        }
    } catch (e) {
        console.log('Could not parse as proposal data:', e);
    }
    
    // Create clean overview
    if (proposalData) {
        console.log('Creating clean overview from proposal data');
        sections.overview = createCleanOverview(proposalData, data);
    } else {
        console.log('Creating basic overview from raw data');
        sections.overview = createBasicOverviewFromData(data);
    }
    
    console.log('Generated overview:', sections.overview);
    return sections;
}

// Parse proposal text into structured data
function parseProposalText(text) {
    const data = {};
    
    // Extract API Name
    const nameMatch = text.match(/API Name:\s*([^\n]+)/);
    if (nameMatch) data.apiName = nameMatch[1].trim();
    
    // Extract Description
    const descMatch = text.match(/Description:\s*([^\n]+(?:\n(?!Functionality:|Input Format:|Output Format:|Endpoints:)[^\n]*)*)/);
    if (descMatch) data.description = descMatch[1].trim();
    
    // Extract Functionality
    const funcMatch = text.match(/Functionality:\s*((?:\n\s*-[^\n]*)*)/);
    if (funcMatch) {
        data.functionality = funcMatch[1]
            .split('\n')
            .map(line => line.trim())
            .filter(line => line.startsWith('-'))
            .map(line => line.substring(1).trim());
    }
    
    return data;
}

// Create a clean overview from parsed proposal data
function createCleanOverview(proposalData, apiData) {
    let overview = '';
    
    if (proposalData.description) {
        overview += `<p class="text-lg text-slate-300 leading-relaxed mb-4">${proposalData.description}</p>`;
    }
    
    if (proposalData.functionality && proposalData.functionality.length > 0) {
        overview += `
            <div class="mt-6">
                <h4 class="text-lg font-semibold text-white mb-3">Key Features</h4>
                <ul class="space-y-2 text-slate-300">
                    ${proposalData.functionality.map(item => 
                        `<li class="flex items-start gap-2">
                            <svg class="w-4 h-4 text-green-400 mt-1 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                            </svg>
                            ${item}
                        </li>`
                    ).join('')}
                </ul>
            </div>
        `;
    }
    
    overview += `
        <div class="mt-6">
            <h4 class="text-lg font-semibold text-white mb-3">Getting Started</h4>
            <p class="text-slate-300">
                This API accepts JSON requests and returns structured JSON responses. 
                Use the interactive testing section below to try it out, or refer to the code examples for integration guidance.
            </p>
        </div>
    `;
    
    return overview;
}

// Create basic overview from API data
function createBasicOverviewFromData(data) {
    return `
        <p class="text-lg text-slate-300 leading-relaxed mb-4">
            ${data.prompt || data.api_name || 'API endpoint for processing requests and returning structured data.'}
        </p>
        <div class="mt-6">
            <h4 class="text-lg font-semibold text-white mb-3">About This API</h4>
            <p class="text-slate-300">
                This API provides data processing capabilities through a RESTful interface. 
                Send JSON requests to receive structured responses for your application needs.
            </p>
        </div>
    `;
}

// Create basic overview when no data is available
function createBasicOverview(data) {
    const sections = {
        overview: createBasicOverviewFromData(data || {}),
        authentication: '',
        endpoints: '',
        requestFormat: '',
        responseFormat: '',
        errorCodes: '',
        usageNotes: '',
        codeExamples: ''
    };
    return sections;
}

// Create fallback overview
function createFallbackOverview() {
    const sections = {
        overview: `
            <p class="text-lg text-slate-300 leading-relaxed mb-4">
                This API provides data processing capabilities through a simple REST interface.
            </p>
            <div class="mt-6">
                <h4 class="text-lg font-semibold text-white mb-3">Getting Started</h4>
                <p class="text-slate-300">
                    Send POST requests with JSON data to receive structured responses. 
                    Check the interactive testing section to try out the API.
                </p>
            </div>
        `,
        authentication: '',
        endpoints: '',
        requestFormat: '',
        responseFormat: '',
        errorCodes: '',
        usageNotes: '',
        codeExamples: ''
    };
    return sections;
}

// Create clean description for endpoint from API data
function createCleanDescription(data) {
    // Try to extract description from documentation if it contains proposal data
    if (data.documentation && data.documentation.includes('Description:')) {
        try {
            const descMatch = data.documentation.match(/Description:\s*([^\n]+(?:\n(?!Functionality:|Input Format:|Output Format:|Endpoints:)[^\n]*)*)/);
            if (descMatch) {
                return descMatch[1].trim();
            }
        } catch (e) {
            console.log('Could not extract description from documentation:', e);
        }
    }
    
    // Try to extract from api_name or use fallback
    if (data.api_name && data.api_name !== 'API undefined' && !data.api_name.startsWith('API ')) {
        return `${data.api_name} - A specialized API endpoint for data processing and analysis.`;
    }
    
    // Final fallback
    return 'API endpoint for processing JSON requests and returning structured data responses.';
}

// Simple markdown parser
function parseMarkdown(content) {
    if (!content) return '';
    
    return content
        // Headers
        .replace(/^#### (.*$)/gim, '<h4>$1</h4>')
        .replace(/^### (.*$)/gim, '<h3>$1</h3>')
        .replace(/^## (.*$)/gim, '<h2>$1</h2>')
        .replace(/^# (.*$)/gim, '<h1>$1</h1>')
        // Bold
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        // Italic
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        // Code blocks
        .replace(/```(\w+)?\n([\s\S]*?)```/g, '<div class="code-block"><div class="code-content"><pre><code class="language-$1">$2</code></pre></div></div>')
        // Inline code
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        // Tables
        .replace(/^\|(.+)\|\s*$/gm, function(match, row) {
            const cells = row.split('|').map(cell => cell.trim()).filter(cell => cell);
            return '<tr>' + cells.map(cell => `<td>${cell}</td>`).join('') + '</tr>';
        })
        // Wrap tables
        .replace(/(<tr>.*<\/tr>)/s, '<table class="parameter-table">$1</table>')
        // Lists
        .replace(/^\- (.*$)/gim, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
        // Links
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
        // Line breaks
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>');
}

// Extract API name from prompt (same logic as profile.html)
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

// Load API data and populate endpoints
async function loadAPIData() {
    try {
        const response = await fetch(`/api/${apiData.user_id}/${apiData.api_slug}/apidetails`);
        const data = await response.json();
        
        if (response.ok) {
            // Update the API name in the sidebar header
            updateAPIName(data);
            populateEndpoints(data);
        }
    } catch (error) {
        console.error('Failed to load API data:', error);
    }
}

// Update API name in the sidebar header
function updateAPIName(data) {
    const apiNameElement = document.querySelector('.docs-sidebar h1');
    if (apiNameElement && data.prompt) {
        const displayName = extractAPINameFromPrompt(data.prompt, data.api_name || `API ${apiData.api_slug}`);
        apiNameElement.textContent = displayName;
    }
}

// Populate endpoints section
function populateEndpoints(data) {
    const endpointList = document.getElementById('endpoint-list');
    
    // Create clean description from data
    const cleanDescription = createCleanDescription(data);
    
    // Extract parameters from OpenAPI spec or sample input
    const parameters = extractParametersFromData(data);
    const hasParameters = parameters.length > 0;
    
    // Extract example request from sample_input or use defaults
    const exampleRequest = extractExampleRequest(data);
    
    // Extract example responses from expected_output or use defaults
    const exampleResponses = extractExampleResponses(data);
    
    // Main endpoint
    const endpointHtml = `
        <div class="endpoint-card">
            <div class="endpoint-header">
                <span class="method-badge method-post">POST</span>
                <div class="flex-1">
                    <div class="endpoint-url">${data.endpoint_url || apiData.base_url}</div>
                </div>
            </div>
            
            <div class="prose prose-invert max-w-none">
                <h4 class="text-lg font-semibold text-white mb-3">Description</h4>
                <p class="text-slate-300 mb-4">${cleanDescription}</p>
                
                <h4 class="text-lg font-semibold text-white mb-3">Request</h4>
                <div class="tabs-container">
                    <div class="tabs-nav">
                        ${hasParameters ? `<button class="tab-button active" onclick="switchEndpointTab('parameters')">Parameters</button>` : ''}
                        <button class="tab-button ${hasParameters ? '' : 'active'}" onclick="switchEndpointTab('example-request')">Example</button>
                    </div>
                    
                    ${hasParameters ? `
                    <div id="parameters-tab" class="tab-content active">
                        <table class="parameter-table">
                            <thead>
                                <tr>
                                    <th>Parameter</th>
                                    <th>Type</th>
                                    <th>Required</th>
                                    <th>Description</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${parameters.map(param => `
                                    <tr>
                                        <td><span class="param-name">${param.name}</span></td>
                                        <td><span class="param-type">${param.type}</span></td>
                                        <td><span class="param-${param.required ? 'required' : 'optional'}">${param.required ? 'required' : 'optional'}</span></td>
                                        <td>${param.description}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                    ` : ''}
                    
                    <div id="example-request-tab" class="tab-content ${hasParameters ? '' : 'active'}">
                        <div class="code-block">
                            <div class="code-header">
                                <div class="code-title">Example Request</div>
                                <button class="copy-btn" onclick="copyCode('example-request')">Copy</button>
                            </div>
                            <div class="code-content">
                                <pre><code id="example-request" class="language-json">${JSON.stringify(exampleRequest, null, 2)}</code></pre>
                            </div>
                        </div>
                    </div>
                </div>
                
                <h4 class="text-lg font-semibold text-white mb-3 mt-6">Responses</h4>
                
                ${exampleResponses.map(response => `
                    <div class="response-example">
                        <div class="flex items-center gap-2 mb-3">
                            <span class="status-badge status-${response.status}">${response.status}</span>
                            <span class="text-white font-medium">${response.title}</span>
                        </div>
                        <div class="code-block">
                            <div class="code-content">
                                <pre><code class="language-json">${JSON.stringify(response.body, null, 2)}</code></pre>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
    
    endpointList.innerHTML = endpointHtml;
}

// Extract parameters from OpenAPI spec or API data
function extractParametersFromData(data) {
    const parameters = [];
    
    // Try to extract from OpenAPI spec first
    if (data.openapi_spec) {
        try {
            const spec = typeof data.openapi_spec === 'string' ? JSON.parse(data.openapi_spec) : data.openapi_spec;
            const paths = spec.paths || {};
            const pathKey = Object.keys(paths)[0];
            if (pathKey && paths[pathKey].post && paths[pathKey].post.requestBody) {
                const schema = paths[pathKey].post.requestBody.content?.['application/json']?.schema;
                if (schema && schema.properties) {
                    for (const [name, prop] of Object.entries(schema.properties)) {
                        parameters.push({
                            name: name,
                            type: prop.type || 'string',
                            required: schema.required?.includes(name) || false,
                            description: prop.description || `Parameter: ${name}`
                        });
                    }
                }
            }
        } catch (e) {
            console.log('Failed to parse OpenAPI spec:', e);
        }
    }

    // Fallback: infer parameters from sample_input if OpenAPI did not provide any
    if (parameters.length === 0 && data.sample_input) {
        try {
            const sample = JSON.parse(data.sample_input);
            if (sample && typeof sample === 'object' && !Array.isArray(sample)) {
                for (const [name, value] of Object.entries(sample)) {
                    parameters.push({
                        name,
                        type: Array.isArray(value) ? 'array' : typeof value,
                        required: true,
                        description: `Field "${name}" from sample input`
                    });
                }
            }
        } catch (e) {
            console.log('Failed to infer parameters from sample_input:', e);
        }
    }

    return parameters;
}

// Extract example request from sample_input only
function extractExampleRequest(data) {
    if (data.sample_input) {
        try {
            return JSON.parse(data.sample_input);
        } catch (e) {
            console.log('Failed to parse sample_input:', e);
        }
    }
    
    // Return empty object if no sample_input available
    return {};
}

// Extract example responses from expected_output only
function extractExampleResponses(data) {
    const responses = [];
    
    // Try to extract from expected_output
    if (data.expected_output) {
        try {
            const output = JSON.parse(data.expected_output);
            responses.push({
                status: '200',
                title: 'Success',
                body: output
            });
        } catch (e) {
            console.log('Failed to parse expected_output:', e);
        }
    }
    
    // Return empty array if no expected_output available
    return responses;
}

// Setup interactive testing
function setupInteractiveTest() {
    const form = document.getElementById('api-test-form');
    form.addEventListener('submit', handleTestSubmit);
    
    // Load example data
    const testData = document.getElementById('test-data');
    testData.value = JSON.stringify({
        "example": "value",
        "key": "data",
        "timestamp": new Date().toISOString()
    }, null, 2);
}

// Handle test form submission
async function handleTestSubmit(e) {
    e.preventDefault();
    
    const testDataInput = document.getElementById('test-data');
    const resultDiv = document.getElementById('test-result');
    const responseBody = document.getElementById('response-body');
    
    try {
        // Parse test data
        let requestData = {};
        if (testDataInput.value.trim()) {
            requestData = JSON.parse(testDataInput.value);
        }
        
        // Show loading state
        resultDiv.style.display = 'block';
        responseBody.textContent = 'Sending request...';
        
        // Make the API request
        const response = await fetch('/test-api', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: apiData.user_id,
                api_slug: apiData.api_slug,
                test_data: requestData,
                test_type: 'documentation'
            })
        });
        
        const result = await response.json();
        
        // Display the result
        if (result.success && result.response_data) {
            responseBody.textContent = JSON.stringify(result.response_data, null, 2);
        } else if (result.error) {
            responseBody.textContent = JSON.stringify({ error: result.error }, null, 2);
        } else {
            responseBody.textContent = JSON.stringify(result, null, 2);
        }
        
        // Highlight the code
        Prism.highlightElement(responseBody);
        
    } catch (error) {
        responseBody.textContent = JSON.stringify({ 
            error: 'Test failed', 
            message: error.message 
        }, null, 2);
        Prism.highlightElement(responseBody);
    }
}

// Clear test data
function clearTestData() {
    document.getElementById('test-data').value = '';
    document.getElementById('test-result').style.display = 'none';
}

// Setup smooth scrolling for navigation
function setupSmoothScrolling() {
    document.querySelectorAll('.nav-item').forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href').substring(1);
            const targetElement = document.getElementById(targetId);
            
            if (targetElement) {
                // Update active nav item
                document.querySelectorAll('.nav-item').forEach(item => item.classList.remove('active'));
                this.classList.add('active');
                
                // Scroll to target
                targetElement.scrollIntoView({ behavior: 'smooth' });
            }
        });
    });
}

// Tab switching functions
function switchCodeTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('#code-examples .tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('#code-examples .tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(tabName + '-tab').classList.add('active');
    event.target.classList.add('active');
}

function switchEndpointTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.endpoint-card .tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('.endpoint-card .tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(tabName + '-tab').classList.add('active');
    event.target.classList.add('active');
}

function switchAuthTab(tabName) {
    // Hide all auth tabs
    document.querySelectorAll('#authentication .tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all auth tab buttons
    document.querySelectorAll('#authentication .tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(tabName + '-tab').classList.add('active');
    event.target.classList.add('active');
}

// Load OpenAPI specification
async function loadOpenAPISpec() {
    try {
        const response = await fetch(`/api/${apiData.user_id}/${apiData.api_slug}/openapi`);
        openApiSpec = await response.json();
        
        // Initialize Swagger UI
        initializeSwaggerUI();
        
        // Show raw YAML
        displayRawSpec();
        
    } catch (error) {
        console.error('Failed to load OpenAPI spec:', error);
        document.getElementById('swagger-ui').innerHTML = `
            <div class="p-8 text-center text-red-400">
                <svg class="w-12 h-12 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"></path>
                </svg>
                <p>Failed to load OpenAPI specification</p>
            </div>
        `;
    }
}

// Initialize Swagger UI
function initializeSwaggerUI() {
    if (!openApiSpec) return;
    
    swaggerUI = SwaggerUIBundle({
        dom_id: '#swagger-ui',
        spec: openApiSpec,
        deepLinking: true,
        presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIBundle.presets.standalone
        ],
        plugins: [
            SwaggerUIBundle.plugins.DownloadUrl
        ],
        layout: "BaseLayout",
        theme: "dark",
        tryItOutEnabled: true,
        requestInterceptor: (req) => {
            // Add any custom headers or modifications here
            return req;
        }
    });
}

// Display raw OpenAPI spec as YAML
function displayRawSpec() {
    if (!openApiSpec) return;
    
    try {
        const yamlString = jsyaml.dump(openApiSpec, {
            indent: 2,
            lineWidth: -1,
            noRefs: true
        });
        
        document.getElementById('openapi-yaml').textContent = yamlString;
        Prism.highlightElement(document.getElementById('openapi-yaml'));
    } catch (error) {
        document.getElementById('openapi-yaml').textContent = 'Error converting to YAML: ' + error.message;
    }
}

// Switch between OpenAPI spec tabs
function switchSpecTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('#openapi-spec .tab-content').forEach(tab => {
        tab.classList.remove('active');
    });
    
    // Remove active class from all buttons
    document.querySelectorAll('#openapi-spec .tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(tabName + '-tab').classList.add('active');
    event.target.classList.add('active');
    
    // Re-initialize Swagger UI if switching to viewer tab
    if (tabName === 'viewer' && openApiSpec && !swaggerUI) {
        setTimeout(initializeSwaggerUI, 100);
    }
}

// Download OpenAPI spec as YAML
function downloadOpenAPISpec() {
    if (!openApiSpec) return;
    
    try {
        const yamlString = jsyaml.dump(openApiSpec, {
            indent: 2,
            lineWidth: -1,
            noRefs: true
        });
        
        const blob = new Blob([yamlString], { type: 'text/yaml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${apiData.api_slug}-openapi.yaml`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Failed to download OpenAPI spec:', error);
    }
}

// Open in external Swagger UI
function viewSwaggerUI() {
    if (!openApiSpec) return;
    
    const specUrl = `/api/${apiData.user_id}/${apiData.api_slug}/openapi`;
    const swaggerUrl = `https://petstore.swagger.io/?url=${encodeURIComponent(window.location.origin + specUrl)}`;
    window.open(swaggerUrl, '_blank');
}

// Simple markdown processing for documentation
function processMarkdownContent() {
    const markdownElements = document.querySelectorAll('.markdown-content pre');
    markdownElements.forEach(element => {
        let content = element.textContent;
        
        // Convert markdown to HTML
        content = content
            // Headers
            .replace(/^### (.*$)/gim, '<h3>$1</h3>')
            .replace(/^## (.*$)/gim, '<h2>$1</h2>')
            .replace(/^# (.*$)/gim, '<h1>$1</h1>')
            // Bold
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            // Italic
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            // Code blocks
            .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="language-$1">$2</code></pre>')
            // Inline code
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            // Lists
            .replace(/^\- (.*$)/gim, '<li>$1</li>')
            .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
            // Links
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
            // Line breaks
            .replace(/\n\n/g, '</p><p>')
            .replace(/\n/g, '<br>');
        
        // Wrap in paragraphs if not already wrapped
        if (!content.startsWith('<')) {
            content = '<p>' + content + '</p>';
        }
        
        element.innerHTML = content;
        element.classList.remove('whitespace-pre-wrap');
        element.classList.add('rendered-markdown');
    });
}

// Copy code function
function copyCode(elementId) {
    const element = document.getElementById(elementId);
    const text = element.textContent;
    
    navigator.clipboard.writeText(text).then(() => {
        // Show feedback
        const button = event.target;
        const originalText = button.textContent;
        button.textContent = 'Copied!';
        setTimeout(() => {
            button.textContent = originalText;
        }, 2000);
    });
}
