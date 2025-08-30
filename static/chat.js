let currentConversation = [];
let isGenerating = false;
let currentApiData = null;
let isModificationMode = false;
let generationMode = 'multi-step'; // Default to multi-step

// Conversation state tracking
let conversationState = null; // "proposal", "code_generated", null
let currentProposalId = null; // Unique identifier for current proposal session
let currentProposal = null; // Store current proposal data

// Helper function to detect if a message is a modification request using cheap LLM classification
async function isModificationRequest(message) {
    try {
        // Quick local checks for very obvious cases to save API calls
        const lowerMessage = message.toLowerCase().trim();
        
        console.log('isModificationRequest called with:', {
            originalMessage: message,
            lowerMessage: lowerMessage
        });
        
        // Very obvious conversational patterns - no need for LLM
        if (/^(thanks?|thank you|ty|thx|good|great|perfect|ok|okay|yes|no)$/i.test(lowerMessage)) {
            console.log('Matched conversational pattern - returning false');
            return false;
        }
        
        // Very obvious modification patterns - no need for LLM  
        if (/^(add|remove|change|delete|modify|update)\s/i.test(lowerMessage)) {
            console.log('Matched obvious modification pattern - returning true');
            return true;
        }
        
        // Additional obvious modification patterns
        if (/(but i|i only|i don't need|i want|i need|without|exclude|only extract|just|remove|add|change|delete|modify|update|can you)/i.test(lowerMessage)) {
            console.log('Matched additional modification pattern - returning true');
            return true;
        }
        
        // For everything else, use cheap LLM classification
        console.log('No local pattern matched, calling LLM classification...');
        
        const response = await fetch('/classify-message-intent', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                message: message,
                context: 'user_has_api_proposal'
            })
        });
        
        const result = await response.json();
        console.log('LLM classification result:', result);
        
        if (result.success) {
            const isModification = result.intent === 'modification';
            console.log('LLM classification: returning', isModification);
            return isModification;
        } else {
            console.warn('Intent classification failed, falling back to conservative approach');
            // Fallback: assume it's conversational unless it clearly looks like modification
            return false;
        }
        
    } catch (error) {
        console.error('Error classifying message intent:', error);
        // Fallback: assume conversational to be safe
        return false;
    }
}

// Helper function to handle conversational messages
function handleConversationalMessage(message) {
    const lowerMessage = message.toLowerCase().trim();
    
    // Generate appropriate responses for different types of conversational messages
    let response = '';
    
    if (/^(thanks?|thank you|ty|thx)/.test(lowerMessage)) {
        response = "You're welcome! 😊 When you're ready to proceed, you can click 'Build It!' to generate your API, or let me know if you'd like to make any changes to the proposal.";
    } else if (/(good|great|perfect|excellent|awesome|nice|cool)/.test(lowerMessage)) {
        response = "Great to hear! 🎉 Your API proposal is ready. You can click 'Build It!' to generate the code, or feel free to request any modifications you'd like.";
    } else if (/(looks? good|that('?s| is) good)/.test(lowerMessage)) {
        response = "Perfect! 👍 Your API proposal meets your needs. Ready to build it? Just click 'Build It!' or let me know if you want to adjust anything.";
    } else if (/^(hi|hello|hey)/.test(lowerMessage)) {
        response = "Hello! 👋 I see you have an API proposal ready. You can review it in the preview panel and click 'Build It!' when you're ready, or ask me to make any changes.";
    } else if (/^(ok|okay|alright|sounds? good)/.test(lowerMessage)) {
        response = "Excellent! ✅ Your API proposal is all set. You can proceed with building it or request any modifications you need.";
    } else {
        // Generic response for other conversational messages
        response = "I'm here to help with your API! 🤖 Your current proposal is ready for review. You can build it as-is or ask me to make any changes you'd like.";
    }
    
    addMessage('assistant', response);
}

// Proposal modification handling with explicit context
async function handleProposalModificationWithContext(modificationRequest, userId, proposalContext) {
    try {
        console.log('handleProposalModificationWithContext called with:', {
            modificationRequest,
            userId,
            proposalContext,
            hasProposalData: !!proposalContext?.proposal
        });
        
        showTypingIndicator("Analyzing your proposal modification...");
        
        const modifyResponse = await fetch('/modify-proposal', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                original_prompt: proposalContext.original_prompt,
                modification_request: modificationRequest,
                user_id: userId,
                proposal_id: proposalContext.proposal_id || currentProposalId,
                current_proposal: proposalContext.proposal
            })
        });

        const modifyResult = await modifyResponse.json();
        console.log('Proposal Modification Response:', modifyResult);
        console.log('Modification Result Keys:', Object.keys(modifyResult));
        console.log('Modification Proposal field exists:', 'proposal' in modifyResult);
        console.log('Modification Proposal field value:', modifyResult.proposal);
        
        if (modifyResult.success) {
            // Update conversation state
            conversationState = modifyResult.conversation_state;
            currentProposalId = modifyResult.proposal_id;
            
            // Update current proposal with modified version
            if (modifyResult.modified_prompt) {
                currentProposal = {
                    ...currentProposal,
                    original_prompt: modifyResult.modified_prompt,
                    modified_prompt: modifyResult.modified_prompt,
                    status: modifyResult.status
                };
            }
            
            // If the modification response contains updated proposal data, update the current proposal
            if (modifyResult.proposal) {
                currentProposal = {
                    ...currentProposal,
                    proposal: modifyResult.proposal
                };
                console.log('Updated currentProposal with modified proposal data');
            }
            
            // Also update with modified requirements if available
            if (modifyResult.modified_requirements) {
                currentProposal = {
                    ...currentProposal,
                    modified_requirements: modifyResult.modified_requirements
                };
                console.log('Updated currentProposal with modified requirements');
            }
            
            // Handle the modification response
            if (modifyResult.status === 'buildable') {
                addProposalMessage(modifyResult, modifyResult.modified_prompt || modificationRequest, userId);
            } else if (modifyResult.status === 'needs_clarification') {
                addClarificationMessage(modifyResult);
            } else if (modifyResult.status === 'not_buildable') {
                addRejectionMessage(modifyResult);
            }
        } else {
            addMessage('assistant', `❌ Failed to process proposal modification: ${modifyResult.message || 'Unknown error'}`);
        }
        
        hideTypingIndicator();
    } catch (error) {
        console.error('Error handling proposal modification:', error);
        addMessage('assistant', '❌ Failed to process proposal modification: Network error');
        hideTypingIndicator();
    }
}

