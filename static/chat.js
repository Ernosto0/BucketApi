let currentConversation = [];
let isGenerating = false;
let currentApiData = null;

// Chat functionality
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function handleInputChange() {
    const input = document.getElementById('chatInput');
    const sendButton = document.getElementById('sendButton');
    const charCount = document.getElementById('charCount');
    
    const length = input.value.length;
    charCount.textContent = `${length} characters`;
    
    sendButton.disabled = !input.value.trim() || isGenerating;
    
    // Auto-resize textarea
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 128) + 'px';
}

function sendQuickMessage(message) {
    document.getElementById('chatInput').value = message;
    handleInputChange();
    sendMessage();
}

function showActionButtons() {
    const actionArea = document.getElementById('actionButtonsArea');
    actionArea.classList.remove('hidden');
    actionArea.classList.add('animate-slide-up');
}

function hideActionButtons() {
    const actionArea = document.getElementById('actionButtonsArea');
    actionArea.classList.add('hidden');
}

function handleChatScroll() {
    const messagesContainer = document.getElementById('chatMessages');
    const scrollToBottomBtn = document.getElementById('scrollToBottomBtn');
    
    // Show scroll to bottom button if not at bottom
    const isAtBottom = messagesContainer.scrollTop + messagesContainer.clientHeight >= messagesContainer.scrollHeight - 50;
    
    if (isAtBottom) {
        scrollToBottomBtn.classList.add('hidden');
    } else {
        scrollToBottomBtn.classList.remove('hidden');
    }
}

function scrollToBottom() {
    const messagesContainer = document.getElementById('chatMessages');
    messagesContainer.scrollTo({
        top: messagesContainer.scrollHeight,
        behavior: 'smooth'
    });
    document.getElementById('scrollToBottomBtn').classList.add('hidden');
}

function clearChat() {
    const messagesContainer = document.getElementById('chatMessages');
    messagesContainer.innerHTML = `
        <!-- Welcome Message -->
        <div class="message-animation">
            <div class="flex items-start space-x-3 max-w-4xl">
                <div class="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0">
                    <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                    </svg>
                </div>
                <div class="glass-card rounded-2xl p-6 flex-1">
                    <div class="mb-4">
                        <div class="flex items-center space-x-2 mb-2">
                            <span class="status-badge status-buildable">Ready</span>
                            <h3 class="font-semibold text-white">Chat Cleared - Ready for New API!</h3>
                        </div>
                        <p class="text-slate-300">What would you like to build today?</p>
                    </div>
                </div>
            </div>
        </div>
    `;
    currentConversation = [];
    currentApiData = null;
    hideActionButtons();
}

async function sendMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    
    if (!message || isGenerating) return;

    // Add user message to chat
    addMessage('user', message);
    
    // Clear input
    input.value = '';
    handleInputChange();

    // Show typing indicator
    showTypingIndicator("Analyzing your request...");

    try {
        isGenerating = true;
        
        // Get user ID (from auth or generate temp one)
        const userId = currentUser ? currentUser.id : 'temp_' + Date.now();
        
        // First, analyze the prompt using ChatService
        const analysisResponse = await fetch('/chat/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                prompt: message,
                user_id: userId
            })
        });

        const analysisResult = await analysisResponse.json();
        console.log('Analysis Response:', analysisResult);
        
        if (analysisResult.success) {
            const analysis = JSON.parse(analysisResult.analysis_result);
            console.log('Parsed Analysis:', analysis);
            // Handle different response types
            if (analysis.status === 'buildable') {
                // Show positive response and proceed to generate API
                addChatAnalysisMessage(analysis);
                await generateAPI(message, userId, true);
            } else if (analysis.status === 'proposal_ready') {
                // Show detailed API proposal and ask for confirmation
                addProposalMessage(analysis, message, userId);
            } else if (analysis.status === 'needs_clarification') {
                // Show clarification questions
                addClarificationMessage(analysis);
            } else if (analysis.status === 'modify_request') {
                // Show modify request message
                addModifyRequestMessage(analysis);
            } else if (analysis.status === 'not_buildable') {
                // Show rejection with suggestions
                addRejectionMessage(analysis);
            }
        } else {
            // Fallback: proceed with API generation if analysis fails
            await generateAPI(message, userId, false);
        }
        
    } catch (error) {
        hideTypingIndicator();
        addMessage('assistant', `❌ Network error: ${error.message}`);
    } finally {
        isGenerating = false;
        handleInputChange();
    }
}

async function generateAPI(message, userId, skipAnalysis = true) {
    try {
        console.log(`Generating API - Skip Analysis: ${skipAnalysis}`);
        const response = await fetch('/generate-api', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                prompt: message,
                user_id: userId,
                skip_analysis: skipAnalysis
            })
        });

        const result = await response.json();
        
        hideTypingIndicator();

        if (result.success) {
            currentApiData = result;
            addAPIResultMessage(result);
            showActionButtons();
            addMessage('system', '🎉 API generated successfully! Use the action buttons below to save, test, or modify your API.');
        } else {
            // Handle different types of unsuccessful responses
            if (result.status === 'needs_clarification') {
                addClarificationMessage(result);
            } else if (result.status === 'modify_request') {
                addModifyRequestMessage(result);
            } else if (result.status === 'not_buildable') {
                addRejectionMessage(result);
            } else {
                // Fallback for any other error
                addMessage('assistant', `❌ Error: ${result.message || 'Failed to generate API'}`);
            }
        }
    } catch (error) {
        hideTypingIndicator();
        addMessage('assistant', `❌ Network error: ${error.message}`);
    }
}

function addMessage(type, content) {
    const messagesContainer = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message-animation';
    
    // Remember if user was at bottom before adding message
    const wasAtBottom = messagesContainer.scrollTop + messagesContainer.clientHeight >= messagesContainer.scrollHeight - 50;
    
    if (type === 'user') {
        messageDiv.innerHTML = `
            <div class="flex items-start space-x-3 justify-end">
                <div class="glass-card rounded-2xl p-4 max-w-lg bg-gradient-to-r from-blue-600/20 to-purple-600/20 border-blue-500/30">
                    <p class="text-white">${content}</p>
                </div>
                <div class="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0">
                    <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                    </svg>
                </div>
            </div>
        `;
    } else if (type === 'assistant') {
        messageDiv.innerHTML = `
            <div class="flex items-start space-x-3 w-full">
                <div class="w-8 h-8 bg-gradient-to-r from-emerald-500 to-green-600 rounded-full flex items-center justify-center flex-shrink-0">
                    <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                    </svg>
                </div>
                <div class="glass-card rounded-2xl p-6 flex-1 min-w-0">
                    ${content}
                </div>
            </div>
        `;
    } else if (type === 'system') {
        messageDiv.innerHTML = `
            <div class="flex justify-center">
                <div class="glass-card rounded-xl p-3 text-center text-sm text-slate-300 max-w-md">
                    ${content}
                </div>
            </div>
        `;
    }
    
    messagesContainer.appendChild(messageDiv);
    
    // Only auto-scroll if user was already at bottom or if it's a new user message
    if (wasAtBottom || type === 'user') {
        setTimeout(() => {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }, 100);
    }
    
    // Store in conversation history
    currentConversation.push({ type, content });
}

