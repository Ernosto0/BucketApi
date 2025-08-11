let currentConversation = [];
let isGenerating = false;
let currentApiData = null;
let isModificationMode = false;

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

function hideChatInput() {
    const chatInputContainer = document.getElementById('chatInputContainer');
    const chatContainer = document.getElementById('chatContainer');
    
    if (chatInputContainer) {
        chatInputContainer.style.display = 'none';
        
        // Add CSS class to expand chat area
        if (chatContainer) {
            chatContainer.classList.add('chat-input-hidden');
        }
        
        // Add a message to indicate why chat input is hidden
        addMessage('system', '💡 Chat input hidden - Your API is being generated! You can test and deploy it once it\'s ready.');
    }
}

function showChatInput() {
    const chatInputContainer = document.getElementById('chatInputContainer');
    const chatContainer = document.getElementById('chatContainer');
    
    if (chatInputContainer) {
        chatInputContainer.style.display = 'block';
        
        // Remove CSS class to restore normal chat area
        if (chatContainer) {
            chatContainer.classList.remove('chat-input-hidden');
        }
    }
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
    isModificationMode = false; // Reset modification mode
    showChatInput(); // Show chat input when clearing chat for new conversation
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

    // Check if we're in modification mode
    if (isModificationMode) {
        // Reset modification mode flag
        isModificationMode = false;
        
        // Reset placeholder
        input.placeholder = "Describe your API requirements... (e.g., 'Create an API that extracts text from PDF files')";
        
        // Get user ID (from auth or generate temp one)
        const userId = currentUser ? currentUser.id : 'temp_' + Date.now();
        
        // Process the modification request directly
        await processModificationRequest(message, userId);
        return;
    }

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
            addMessage('system', '🎉 API generated successfully! You can now test and deploy your API using the interface above.');
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

// Helper function to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
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
                <h4 class="font-bold text-xl text-white mb-2">${escapeHtml(proposal.api_name || 'Custom API')}</h4>
                <p class="text-slate-300 mb-3">${escapeHtml(proposal.description || 'A custom API based on your requirements')}</p>
                ${analysis.original_prompt ? `
                <div class="mt-4 p-3 bg-slate-800/30 border border-slate-600/30 rounded-lg">
                    <h6 class="text-xs font-medium text-slate-400 mb-1">Based on your request:</h6>
                    <p class="text-sm text-slate-300 italic">"${escapeHtml(analysis.original_prompt)}"</p>
                </div>
                ` : ''}
                ${analysis.confirmation_needed ? `
                <div class="mt-3 flex items-center space-x-2">
                    <div class="w-2 h-2 bg-orange-400 rounded-full animate-pulse"></div>
                    <span class="text-xs text-orange-400">Confirmation Required</span>
                </div>
                ` : ''}
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
                    ${proposal.input_format.fields ? `
                    <div class="mb-3">
                        <h6 class="text-xs font-medium text-green-300 mb-1">Required Fields:</h6>
                        <div class="flex flex-wrap gap-1">
                            ${proposal.input_format.fields.map(field => `<span class="px-2 py-1 bg-green-600/20 text-green-300 rounded text-xs font-mono">${field}</span>`).join('')}
                        </div>
                    </div>
                    ` : ''}
                    ${proposal.input_format.example ? `
                    <div class="code-highlight rounded p-3">
                        <h6 class="text-xs font-medium text-green-300 mb-2">Example:</h6>
                        <pre class="text-xs text-slate-300 font-mono">${typeof proposal.input_format.example === 'object' ? JSON.stringify(proposal.input_format.example, null, 2) : proposal.input_format.example}</pre>
                    </div>
                    ` : ''}
                </div>
                ` : ''}
                ${proposal.output_format ? `
                <div class="glass-card rounded-xl p-4">
                    <h5 class="font-semibold text-purple-400 mb-2">📤 Output Format</h5>
                    <p class="text-sm text-slate-300 mb-2">${proposal.output_format.type || 'JSON'}</p>
                    ${proposal.output_format.fields ? `
                    <div class="mb-3">
                        <h6 class="text-xs font-medium text-purple-300 mb-1">Response Fields:</h6>
                        <div class="flex flex-wrap gap-1">
                            ${proposal.output_format.fields.map(field => `<span class="px-2 py-1 bg-purple-600/20 text-purple-300 rounded text-xs font-mono">${field}</span>`).join('')}
                        </div>
                    </div>
                    ` : ''}
                    ${proposal.output_format.example ? `
                    <div class="code-highlight rounded p-3">
                        <h6 class="text-xs font-medium text-purple-300 mb-2">Example:</h6>
                        <pre class="text-xs text-slate-300 font-mono">${typeof proposal.output_format.example === 'object' ? JSON.stringify(proposal.output_format.example, null, 2) : proposal.output_format.example}</pre>
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

            <!-- Next Steps (if available) -->
            ${analysis.next_steps && analysis.next_steps.length > 0 ? `
            <div class="glass-card rounded-xl p-6">
                <h4 class="font-semibold text-white mb-3 flex items-center space-x-2">
                    <span class="text-blue-400">📋</span>
                    <span>Next Steps</span>
                </h4>
                <ul class="space-y-2">
                    ${analysis.next_steps.map(step => `<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-slate-300">${step}</span></li>`).join('')}
                </ul>
            </div>
            ` : ''}

            

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
        
        // Hide the chat input container since user won't need to send more messages
        hideChatInput();
        
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
    
    // Show chat input back since user needs to type their modifications
    showChatInput();
    
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
    
    // Show chat input back since user cancelled and might want to start over
    showChatInput();
    
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
                
                <!-- Pricing Estimation (Will be populated after generation) -->
                <div id="pricingEstimation" class="mt-4 p-3 bg-slate-800/30 rounded-lg border border-slate-600/30">
                    <div class="flex items-center space-x-2 mb-2">
                        <span class="text-yellow-400">💰</span>
                        <span class="text-sm font-medium text-slate-300">Estimated Pricing</span>
                        <span class="text-xs text-slate-500">(Run test to see exact costs)</span>
                    </div>
                    <div class="text-xs text-slate-400">
                        <div class="grid grid-cols-3 gap-2">
                            <div class="text-center py-2 bg-slate-700/30 rounded">
                                <div class="text-slate-500">Cost per call</div>
                                <div class="text-green-400 font-mono">~$0.02</div>
                            </div>
                            <div class="text-center py-2 bg-slate-700/30 rounded">
                                <div class="text-slate-500">Internal tokens</div>
                                <div class="text-blue-400 font-mono">~20</div>
                            </div>
                            <div class="text-center py-2 bg-slate-700/30 rounded">
                                <div class="text-slate-500">AI model</div>
                                <div class="text-purple-400 font-mono">estimated</div>
                            </div>
                        </div>
                        <p class="text-center mt-2 text-slate-500 text-xs">🔍 Test your API to see exact pricing based on actual usage</p>
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
                            <p class="text-sm text-slate-400">Your API is working! Deploy it to make it publicly available or modify it further.</p>
                        </div>
                        <div class="flex items-center space-x-3">
                            <button onclick="modifyCurrentAPI()" 
                                    class="px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-xl font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg flex items-center space-x-2">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                                </svg>
                                <span>Modify API</span>
                            </button>
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
            </div>
            
            <!-- Documentation Card -->
            <div id="documentationSection" class="glass-card rounded-xl p-6">
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
        
        // Response body - show the actual API response or a user-friendly message
        let displayData;
        if (testResult.debugged) {
            displayData = { message: "The code had an issue but it has been fixed automatically. Please run the test again to verify the fix." };
        } else if (testResult.success && testResult.response_data) {
            displayData = testResult.response_data;
        } else if (testResult.error) {
            displayData = { error: "The test failed. Please check your input data and try again." };
        } else {
            displayData = testResult;
        }
        
        responseBody.textContent = typeof displayData === 'object' ? 
            JSON.stringify(displayData, null, 2) : String(displayData);
        
        // Response headers - use headers from test result
        const headers = testResult.response_headers || {};
        responseHeadersContent.textContent = JSON.stringify(headers, null, 2);
        
        // Extract pricing information from response headers
        const responseHeaders = testResult.response_headers || {};
        const costPerCallCents = responseHeaders['x-cost-per-call-cents'];
        const internalTokensPerCall = responseHeaders['x-internal-tokens-per-call'];
        const aiModelUsed = responseHeaders['x-ai-model-used'];

        // Update status based on test result
        if (testResult.success && !testResult.debugged) {
            testStatus.className = 'w-3 h-3 bg-green-500 rounded-full';
            testStatusText.textContent = 'Test successful';
            testStatusText.className = 'text-sm text-green-400';
            
            // Show deploy section after successful test
            deploySection.classList.remove('hidden');
            
            // Add pricing information message to chat
            if (costPerCallCents && internalTokensPerCall) {
                const costInDollars = (parseFloat(costPerCallCents) / 100).toFixed(4);
                                 const pricingMessage = `
                     💰 <strong>API Pricing Information</strong>
                    <div class="mt-3 p-4 bg-blue-900/20 border border-blue-500/30 rounded-xl">
                        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                            <div class="bg-slate-700/50 rounded-lg p-3">
                                <div class="text-slate-400 text-xs uppercase tracking-wide mb-1">Cost per Call</div>
                                <div class="text-green-400 font-bold text-lg">$${costInDollars}</div>
                                <div class="text-slate-500 text-xs">${costPerCallCents} cents</div>
                            </div>
                            <div class="bg-slate-700/50 rounded-lg p-3">
                                <div class="text-slate-400 text-xs uppercase tracking-wide mb-1">Internal Tokens</div>
                                <div class="text-blue-400 font-bold text-lg">${internalTokensPerCall}</div>
                                <div class="text-slate-500 text-xs">tokens per call</div>
                            </div>
                            <div class="bg-slate-700/50 rounded-lg p-3">
                                <div class="text-slate-400 text-xs uppercase tracking-wide mb-1">AI Model</div>
                                <div class="text-purple-400 font-medium">${aiModelUsed || 'estimated'}</div>
                                <div class="text-slate-500 text-xs">underlying model</div>
                            </div>
                        </div>
                        <div class="mt-3 pt-3 border-t border-slate-600/50">
                            <p class="text-xs text-slate-400">
                                🔍 <strong>Estimated monthly cost for 1,000 calls:</strong> 
                                <span class="text-green-400 font-medium">$${(parseFloat(costPerCallCents) * 1000 / 100).toFixed(2)}</span>
                                <span class="text-slate-500 ml-2">(${(parseInt(internalTokensPerCall) * 1000).toLocaleString()} internal tokens)</span>
                            </p>
                        </div>
                    </div>
                `;
                addMessage('system', pricingMessage);
            }
        } else if (testResult.debugged) {
            testStatus.className = 'w-3 h-3 bg-yellow-500 rounded-full';
            testStatusText.textContent = 'Code was fixed automatically. Please test again.';
            testStatusText.className = 'text-sm text-yellow-400';
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

    // Save the deployed API
    saveCurrentAPI();

    // Get pricing information from the last test (if available)
    const testResults = document.getElementById('testResults');
    const responseHeadersContent = document.getElementById('responseHeadersContent');
    let pricingSummary = '';
    
    try {
        // Try to extract pricing from headers if test was run
        if (responseHeadersContent && responseHeadersContent.textContent) {
            const headers = JSON.parse(responseHeadersContent.textContent);
            const costPerCallCents = headers['x-cost-per-call-cents'];
            const internalTokensPerCall = headers['x-internal-tokens-per-call'];
            const aiModelUsed = headers['x-ai-model-used'];
            
            if (costPerCallCents && internalTokensPerCall) {
                const costInDollars = (parseFloat(costPerCallCents) / 100).toFixed(4);
                pricingSummary = `
                    <div class="mt-3 pt-3 border-t border-green-500/30">
                        <h5 class="text-sm font-medium text-green-200 mb-2">💰 Pricing Summary:</h5>
                        <div class="grid grid-cols-3 gap-3 text-xs">
                            <div class="text-center">
                                <div class="text-green-300 font-bold">$${costInDollars}</div>
                                <div class="text-green-400/70">per call</div>
                            </div>
                            <div class="text-center">
                                <div class="text-blue-300 font-bold">${internalTokensPerCall}</div>
                                <div class="text-blue-400/70">tokens</div>
                            </div>
                            <div class="text-center">
                                <div class="text-purple-300 font-medium">${aiModelUsed || 'est.'}</div>
                                <div class="text-purple-400/70">model</div>
                            </div>
                        </div>
                    </div>
                `;
            }
        }
    } catch (e) {
        // Ignore JSON parsing errors
        console.log('Could not extract pricing info for deployment summary');
    }
    
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
                <div class="flex-1">
                    <h4 class="font-medium text-green-300 mb-1">Deployment Complete</h4>
                    <p class="text-sm text-green-200">Taking you to the API management page where you can test, monitor, and manage your API.</p>
                    ${pricingSummary}
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

    // Set modification mode flag
    isModificationMode = true;
    
    // Show chat input for modification request
    showChatInput();
    
    // Add a message explaining how to modify
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <span class="status-badge bg-blue-900/50 text-blue-400 border-blue-500/30">Modification Mode</span>
                <h3 class="font-semibold text-white">How would you like to modify your API?</h3>
            </div>
            <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4">
                <p class="text-blue-300 text-sm mb-3">
                    Describe the changes you'd like to make to your current API:
                </p>
                <ul class="text-sm text-blue-200 space-y-2">
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Add new features or endpoints</span></li>
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Change input/output formats</span></li>
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Modify existing functionality</span></li>
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Update error handling or validation</span></li>
                    <li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span>Change technologies or approach</span></li>
                </ul>
            </div>
            <div class="text-center text-sm text-slate-400">
                Type your modification request in the chat input below and press Enter
            </div>
        </div>
    `;
    
    addMessage('assistant', content);
    
    // Focus on the chat input
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.focus();
        chatInput.placeholder = "Describe how you'd like to modify your API... (e.g., 'Add email validation to the input')";
    }
}

async function processModificationRequest(modificationPrompt, userId) {
    try {
        // Show modification in progress
        showTypingIndicator('Modifying your API...');
        
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
            
            // Reset placeholder
            const chatInput = document.getElementById('chatInput');
            if (chatInput) {
                chatInput.placeholder = "Describe your API requirements... (e.g., 'Create an API that extracts text from PDF files')";
            }
            
            // Hide chat input again since modification is complete
            hideChatInput();
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
    const chatInputContainer = document.getElementById('chatInputContainer');
    const windowHeight = window.innerHeight;
    
    // Calculate height: full viewport minus input area and padding (no header)
    const headerHeight = 0; // No header since it's commented out
    const paddingBuffer = 20; // Reduced buffer for tighter layout
    
    // Check if chat input is hidden
    const isInputHidden = chatInputContainer && (chatInputContainer.style.display === 'none' || chatInputContainer.classList.contains('hidden'));
    const inputAreaHeight = isInputHidden ? 0 : 250; // No input area height if hidden
    
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