// Legacy proposal modification handling (for modify_request status)
async function handleProposalModification(modificationRequest, userId) {
    try {
        console.log('handleProposalModification called with:', {
            modificationRequest,
            userId,
            currentProposal,
            currentProposalId,
            hasProposalData: !!currentProposal?.proposal
        });
        
        showTypingIndicator("Analyzing your proposal modification...");
        
        const modifyResponse = await fetch('/modify-proposal', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                original_prompt: currentProposal.original_prompt,
                modification_request: modificationRequest,
                user_id: userId,
                proposal_id: currentProposalId,
                current_proposal: currentProposal.proposal
            })
        });

        const modifyResult = await modifyResponse.json();
        console.log('Proposal Modification Response:', modifyResult);
        console.log('Modification Result Keys:', Object.keys(modifyResult));
        console.log('Modification Proposal field exists:', 'proposal' in modifyResult);
        console.log('Modification Proposal field value:', modifyResult.proposal);
        
        if (modifyResult.success) {
            // Update conversation state
            conversationState = modifyResult.conversation_state;
            currentProposalId = modifyResult.proposal_id;
            
            // Update current proposal with modified version
            if (modifyResult.modified_prompt) {
                currentProposal = {
                    ...currentProposal,
                    original_prompt: modifyResult.modified_prompt,
                    modified_prompt: modifyResult.modified_prompt,
                    status: modifyResult.status
                };
            }
            
            // If the modification response contains updated proposal data, update the current proposal
            if (modifyResult.proposal) {
                currentProposal = {
                    ...currentProposal,
                    proposal: modifyResult.proposal
                };
                console.log('Updated currentProposal with modified proposal data');
            }
            
            // Also update with modified requirements if available
            if (modifyResult.modified_requirements) {
                currentProposal = {
                    ...currentProposal,
                    modified_requirements: modifyResult.modified_requirements
                };
                console.log('Updated currentProposal with modified requirements');
            }
            
            // Handle the modification response
            if (modifyResult.status === 'buildable') {
                addProposalMessage(modifyResult, modifyResult.modified_prompt || modificationRequest, userId);
            } else if (modifyResult.status === 'needs_clarification') {
                addClarificationMessage(modifyResult);
            } else if (modifyResult.status === 'not_buildable') {
                addRejectionMessage(modifyResult);
            }
        } else {
            addMessage('assistant', `❌ Failed to process proposal modification: ${modifyResult.detail || 'Unknown error'}`);
        }
        
    } catch (error) {
        console.error('Error handling proposal modification:', error);
        addMessage('assistant', `❌ Network error: ${error.message}`);
    } finally {
        hideTypingIndicator();
    }
}

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

// Generation mode handling
function handleGenerationModeChange() {
    const generationModeSelect = document.getElementById('generationModeSelect');
    generationMode = generationModeSelect.value;
    console.log('Generation mode changed to:', generationMode);
}