function addChatAnalysisMessage(analysis) {
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <h3 class="font-semibold text-white">Perfect! I can build this API for you.</h3>
            </div>
            <div class="bg-emerald-900/20 border border-emerald-500/30 rounded-xl p-4">
                <h4 class="text-sm font-medium text-emerald-300 mb-2">Implementation Plan:</h4>
                <ul class="text-sm text-emerald-200 space-y-1">
                    ${analysis.next_steps ? analysis.next_steps.map(step => `<li class="flex items-start space-x-2"><span class="text-emerald-400">•</span><span>${step}</span></li>`).join('') : ''}
                </ul>
            </div>
            <div class="flex items-center space-x-2 text-sm text-slate-400">
                <div class="w-2 h-2 bg-blue-500 rounded-full animate-pulse"></div>
                <span>Generating your API...</span>
            </div>
        </div>
    `;
    addMessage('assistant', content);
}

function addClarificationMessage(analysis) {
    const questionsHtml = analysis.questions ? 
        analysis.questions.map(q => `<li class="flex items-start space-x-2"><span class="text-amber-400">•</span><span class="text-amber-200">${q}</span></li>`).join('') : 
        '<li class="flex items-start space-x-2"><span class="text-amber-400">•</span><span class="text-amber-200">Please provide more details about your requirements</span></li>';
    
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <span class="status-badge status-clarification">Need Info</span>
                <h3 class="font-semibold text-white">I need more information to build this API</h3>
            </div>
            <div class="bg-amber-900/20 border border-amber-500/30 rounded-xl p-4">
                <h4 class="text-sm font-medium text-amber-300 mb-3">Please help me understand:</h4>
                <ul class="space-y-2">
                    ${questionsHtml}
                </ul>
            </div>
            <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4">
                <p class="text-blue-300 text-sm">
                    💡 <strong>Tip:</strong> The more specific you are, the better I can help you build exactly what you need!
                </p>
            </div>
        </div>
    `;
    addMessage('assistant', content);
    hideTypingIndicator();
}

