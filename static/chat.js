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
    showTypingIndicator();

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

function addAPIResultMessage(result) {
    const endpointUrl = window.location.origin + result.endpoint_url;
    
    const content = `
        <div class="space-y-6">
            <div class="flex items-center space-x-2">
                <span class="status-badge status-buildable">Success</span>
                <h3 class="font-semibold text-white">🎉 API Generated Successfully!</h3>
            </div>
            
            <!-- Endpoint URL Card -->
            <div class="glass-card rounded-xl p-6 border-emerald-500/30">
                <div class="flex items-center justify-between mb-4">
                    <h4 class="font-semibold text-white flex items-center space-x-2">
                        <span class="text-emerald-400">📡</span>
                        <span>Endpoint URL</span>
                    </h4>
                    <button onclick="copyToClipboard('${endpointUrl}')" 
                            class="px-3 py-1 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg transition-colors">
                        Copy URL
                    </button>
                </div>
                <div class="code-highlight rounded-lg p-4">
                    <code class="text-emerald-400 font-mono text-sm break-all">${endpointUrl}</code>
                </div>
            </div>
            
            <!-- Documentation Card -->
            <div class="glass-card rounded-xl p-6">
                <h4 class="font-semibold text-white mb-4 flex items-center space-x-2">
                    <span class="text-blue-400">📚</span>
                    <span>Documentation</span>
                </h4>
                <div class="code-highlight rounded-lg p-4">
                    <pre class="whitespace-pre-wrap text-slate-300 text-sm">${result.documentation}</pre>
                </div>
            </div>
            
            <!-- cURL Example Card -->
            <div class="glass-card rounded-xl p-6">
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

function showTypingIndicator() {
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
                <span class="text-sm text-slate-300">AI is generating your API...</span>
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


async function quickTestAPI() {
    if (!currentApiData) {
        addMessage('system', '❌ No API available to test. Please generate an API first.');
        return;
    }
    
    const endpointUrl = window.location.origin + currentApiData.endpoint_url;
    const testData = prompt('Enter test data (JSON format, optional):');
        
    try {
        const formData = new FormData();
        if (testData && testData.trim()) {
            formData.append('input_data', testData);
        }

        const response = await fetch(endpointUrl, {
            method: 'POST',
            body: formData
        });

        const result = await response.json();
        
        if (result.success) {
            addMessage('system', `✅ Test successful! Result: <div class="code-highlight rounded p-3 mt-2"><pre class="text-sm">${JSON.stringify(result.result, null, 2)}</pre></div>`);
        } else {
            addMessage('system', `❌ Test failed: ${result.error || 'Unknown error'}`);
        }
    } catch (error) {
        addMessage('system', `❌ Test error: ${error.message}`);
    }
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
        showTypingIndicator();
        
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
    
    // Calculate height: full viewport minus header, input area, and padding
    const headerHeight = 120; // Approximate header height
    const inputAreaHeight = 250; // Approximate input area height
    const paddingBuffer = 40; // Buffer for spacing
    
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