// Initialize generation mode on page load
document.addEventListener('DOMContentLoaded', function() {
    // Initialize generation mode
    handleGenerationModeChange();
});

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
    // Reset conversation state tracking
    conversationState = null;
    currentProposalId = null;
    currentProposal = null;
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

    // Check if we're already in proposal state - if so, check if it's a modification request
    if (conversationState === 'proposal' && currentProposal && currentProposal.proposal) {
        console.log('Already in proposal state - checking if message is a modification request', {
            conversationState,
            hasCurrentProposal: !!currentProposal,
            hasProposalData: !!currentProposal?.proposal,
            message: message
        });
        
        // Check if the message looks like a modification request
        const isModification = await isModificationRequest(message);
        console.log('isModificationRequest returned:', isModification);
        
        if (isModification) {
            console.log('Message detected as modification request - bypassing analysis');
            
            // Get user ID (from auth or generate temp one)
            const userId = currentUser ? currentUser.id : 'temp_' + Date.now();
            
            // Go directly to modification without analysis
            await handleProposalModificationWithContext(message, userId, currentProposal);
            return;
        } else {
            console.log('Message does not appear to be a modification request - handling as conversational');
            
            // Handle conversational messages (thanks, looks good, etc.)
            handleConversationalMessage(message);
            return;
        }
    }

            // Show typing indicator with generation mode info
        const modeText = generationMode === 'multi-step' ? 
            `Analyzing your request... (Multi-step)` : 
            "Analyzing your request... (Single-step)";
        showTypingIndicator(modeText);

    try {
        isGenerating = true;
        
        // Get user ID (from auth or generate temp one)
        const userId = currentUser ? currentUser.id : 'temp_' + Date.now();
        
        // First, generate a proposal for the prompt
        const proposalResponse = await fetch('/generate-proposal', {
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

        const proposalResult = await proposalResponse.json();
        console.log('Proposal Response:', proposalResult);
        console.log('Proposal Status:', proposalResult.status);
        console.log('Proposal Success:', proposalResult.success);
        console.log('Proposal Result Keys:', Object.keys(proposalResult));
        console.log('Proposal field exists:', 'proposal' in proposalResult);
        console.log('Proposal field value:', proposalResult.proposal);
        
        if (proposalResult.success) {
            // Store the previous conversation state before updating
            const previousConversationState = conversationState;
            const previousProposal = currentProposal;
            
            // Store conversation state from proposal response
            conversationState = proposalResult.conversation_state;
            currentProposalId = proposalResult.proposal_id;
            currentProposal = proposalResult;
            
            console.log('Proposal State:', { 
                previousState: previousConversationState, 
                newState: conversationState, 
                currentProposalId,
                hasPreviousProposal: !!previousProposal?.proposal
            });
            
            // Handle different proposal response types
            if (proposalResult.status === 'buildable' || proposalResult.status === 'proposal_ready') {
                console.log('Creating new proposal - calling addProposalMessage');
                // Show detailed API proposal and ask for confirmation
                addProposalMessage(proposalResult, message, userId);
            } else if (proposalResult.status === 'needs_clarification') {
                // Show clarification questions
                addClarificationMessage(proposalResult);
            } else if (proposalResult.status === 'modify_request') {
                // Check if we're in proposal state - if so, handle as proposal modification
                if (conversationState === 'proposal') {
                    console.log('Handling as proposal modification request');
                    await handleProposalModification(message, userId);
                } else {
                    // Show generic modify request message
                    addModifyRequestMessage(proposalResult);
                }
            } else if (proposalResult.status === 'not_buildable') {
                // Show rejection with suggestions
                addRejectionMessage(proposalResult);
            } else {
                console.log('UNEXPECTED STATUS:', proposalResult.status);
                console.log('Full proposal result:', proposalResult);
                addMessage('assistant', `⚠️ Unexpected proposal status: ${proposalResult.status}`);
            }
            
            // Hide typing indicator after processing proposal response
            hideTypingIndicator();
        } else {
            console.log('Proposal request failed:', proposalResult);
            // Fallback: proceed with API generation if analysis fails
            hideTypingIndicator();
            addMessage('assistant', `❌ Proposal generation failed: ${proposalResult.detail || 'Unknown error'}`);
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
        console.log(`Generating API - Skip Analysis: ${skipAnalysis}, Mode: ${generationMode}`);
        console.log('generateAPI called with message:', message);
        
        // Update generation progress text if it exists
        const progressText = document.getElementById('generationProgressText');
        if (progressText) {
            const genModeText = generationMode === 'multi-step' ? 
                `Generating your API... (Multi-step)` : 
                'Generating your API... (Single-step)';
            progressText.textContent = genModeText;
        }
        
        const response = await fetch('/generate-api', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                prompt: message,
                user_id: userId,
                skip_analysis: skipAnalysis,
                use_multi_step: generationMode === 'multi-step',
                pipeline_name: 'full_pipeline',
                proposal_id: currentProposalId,
                // Extract sample input/output from proposal if available
                sample_input: currentProposal?.proposal?.input_format?.example || null,
                expected_output: currentProposal?.proposal?.output_format?.example || null
            })
        });

        const result = await response.json();
        
        hideTypingIndicator();

        if (result.success) {
            // Update conversation state to indicate code has been generated
            conversationState = result.conversation_state || 'code_generated';
            
            currentApiData = result;
            addAPIResultMessage(result);
            addMessage('system', '🎉 API generated successfully! You can now test and deploy your API using the interface above.');
            
            console.log('Updated conversation state to:', conversationState);
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
                <span id="generationProgressText">Generating your API...</span>
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
    // Update the API preview panel with the proposal
    updateAPIProposal(analysis, originalPrompt, userId);
    
    // Get the conversational message from the analysis
    // First try to get it from the proposal object, then fallback to the main message
    const conversationalMessage = analysis.proposal?.conversational_message || analysis.message || "I've created a detailed API proposal based on your requirements!";
    
    // Show organic conversational response in chat
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <span class="status-badge bg-blue-900/50 text-blue-400 border-blue-500/30">Proposal Ready</span>
                <h3 class="font-semibold text-white">API Proposal Generated</h3>
            </div>
            <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4">
                <p class="text-blue-300 text-base leading-relaxed">
                    ${escapeHtml(conversationalMessage)} 
                </p>
                <p class="text-blue-300/80 text-sm mt-3">
                    📋 Check out the detailed specifications in the <strong>API Preview panel</strong> on the right, then let me know if you'd like to build it or make any changes.
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
        
        // Create a comprehensive prompt that includes proposal details if available
        let promptToUse;
        
        if (currentProposal?.proposal) {
            // If we have detailed proposal data, create a comprehensive prompt
            const proposal = currentProposal.proposal;
            promptToUse = `Build an API with these specifications:

API Name: ${proposal.api_name || 'API'}
Description: ${proposal.description || 'No description provided'}

Functionality:
${proposal.functionality ? proposal.functionality.map(f => `- ${f}`).join('\n') : '- Basic functionality'}

Input Format:
${proposal.input_format ? JSON.stringify(proposal.input_format, null, 2) : 'Standard input format'}

Output Format:
${proposal.output_format ? JSON.stringify(proposal.output_format, null, 2) : 'Standard output format'}

Endpoints:
${proposal.endpoints ? proposal.endpoints.map(e => `- ${e.method || 'POST'} ${e.path || '/api'}: ${e.description || 'Main endpoint'}`).join('\n') : '- POST /api: Main endpoint'}

Original User Request: ${currentProposal?.modified_prompt || currentProposal?.original_prompt || originalPrompt}`;
        } else {
            // Fall back to the modified requirements, modified prompt, or original prompt
            promptToUse = currentProposal?.modified_requirements || currentProposal?.modified_prompt || currentProposal?.original_prompt || originalPrompt;
        }
        
        console.log('=== BUILD API DEBUG INFO ===');
        console.log('Building API with comprehensive prompt:', promptToUse);
        console.log('Original prompt was:', originalPrompt);
        console.log('Current proposal data:', currentProposal?.proposal);
        console.log('Current proposal structure:', currentProposal);
        console.log('Modified requirements:', currentProposal?.modified_requirements);
        console.log('Modified prompt:', currentProposal?.modified_prompt);
        console.log('================================');
        
        // Generate the API with skip_analysis = true since we already analyzed
        await generateAPI(promptToUse, userId, true);
        
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
                    Please describe the changes you'd like to make to the API proposal shown in the Preview panel:
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
    
    // Reset preview panel to empty state
    resetPreviewPanel();
    
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

function resetPreviewPanel() {
    // Reset state variables
    currentAPISpec = null;
    currentProposal = null;
    previewMode = 'empty';
    
    // Hide preview panel and show empty state
    document.getElementById('apiPreviewPanel').classList.add('hidden');
    document.getElementById('emptyState').classList.remove('hidden');
    
    // Remove proposal section if it exists
    const proposalSection = document.getElementById('proposalSection');
    if (proposalSection) {
        proposalSection.remove();
    }
    
    // Reset header
    updatePreviewHeader('🔧 API Preview', 'Live preview of your API as it\'s being built');
}

function addAPIResultMessage(result) {
    const endpointUrl = window.location.origin + result.endpoint_url;
    
    // Update the API preview panel
    updateAPIPreview(result);
    
    // Extract or generate smart test data based on the API
    const testData = {"json": "Place Holder", "description": "Place Holder", "examples": []}
    
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <span class="status-badge status-buildable">Success</span>
                <h3 class="font-semibold text-white">🎉 API Generated Successfully!</h3>
            </div>
            
            <div class="glass-card rounded-xl p-6 border-green-500/30">
                <div class="flex items-center space-x-3 mb-4">
                    <div class="w-12 h-12 bg-green-500/20 rounded-full flex items-center justify-center">
                        <svg class="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                        </svg>
                    </div>
                    <div class="flex-1">
                        <h4 class="font-medium text-white mb-1">Your API is ready!</h4>
                        <p class="text-sm text-green-200">Check the preview panel on the right to test, get code snippets, and deploy your API.</p>
                </div>
                        </div>
                
                <div class="bg-slate-800/30 rounded-lg p-4">
                        <div class="text-sm">
                            <span class="text-slate-400">Endpoint:</span>
                        <code class="ml-2 text-emerald-400 font-mono text-sm bg-slate-700/50 px-2 py-1 rounded">${endpointUrl}</code>
                        <button onclick="copyToClipboard('${endpointUrl}')" 
                                class="ml-2 px-2 py-1 bg-emerald-600 hover:bg-emerald-700 text-white text-xs rounded transition-colors">
                            Copy
                                            </button>
                        </div>
                    </div>
                    
                <div class="mt-4 p-3 bg-blue-900/20 border border-blue-500/30 rounded-lg">
                    <p class="text-blue-300 text-sm">
                        <strong>💡 Next Steps:</strong> Use the API Preview panel to test your endpoint, copy code snippets for integration, or deploy it live!
                    </p>
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
            // Check if this is a final API or a modified proposal
            if (result.endpoint_url) {
                // This is a final API
            currentApiData = result;
            addAPIResultMessage(result);
                addMessage('system', '✅ API modified successfully! The updated version is now available in the Preview panel.');
            
            // Reset placeholder
            const chatInput = document.getElementById('chatInput');
            if (chatInput) {
                chatInput.placeholder = "Describe your API requirements... (e.g., 'Create an API that extracts text from PDF files')";
            }
            
            // Hide chat input again since modification is complete
            hideChatInput();
        } else {
                // This might be a modified proposal
                currentApiData = result;
                addMessage('system', '✅ Proposal updated successfully! Review the changes in the Preview panel.');
            }
        } else {
            // Handle different types of responses
            if (result.status === 'proposal_ready') {
                // Show updated proposal
                addProposalMessage(result, modificationPrompt, userId);
            } else if (result.status === 'needs_clarification') {
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

async function logout() {
    try {
        // Call server logout endpoint to clear cookie
        await fetch('/auth/logout', {
            method: 'POST',
            credentials: 'include'
        });
    } catch (error) {
        console.log('Error during logout:', error);
    }
    
    authToken = null;
    currentUser = null;
    updateAuthUI();
    addMessage('system', '👋 Logged out successfully! Redirecting to landing page...');
    
    // Redirect to landing page after a short delay
    setTimeout(() => {
        window.location.href = '/landing';
    }, 1500);
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

// API Preview Panel Functions
let currentAPISpec = null;
let previewMode = 'empty'; // 'empty', 'proposal', 'api'

function extractHTTPMethod(curlExample) {
    if (!curlExample) return 'POST';
    
    // Extract method from curl command
    const methodMatch = curlExample.match(/-X\s+(\w+)/i);
    if (methodMatch) {
        return methodMatch[1].toUpperCase();
    }
    
    // Check for explicit method indicators
    if (curlExample.includes('POST') || curlExample.includes('-d ')) {
        return 'POST';
    } else if (curlExample.includes('PUT')) {
        return 'PUT';
    } else if (curlExample.includes('DELETE')) {
        return 'DELETE';
    } else if (curlExample.includes('PATCH')) {
        return 'PATCH';
    } else {
        return 'GET';
    }
}

function getMethodColor(method) {
    switch (method.toUpperCase()) {
        case 'GET':
            return 'bg-green-600/20 text-green-300';
        case 'POST':
            return 'bg-blue-600/20 text-blue-300';
        case 'PUT':
            return 'bg-yellow-600/20 text-yellow-300';
        case 'PATCH':
            return 'bg-orange-600/20 text-orange-300';
        case 'DELETE':
            return 'bg-red-600/20 text-red-300';
        default:
            return 'bg-gray-600/20 text-gray-300';
    }
}

function updateAPIPreview(apiData) {
    currentAPISpec = apiData;
    currentProposal = null;
    previewMode = 'api';
    
    // Show the preview panel and hide empty state
    document.getElementById('emptyState').classList.add('hidden');
    document.getElementById('apiPreviewPanel').classList.remove('hidden');
    
    // Hide proposal elements and show API elements
    hideProposalElements();
    showAPIElements();
    
    // Extract HTTP method from curl example or default to POST
    const method = extractHTTPMethod(apiData.curl_example) || 'POST';
    
    // Update endpoint info
    document.getElementById('apiMethod').textContent = method;
    document.getElementById('apiMethod').className = `px-2 py-1 rounded font-mono text-xs ${getMethodColor(method)}`;
    document.getElementById('apiEndpoint').textContent = apiData.endpoint_url || '-';
    document.getElementById('apiDescription').textContent = extractAPIDescription(apiData.documentation) || 'API endpoint for your custom functionality';
    
    // Update parameters table
    updateParametersTable(apiData);
    
    // Update example response
    updateExampleResponse(apiData);
    
    // Update test input with sample data
    updateTestInput(apiData);
}

function updateAPIProposal(analysis, originalPrompt, userId) {
    const proposal = analysis.proposal || {};
    console.log('updateAPIProposal - analysis:', analysis);
    console.log('updateAPIProposal - proposal:', proposal);
    
    // Safety check for proposal object
    if (!analysis.proposal) {
        console.warn('No proposal object found in analysis response');
        console.log('Available keys in analysis:', Object.keys(analysis));
    }
    
    // FIX: Store proposal data in the correct structure for confirmBuildAPI
    currentProposal = { 
        analysis, 
        originalPrompt, 
        userId,
        proposal: analysis.proposal,  // Make proposal accessible at top level
        original_prompt: originalPrompt,
        modified_prompt: analysis.modified_requirements || originalPrompt
    };
    currentAPISpec = null;
    previewMode = 'proposal';
    
    // Show the preview panel and hide empty state
    document.getElementById('emptyState').classList.add('hidden');
    document.getElementById('apiPreviewPanel').classList.remove('hidden');
    
    // Hide API elements and show proposal elements
    hideAPIElements();
    showProposalElements();
    
    // Update header to show it's a proposal
    updatePreviewHeader('🔧 API Proposal', 'Review and approve your API specification');
    
    // Populate proposal content
    populateProposalContent(analysis, originalPrompt, userId);
}

function extractAPIDescription(documentation) {
    if (!documentation) return '';
    
    // Look for Description section first
    const descMatch = documentation.match(/###?\s*Description[:\s]*\n([^\n#]+)/i);
    if (descMatch) {
        const desc = descMatch[1].trim();
        return desc.length > 150 ? desc.substring(0, 150) + '...' : desc;
    }
    
    // Extract first meaningful line as description, filtering out emoji headers and formatting
    const lines = documentation.split('\n');
    for (const line of lines) {
        const trimmed = line.trim();
        // Skip empty lines, headers, and lines that start with emojis or are formatting artifacts
        if (trimmed && 
            !trimmed.startsWith('#') && 
            !trimmed.startsWith('*') && 
            !trimmed.startsWith('🌐') && 
            !trimmed.startsWith('📝') && 
            !trimmed.startsWith('📤') && 
            !trimmed.startsWith('💻') &&
            !trimmed.startsWith('Based on the provided') &&
            !trimmed.match(/^[\u{1F000}-\u{1F9FF}]/u) && // Filter out other emojis
            trimmed.length > 10) {
            return trimmed.length > 150 ? trimmed.substring(0, 150) + '...' : trimmed;
        }
    }
    return 'API endpoint for processing requests';
}

function updateParametersTable(apiData) {
    const container = document.getElementById('parametersTable');
    
    // Try to extract parameters from documentation or create generic ones
    const params = extractParametersFromDocumentation(apiData.documentation);
    
    if (params.length === 0) {
        container.innerHTML = '<div class="text-slate-400 text-sm text-center py-8">No parameters defined</div>';
        return;
    }
    
    const tableHTML = `
        <table class="w-full text-sm">
            <thead>
                <tr class="border-b border-slate-600/50">
                    <th class="text-left py-2 text-green-300 font-medium">Name</th>
                    <th class="text-left py-2 text-green-300 font-medium">Type</th>
                    <th class="text-left py-2 text-green-300 font-medium">Required</th>
                    <th class="text-left py-2 text-green-300 font-medium">Example</th>
                </tr>
            </thead>
            <tbody>
                ${params.map(param => `
                    <tr class="border-b border-slate-700/50">
                        <td class="py-2 text-white font-mono">${param.name}</td>
                        <td class="py-2 text-blue-300">${param.type}</td>
                        <td class="py-2">
                            <span class="px-2 py-1 rounded text-xs ${param.required ? 'bg-red-600/20 text-red-300' : 'bg-gray-600/20 text-gray-300'}">
                                ${param.required ? 'Required' : 'Optional'}
                            </span>
                        </td>
                        <td class="py-2 text-slate-300 font-mono">${param.example}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    
    container.innerHTML = tableHTML;
}

function extractParametersFromDocumentation(documentation) {
    const params = [];
    
    if (!documentation) {
        params.push({name: 'data', type: 'string', required: true, example: '"example input"'});
        return params;
    }
    
    // Enhanced parameter extraction from markdown documentation
    const doc = documentation.toLowerCase();
    
    // Look for parameter sections in documentation with better emoji filtering
    const paramSectionMatch = documentation.match(/(?:📝\s*)?parameters?[:\-\s]*\n(.*?)(?=\n\n|\n#|\n📤|\n💻|$)/is);
    if (paramSectionMatch) {
        const paramSection = paramSectionMatch[1];
        
        // Extract parameters from bulleted or listed format
        const paramMatches = paramSection.match(/[-*•]\s*`?(\w+)`?\s*[-–:]\s*(.+?)(?=\n[-*•]|\n\n|$)/gim);
        if (paramMatches) {
            paramMatches.forEach(match => {
                const paramMatch = match.match(/[-*•]\s*`?(\w+)`?\s*[-–:]\s*(.+)/i);
                if (paramMatch) {
                    const name = paramMatch[1];
                    const description = paramMatch[2].trim();
                    
                    let type = 'string';
                    let required = false;
                    let example = `"example ${name}"`;
                    
                    // Determine type from description
                    if (description.includes('number') || description.includes('integer') || description.includes('int')) {
                        type = 'number';
                        example = '123';
                    } else if (description.includes('boolean') || description.includes('bool')) {
                        type = 'boolean';
                        example = 'true';
                    } else if (description.includes('array') || description.includes('list')) {
                        type = 'array';
                        example = '["item1", "item2"]';
                    } else if (description.includes('object') || description.includes('json')) {
                        type = 'object';
                        example = '{"key": "value"}';
                    } else if (description.includes('file') || description.includes('upload')) {
                        type = 'file';
                        example = 'file.pdf';
                    }
                    
                    // Determine if required
                    if (description.includes('required') || description.includes('mandatory')) {
                        required = true;
                    }
                    
                    params.push({name, type, required, example});
                }
            });
        }
    }
    
    // Fallback: Look for common patterns if no formal parameter section
    if (params.length === 0) {
        // Common API patterns
        if (doc.includes('text') && !doc.includes('no parameters')) {
            params.push({name: 'text', type: 'string', required: true, example: '"Sample text for processing"'});
        }
        if (doc.includes('file') || doc.includes('upload')) {
            params.push({name: 'file', type: 'file', required: true, example: 'document.pdf'});
        }
        if (doc.includes('url') || doc.includes('link')) {
            params.push({name: 'url', type: 'string', required: true, example: '"https://example.com"'});
        }
        if (doc.includes('image') || doc.includes('photo')) {
            params.push({name: 'image', type: 'file', required: true, example: 'image.jpg'});
        }
        if (doc.includes('json') || doc.includes('data')) {
            params.push({name: 'data', type: 'object', required: true, example: '{"key": "value"}'});
        }
        
        // If still no parameters found, add a default
        if (params.length === 0) {
            params.push({name: 'input', type: 'string', required: true, example: '"example input"'});
        }
    }
    
    return params;
}

function updateExampleResponse(apiData) {
    const container = document.getElementById('exampleResponse');
    
    // Create a sample response based on the API type
    const exampleResponse = generateExampleResponse(apiData);
    container.textContent = JSON.stringify(exampleResponse, null, 2);
}

function generateExampleResponse(apiData) {
    // Generate example based on API documentation or type
    const doc = (apiData.documentation || '').toLowerCase();
    
    // Try to extract actual response format from documentation (handling emoji headers)
    const responseMatch = apiData.documentation && apiData.documentation.match(/(?:📤\s*)?(?:example\s*)?response[:\-\s]*\n```json\s*(.*?)\s*```/is);
    if (responseMatch) {
        try {
            return JSON.parse(responseMatch[1]);
        } catch (e) {
            // Fall through to pattern-based generation
        }
    }
    
    // Pattern-based response generation
    if (doc.includes('sentiment') || doc.includes('emotion')) {
        return {
            sentiment: "positive",
            confidence: 0.95,
            score: 0.8,
            timestamp: new Date().toISOString()
        };
    } else if (doc.includes('summarize') || doc.includes('summary')) {
        return {
            summary: "This is a concise summary of the provided text.",
            word_count: 156,
            summary_ratio: 0.3,
            success: true
        };
    } else if (doc.includes('translate') || doc.includes('translation')) {
        return {
            translated_text: "Hola, ¿cómo estás?",
            source_language: "en",
            target_language: "es",
            confidence: 0.98
        };
    } else if (doc.includes('extract') && doc.includes('email')) {
        return {
            emails: ["john@example.com", "support@company.com"],
            count: 2,
            success: true
        };
    } else if (doc.includes('extract') && doc.includes('name')) {
        return {
            names: ["John Smith", "Mary Johnson"],
            count: 2,
            success: true
        };
    } else if (doc.includes('text') || doc.includes('process')) {
        return {
            processed_text: "Sample processed text result",
            word_count: 42,
            character_count: 254,
            success: true,
            processed_at: new Date().toISOString()
        };
    } else if (doc.includes('image') || doc.includes('resize') || doc.includes('photo')) {
        return {
            image_url: "https://api.example.com/processed/image.jpg",
            original_size: {width: 1200, height: 800},
            new_size: {width: 600, height: 400},
            size_reduction: "45%",
            format: "jpeg"
        };
    } else if (doc.includes('classify') || doc.includes('classification') || doc.includes('category')) {
        return {
            classification: "positive",
            categories: ["Technology", "AI", "Software"],
            confidence: 0.92,
            top_category: "Technology"
        };
    } else if (doc.includes('analyze') || doc.includes('analysis')) {
        return {
            analysis_result: "Detailed analysis complete",
            metrics: {
                complexity: "medium",
                sentiment: "positive",
                readability: 8.5
            },
            success: true
        };
    } else if (doc.includes('generate') || doc.includes('create')) {
        return {
            generated_content: "This is generated content based on your input",
            length: 156,
            format: "text",
            success: true
        };
    } else if (doc.includes('convert') || doc.includes('transform')) {
        return {
            converted_data: "Converted output data",
            original_format: "input_format",
            target_format: "output_format",
            success: true
        };
    } else {
        // Generic response
        return {
            result: "API response data",
            success: true,
            message: "Request processed successfully",
            timestamp: new Date().toISOString()
        };
    }
}

function extractSampleTestDataFromDocumentation(documentation) {
    if (!documentation) return null;
    
    // Look for Sample Test Data section in documentation (with or without emoji)
    const sampleTestDataMatch = documentation.match(/###?\s*Sample Test Data\s*\n```json\s*(.*?)\s*```/is);
    if (sampleTestDataMatch) {
        try {
            return JSON.parse(sampleTestDataMatch[1]);
        } catch (e) {
            console.log('Failed to parse sample test data from documentation:', e);
            return null;
        }
    }
    
    // Also look for example request/payload sections
    const exampleMatch = documentation.match(/(?:example|request|payload)[:\s]*\n```json\s*(.*?)\s*```/is);
    if (exampleMatch) {
        try {
            return JSON.parse(exampleMatch[1]);
        } catch (e) {
            console.log('Failed to parse example data from documentation:', e);
            return null;
        }
    }
    
    return null;
}

async function updateTestInput(apiData) {
    const testInput = document.getElementById('previewTestInput');
    
    // Try to generate smart test data using our AI endpoint
    if (apiData.api_slug && apiData.user_id) {
        try {
            console.log('Generating smart test data for API:', apiData.api_slug);
            
            // Show loading indicator
            const existingIndicator = testInput.parentElement.querySelector('.sample-data-indicator');
            if (existingIndicator) {
                existingIndicator.remove();
            }
            
            const loadingIndicator = document.createElement('div');
            loadingIndicator.className = 'sample-data-indicator text-xs text-blue-400 mb-2 flex items-center space-x-2';
            loadingIndicator.innerHTML = `
                <svg class="w-3 h-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
                </svg>
                <span>Generating smart test data...</span>
            `;
            testInput.parentElement.insertBefore(loadingIndicator, testInput);
            
            // Call our AI test data generation endpoint
            const response = await fetch(`/generate-test-data/${apiData.user_id}/${apiData.api_slug}`);
            
            if (response.ok) {
                const data = await response.json();
                
                if (data.success && data.test_scenarios && data.test_scenarios.length > 0) {
                    // Use the first scenario's data as the default test input
                    const firstScenario = data.test_scenarios[0];
                    testInput.value = JSON.stringify(firstScenario.data, null, 2);
                    
                    // Store all scenarios for potential future use
                    testInput.setAttribute('data-ai-scenarios', JSON.stringify(data.test_scenarios));
                    testInput.setAttribute('data-sample-json', JSON.stringify(firstScenario.data, null, 2));
                    
                    // Update indicator to show success
                    loadingIndicator.className = 'sample-data-indicator text-xs text-green-400 mb-2 flex items-center space-x-2';
                    loadingIndicator.innerHTML = `
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                        </svg>
                        <span>AI-generated test data loaded (${data.test_scenarios.length} scenarios available)</span>
                        <button onclick="loadSampleTestData()" class="text-green-300 hover:text-green-200 underline">Reload</button>
                    `;
                    
                    console.log('Smart test data generated successfully:', data.test_scenarios.length, 'scenarios');
                    return;
                } else {
                    console.warn('AI test data generation returned no scenarios, falling back to documentation extraction');
                }
            } else {
                console.warn('AI test data generation failed, falling back to documentation extraction');
            }
        } catch (error) {
            console.error('Error generating smart test data:', error);
        }
        
        // Remove loading indicator if AI generation failed
        const loadingIndicator = testInput.parentElement.querySelector('.sample-data-indicator');
        if (loadingIndicator) {
            loadingIndicator.remove();
        }
    }
    
    // Fallback: First try to use AI-generated sample test data from documentation
    const aiSampleData = extractSampleTestDataFromDocumentation(apiData.documentation);
    if (aiSampleData) {
        testInput.value = JSON.stringify(aiSampleData, null, 2);
        
        // Store the sample data for easy reloading
        testInput.setAttribute('data-sample-json', JSON.stringify(aiSampleData, null, 2));
        
        // Add a visual indicator that this is AI-generated sample data from documentation
        const sampleDataIndicator = testInput.parentElement.querySelector('.sample-data-indicator');
        if (!sampleDataIndicator) {
            const indicator = document.createElement('div');
            indicator.className = 'sample-data-indicator text-xs text-yellow-400 mb-2 flex items-center space-x-2';
            indicator.innerHTML = `
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                </svg>
                <span>Test data extracted from documentation</span>
                <button onclick="loadSampleTestData()" class="text-yellow-300 hover:text-yellow-200 underline">Reload</button>
            `;
            testInput.parentElement.insertBefore(indicator, testInput);
        }
        return;
    }
    
    // Fallback to parameter-based generation
    const params = extractParametersFromDocumentation(apiData.documentation);
    
    if (params.length > 0) {
        const testData = {};
        params.forEach(param => {
            // Generate appropriate test values based on parameter type and name
            if (param.type === 'number') {
                testData[param.name] = 123;
            } else if (param.type === 'boolean') {
                testData[param.name] = true;
            } else if (param.type === 'array') {
                if (param.name.includes('email')) {
                    testData[param.name] = ["test@example.com", "user@demo.com"];
                } else if (param.name.includes('name')) {
                    testData[param.name] = ["John Doe", "Jane Smith"];
                } else {
                    testData[param.name] = ["item1", "item2"];
                }
            } else if (param.type === 'object') {
                testData[param.name] = {"key": "value", "example": "data"};
            } else if (param.type === 'file') {
                testData[param.name] = param.name.includes('image') ? "image.jpg" : "document.pdf";
            } else {
                // String type - generate contextual examples
                if (param.name === 'text') {
                    testData[param.name] = "This is sample text for processing by the API.";
                } else if (param.name === 'url' || param.name === 'link') {
                    testData[param.name] = "https://example.com";
                } else if (param.name.includes('email')) {
                    testData[param.name] = "user@example.com";
                } else if (param.name.includes('name')) {
                    testData[param.name] = "John Doe";
                } else if (param.name.includes('title')) {
                    testData[param.name] = "Example Title";
                } else if (param.name.includes('content') || param.name.includes('message')) {
                    testData[param.name] = "Sample content for processing";
                } else if (param.name.includes('language') || param.name.includes('lang')) {
                    testData[param.name] = "en";
                } else if (param.name.includes('format')) {
                    testData[param.name] = "json";
                } else {
                    testData[param.name] = `example ${param.name}`;
                }
            }
        });
        testInput.value = JSON.stringify(testData, null, 2);
    } else {
        testInput.value = '{\n  "data": "example input"\n}';
    }
}

// Sample Test Data Functions
function loadSampleTestData() {
    const testInput = document.getElementById('previewTestInput');
    const sampleData = testInput.getAttribute('data-sample-json');
    
    if (sampleData) {
        testInput.value = sampleData;
        
        // Show feedback
        const notification = document.createElement('div');
        notification.className = 'fixed top-4 right-4 bg-green-600 text-white px-6 py-3 rounded-xl shadow-xl z-50 notification-slide-up';
        notification.innerHTML = `
            <div class="flex items-center space-x-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>
                <span>Sample test data reloaded</span>
            </div>
        `;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.remove();
        }, 2000);
    }
}

// Copy Functions
function copyApiEndpoint() {
    if (!currentAPISpec) return;
    
    const endpointUrl = window.location.origin + currentAPISpec.endpoint_url;
    copyToClipboard(endpointUrl);
}

function copyExampleResponse() {
    const responseText = document.getElementById('exampleResponse').textContent;
    copyToClipboard(responseText);
}

function copyCodeSnippet(language) {
    if (!currentAPISpec) return;
    
    const endpointUrl = window.location.origin + currentAPISpec.endpoint_url;
    let snippet = '';
    
    switch (language) {
        case 'curl':
            snippet = `curl -X POST "${endpointUrl}" \\
  -H "Content-Type: application/json" \\
  -d '${document.getElementById('previewTestInput').value || '{"data": "example"}'}'`;
            break;
            
        case 'python':
            snippet = `import requests
import json

url = "${endpointUrl}"
data = ${document.getElementById('previewTestInput').value || '{"data": "example"}'}

response = requests.post(url, json=data)
result = response.json()
print(result)`;
            break;
            
        case 'javascript':
            snippet = `const response = await fetch('${endpointUrl}', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify(${document.getElementById('previewTestInput').value || '{"data": "example"}'})
});

const result = await response.json();
console.log(result);`;
            break;
    }
    
    copyToClipboard(snippet);
}

// Preview Test Functions
async function runPreviewTest() {
    if (!currentAPISpec) return;
    
    const testInput = document.getElementById('previewTestInput');
    const runBtn = document.getElementById('previewRunTestBtn');
    const status = document.getElementById('previewTestStatus');
    const statusText = document.getElementById('previewTestStatusText');
    const results = document.getElementById('previewTestResults');
    const responseStatus = document.getElementById('previewResponseStatus');
    const responseBody = document.getElementById('previewResponseBody');
    
    // Update UI to show testing
    runBtn.disabled = true;
    runBtn.innerHTML = `
        <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path>
        </svg>
        <span>Testing...</span>
    `;
    status.className = 'w-3 h-3 bg-yellow-500 rounded-full animate-pulse';
    statusText.textContent = 'Running...';
    statusText.className = 'text-sm text-yellow-400';
    
    try {
        // Parse the endpoint URL to get user_id and api_slug
        const urlPath = currentAPISpec.endpoint_url;
        const urlParts = urlPath.split('/').filter(part => part);
        
        if (urlParts.length < 3 || urlParts[0] !== 'api') {
            throw new Error('Invalid endpoint URL format');
        }
        
        const user_id = urlParts[1];
        const api_slug = urlParts[2];
        
        // Prepare test data
        const testData = {
            user_id: user_id,
            api_slug: api_slug,
            test_type: 'preview'
        };
        
        // Add test input if provided
        const testInputValue = testInput.value.trim();
        if (testInputValue) {
            try {
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
        
        const testResult = await response.json();
        
        // Show results
        results.classList.remove('hidden');
        
        // Update status
        if (testResult.success) {
            status.className = 'w-3 h-3 bg-green-500 rounded-full';
            statusText.textContent = 'Success';
            statusText.className = 'text-sm text-green-400';
            
            responseStatus.textContent = '200 OK';
            responseStatus.className = 'px-2 py-1 bg-green-600/20 text-green-300 rounded text-xs font-mono';
            
            responseBody.textContent = JSON.stringify(testResult.response_data || testResult, null, 2);
        } else {
            status.className = 'w-3 h-3 bg-red-500 rounded-full';
            statusText.textContent = 'Failed';
            statusText.className = 'text-sm text-red-400';
            
            responseStatus.textContent = 'Error';
            responseStatus.className = 'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';
            
            responseBody.textContent = JSON.stringify({error: testResult.error || 'Test failed'}, null, 2);
        }
        
    } catch (error) {
        results.classList.remove('hidden');
        
        status.className = 'w-3 h-3 bg-red-500 rounded-full';
        statusText.textContent = 'Error';
        statusText.className = 'text-sm text-red-400';
        
        responseStatus.textContent = 'Error';
        responseStatus.className = 'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';
        
        responseBody.textContent = `Error: ${error.message}`;
    } finally {
        // Reset button
        runBtn.disabled = false;
        runBtn.innerHTML = `
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1m4 0h1m-6 4h1m4 0h1m6-10V7a3 3 0 11-6 0V4h6zM4 7v10a2 2 0 002 2h12a2 2 0 002-2V7"></path>
            </svg>
            <span>Run Test</span>
        `;
    }
}

// Preview Panel Helper Functions
function updatePreviewHeader(title, subtitle) {
    const headerTitle = document.querySelector('#apiPreviewContent .p-6 h3');
    const headerSubtitle = document.querySelector('#apiPreviewContent .p-6 p');
    
    if (headerTitle) {
        headerTitle.innerHTML = title;
    }
    if (headerSubtitle) {
        headerSubtitle.textContent = subtitle;
    }
}

function hideAPIElements() {
    // Hide API-specific elements (parameters, response, test playground, code snippets, deploy/modify buttons)
    const apiElements = [
        'previewTestResults', 
        'previewDeployBtn', 
        'previewModifyBtn',
        'testPlaygroundSection',
        'codeSnippetsSection',
        'parametersSection',
        'exampleResponseSection'
    ];
    apiElements.forEach(id => {
        const element = document.getElementById(id);
        if (element) element.classList.add('hidden');
    });
}

function showAPIElements() {
    // Show API-specific elements (parameters, response, test playground, code snippets, deploy/modify buttons)
    const apiElements = [
        'previewDeployBtn', 
        'previewModifyBtn',
        'testPlaygroundSection',
        'codeSnippetsSection',
        'parametersSection',
        'exampleResponseSection'
    ];
    apiElements.forEach(id => {
        const element = document.getElementById(id);
        if (element) element.classList.remove('hidden');
    });
}

function hideProposalElements() {
    // Hide proposal-specific elements
    const proposalSection = document.getElementById('proposalSection');
    if (proposalSection) proposalSection.classList.add('hidden');
}

function showProposalElements() {
    // Show proposal-specific elements  
    const proposalSection = document.getElementById('proposalSection');
    if (proposalSection) proposalSection.classList.remove('hidden');
}

function populateProposalContent(analysis, originalPrompt, userId) {
    const proposal = analysis.proposal || {};
    
    // Safety check for proposal object
    if (!analysis.proposal) {
        console.warn('No proposal object found in populateProposalContent');
        console.log('Available keys in analysis:', Object.keys(analysis));
    }
    
    // Update API name and description in the endpoint section
    document.getElementById('apiMethod').textContent = 'DRAFT';
    document.getElementById('apiMethod').className = 'px-2 py-1 bg-blue-600/20 text-blue-300 rounded font-mono text-xs';
    document.getElementById('apiEndpoint').textContent = `${(proposal && proposal.api_name) || 'Custom API'}`;
    document.getElementById('apiDescription').textContent = (proposal && proposal.description) || 'A custom API based on your requirements';
    
    // Create proposal content in the preview panel
    createProposalContentInPreview(analysis, originalPrompt, userId);
    
    // Note: Parameters table, example response, test playground, and code snippets 
    // are hidden during proposal mode. They will be populated when the API is actually built.
}

function createProposalContentInPreview(analysis, originalPrompt, userId) {
    const proposal = analysis.proposal || {};
    
    // Safety check for proposal object
    if (!analysis.proposal) {
        console.warn('No proposal object found in createProposalContentInPreview');
        console.log('Available keys in analysis:', Object.keys(analysis));
    }
    
    // Create or update proposal section in the preview panel
    let proposalSection = document.getElementById('proposalSection');
    if (!proposalSection) {
        proposalSection = document.createElement('div');
        proposalSection.id = 'proposalSection';
        proposalSection.className = 'space-y-6 p-6';
        
        // Insert after the API endpoint section
        const apiInfoSection = document.querySelector('#apiPreviewPanel .bg-blue-900\\/20');
        if (apiInfoSection) {
            apiInfoSection.parentNode.insertBefore(proposalSection, apiInfoSection.nextSibling);
        }
    }
    
    // Create functionality HTML
    const functionalityHtml = proposal.functionality ? 
        proposal.functionality.map(func => `<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-slate-300">${func}</span></li>`).join('') : 
        '<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-slate-300">Custom API functionality</span></li>';
    
    proposalSection.innerHTML = `
        <!-- Key Features -->
        <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4">
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
            <div class="bg-green-900/20 border border-green-500/30 rounded-xl p-4">
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
                <div class="bg-slate-800/50 rounded-lg p-3">
                    <h6 class="text-xs font-medium text-green-300 mb-2">Example:</h6>
                    <pre class="text-xs text-slate-300 font-mono whitespace-pre-wrap break-all">${typeof proposal.input_format.example === 'object' ? JSON.stringify(proposal.input_format.example, null, 2) : proposal.input_format.example}</pre>
                </div>
                ` : ''}
            </div>
            ` : ''}
            ${proposal.output_format ? `
            <div class="bg-purple-900/20 border border-purple-500/30 rounded-xl p-4">
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
                <div class="bg-slate-800/50 rounded-lg p-3">
                    <h6 class="text-xs font-medium text-purple-300 mb-2">Example:</h6>
                    <pre class="text-xs text-slate-300 font-mono whitespace-pre-wrap break-all">${typeof proposal.output_format.example === 'object' ? JSON.stringify(proposal.output_format.example, null, 2) : proposal.output_format.example}</pre>
                </div>
                ` : ''}
            </div>
            ` : ''}
        </div>
        ` : ''}

        <!-- Confirmation Buttons -->
        <div class="bg-green-900/20 border border-green-500/30 rounded-xl p-4">
            <h4 class="font-semibold text-white mb-4 flex items-center space-x-2">
                <span class="text-green-400">✅</span>
                <span>Ready to build this API?</span>
            </h4>
            <div class="flex flex-wrap gap-3">
                <button onclick="confirmBuildAPI('${originalPrompt.replace(/'/g, "\\'")}', '${userId}')" 
                        class="px-4 py-2 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                    🚀 Build It!
                </button>
                <button onclick="requestModifications('${originalPrompt.replace(/'/g, "\\'")}', '${userId}')" 
                        class="px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                    ✏️ Modify
                </button>
                <button onclick="cancelAPIBuild()" 
                        class="px-4 py-2 bg-gradient-to-r from-gray-600 to-gray-700 hover:from-gray-700 hover:to-gray-800 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                    ❌ Cancel
                </button>
            </div>
            <p class="text-sm text-slate-400 mt-3">
                💡 Review the proposal carefully. You can request modifications or proceed with building the API.
            </p>
        </div>
    `;
}

function updateParametersTableFromProposal(proposal) {
    const container = document.getElementById('parametersTable');
    
    // Debug: Log the proposal data to understand what we're working with
    console.log('updateParametersTableFromProposal - proposal:', proposal);
    
    // Extract parameters from proposal input format with better type detection
    let params = [];
    if (proposal.input_format && proposal.input_format.fields) {
        params = proposal.input_format.fields.map(field => {
            // Determine type and example based on field name and proposal context
            let type = 'string';
            let example = `"example ${field}"`;
            
            if (field.toLowerCase().includes('number') || field.toLowerCase().includes('count') || field.toLowerCase().includes('id')) {
                type = 'number';
                example = '123';
            } else if (field.toLowerCase().includes('boolean') || field.toLowerCase().includes('flag')) {
                type = 'boolean';
                example = 'true';
            } else if (field.toLowerCase().includes('array') || field.toLowerCase().includes('list')) {
                type = 'array';
                example = '["item1", "item2"]';
            } else if (field.toLowerCase().includes('object') || field.toLowerCase().includes('data')) {
                type = 'object';
                example = '{"key": "value"}';
            }
            
            return {
                name: field,
                type: type,
                required: true,
                example: example
            };
        });
    } else if (proposal.input_format && proposal.input_format.example) {
        // Extract parameters from example object
        try {
            const exampleObj = typeof proposal.input_format.example === 'object' 
                ? proposal.input_format.example 
                : JSON.parse(proposal.input_format.example);
            
            params = Object.keys(exampleObj).map(key => ({
                name: key,
                type: typeof exampleObj[key] === 'number' ? 'number' : 
                      typeof exampleObj[key] === 'boolean' ? 'boolean' :
                      Array.isArray(exampleObj[key]) ? 'array' :
                      typeof exampleObj[key] === 'object' ? 'object' : 'string',
                required: true,
                example: JSON.stringify(exampleObj[key])
            }));
        } catch (e) {
            params = [{name: 'data', type: 'string', required: true, example: '"example input"'}];
        }
    } else {
        // If no proper proposal format, create a basic structure for proposal mode
        console.log('No proper input_format found in proposal, using generic structure');
        params = [{name: 'input', type: 'string', required: true, example: '"your input data here"'}];
    }
    
    if (params.length === 0) {
        container.innerHTML = '<div class="text-slate-400 text-sm text-center py-8">No parameters defined</div>';
        return;
    }
    
    const tableHTML = `
        <table class="w-full text-sm">
            <thead>
                <tr class="border-b border-slate-600/50">
                    <th class="text-left py-2 text-green-300 font-medium">Name</th>
                    <th class="text-left py-2 text-green-300 font-medium">Type</th>
                    <th class="text-left py-2 text-green-300 font-medium">Required</th>
                    <th class="text-left py-2 text-green-300 font-medium">Example</th>
                </tr>
            </thead>
            <tbody>
                ${params.map(param => `
                    <tr class="border-b border-slate-700/50">
                        <td class="py-2 text-white font-mono">${param.name}</td>
                        <td class="py-2 text-blue-300">${param.type}</td>
                        <td class="py-2">
                            <span class="px-2 py-1 rounded text-xs ${param.required ? 'bg-red-600/20 text-red-300' : 'bg-gray-600/20 text-gray-300'}">
                                ${param.required ? 'Required' : 'Optional'}
                            </span>
                        </td>
                        <td class="py-2 text-slate-300 font-mono">${param.example}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    
    container.innerHTML = tableHTML;
}

function updateExampleResponseFromProposal(proposal) {
    const container = document.getElementById('exampleResponse');
    
    // Use proposal output format example if available
    let exampleResponse;
    if (proposal.output_format && proposal.output_format.example) {
        try {
            exampleResponse = typeof proposal.output_format.example === 'object' 
                ? proposal.output_format.example 
                : JSON.parse(proposal.output_format.example);
        } catch (e) {
            exampleResponse = proposal.output_format.example;
        }
    } else {
        // Generate a contextual example based on the proposal's API name and description
        const apiName = ((proposal && proposal.api_name) || '').toLowerCase();
        const description = ((proposal && proposal.description) || '').toLowerCase();
        
        if (apiName.includes('sentiment') || description.includes('sentiment')) {
            exampleResponse = {
                sentiment: "positive",
                confidence: 0.95,
                timestamp: new Date().toISOString()
            };
        } else if (apiName.includes('extract') || description.includes('extract')) {
            if (description.includes('name')) {
                exampleResponse = {
                    extracted_names: ["John Doe", "Jane Smith"],
                    count: 2,
                    success: true
                };
            } else if (description.includes('email')) {
                exampleResponse = {
                    extracted_emails: ["user@example.com", "contact@company.com"],
                    count: 2,
                    success: true
                };
            } else {
                exampleResponse = {
                    extracted_data: ["item1", "item2"],
                    count: 2,
                    success: true
                };
            }
        } else if (apiName.includes('process') || description.includes('process')) {
            exampleResponse = {
                processed_result: "Successfully processed the input data",
                success: true,
                timestamp: new Date().toISOString()
            };
        } else {
            // Generic response based on proposal
            exampleResponse = {
                result: "Sample response based on your API proposal",
                success: true,
                message: "Request processed successfully",
                timestamp: new Date().toISOString(),
                note: "This is from proposal mode"
            };
        }
    }
    
    container.textContent = JSON.stringify(exampleResponse, null, 2);
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