function addModifyRequestMessage(analysis) {
    const modify_request = analysis.modify_request;
    const modify_request_html = modify_request ? 
        modify_request.map(request => `<li class="flex items-start space-x-2"><span class="text-purple-400">•</span><span class="text-purple-200">${request}</span></li>`).join('') : 
        '<li class="flex items-start space-x-2"><span class="text-purple-400">•</span><span class="text-purple-200">Please provide more details about your requirements</span></li>';

    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <span class="status-badge bg-purple-900/50 text-purple-400 border-purple-500/30">Modify Request</span>
                <h3 class="font-semibold text-white">I can help you modify an existing API</h3>
            </div>
            <div class="bg-purple-900/20 border border-purple-500/30 rounded-xl p-4">
                <p class="text-purple-200 text-sm mb-3">To modify an API, you can:</p>
                <ul class="text-sm text-purple-200 space-y-2">
                    <li class="flex items-start space-x-2"><span class="text-purple-400">•</span><span>Use the "Modify API" button if you just generated an API</span></li>
                    <li class="flex items-start space-x-2"><span class="text-purple-400">•</span><span>Tell me which specific API you want to modify</span></li>
                    <li class="flex items-start space-x-2"><span class="text-purple-400">•</span><span>Describe the changes you want to make</span></li>
                </ul>
                <ul class="text-sm text-purple-200 space-y-2">
                    ${modify_request_html}
                </ul>
            </div>
        </div>
    `;
    addMessage('assistant', content);
    hideTypingIndicator();
}

function addRejectionMessage(analysis) {
    const reasonsHtml = analysis.reasons ? 
        analysis.reasons.map(reason => `<li class="flex items-start space-x-2"><span class="text-red-400">•</span><span class="text-red-200">${reason}</span></li>`).join('') : 
        '<li class="flex items-start space-x-2"><span class="text-red-400">•</span><span class="text-red-200">The request is unclear or not feasible</span></li>';
        
    const suggestionsHtml = analysis.suggestions ? 
        analysis.suggestions.map(suggestion => `<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-blue-200">${suggestion}</span></li>`).join('') : 
        '<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-blue-200">Try being more specific about your requirements</span></li>';
    
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <h3 class="font-semibold text-white">I can't build this API</h3>
            </div>
            <div class="bg-red-900/20 border border-red-500/30 rounded-xl p-4">
                <h4 class="text-sm font-medium text-red-300 mb-3">Here's why:</h4>
                <ul class="space-y-2">
                    ${reasonsHtml}
                </ul>
            </div>
            <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4">
                <h4 class="text-sm font-medium text-blue-300 mb-3">💡 Suggestions:</h4>
                <ul class="space-y-2">
                    ${suggestionsHtml}
                </ul>
            </div>
            <div class="text-center text-sm text-slate-400 mt-4">
                Feel free to rephrase your request or try a different approach!
            </div>
        </div>
    `;
    addMessage('assistant', content);
    hideTypingIndicator();
}

function addProposalMessage(analysis, originalPrompt, userId) {
    const proposal = analysis.proposal;
    
    // Create endpoints HTML
    const endpointsHtml = proposal.endpoints ? 
        proposal.endpoints.map(endpoint => 
            `<div class="flex items-center space-x-2 text-sm">
                <span class="px-2 py-1 bg-${endpoint.method === 'GET' ? 'green' : endpoint.method === 'POST' ? 'blue' : endpoint.method === 'PUT' ? 'yellow' : 'red'}-600/20 text-${endpoint.method === 'GET' ? 'green' : endpoint.method === 'POST' ? 'blue' : endpoint.method === 'PUT' ? 'yellow' : 'red'}-300 rounded font-mono text-xs">${endpoint.method}</span>
                <span class="font-mono text-slate-300">${endpoint.path}</span>
                <span class="text-slate-400">- ${endpoint.description}</span>
            </div>`
        ).join('') : 
        '<div class="text-sm text-slate-400">Standard REST API endpoints</div>';

    // Create functionality HTML
    const functionalityHtml = proposal.functionality ? 
        proposal.functionality.map(func => `<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-slate-300">${func}</span></li>`).join('') : 
        '<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-slate-300">Custom API functionality</span></li>';



    const content = `
        <div class="space-y-6">
            <div class="flex items-center space-x-2">
                <span class="status-badge bg-blue-900/50 text-blue-400 border-blue-500/30">Proposal Ready</span>
                <h3 class="font-semibold text-white">Here's what I propose to build for you:</h3>
            </div>
            
            <!-- API Name and Description -->
            <div class="glass-card rounded-xl p-6 border-blue-500/30">
                <h4 class="font-bold text-xl text-white mb-2">${proposal.api_name || 'Custom API'}</h4>
                <p class="text-slate-300">${proposal.description || 'A custom API based on your requirements'}</p>
            </div>

            <!-- Functionality -->
            <div class="glass-card rounded-xl p-6">
                <h4 class="font-semibold text-white mb-3 flex items-center space-x-2">
                    <span class="text-blue-400">⚡</span>
                    <span>Key Features</span>
                </h4>
                <ul class="space-y-2">
                    ${functionalityHtml}
                </ul>
            </div>

            <!-- Input/Output Format -->
            ${proposal.input_format || proposal.output_format ? `
            <div class="grid md:grid-cols-2 gap-4">
                ${proposal.input_format ? `
                <div class="glass-card rounded-xl p-4">
                    <h5 class="font-semibold text-green-400 mb-2">📥 Input Format</h5>
                    <p class="text-sm text-slate-300 mb-2">${proposal.input_format.type || 'JSON'}</p>
                    ${proposal.input_format.example ? `
                    <div class="code-highlight rounded p-3">
                        <pre class="text-xs text-slate-300 font-mono">${proposal.input_format.example}</pre>
                    </div>
                    ` : ''}
                </div>
                ` : ''}
                ${proposal.output_format ? `
                <div class="glass-card rounded-xl p-4">
                    <h5 class="font-semibold text-purple-400 mb-2">📤 Output Format</h5>
                    <p class="text-sm text-slate-300 mb-2">${proposal.output_format.type || 'JSON'}</p>
                    ${proposal.output_format.example ? `
                    <div class="code-highlight rounded p-3">
                        <pre class="text-xs text-slate-300 font-mono">${proposal.output_format.example}</pre>
                    </div>
                    ` : ''}
                </div>
                ` : ''}
            </div>
            ` : ''}

            <!-- Endpoints -->
            <div class="glass-card rounded-xl p-6">
                <h4 class="font-semibold text-white mb-3 flex items-center space-x-2">
                    <span class="text-yellow-400">🔗</span>
                    <span>API Endpoints</span>
                </h4>
                <div class="space-y-2">
                    ${endpointsHtml}
                </div>
            </div>



            <!-- Confirmation Buttons -->
            <div class="glass-card rounded-xl p-6 border-green-500/30">
                <h4 class="font-semibold text-white mb-4 flex items-center space-x-2">
                    <span class="text-green-400">✅</span>
                    <span>Ready to build this API?</span>
                </h4>
                <div class="flex flex-wrap gap-3">
                    <button onclick="confirmBuildAPI('${originalPrompt}', '${userId}')" 
                            class="px-6 py-3 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white rounded-xl font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                        🚀 Yes, Build It!
                    </button>
                    <button onclick="requestModifications('${originalPrompt}', '${userId}')" 
                            class="px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-xl font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                        ✏️ Modify Proposal
                    </button>
                    <button onclick="cancelAPIBuild()" 
                            class="px-6 py-3 bg-gradient-to-r from-gray-600 to-gray-700 hover:from-gray-700 hover:to-gray-800 text-white rounded-xl font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                        ❌ Cancel
                    </button>
                </div>
                <p class="text-sm text-slate-400 mt-4">
                    💡 Review the proposal carefully. You can request modifications or proceed with building the API.
                </p>
            </div>
        </div>
    `;
    
    addMessage('assistant', content);
    hideTypingIndicator();
}

function hideProposalMessage() {
    const proposalMessage = document.getElementById('proposalMessage');
    if (proposalMessage) {
        proposalMessage.remove();
    }
}

// Confirmation handler functions
async function confirmBuildAPI(originalPrompt, userId) {
    try {
        // Add user confirmation message
        addMessage('user', '🚀 Yes, build this API!');
        
        // Show building message
        
        
        showTypingIndicator("Building your API...");
        

        hideProposalMessage();
        // Generate the API with skip_analysis = true since we already analyzed
        await generateAPI(originalPrompt, userId, true);
        
    } catch (error) {
        hideTypingIndicator();
        addMessage('assistant', `❌ Error building API: ${error.message}`);
    }
}

function requestModifications(originalPrompt, userId) {
    addMessage('user', '✏️ I want to modify the proposal');
    
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <span class="status-badge bg-blue-900/50 text-blue-400 border-blue-500/30">Modification Request</span>
                <h3 class="font-semibold text-white">What would you like to modify?</h3>
            </div>
            <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4">
                <p class="text-blue-300 text-sm mb-3">
                    Please describe the changes you'd like to make to the API proposal:
                </p>
                <ul class="text-sm text-blue-200 space-y-2">
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Add or remove features</span></li>
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Change input/output formats</span></li>
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Modify endpoints or functionality</span></li>
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Update technologies or approach</span></li>
                </ul>
            </div>
            <div class="text-center text-sm text-slate-400">
                Type your modification request in the chat input below
            </div>
        </div>
    `;
    
    addMessage('assistant', content);
}

function cancelAPIBuild() {
    addMessage('user', '❌ Cancel - Don\'t build this API');
    
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <h3 class="font-semibold text-white">No problem! API build cancelled.</h3>
            </div>
            <div class="bg-slate-900/20 border border-slate-500/30 rounded-xl p-4">
                <p class="text-slate-300 text-sm">
                    Feel free to describe a different API you'd like to build, or modify your original request.
                </p>
            </div>
            <div class="text-center text-sm text-slate-400">
                What else can I help you build today?
            </div>
        </div>
    `;
    
    addMessage('assistant', content);
}

function addAPIResultMessage(result) {
    const endpointUrl = window.location.origin + result.endpoint_url;
    
    // Extract or generate smart test data based on the API
    const testData = {"json": "Place Holder", "description": "Place Holder", "examples": []}
    
    const content = `
        <div class="space-y-6">
            <div class="flex items-center space-x-2">
                <span class="status-badge status-buildable">Success</span>
                <h3 class="font-semibold text-white">🎉 API Generated Successfully!</h3>
            </div>
            
            <!-- API Test Section -->
            <div class="glass-card rounded-xl p-6 border-blue-500/30 test-section">
                <div class="flex items-center justify-between mb-4">
                    <h4 class="font-semibold text-white flex items-center space-x-2">
                        <span class="text-blue-400">🧪</span>
                        <span>Test Your API</span>
                    </h4>
                    <div class="flex items-center space-x-2">
                        <div id="testStatus" class="w-3 h-3 bg-gray-500 rounded-full"></div>
                        <span id="testStatusText" class="text-sm text-gray-400">Ready to test</span>
                    </div>
                </div>
                
                <!-- API Documentation -->
                <div class="mb-6 p-4 bg-slate-800/30 rounded-lg border border-slate-600/30">
                    <div class="flex items-center justify-between mb-3">
                        <h5 class="font-medium text-white flex items-center space-x-2">
                            <span class="text-blue-400">📚</span>
                            <span>API Documentation</span>
                        </h5>
                        <div class="flex items-center space-x-2">
                            <button onclick="copyToClipboard('${endpointUrl}')" 
                                    class="px-2 py-1 bg-emerald-600 hover:bg-emerald-700 text-white text-xs rounded transition-colors">
                                Copy URL
                            </button>
                        </div>
                    </div>
                    <div class="space-y-3">
                        <div class="text-sm">
                            <span class="text-slate-400">Endpoint:</span>
                            <code class="ml-2 text-emerald-400 font-mono text-xs bg-slate-700/50 px-2 py-1 rounded">${endpointUrl}</code>
                        </div>
                        <div class="text-sm text-slate-300 leading-relaxed">
                            ${result.documentation.replace(/\n/g, '<br>').replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>').replace(/`(.*?)`/g, '<code class="bg-slate-700/50 px-1 py-0.5 rounded text-xs font-mono">$1</code>')}
                        </div>
                    </div>
                </div>
                
                <!-- Test Input Area -->
                <div class="space-y-4">
                    <div>
                        <div class="flex items-center justify-between mb-2">
                            <label class="block text-sm font-medium text-slate-300">Request Data (JSON)</label>
                            <div class="flex items-center space-x-2">
                                <button onclick="formatTestInput()" class="text-xs text-blue-400 hover:text-blue-300 transition-colors format-json-btn">Format JSON</button>
                            </div>
                        </div>
                        <div class="test-input-container">
                            <textarea 
                                id="testInput" 
                                class="w-full h-32 p-3 bg-slate-700/50 border border-slate-600 rounded-lg text-white placeholder-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200 font-mono text-sm" 
                                placeholder="Generated example data will appear here..."
                            >${testData.json}</textarea>
                        </div>
                        <div class="mt-2">
                            <div class="flex items-center justify-between">
                                <p class="text-xs text-slate-400">${testData.description}</p>
                                <div class="flex items-center space-x-2">
                                    ${testData.requiresFile ? '<span class="text-xs text-amber-400">📎 File upload supported</span>' : ''}
                                </div>
                            </div>
                            ${testData.examples.length > 0 ? `
                            <div class="mt-2">
                                <details class="text-xs">
                                    <summary class="text-slate-400 cursor-pointer hover:text-slate-300">More examples</summary>
                                    <div class="mt-2 space-y-1 pl-4 border-l border-slate-600">
                                        ${testData.examples.map(example => `
                                            <button onclick="setTestData('${example.data.replace(/'/g, "\\'")}', '${example.label}')" 
                                                    class="block text-blue-400 hover:text-blue-300 transition-colors">
                                                ${example.label}
                                            </button>
                                        `).join('')}
                                    </div>
                                </details>
                            </div>
                            ` : ''}
                        </div>
                    </div>
                    
                    <!-- Test Controls -->
                    <div class="flex items-center justify-between test-controls">
                        <div class="flex items-center space-x-3">
                            <button onclick="runAPITest('${endpointUrl}')" 
                                    id="runTestBtn"
                                    class="px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg flex items-center space-x-2 test-button">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1m4 0h1m-6 4h1m4 0h1m6-10V7a3 3 0 11-6 0V4h6zM4 7v10a2 2 0 002 2h12a2 2 0 002-2V7"></path>
                                </svg>
                                <span>Run Test</span>
                            </button>
                            <button onclick="clearTestData()" 
                                    class="px-3 py-2 bg-gray-600 hover:bg-gray-700 text-white rounded-lg text-sm transition-colors">
                                Clear
                            </button>
                        </div>
                        <div class="flex items-center space-x-2 text-xs text-slate-400">
                            <span>Method:</span>
                            <span class="px-2 py-1 bg-blue-600/20 text-blue-300 rounded font-mono">POST</span>
                        </div>
                    </div>
                </div>
                
                <!-- Test Results Area -->
                <div id="testResults" class="hidden mt-6 space-y-4 test-results-container">
                    <!-- Response Status -->
                    <div class="flex items-center justify-between response-info">
                        <h5 class="font-medium text-white">Response</h5>
                        <div class="flex items-center space-x-2">
                            <span id="responseStatus" class="px-2 py-1 rounded text-xs font-mono"></span>
                            <span id="responseTime" class="text-xs text-slate-400"></span>
                        </div>
                    </div>
                    
                    <!-- Response Body -->
                    <div class="code-highlight rounded-lg p-4">
                        <pre id="responseBody" class="text-sm text-slate-300 font-mono whitespace-pre-wrap overflow-x-auto"></pre>
                    </div>
                    
                    <!-- Response Headers (Collapsible) -->
                    <div>
                        <button onclick="toggleResponseHeaders()" class="flex items-center space-x-2 text-sm text-slate-400 hover:text-slate-300 transition-colors headers-toggle-button">
                            <svg id="headersChevron" class="w-4 h-4 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
                            </svg>
                            <span>Response Headers</span>
                        </button>
                        <div id="responseHeaders" class="hidden mt-2 code-highlight rounded-lg p-4 headers-content">
                            <pre id="responseHeadersContent" class="text-xs text-slate-400 font-mono"></pre>
                        </div>
                    </div>
                </div>
                
                <!-- Deploy Button (Initially Hidden) -->
                <div id="deploySection" class="hidden mt-6 pt-6 border-t border-slate-600/50 deploy-section">
                    <div class="flex items-center justify-between">
                        <div>
                            <h5 class="font-medium text-white mb-1">Ready to Deploy?</h5>
                            <p class="text-sm text-slate-400">Your API is working! Deploy it to make it publicly available.</p>
                        </div>
                        <button onclick="deployCurrentAPI()" 
                                class="px-6 py-3 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white rounded-xl font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg flex items-center space-x-2">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"></path>
                            </svg>
                            <span>Deploy API</span>
                            
                        </button>
                    </div>
                </div>
            </div>
            
            <!-- Documentation Card (Initially Hidden) -->
            <div id="documentationSection" class="hidden glass-card rounded-xl p-6">
                <h4 class="font-semibold text-white mb-4 flex items-center space-x-2">
                    <span class="text-blue-400">📚</span>
                    <span>Documentation</span>
                </h4>
                <div class="code-highlight rounded-lg p-4">
                    <pre class="whitespace-pre-wrap text-slate-300 text-sm">${result.documentation}</pre>
                </div>
            </div>
            
            <!-- cURL Example Card (Initially Hidden) -->
            <div id="curlSection" class="hidden glass-card rounded-xl p-6">
                <div class="flex items-center justify-between mb-4">
                    <h4 class="font-semibold text-white flex items-center space-x-2">
                        <span class="text-purple-400">💻</span>
                        <span>cURL Example</span>
                    </h4>
                    <button onclick="copyToClipboard(\`${result.curl_example.replace(/`/g, '\\`')}\`)" 
                            class="px-3 py-1 bg-purple-600 hover:bg-purple-700 text-white text-xs rounded-lg transition-colors">
                        Copy cURL
                    </button>
                </div>
                <div class="code-highlight rounded-lg p-4">
                    <pre class="text-sm text-slate-300 font-mono overflow-x-auto">${result.curl_example}</pre>
                </div>
            </div>
        </div>
    `;

    addMessage('assistant', content);
}


function analyzeAPIType(prompt, documentation) {
    const text = (prompt + ' ' + documentation).toLowerCase();
    
    // Text analysis APIs
    if (text.includes('sentiment') || text.includes('emotion') || text.includes('mood')) {
        return { type: 'text_analysis', subtype: 'sentiment' };
    }
    if (text.includes('summarize') || text.includes('summary') || text.includes('abstract')) {
        return { type: 'text_analysis', subtype: 'summarization' };
    }
    if (text.includes('translate') || text.includes('translation') || text.includes('language')) {
        return { type: 'text_analysis', subtype: 'translation' };
    }
    
    // File processing APIs
    if (text.includes('pdf') || text.includes('document') || text.includes('file')) {
        return { type: 'file_processing', subtype: 'pdf' };
    }
    if (text.includes('csv') || text.includes('excel') || text.includes('spreadsheet')) {
        return { type: 'file_processing', subtype: 'csv' };
    }
    
    // Data extraction APIs
    if (text.includes('extract') && (text.includes('email') || text.includes('contact'))) {
        return { type: 'data_extraction', subtype: 'contacts' };
    }
    if (text.includes('extract') && (text.includes('name') || text.includes('person'))) {
        return { type: 'data_extraction', subtype: 'names' };
    }
    if (text.includes('extract') && text.includes('date')) {
        return { type: 'data_extraction', subtype: 'dates' };
    }
    
    // AI processing APIs
    if (text.includes('ai') || text.includes('artificial intelligence') || text.includes('machine learning')) {
        return { type: 'ai_processing', subtype: 'general' };
    }
    if (text.includes('classify') || text.includes('classification') || text.includes('category')) {
        return { type: 'ai_processing', subtype: 'classification' };
    }
    
    // Image processing APIs
    if (text.includes('image') || text.includes('photo') || text.includes('picture')) {
        return { type: 'image_processing', subtype: 'general' };
    }
    if (text.includes('resize') || text.includes('compress') || text.includes('optimize')) {
        return { type: 'image_processing', subtype: 'resize' };
    }
    
    // Authentication APIs
    if (text.includes('auth') || text.includes('login') || text.includes('jwt') || text.includes('token')) {
        return { type: 'authentication', subtype: 'jwt' };
    }
    
    return { type: 'generic', subtype: 'unknown' };
}

function generateTextAnalysisTestData(subtype) {
    const examples = [];
    let json = '';
    let description = '';
    
    switch (subtype) {
        case 'sentiment':
            json = JSON.stringify({
                text: "I absolutely love this new product! It's amazing and works perfectly. Highly recommend it to everyone."
            }, null, 2);
            description = "Example text for sentiment analysis";
            examples.push(
                { label: "Positive text", data: JSON.stringify({text: "This is fantastic! I love it!"}) },
                { label: "Negative text", data: JSON.stringify({text: "This is terrible and disappointing."}) },
                { label: "Neutral text", data: JSON.stringify({text: "The weather is cloudy today."}) }
            );
            break;
        case 'summarization':
            json = JSON.stringify({
                text: "Artificial intelligence (AI) is intelligence demonstrated by machines, unlike the natural intelligence displayed by humans and animals. Leading AI textbooks define the field as the study of intelligent agents: any device that perceives its environment and takes actions that maximize its chance of successfully achieving its goals. The term artificial intelligence is often used to describe machines that mimic cognitive functions that humans associate with the human mind, such as learning and problem solving."
            }, null, 2);
            description = "Long text to be summarized";
            examples.push(
                { label: "Article text", data: JSON.stringify({text: "Long article content here..."}) },
                { label: "Research paper", data: JSON.stringify({text: "Abstract and research content..."}) }
            );
            break;
        case 'translation':
            json = JSON.stringify({
                text: "Hello, how are you?",
                target_language: "es"
            }, null, 2);
            description = "Text to translate with target language";
            examples.push(
                { label: "English to Spanish", data: JSON.stringify({text: "Good morning", target_language: "es"}) },
                { label: "English to French", data: JSON.stringify({text: "Thank you", target_language: "fr"}) }
            );
            break;
    }
    
    return { json, description, examples, requiresFile: false };
}

function generateFileProcessingTestData(subtype) {
    const examples = [];
    let json = '';
    let description = '';
    
    switch (subtype) {
        case 'pdf':
            json = JSON.stringify({
                action: "extract_text",
                options: {
                    preserve_formatting: true
                }
            }, null, 2);
            description = "Upload a PDF file and specify extraction options";
            examples.push(
                { label: "Extract text", data: JSON.stringify({action: "extract_text"}) },
                { label: "Extract metadata", data: JSON.stringify({action: "extract_metadata"}) }
            );
            break;
        case 'csv':
            json = JSON.stringify({
                operation: "analyze",
                columns: ["name", "age", "city"]
            }, null, 2);
            description = "Upload a CSV file and specify analysis parameters";
            examples.push(
                { label: "Basic analysis", data: JSON.stringify({operation: "analyze"}) },
                { label: "Filter data", data: JSON.stringify({operation: "filter", criteria: {age: ">18"}}) }
            );
            break;
    }
    
    return { json, description, examples, requiresFile: true };
}

function generateDataExtractionTestData(subtype) {
    const examples = [];
    let json = '';
    let description = '';
    
    switch (subtype) {
        case 'contacts':
            json = JSON.stringify({
                text: "Contact John Doe at john.doe@email.com or call (555) 123-4567. You can also reach Mary Smith at mary.smith@company.com."
            }, null, 2);
            description = "Text containing contact information to extract";
            examples.push(
                { label: "Business card text", data: JSON.stringify({text: "Dr. Jane Wilson, MD\\nwilson@hospital.com\\n(555) 987-6543"}) },
                { label: "Email signature", data: JSON.stringify({text: "Best regards,\\nMike Johnson\\nmjohnson@company.com"}) }
            );
            break;
        case 'names':
            json = JSON.stringify({
                text: "The meeting was attended by John Smith, Mary Johnson, and Dr. Robert Brown from the university."
            }, null, 2);
            description = "Text containing person names to extract";
            break;
        case 'dates':
            json = JSON.stringify({
                text: "The project deadline is March 15, 2024. The meeting is scheduled for next Tuesday, January 10th."
            }, null, 2);
            description = "Text containing dates to extract and normalize";
            break;
    }
    
    return { json, description, examples, requiresFile: false };
}

function generateAIProcessingTestData(subtype) {
    const examples = [];
    let json = '';
    let description = '';
    
    switch (subtype) {
        case 'classification':
            json = JSON.stringify({
                text: "I need help with my account settings and password reset.",
                categories: ["technical_support", "billing", "general_inquiry", "bug_report"]
            }, null, 2);
            description = "Text to classify with possible categories";
            examples.push(
                { label: "Customer service", data: JSON.stringify({text: "My order hasn't arrived yet", categories: ["shipping", "billing", "returns"]}) },
                { label: "Product review", data: JSON.stringify({text: "Great product, works as expected", categories: ["positive", "negative", "neutral"]}) }
            );
            break;
        default:
            json = JSON.stringify({
                input: "Sample data for AI processing",
                parameters: {
                    temperature: 0.7,
                    max_tokens: 100
                }
            }, null, 2);
            description = "Input data for AI model processing";
            break;
    }
    
    return { json, description, examples, requiresFile: false };
}

function generateImageProcessingTestData(subtype) {
    const examples = [];
    let json = '';
    let description = '';
    
    switch (subtype) {
        case 'resize':
            json = JSON.stringify({
                width: 800,
                height: 600,
                maintain_aspect_ratio: true,
                quality: 85
            }, null, 2);
            description = "Upload an image and specify resize parameters";
            examples.push(
                { label: "Thumbnail", data: JSON.stringify({width: 150, height: 150}) },
                { label: "High quality", data: JSON.stringify({width: 1920, height: 1080, quality: 95}) }
            );
            break;
        default:
            json = JSON.stringify({
                operation: "analyze",
                return_metadata: true
            }, null, 2);
            description = "Upload an image and specify processing options";
            break;
    }
    
    return { json, description, examples, requiresFile: true };
}

function generateAuthTestData(subtype) {
    const examples = [];
    let json = '';
    let description = '';
    
    switch (subtype) {
        case 'jwt':
            json = JSON.stringify({
                username: "testuser",
                password: "testpassword"
            }, null, 2);
            description = "User credentials for authentication";
            examples.push(
                { label: "Login", data: JSON.stringify({username: "john_doe", password: "secure123"}) },
                { label: "Register", data: JSON.stringify({username: "new_user", password: "newpass123", email: "user@example.com"}) }
            );
            break;
        default:
            json = JSON.stringify({
                action: "authenticate",
                credentials: {
                    username: "user",
                    password: "pass"
                }
            }, null, 2);
            description = "Authentication request data";
            break;
    }
    
    return { json, description, examples, requiresFile: false };
}

function extractDataFromCurl(curlExample) {
    if (!curlExample) return null;
    
    try {
        // Look for -d or --data flag in curl command
        const dataMatch = curlExample.match(/-d\s+'([^']+)'|--data\s+'([^']+)'|-d\s+"([^"]+)"|--data\s+"([^"]+)"/);
        if (dataMatch) {
            const data = dataMatch[1] || dataMatch[2] || dataMatch[3] || dataMatch[4];
            // Try to parse and reformat JSON
            try {
                const parsed = JSON.parse(data);
                return JSON.stringify(parsed, null, 2);
            } catch {
                return data;
            }
        }
        
        // Look for JSON-like content in the curl example
        const jsonMatch = curlExample.match(/\{[^}]+\}/);
        if (jsonMatch) {
            try {
                const parsed = JSON.parse(jsonMatch[0]);
                return JSON.stringify(parsed, null, 2);
            } catch {
                return jsonMatch[0];
            }
        }
    } catch (error) {
        console.warn('Error extracting data from curl example:', error);
    }
    
    return null;
}

function getCurrentPrompt() {
    // Get the last user message from the conversation
    if (currentConversation && currentConversation.length > 0) {
        for (let i = currentConversation.length - 1; i >= 0; i--) {
            if (currentConversation[i].type === 'user') {
                return currentConversation[i].content;
            }
        }
    }
    return '';
}

// New helper functions for the enhanced test interface
function setTestData(data, label) {
    const testInput = document.getElementById('testInput');
    if (testInput) {
        try {
            const parsed = JSON.parse(data);
            testInput.value = JSON.stringify(parsed, null, 2);
        } catch {
            testInput.value = data;
        }
        
        // Show feedback
        const notification = document.createElement('div');
        notification.className = 'fixed top-4 right-4 bg-blue-600 text-white px-6 py-3 rounded-xl shadow-xl z-50 notification-slide-up';
        notification.innerHTML = `
            <div class="flex items-center space-x-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>
                <span>Loaded: ${label}</span>
            </div>
        `;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 2000);
    }
}



// Test-related functions
async function runAPITest(endpointUrl) {
    console.log("Running API Test");
    console.log("Received endpointUrl:", endpointUrl);
    const testInput = document.getElementById('testInput');
    const runTestBtn = document.getElementById('runTestBtn');
    const testStatus = document.getElementById('testStatus');
    const testStatusText = document.getElementById('testStatusText');
    const testResults = document.getElementById('testResults');
    const responseStatus = document.getElementById('responseStatus');
    const responseTime = document.getElementById('responseTime');
    const responseBody = document.getElementById('responseBody');
    const responseHeadersContent = document.getElementById('responseHeadersContent');
    const deploySection = document.getElementById('deploySection');
    
    // Update UI to show testing in progress
    runTestBtn.disabled = true;
    runTestBtn.innerHTML = `
        <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
        </svg>
        <span>Testing...</span>
    `;
    testStatus.className = 'w-3 h-3 bg-yellow-500 rounded-full animate-pulse';
    testStatusText.textContent = 'Running test...';
    testStatusText.className = 'text-sm text-yellow-400';
    
    const startTime = Date.now();
    
    try {
        // Extract user_id and api_slug from endpointUrl
        // Handle both full URLs (with origin) and relative URLs
        let urlPath;
        if (endpointUrl.startsWith('http')) {
            // Full URL - extract the pathname
            const url = new URL(endpointUrl);
            urlPath = url.pathname;
        } else {
            // Relative URL
            urlPath = endpointUrl;
        }
        
        // Expected format: /api/{user_id}/{api_slug}
        const urlParts = urlPath.split('/').filter(part => part); // filter removes empty strings
        if (urlParts.length < 3 || urlParts[0] !== 'api') {
            throw new Error(`Invalid endpoint URL format. Expected /api/{user_id}/{api_slug}, got: ${urlPath}`);
        }
        
        const user_id = urlParts[1];
        const api_slug = urlParts[2];
        
        console.log("Parsed URL components:", { urlPath, urlParts, user_id, api_slug });
        
        // Prepare request data for the backend test endpoint
        const testData = {
            user_id: user_id,
            api_slug: api_slug,
            test_type: 'manual'
        };
        
        // Add test data if provided
        const testInputValue = testInput.value.trim();
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
        
        console.log("Request sent to /test-api:", testData);
        console.log("Response status:", response.status);
        
        const endTime = Date.now();
        const requestTime = endTime - startTime;
        
        // Get response data
        const testResult = await response.json();
        
        // Update UI with results
        testResults.classList.remove('hidden');
        
        // Response status - use the actual API status from the test result
        const actualStatusCode = testResult.status_code || response.status;
        const actualStatusText = testResult.success ? 'OK' : (testResult.error ? 'Error' : response.statusText);
        
        responseStatus.textContent = `${actualStatusCode} ${actualStatusText}`;
        responseStatus.className = testResult.success ? 
            'px-2 py-1 bg-green-600/20 text-green-300 rounded text-xs font-mono' :
            'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';
        
        // Use execution time from the test result if available, otherwise use request time
        const executionTimeMs = testResult.execution_time ? Math.round(testResult.execution_time * 1000) : requestTime;
        responseTime.textContent = `${executionTimeMs}ms`;
        
        // Response body - show the actual API response or error
        let displayData;
        if (testResult.success && testResult.response_data) {
            displayData = testResult.response_data;
        } else if (testResult.error) {
            displayData = { error: testResult.error };
        } else {
            displayData = testResult;
        }
        
        responseBody.textContent = typeof displayData === 'object' ? 
            JSON.stringify(displayData, null, 2) : String(displayData);
        
        // Response headers - use headers from test result
        const headers = testResult.response_headers || {};
        responseHeadersContent.textContent = JSON.stringify(headers, null, 2);
        
        // Update status based on test result
        if (testResult.success) {
            testStatus.className = 'w-3 h-3 bg-green-500 rounded-full';
            testStatusText.textContent = 'Test successful';
            testStatusText.className = 'text-sm text-green-400';
            
            // Show deploy section after successful test
            deploySection.classList.remove('hidden');
        } else {
            testStatus.className = 'w-3 h-3 bg-red-500 rounded-full';
            testStatusText.textContent = 'Test failed';
            testStatusText.className = 'text-sm text-red-400';
        }
        
    } catch (error) {
        // Handle errors
        testResults.classList.remove('hidden');
        
        responseStatus.textContent = 'Error';
        responseStatus.className = 'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';
        
        responseTime.textContent = `${Date.now() - startTime}ms`;
        responseBody.textContent = `Error: ${error.message}`;
        responseHeadersContent.textContent = 'No headers (request failed)';
        
        testStatus.className = 'w-3 h-3 bg-red-500 rounded-full';
        testStatusText.textContent = 'Test error';
        testStatusText.className = 'text-sm text-red-400';
    } finally {
        // Reset button
        runTestBtn.disabled = false;
        runTestBtn.innerHTML = `
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1m4 0h1m-6 4h1m4 0h1m6-10V7a3 3 0 11-6 0V4h6zM4 7v10a2 2 0 002 2h12a2 2 0 002-2V7"></path>
            </svg>
            <span>Run Test</span>
        `;
    }
}

function formatTestInput() {
    const testInput = document.getElementById('testInput');
    const value = testInput.value.trim();
    
    if (!value) {
        testInput.value = '{\n  "example": "value",\n  "key": "data"\n}';
        return;
    }
    
    try {
        const parsed = JSON.parse(value);
        testInput.value = JSON.stringify(parsed, null, 2);
    } catch (error) {
        // Show error feedback
        const notification = document.createElement('div');
        notification.className = 'fixed top-4 right-4 bg-red-600 text-white px-6 py-3 rounded-xl shadow-xl z-50 notification-slide-up';
        notification.innerHTML = `
            <div class="flex items-center space-x-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
                <span>Invalid JSON format</span>
            </div>
        `;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 3000);
    }
}

function clearTestData() {
    const testInput = document.getElementById('testInput');
    const testResults = document.getElementById('testResults');
    const deploySection = document.getElementById('deploySection');
    const testStatus = document.getElementById('testStatus');
    const testStatusText = document.getElementById('testStatusText');
    
    testInput.value = '';
    testResults.classList.add('hidden');
    deploySection.classList.add('hidden');
    
    // Reset status
    testStatus.className = 'w-3 h-3 bg-gray-500 rounded-full';
    testStatusText.textContent = 'Ready to test';
    testStatusText.className = 'text-sm text-gray-400';
}

function toggleResponseHeaders() {
    const headers = document.getElementById('responseHeaders');
    const chevron = document.getElementById('headersChevron');
    
    if (headers.classList.contains('hidden')) {
        headers.classList.remove('hidden');
        chevron.style.transform = 'rotate(90deg)';
    } else {
        headers.classList.add('hidden');
        chevron.style.transform = 'rotate(0deg)';
    }
}

function deployCurrentAPI() {
    // Create API details URL
    const apiDetailsUrl = `/api/${currentApiData.user_id}/${currentApiData.api_slug}/details`;
    
    // Add deployment success message
    addMessage('system', `
        🚀 API deployed successfully! Redirecting to API details page...
        <div class="mt-4 p-4 bg-green-900/20 border border-green-500/30 rounded-xl">
            <div class="flex items-center space-x-3">
                <div class="w-8 h-8 bg-green-500 rounded-full flex items-center justify-center">
                    <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                    </svg>
                </div>
                <div>
                    <h4 class="font-medium text-green-300 mb-1">Deployment Complete</h4>
                    <p class="text-sm text-green-200">Taking you to the API management page where you can test, monitor, and manage your API.</p>
                </div>
            </div>
        </div>
    `);
    
    // Show a brief animation/delay then redirect
    setTimeout(() => {
        // Add a loading/redirect message
        addMessage('system', `
            <div class="flex items-center justify-center space-x-3 p-4">
                <svg class="w-5 h-5 text-blue-400 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                </svg>
                <span class="text-blue-400">Redirecting to API details page...</span>
            </div>
        `);
        
        // Redirect after a short delay
        setTimeout(() => {
            window.location.href = apiDetailsUrl;
        }, 1500);
    }, 2000);
}

function showTypingIndicator(message) {
    const messagesContainer = document.getElementById('chatMessages');
    const typingDiv = document.createElement('div');
    typingDiv.id = 'typingIndicator';
    typingDiv.className = 'typing-indicator';
    typingDiv.innerHTML = `
        <div class="flex items-center space-x-3">
            <div class="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0">
                <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                </svg>
            </div>
            <div class="flex items-center space-x-3">
                <div class="typing-dots">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
                <span class="text-sm text-slate-300">${message}</span>
            </div>
        </div>
    `;
    messagesContainer.appendChild(typingDiv);
    setTimeout(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }, 50);
}

function hideTypingIndicator() {
    const typingIndicator = document.getElementById('typingIndicator');
    if (typingIndicator) {
        typingIndicator.remove();
    }
}

// Utility functions
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        // Show temporary feedback
        const notification = document.createElement('div');
        notification.className = 'fixed top-4 right-4 bg-emerald-600 text-white px-6 py-3 rounded-xl shadow-xl z-50 animate-slide-up';
        notification.innerHTML = `
            <div class="flex items-center space-x-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>
                <span>Copied to clipboard!</span>
            </div>
        `;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 3000);
    });
}


async function saveCurrentAPI() {
    if (!currentApiData) {
        addMessage('system', '❌ No API available to save. Please generate an API first.');
        return;
    }
    
    if (!currentUser) {
        addMessage('system', 'Please <a href="/login" class="text-blue-400 hover:text-blue-300 underline">login</a> to save APIs');
        return;
    }

    try {
        const response = await fetch('/save-api', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authToken}`
            },
            body: JSON.stringify({
                user_id: currentUser.id,
                api_slug: currentApiData.api_slug,
                api_name: currentApiData.api_name || `API ${currentApiData.api_slug}`,
                prompt: currentConversation.find(m => m.type === 'user')?.content || '',
                endpoint_url: currentApiData.endpoint_url,
                documentation: currentApiData.documentation,
                curl_example: currentApiData.curl_example
            })
        });

        const result = await response.json();
        
        if (result.success) {
            addMessage('system', '✅ API saved successfully! You can view it in your <a href="/profile" class="text-blue-400 hover:text-blue-300 underline">profile</a>.');
        } else {
            addMessage('system', `❌ Failed to save API: ${result.message}`);
        }
    } catch (error) {
        addMessage('system', `❌ Save error: ${error.message}`);
    }
}

async function modifyCurrentAPI() {
    if (!currentApiData) {
        addMessage('system', '❌ No API available to modify. Please generate an API first.');
        return;
    }

    // Ask user for modification prompt
    const modificationPrompt = prompt('What would you like to modify in this API?');
    if (!modificationPrompt) {
        return;
    }

    try {
        // Get user ID (from auth or generate temp one)
        const userId = currentUser ? currentUser.id : 'temp_' + Date.now();
        
        // Show modification in progress
        addMessage('user', `Modify API: ${modificationPrompt}`);
        showTypingIndicator('Modifying API...');
        
        const response = await fetch('/modify-api', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                prompt: modificationPrompt,
                api_slug: currentApiData.api_slug,
                user_id: userId
            })
        });

        const result = await response.json();
        
        hideTypingIndicator();

        if (result.success) {
            // Update current API data
            currentApiData = result;
            addAPIResultMessage(result);
            addMessage('system', '✅ API modified successfully! The updated version is now available above.');
        } else {
            // Handle different types of unsuccessful responses
            if (result.status === 'needs_clarification') {
                addClarificationMessage(result);
            } else if (result.status === 'modify_request') {
                addModifyRequestMessage(result);
            } else if (result.status === 'not_buildable') {
                addRejectionMessage(result);
            } else {
                // Fallback for any other error
                addMessage('assistant', `❌ Error: ${result.message || 'Failed to modify API'}`);
            }
        }
    } catch (error) {
        hideTypingIndicator();
        addMessage('assistant', `❌ Network error: ${error.message}`);
    }
}

function logout() {
    authToken = null;
    currentUser = null;
    localStorage.removeItem('authToken');
    localStorage.removeItem('currentUser');
    updateAuthUI();
    addMessage('system', '👋 Logged out successfully!');
}

// Adjust chat height dynamically
function adjustChatHeight() {
    const chatMessages = document.getElementById('chatMessages');
    const windowHeight = window.innerHeight;
    
    // Calculate height: full viewport minus input area and padding (no header)
    const headerHeight = 0; // No header since it's commented out
    const inputAreaHeight = 250; // Approximate input area height
    const paddingBuffer = 20; // Reduced buffer for tighter layout
    
    const maxHeight = windowHeight - headerHeight - inputAreaHeight - paddingBuffer;
    chatMessages.style.maxHeight = `${Math.max(300, maxHeight)}px`; // Minimum 300px
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Focus on input
    document.getElementById('chatInput').focus();
    
    // Initialize character counter
    handleInputChange();
    
    // Adjust chat height on load and resize
    adjustChatHeight();
    window.addEventListener('resize', adjustChatHeight);
    
    // Ensure scroll to bottom button starts hidden
    document.getElementById('scrollToBottomBtn').classList.add('hidden');
}); 