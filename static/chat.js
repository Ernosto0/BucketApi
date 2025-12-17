let currentConversation = [];
let isGenerating = false;
let currentApiData = null;
let isModificationMode = false;
let generationMode = 'multi-step'; // Default to multi-step

// Conversation state tracking
let conversationState = null; // "proposal", "code_generated", null
let currentProposalId = null; // Unique identifier for current proposal session
let currentProposal = null; // Store current proposal data

// Database configuration
let databaseConfig = null;
let selectedDatabaseType = null;
let connectionMethod = 'fields'; // 'fields' or 'string'

// Message queue for staggered status updates
let messageQueue = [];
let isProcessingQueue = false;
let lastMessageTime = 0;
const MIN_MESSAGE_DELAY = 500;//500 milliseconds between messages

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
async function handleConversationalMessage(message) {
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
    
    await addMessage('assistant', response);
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

        // Check for rate limiting or other HTTP errors
        if (modifyResponse.status === 429) {
            const errorData = await modifyResponse.json();
            hideTypingIndicator();
            addRateLimitMessage(errorData.detail);
            return;
        } else if (!modifyResponse.ok) {
            const errorData = await modifyResponse.json();
            hideTypingIndicator();
            addMessage('assistant', `❌ Error: ${errorData.detail || 'Request failed'}`);
            return;
        }

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

        // Check for rate limiting or other HTTP errors
        if (modifyResponse.status === 429) {
            const errorData = await modifyResponse.json();
            hideTypingIndicator();
            addRateLimitMessage(errorData.detail);
            return;
        } else if (!modifyResponse.ok) {
            const errorData = await modifyResponse.json();
            hideTypingIndicator();
            addMessage('assistant', `❌ Error: ${errorData.detail || 'Request failed'}`);
            return;
        }

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
document.addEventListener('DOMContentLoaded', async function() {
    // Initialize generation mode
    handleGenerationModeChange();
    
    // Initialize mode switcher (default to generation mode)
    switchToGenerationMode();

    // Check for modify parameter
    const urlParams = new URLSearchParams(window.location.search);
    const modifySlug = urlParams.get('modify');
    const modifyUserId = urlParams.get('user_id');
    
    if (modifySlug && modifyUserId) {
        // Clear chat first (remove generation welcome message)
        const chatMessages = document.getElementById('chatMessages');
        if (chatMessages) {
            chatMessages.innerHTML = '';
        }
        
        // Reset conversation state
        currentConversation = [];
        conversationState = null;
        currentProposalId = null;
        currentProposal = null;
        
        try {
             const response = await fetch(`/api/${modifyUserId}/${modifySlug}/apidetails`);
             if (response.ok) {
                 currentApiData = await response.json();
                 isModificationMode = true;
                 
                 // Update mode switcher to show modification mode active
                 const genBtn = document.getElementById('generationModeBtn');
                 const modBtn = document.getElementById('modificationModeBtn');
                 if (genBtn && modBtn) {
                     genBtn.className = 'px-3 py-1.5 bg-slate-700/50 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
                     modBtn.className = 'px-3 py-1.5 bg-gradient-to-r from-orange-600 to-amber-600 text-white rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
                 }
                 
                 // Hide API selector since API is already selected via URL
                 const apiSelector = document.getElementById('apiSelectorContainer');
                 if (apiSelector) {
                     apiSelector.classList.add('hidden');
                 }
                 
                 // Show modification mode UI
                 showModificationModeUI();
                 
                 // Load API details in preview panel
                 loadAPIDetailsInPreview(currentApiData);
                 
                 // Enable chat input
                 const chatInput = document.getElementById('chatInput');
                 if (chatInput) {
                     chatInput.disabled = false;
                 }
                 
                 // Add modification welcome message
                 setTimeout(() => {
                     addModificationWelcomeMessage(currentApiData);
                 }, 300);
                 
                 // Switch to modification view if needed, or just conversation state.
                 conversationState = 'api_modification'; // Use appropriate state if defined
             } else {
                 console.error("Failed to load API for modification", response.status);
                 addMessage('assistant', "❌ I couldn't load the API you requested to modify. Please select it from your profile.", { skipDelay: true });
             }
        } catch (e) {
            console.error("Error loading API for modification", e);
            addMessage('assistant', "❌ I couldn't load the API you requested to modify. Please select it from your profile.", { skipDelay: true });
        }
    } else if (modifySlug) {
        // Fallback to old method if only slug is provided (for backwards compatibility)
        // Clear chat first (remove generation welcome message)
        const chatMessages = document.getElementById('chatMessages');
        if (chatMessages) {
            chatMessages.innerHTML = '';
        }
        
        // Reset conversation state
        currentConversation = [];
        conversationState = null;
        currentProposalId = null;
        currentProposal = null;
        
        try {
             // Extract user_id from slug (assuming format user_id_api_name)
             // This is a bit hacky, but efficient.
             const parts = modifySlug.split('_');
             const presumedUserId = parts[0];
             
             const response = await fetch(`/api/${presumedUserId}/${modifySlug}/apidetails`);
             if (response.ok) {
                 currentApiData = await response.json();
                 isModificationMode = true;
                 
                 // Update mode switcher to show modification mode active
                 const genBtn = document.getElementById('generationModeBtn');
                 const modBtn = document.getElementById('modificationModeBtn');
                 if (genBtn && modBtn) {
                     genBtn.className = 'px-3 py-1.5 bg-slate-700/50 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
                     modBtn.className = 'px-3 py-1.5 bg-gradient-to-r from-orange-600 to-amber-600 text-white rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
                 }
                 
                 // Hide API selector since API is already selected via URL
                 const apiSelector = document.getElementById('apiSelectorContainer');
                 if (apiSelector) {
                     apiSelector.classList.add('hidden');
                 }
                 
                 // Show modification mode UI
                 showModificationModeUI();
                 
                 // Load API details in preview panel
                 loadAPIDetailsInPreview(currentApiData);
                 
                 // Enable chat input
                 const chatInput = document.getElementById('chatInput');
                 if (chatInput) {
                     chatInput.disabled = false;
                 }
                 
                 // Add modification welcome message
                 setTimeout(() => {
                     addModificationWelcomeMessage(currentApiData);
                 }, 300);
                 
                 // Switch to modification view if needed, or just conversation state.
                 conversationState = 'api_modification'; // Use appropriate state if defined
             } else {
                 console.error("Failed to load API for modification", response.status);
                 addMessage('assistant', "❌ I couldn't load the API you requested to modify. Please select it from your profile.", { skipDelay: true });
             }
        } catch (e) {
            console.error("Error loading API for modification", e);
            addMessage('assistant', "❌ I couldn't load the API you requested to modify. Please select it from your profile.", { skipDelay: true });
        }
    }
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

    // Add send animation to input
    input.classList.add('sending');
    
    // Add user message to chat
    await addMessage('user', message);
    
    // Clear input with animation
    setTimeout(() => {
        input.value = '';
        input.classList.remove('sending');
        handleInputChange();
    }, 300);

    // Check if we're in modification mode
    if (isModificationMode && currentApiData) {        
        // Get user ID from currentApiData or auth
        const userId = currentApiData.user_id || (currentUser ? currentUser.id : 'temp_' + Date.now());
        
        // Process the modification request directly
        await processModificationRequest(message, userId);
        
        // Keep modification mode active until successful modification
        // The processModificationRequest will handle resetting if needed
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
            await handleConversationalMessage(message);
            return;
        }
    }

    try {
        isGenerating = true;
        
        // Get user ID (from auth or generate temp one)
        const userId = currentUser ? currentUser.id : 'temp_' + Date.now();
        
        // Add initial proposal analysis system messages (similar to generate-api)
        addStreamingMessage('🔍 Starting proposal analysis...', 'greeting');
        await new Promise(resolve => setTimeout(resolve, 4800)); // Small delay for natural flow
        
        addStreamingMessage('🧠 Analyzing your requirements and determining feasibility...', 'ai_processing');
        await new Promise(resolve => setTimeout(resolve, 4000)); // Small delay for natural flow
        
        // Get database config for the request
        const dbConfig = getDatabaseConfigForRequest();
        if (dbConfig) {
            console.log('📊 Database configuration detected for proposal:', { 
                db_type: dbConfig.db_type, 
                host: dbConfig.host,
                database_name: dbConfig.database_name 
            });
        }
        
        // First, generate a proposal for the prompt
        const proposalResponse = await fetch('/generate-proposal', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            credentials: 'include', // Include cookies for authentication
            body: JSON.stringify({
                prompt: message,
                user_id: userId,
                // Include database configuration if enabled
                database_config: dbConfig
            })
        });

        // Check for rate limiting or other HTTP errors
        if (proposalResponse.status === 429) {
            const errorData = await proposalResponse.json();
            hideTypingIndicator();
            addRateLimitMessage(errorData.detail);
            return;
        } else if (!proposalResponse.ok) {
            const errorData = await proposalResponse.json();
            hideTypingIndicator();
            await addMessage('assistant', `❌ Error: ${errorData.detail || 'Request failed'}`, { enableTyping: false });
            return;
        }

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
                // Add completion message before showing proposal
                addStreamingMessage('✅ Analysis complete! Creating detailed proposal...', 'step_complete');
                await new Promise(resolve => setTimeout(resolve, 500)); // Small delay
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
    
    generationMode = 'multi-step';
    if (generationMode === 'multi-step') {
        return await generateAPIStream(message, userId, skipAnalysis);
    }

    // Original single-step generation logic
    try {
        console.log(`Generating API - Skip Analysis: ${skipAnalysis}, Mode: ${generationMode}`);
        console.log('generateAPI called with message:', message);
        
        // Update generation progress text if it exists
        const progressText = document.getElementById('generationProgressText');
        if (progressText) {
            const genModeText = 'Generating your API... (Single-step)';
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
                use_multi_step: false, // Force single-step for this path
                pipeline_name: 'full_pipeline',
                proposal_id: currentProposalId,
                // Extract sample input/output from proposal if available
                sample_input: currentProposal?.proposal?.input_format?.example || null,
                expected_output: currentProposal?.proposal?.output_format?.example || null
            })
        });

        // Check for rate limiting or other HTTP errors
        if (response.status === 429) {
            const errorData = await response.json();
            hideTypingIndicator();
            addRateLimitMessage(errorData.detail);
            return;
        } else if (!response.ok) {
            const errorData = await response.json();
            hideTypingIndicator();
            addMessage('assistant', `❌ Error: ${errorData.detail || 'Request failed'}`);
            return;
        }

        const result = await response.json();
        
        hideTypingIndicator();

        if (result.success) {
            // Hide the loading animation
            hideAPIBuildLoading();
            
            // Update conversation state to indicate code has been generated
            conversationState = result.conversation_state || 'code_generated';
            
            currentApiData = result;
            addAPIResultMessage(result);
            addMessage('system', '🎉 API generated successfully! You can now test and deploy your API using the interface above.');
            
            console.log('Updated conversation state to:', conversationState);
        } else {
            // Hide the loading animation
            hideAPIBuildLoading();
            
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
        // Hide the loading animation
        hideAPIBuildLoading();
        hideTypingIndicator();
        addMessage('assistant', `❌ Network error: ${error.message}`);
    }
}

// New streaming API generation function with real-time chat updates
async function generateAPIStream(message, userId, skipAnalysis = true) {
    try {
        console.log(`Starting streaming API generation - Mode: ${generationMode}`);
        
        // Reset message queue for new generation
        messageQueue = [];
        isProcessingQueue = false;
        lastMessageTime = 0;
        
        // Clear any existing typing indicator
        hideTypingIndicator();
        
        // Initial greeting is now handled by the streaming step messages
        
        const response = await fetch('/generate-api-stream', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                prompt: message,
                user_id: userId,
                skip_analysis: skipAnalysis,
                pipeline_name: 'full_pipeline',
                proposal_id: currentProposalId,
                // Extract sample input/output from proposal if available
                sample_input: currentProposal?.proposal?.input_format?.example || null,
                expected_output: currentProposal?.proposal?.output_format?.example || null,
                // IMPORTANT: don't use a timestamp slug as the "API name" — it ends up persisted to DB as api_name.
                // Prefer the proposal's friendly name; fall back to structured extraction if the user provided one.
                api_name: getApiNameForGeneration(message),
                // Include database configuration if enabled
                database_config: getDatabaseConfigForRequest()
            })
        });

        // Check for rate limiting or other HTTP errors
        if (response.status === 429) {
            const errorData = await response.json();
            addMessage('assistant', `❌ Rate limit exceeded: ${errorData.detail}`);
            return;
        } else if (!response.ok) {
            const errorData = await response.json();
            addMessage('assistant', `❌ Error: ${errorData.detail || 'Request failed'}`);
            return;
        }

        // Handle the streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            
            // Keep the last incomplete line in the buffer
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const eventData = JSON.parse(line.slice(6));
                        await handleStreamEvent(eventData);
                    } catch (e) {
                        console.warn('Failed to parse SSE data:', line, e);
                    }
                }
            }
        }

    } catch (error) {
        // Hide the loading animation
        hideAPIBuildLoading();
        console.error('Streaming generation error:', error);
        addMessage('assistant', `❌ Connection error: ${error.message}`);
    }
}

// Handle different types of streaming events
async function handleStreamEvent(event) {
    const { type, timestamp, data } = event;

    switch (type) {
        case 'chat_message':
            // Queue chat messages for staggered display
            queueMessage(() => handleChatMessage(data));
            break;
        
        case 'step_start':
            // Queue step start messages
            queueMessage(() => handleStepStart(data));
            break;
        
        case 'step_phase':
            handleStepPhase(data);
            break;
        
        case 'step_complete':
            // Queue step complete messages
            queueMessage(() => handleStepComplete(data));
            break;
        
        case 'step_error':
            handleStepError(data);
            break;
        
        case 'session_complete':
            handleSessionComplete(data);
            break;
        
        case 'generation_complete':
            handleGenerationComplete(data);
            break;
        
        case 'error':
            addMessage('assistant', `❌ ${data.message}`);
            break;
        
        default:
            console.log('Unknown stream event type:', type, data);
    }
}

// Queue messages to be processed with delays
function queueMessage(handler) {
    messageQueue.push(handler);
    processQueue();
}

// Process the message queue with delays
async function processQueue() {
    if (isProcessingQueue || messageQueue.length === 0) {
        return;
    }
    
    isProcessingQueue = true;
    
    while (messageQueue.length > 0) {
        const handler = messageQueue.shift();
        
        // Calculate delay needed to maintain minimum time between messages
        const now = Date.now();
        const timeSinceLastMessage = now - lastMessageTime;
        const delayNeeded = Math.max(0, MIN_MESSAGE_DELAY - timeSinceLastMessage);
        
        // Wait for the required delay
        if (delayNeeded > 0) {
            await new Promise(resolve => setTimeout(resolve, delayNeeded));
        }
        
        // Execute the handler and update last message time
        handler();
        lastMessageTime = Date.now();
    }
    
    isProcessingQueue = false;
}

// Handle chat message events
function handleChatMessage(data) {
    const { message, phase, message_type } = data;
    
    // Add streaming message directly - no typing indicator for streaming messages
    addStreamingMessage(message, message_type || phase);
}

// Handle step start events
function handleStepStart(data) {
    console.log('Step started:', data);
    
    if (data.message) {
        addStreamingMessage(data.message, 'step_start');
    }
    
    // Update any progress indicators if they exist
    updateStepProgress(data);
}

// Handle step phase updates
function handleStepPhase(data) {
    console.log('Step phase:', data);
    
    // Update progress indicators
    updateStepProgress(data);
}

// Handle step completion
function handleStepComplete(data) {
    console.log('Step completed:', data);
    
    if (data.message) {
        addStreamingMessage(data.message, 'step_complete');
    }
    
    // Update progress indicators
    updateStepProgress(data);
}

// Handle step errors
function handleStepError(data) {
    console.log('Step error:', data);
    
    if (data.message) {
        addStreamingMessage(data.message, 'step_error');
    }
}

// Handle session completion
function handleSessionComplete(data) {
    console.log('Session completed:', data);
    
    if (data.message) {
        addStreamingMessage(data.message, 'session_complete');
    }
}

// Handle final generation completion with results
function handleGenerationComplete(data) {
    console.log('Generation completed:', data);
    
    // Hide the loading animation
    hideAPIBuildLoading();
    
    if (data.success) {
        // Update conversation state
        conversationState = 'code_generated';
        currentApiData = data;
        
        // Add the API result
        addAPIResultMessage(data);
        addMessage('system', '🎉 API generated successfully! You can now test and deploy your API using the interface above.');
    } else {
        addMessage('assistant', `❌ Generation failed: ${data.message}`);
    }
}

// Add streaming message with enhanced styling
function addStreamingMessage(message, messageType = 'default') {
    const messagesContainer = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message-animation streaming-message';
    
    // Remember if user was at bottom before adding message
    const wasAtBottom = messagesContainer.scrollTop + messagesContainer.clientHeight >= messagesContainer.scrollHeight - 50;
    
    // Get appropriate styling based on message type
    const styling = getStreamingMessageStyling(messageType);
    
    messageDiv.innerHTML = `
        <div class="flex items-start space-x-3 w-full">
            <div class="w-8 h-8 ${styling.avatarBg} rounded-full flex items-center justify-center flex-shrink-0">
                <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    ${styling.icon}
                </svg>
            </div>
            <div class="glass-card rounded-2xl p-4 flex-1 min-w-0 ${styling.cardBg}">
                <div class="text-white text-sm ${styling.textStyle}">
                    ${formatStreamingMessage(message)}
                </div>
                ${messageType !== 'default' ? `<div class="text-xs text-slate-400 mt-1">${formatMessageType(messageType)}</div>` : ''}
            </div>
        </div>
    `;
    
    messagesContainer.appendChild(messageDiv);
    
    // Auto-scroll if user was at bottom
    if (wasAtBottom) {
        setTimeout(() => {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }, 100);
    }
    
    // Store in conversation history
    currentConversation.push({ type: 'assistant', content: message, messageType });
}

// Get styling for different message types
function getStreamingMessageStyling(messageType) {
    const styles = {
        greeting: {
            avatarBg: 'bg-gradient-to-r from-green-500 to-emerald-600',
            cardBg: 'border-green-500/30 bg-gradient-to-r from-green-600/10 to-emerald-600/10',
            icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 8h10m0 0V6a2 2 0 00-2-2H9a2 2 0 00-2 2v2m0 0v10a2 2 0 002 2h6a2 2 0 002-2V8M9 12h6"></path>',
            textStyle: 'font-medium'
        },
        step_start: {
            avatarBg: 'bg-gradient-to-r from-blue-500 to-cyan-600',
            cardBg: 'border-blue-500/30 bg-gradient-to-r from-blue-600/10 to-cyan-600/10',
            icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>',
            textStyle: 'font-medium'
        },
        step_complete: {
            avatarBg: 'bg-gradient-to-r from-green-500 to-emerald-600',
            cardBg: 'border-green-500/30 bg-gradient-to-r from-green-600/10 to-emerald-600/10',
            icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>',
            textStyle: 'font-medium'
        },
        step_error: {
            avatarBg: 'bg-gradient-to-r from-red-500 to-pink-600',
            cardBg: 'border-red-500/30 bg-gradient-to-r from-red-600/10 to-pink-600/10',
            icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>',
            textStyle: 'font-medium'
        },
        ai_processing: {
            avatarBg: 'bg-gradient-to-r from-purple-500 to-indigo-600',
            cardBg: 'border-purple-500/30 bg-gradient-to-r from-purple-600/10 to-indigo-600/10',
            icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>',
            textStyle: 'italic'
        },
        default: {
            avatarBg: 'bg-gradient-to-r from-slate-500 to-gray-600',
            cardBg: 'border-slate-500/30',
            icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path>',
            textStyle: ''
        }
    };
    
    return styles[messageType] || styles.default;
}

// Format streaming message content
function formatStreamingMessage(message) {
    return message
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code class="bg-black/20 px-1 py-0.5 rounded text-xs">$1</code>');
}

// Format message type for display
function formatMessageType(messageType) {
    const typeMap = {
        greeting: '🤖 AI Assistant',
        step_start: ' Step Started',
        step_complete: '✅ Step Complete',
        step_error: '❌ Step Error',
        ai_processing: '🧠 AI Processing',
        template_loading: '📝 Loading Template',
        prompt_preparation: '🔧 Preparing Prompts',
        response_processing: '⚡ Processing Response',
        code_extraction: '🔍 Code Extraction',
        finalization: '✨ Finalizing',
        default: '💬 Status Update'
    };
    
    return typeMap[messageType] || typeMap.default;
}

// Update step progress (placeholder for future progress UI)
function updateStepProgress(data) {
    // This can be enhanced to show actual progress bars
    console.log('Progress update:', data);
    
    // Update generation progress text if it exists
    const progressText = document.getElementById('generationProgressText');
    if (progressText && data.description) {
        progressText.textContent = data.description;
    }
}

// Enhanced message system with smooth animations and realistic delays
async function addMessage(type, content, options = {}) {
    const messagesContainer = document.getElementById('chatMessages');
    const messageDiv = document.createElement('div');
    
    // Remember if user was at bottom before adding message
    const wasAtBottom = messagesContainer.scrollTop + messagesContainer.clientHeight >= messagesContainer.scrollHeight - 50;
    
    if (type === 'user') {
        // Add instant user message with send animation
        messageDiv.className = 'message-animation message-send';
        messageDiv.innerHTML = `
            <div class="flex items-start space-x-3 justify-end">
                <div class="glass-card rounded-2xl p-4 max-w-lg bg-gradient-to-r from-blue-600/20 to-purple-600/20 border-blue-500/30 user-message-bubble">
                    <p class="text-white">${content}</p>
                </div>
                <div class="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center flex-shrink-0 user-avatar">
                    <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                    </svg>
                </div>
            </div>
        `;
        
        messagesContainer.appendChild(messageDiv);
        
        // Trigger send animation
        setTimeout(() => {
            messageDiv.classList.add('message-sent');
        }, 50);
        
    } else if (type === 'assistant') {
        // Calculate realistic typing delay based on content length
        const typingDelay = options.skipDelay ? 0 : calculateTypingDelay(content);
        
        if (!options.skipDelay && typingDelay > 0) {
            // Show thinking dots during delay
            showThinkingDots();
            await new Promise(resolve => setTimeout(resolve, typingDelay));
            hideThinkingDots();
        }
        
        messageDiv.className = 'message-animation assistant-message-entrance';
        messageDiv.innerHTML = `
            <div class="w-full">
                <div class="glass-card rounded-2xl p-6 max-w-4xl assistant-message-content">
                    <div class="typing-content"></div>
                </div>
            </div>
        `;
        
        messagesContainer.appendChild(messageDiv);
        
        // Start typing animation if enabled
        if (options.enableTyping !== false && !options.skipDelay) {
            await animateTyping(messageDiv.querySelector('.typing-content'), content);
        } else {
            messageDiv.querySelector('.typing-content').innerHTML = content;
        }
        
    } else if (type === 'system') {
        messageDiv.className = 'message-animation system-message-fade';
        messageDiv.innerHTML = `
            <div class="flex justify-center">
                <div class="glass-card rounded-xl p-3 text-center text-sm text-slate-300 max-w-md system-message-bubble">
                    ${content}
                </div>
            </div>
        `;
        messagesContainer.appendChild(messageDiv);
    }
    
    // Enhanced auto-scroll with smooth animation
    if (wasAtBottom || type === 'user') {
        setTimeout(() => {
            messagesContainer.scrollTo({
                top: messagesContainer.scrollHeight,
                behavior: 'smooth'
            });
        }, 100);
    }
    
    // Store in conversation history
    currentConversation.push({ type, content });
}

// Calculate realistic typing delay based on content complexity
function calculateTypingDelay(content) {
    const baseDelay = 800; // Minimum delay
    const maxDelay = 3000; // Maximum delay
    
    // Remove HTML tags for length calculation
    const textContent = content.replace(/<[^>]*>/g, '');
    const wordCount = textContent.split(/\s+/).length;
    const charCount = textContent.length;
    
    // More complex content = longer delay
    let delay = baseDelay + (wordCount * 50) + (charCount * 10);
    
    // Factor in complexity indicators
    if (content.includes('<ul>') || content.includes('<ol>')) delay += 500; // Lists
    if (content.includes('<code>') || content.includes('```')) delay += 800; // Code
    if (content.includes('<table>')) delay += 600; // Tables
    
    return Math.min(delay, maxDelay);
}

// Show thinking dots animation
function showThinkingDots() {
    const messagesContainer = document.getElementById('chatMessages');
    const thinkingDiv = document.createElement('div');
    thinkingDiv.id = 'thinking-indicator';
    thinkingDiv.className = 'thinking-animation';
    thinkingDiv.innerHTML = `
        <div class="w-full">
            <div class="glass-card rounded-2xl p-4 max-w-4xl">
                <div class="flex items-center space-x-2">
                    <div class="thinking-dots">
                        <div class="thinking-dot"></div>
                        <div class="thinking-dot"></div>
                        <div class="thinking-dot"></div>
                    </div>
                    <span class="text-slate-400 text-sm">thinking...</span>
                </div>
            </div>
        </div>
    `;
    messagesContainer.appendChild(thinkingDiv);
    
    // Scroll to show thinking indicator
    setTimeout(() => {
        messagesContainer.scrollTo({
            top: messagesContainer.scrollHeight,
            behavior: 'smooth'
        });
    }, 100);
}

// Hide thinking dots
function hideThinkingDots() {
    const thinkingIndicator = document.getElementById('thinking-indicator');
    if (thinkingIndicator) {
        thinkingIndicator.remove();
    }
}

// Animate typing effect for assistant messages
async function animateTyping(container, content) {
    const typingSpeed = 30; // milliseconds per character
    const minChunkSize = 1;
    const maxChunkSize = 3;
    
    // Remove HTML for typing calculation, but preserve it for display
    const isHTML = /<[^>]*>/.test(content);
    
    if (isHTML) {
        // For HTML content, show it instantly but with a brief delay
        await new Promise(resolve => setTimeout(resolve, 300));
        container.innerHTML = content;
        container.classList.add('content-revealed');
    } else {
        // For plain text, use character-by-character typing
        let currentIndex = 0;
        container.innerHTML = '<span class="typing-cursor">|</span>';
        
        while (currentIndex < content.length) {
            const chunkSize = Math.floor(Math.random() * (maxChunkSize - minChunkSize + 1)) + minChunkSize;
            const chunk = content.slice(currentIndex, currentIndex + chunkSize);
            
            container.innerHTML = content.slice(0, currentIndex + chunkSize) + '<span class="typing-cursor">|</span>';
            currentIndex += chunkSize;
            
            // Variable speed for more natural typing
            const delay = typingSpeed + Math.random() * 20;
            await new Promise(resolve => setTimeout(resolve, delay));
        }
        
        // Remove cursor and add final reveal animation
        container.innerHTML = content;
        container.classList.add('content-revealed');
    }
}

async function addChatAnalysisMessage(analysis) {
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
    await addMessage('assistant', content);
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

function addRateLimitMessage(rateLimitDetails) {
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <div class="w-2 h-2 bg-orange-500 rounded-full flex-shrink-0"></div>
                <span class="text-orange-300 font-medium">⏱️ Rate Limit Reached</span>
            </div>
            <div class="bg-orange-900/20 border border-orange-600/30 rounded-lg p-4">
                <div class="text-orange-200 space-y-3">
                    <p class="text-sm leading-relaxed">
                        You've reached your current usage limit. This helps ensure fair access for all users.
                    </p>
                    <div class="text-xs text-orange-300/80">
                        ${escapeHtml(rateLimitDetails || 'Daily usage limit exceeded')}
                    </div>
                    <div class="space-y-2 text-sm">
                        <p class="font-medium text-orange-200">What you can do:</p>
                        <ul class="space-y-1 text-orange-200/90">
                            <li class="flex items-start space-x-2">
                                <span class="text-orange-400">•</span>
                                <span>Wait for your limits to reset (usually 24 hours)</span>
                            </li>
                            <li class="flex items-start space-x-2">
                                <span class="text-orange-400">•</span>
                                <span>Check your <a href="/profile" class="text-orange-300 hover:text-orange-200 underline">usage dashboard</a> for details</span>
                            </li>
                            <li class="flex items-start space-x-2">
                                <span class="text-orange-400">•</span>
                                <span>Consider upgrading for higher limits</span>
                            </li>
                        </ul>
                    </div>
                </div>
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

// Store proposal data to avoid embedding large prompts in HTML attributes
const proposalDataStore = new Map();

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
function createLoadingAnimation() {
    return `
        <div class="bg-green-900/20 border border-green-500/30 rounded-xl p-4">
            <div class="flex items-center justify-center space-x-4">
                <div class="relative">
                    <div class="w-12 h-12 border-4 border-green-500/30 border-t-green-400 rounded-full animate-spin"></div>
                    <div class="absolute inset-2 w-8 h-8 border-2 border-green-400/20 border-t-green-300 rounded-full animate-spin" style="animation-direction: reverse; animation-duration: 0.8s;"></div>
                </div>
                <div class="text-center">
                    <h4 class="font-semibold text-white mb-2 flex items-center space-x-2">
                        <span class="text-green-400"></span>
                        <span>Building Your API...</span>
                    </h4>
                    <div class="flex items-center space-x-2">
                        <div class="flex space-x-1">
                            <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse" style="animation-delay: 0s;"></div>
                            <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse" style="animation-delay: 0.3s;"></div>
                            <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse" style="animation-delay: 0.6s;"></div>
                        </div>
                        <span class="text-green-300 text-sm font-medium">Generating code and documentation</span>
                    </div>
                </div>
            </div>
            <div class="mt-4 bg-green-900/10 rounded-lg p-3">
                <div class="flex items-center space-x-2 mb-2">
                    <div class="w-3 h-3 bg-green-400 rounded-full animate-pulse"></div>
                    <span class="text-green-200 text-sm">Analyzing requirements...</span>
                </div>
                <div class="w-full bg-green-900/30 rounded-full h-2">
                    <div class="bg-gradient-to-r from-green-500 to-emerald-400 h-2 rounded-full animate-pulse" style="width: 100%; animation-duration: 2s;"></div>
                </div>
                <p class="text-xs text-green-300 mt-2 opacity-75">
                    This may take a few moments. Please don't refresh the page.
                </p>
            </div>
        </div>
    `;
}

function createFullSectionLoadingAnimation() {
    return `
        <div class="h-full flex items-center justify-center p-8">
            <div class="text-center max-w-md mx-auto">
                <!-- Main Loading Animation -->
                <div class="relative mb-8">
                    <div class="w-24 h-24 border-4 border-green-500/20 border-t-green-400 rounded-full animate-spin mx-auto"></div>
                    <div class="absolute inset-4 w-16 h-16 border-3 border-green-400/30 border-t-green-300 rounded-full animate-spin mx-auto" style="animation-direction: reverse; animation-duration: 1.2s;"></div>
                    <div class="absolute inset-8 w-8 h-8 border-2 border-green-300/40 border-t-green-200 rounded-full animate-spin mx-auto" style="animation-duration: 0.8s;"></div>
                </div>

                <!-- Status Text -->
                <div class="space-y-4">
                    <h3 class="text-2xl font-bold text-white flex items-center justify-center space-x-3">
                        <span class="text-green-400"></span>
                        <span>Building Your API</span>
                    </h3>
                    
                    <div class="space-y-3">
                        <div class="flex items-center justify-center space-x-2">
                            <div class="flex space-x-1">
                                <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse" style="animation-delay: 0s;"></div>
                                <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse" style="animation-delay: 0.3s;"></div>
                                <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse" style="animation-delay: 0.6s;"></div>
                                <div class="w-2 h-2 bg-green-400 rounded-full animate-pulse" style="animation-delay: 0.9s;"></div>
                            </div>
                            <span class="text-green-300 font-medium">Generating code and documentation</span>
                        </div>
                        
                        <p class="text-slate-400 text-sm">This may take a few moments while we create your custom API</p>
                    </div>
                </div>

                <!-- Progress Steps -->
                <div class="mt-8 space-y-4">
                    <div class="bg-green-900/10 rounded-lg p-4 border border-green-500/20">
                        <div class="flex items-center space-x-3 mb-3">
                            <div class="w-4 h-4 bg-green-400 rounded-full animate-pulse"></div>
                            <span class="text-green-200 font-medium">Analyzing requirements</span>
                        </div>
                        <div class="w-full bg-green-900/30 rounded-full h-2">
                            <div class="bg-gradient-to-r from-green-500 to-emerald-400 h-2 rounded-full animate-pulse" style="width: 100%; animation-duration: 2s;"></div>
                        </div>
                    </div>
                    
                    <div class="bg-blue-900/10 rounded-lg p-4 border border-blue-500/20">
                        <div class="flex items-center space-x-3 mb-3">
                            <div class="w-4 h-4 bg-blue-400 rounded-full animate-pulse" style="animation-delay: 0.5s;"></div>
                            <span class="text-blue-200 font-medium">Generating endpoints</span>
                        </div>
                        <div class="w-full bg-blue-900/30 rounded-full h-2">
                            <div class="bg-gradient-to-r from-blue-500 to-cyan-400 h-2 rounded-full animate-pulse" style="width: 80%; animation-duration: 2.5s; animation-delay: 0.5s;"></div>
                        </div>
                    </div>
                    
                    <div class="bg-purple-900/10 rounded-lg p-4 border border-purple-500/20">
                        <div class="flex items-center space-x-3 mb-3">
                            <div class="w-4 h-4 bg-purple-400 rounded-full animate-pulse" style="animation-delay: 1s;"></div>
                            <span class="text-purple-200 font-medium">Creating documentation</span>
                        </div>
                        <div class="w-full bg-purple-900/30 rounded-full h-2">
                            <div class="bg-gradient-to-r from-purple-500 to-pink-400 h-2 rounded-full animate-pulse" style="width: 60%; animation-duration: 3s; animation-delay: 1s;"></div>
                        </div>
                    </div>
                </div>

                <!-- Warning Text -->
                <div class="mt-6 p-3 bg-yellow-900/10 border border-yellow-500/20 rounded-lg">
                    <p class="text-yellow-300 text-xs font-medium flex items-center justify-center space-x-2">
                        <span>⚠️</span>
                        <span>Please don't refresh the page during generation</span>
                    </p>
                </div>
            </div>
        </div>
    `;
}

function hideAPIBuildLoading() {
    const previewContent = document.getElementById('apiPreviewContent');
    
    if (previewContent && previewContent.innerHTML.includes('Building Your API')) {
        console.log('Hiding API build loading animation from preview section');
        
        // Don't restore content here - let updateAPIPreview handle it
        // Just mark that we're ready for the content to be updated
        console.log('Loading animation will be replaced by API preview content');
    }
}

// Store original preview content for restoration
let originalPreviewContent = null;

function startAPIBuild(originalPrompt, userId, buttonElement) {
    // Find the confirmation buttons container and hide it
    const container = buttonElement.closest('[id^="confirmation-buttons-"]');
    if (container) {
        container.style.transition = 'opacity 0.3s ease-out';
        container.style.opacity = '0';
        setTimeout(() => {
            container.style.display = 'none';
        }, 300);
    }
    
    // Get the API preview content container
    const previewContent = document.getElementById('apiPreviewContent');
    
    if (previewContent) {
        // Store the original content for restoration later
        originalPreviewContent = previewContent.innerHTML;
        
        // Add smooth transition effect
        previewContent.style.transition = 'opacity 0.3s ease-in-out';
        previewContent.style.opacity = '0';
        
        setTimeout(() => {
            // Replace with full-section loading animation
            previewContent.innerHTML = createFullSectionLoadingAnimation();
            previewContent.style.opacity = '1';
        }, 300);
    }
    
    // Call the original build function
    confirmBuildAPI(originalPrompt, userId);
}

async function confirmBuildAPI(originalPrompt, userId) {
    try {
        // Add user confirmation message
        addMessage('user', ' Yes, build this API!');
        
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

function addAPIResultMessage(result, isModification = false) {
    const endpointUrl = window.location.origin + result.endpoint_url;
    
    // Update the API preview panel
    updateAPIPreview(result);
    
    // Extract or generate smart test data based on the API
    const testData = {"json": "Place Holder", "description": "Place Holder", "examples": []}
    
    // Choose message based on context
    const title = isModification 
        ? "✅ API Modified Successfully!" 
        : "🎉 API Generated Successfully!";
    const subtitle = isModification
        ? "Your changes have been applied!"
        : "Your API is ready!";
    const description = isModification
        ? "Check the preview panel on the right to test the updated API, get code snippets, or make additional changes."
        : "Check the preview panel on the right to test, get code snippets, and deploy your API.";
    const nextSteps = isModification
        ? "Use the API Preview panel to test your updated endpoint, copy code snippets, or make more modifications!"
        : "Use the API Preview panel to test your endpoint, copy code snippets for integration, or deploy it live!";
    const badgeColor = isModification
        ? "bg-orange-900/50 text-orange-400 border-orange-500/30"
        : "status-buildable";
    const cardBorder = isModification
        ? "border-orange-500/30"
        : "border-green-500/30";
    const iconBg = isModification
        ? "bg-orange-500/20"
        : "bg-green-500/20";
    const iconColor = isModification
        ? "text-orange-400"
        : "text-green-400";
    const textColor = isModification
        ? "text-orange-200"
        : "text-green-200";
    
    const content = `
        <div class="space-y-4">
            <div class="flex items-center space-x-2">
                <span class="status-badge ${badgeColor}">Success</span>
                <h3 class="font-semibold text-white">${title}</h3>
            </div>
            
            <div class="glass-card rounded-xl p-6 ${cardBorder}">
                <div class="flex items-center space-x-3 mb-4">
                    <div class="w-12 h-12 ${iconBg} rounded-full flex items-center justify-center">
                        <svg class="w-6 h-6 ${iconColor}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                        </svg>
                    </div>
                    <div class="flex-1">
                        <h4 class="font-medium text-white mb-1">${subtitle}</h4>
                        <p class="text-sm ${textColor}">${description}</p>
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
                        <strong>💡 Next Steps:</strong> ${nextSteps}
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
        API deployed successfully! Redirecting to API details page...
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
function downloadBinaryResponse(base64Data, contentType) {
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
        
        // Show success notification
        showNotification('Downloaded successfully!', 'success');
    } catch (error) {
        console.error('Failed to download binary data:', error);
        showNotification('Failed to download', 'error');
    }
}

function showNotification(message, type = 'success') {
    const notification = document.createElement('div');
    const bgColor = type === 'success' ? 'bg-emerald-600' : 'bg-red-600';
    notification.className = `fixed top-4 right-4 ${bgColor} text-white px-6 py-3 rounded-xl shadow-xl z-50 animate-slide-up`;
    notification.innerHTML = `
        <div class="flex items-center space-x-2">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
            </svg>
            <span>${message}</span>
        </div>
    `;
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 3000);
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(() => {
        // Show temporary feedback
        showNotification('Copied to clipboard!', 'success');
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
        // showTypingIndicator('Modifying your API...'); 
        
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

        // Check for rate limiting or other HTTP errors
        if (response.status === 429) {
            const errorData = await response.json();
            hideTypingIndicator();
            addRateLimitMessage(errorData.detail);
            return;
        } else if (!response.ok) {
            const errorData = await response.json();
            hideTypingIndicator();
            addMessage('assistant', `❌ Error: ${errorData.detail || 'Request failed'}`);
            return;
        }

        hideTypingIndicator();

        // Handle the streaming response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            
            // Keep the last incomplete line in the buffer
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const eventData = JSON.parse(line.slice(6));
                        await handleModificationEvent(eventData);
                    } catch (e) {
                        console.warn('Failed to parse SSE data:', line, e);
                    }
                }
            }
        }

    } catch (error) {
        hideTypingIndicator();
        addMessage('assistant', `❌ Network error: ${error.message}`);
    }
}

async function handleModificationEvent(event) {
    const { type, data } = event;
    
    switch (type) {
        case 'chat_message':
            // Display chat messages from the backend
            await addMessage('assistant', data.message);
            break;
            
        case 'modification_complete':
            handleModificationComplete(data);
            break;
            
        case 'error':
            addMessage('assistant', `❌ Error: ${data.message}`);
            break;
            
        default:
            console.log('Unknown modification event:', type);
    }
}

function handleModificationComplete(result) {
    if (result.success) {
        // Update current API data with modified version
        currentApiData = {...currentApiData, ...result};
        
        // This is a final modified API
        addAPIResultMessage(result, true); 
        
        // Explicitly update test input with new test data for the modified API
        // This ensures test scenarios are regenerated based on the updated API
        if (result.api_slug && result.user_id) {
            updateTestInput({
                api_slug: result.api_slug,
                user_id: result.user_id,
                ...result
            });
        }
        
        // Keep modification mode active
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.placeholder = "Want to make more changes? Describe them here, or click 'Exit & Return' to go back.";
        }
        
        // addMessage('system', '✅ Modification complete! The API has been updated.');
    } else {
        addMessage('assistant', `❌ Modification failed: ${result.message}`);
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
    console.log('updateAPIPreview called with:', apiData);
    console.log('API slug in preview:', apiData?.api_slug);
    console.log('User ID in preview:', apiData?.user_id);
    currentAPISpec = apiData;
    currentProposal = null;
    previewMode = 'api';
    
    // First, restore the preview structure if it's currently showing loading animation
    const previewContent = document.getElementById('apiPreviewContent');
    if (previewContent && previewContent.innerHTML.includes('Building Your API')) {
        console.log('Preview showing loading - restoring original content structure');
        
        // Restore the original preview structure
        previewContent.innerHTML = `
            <!-- Empty State -->
            <div id="emptyState" class="p-6 h-full flex items-center justify-center hidden">
                <div class="text-center">
                    <div class="w-16 h-16 bg-slate-700/50 rounded-full flex items-center justify-center mx-auto mb-4">
                        <svg class="w-8 h-8 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
                        </svg>
                    </div>
                    <h4 class="text-lg font-medium text-slate-300 mb-2">No API in Preview</h4>
                    <p class="text-slate-500 text-sm max-w-sm mx-auto">Start a conversation to generate an API and see a structured preview here with endpoints, parameters, and testing tools.</p>
                </div>
            </div>
            
            <!-- API Preview Content (Hidden by default) -->
            <div id="apiPreviewPanel" class="hidden p-6 space-y-4">
                
                <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4 w-full">
                    <h4 class="font-semibold text-white mb-3 flex items-center space-x-2">
                        <span class="text-blue-400">🌐</span>
                        <span>API Endpoint</span>
                    </h4>
                    <div class="space-y-2">
                        <div class="flex items-center gap-2 flex-wrap">
                            <span id="apiMethod" class="px-2 py-1 bg-green-600/20 text-green-300 rounded font-mono text-xs whitespace-nowrap">POST</span>
                        </div>
                        <code id="apiEndpoint" class="block text-blue-300 font-mono text-sm bg-slate-700/50 px-2 py-1 rounded break-all">-</code>
                        <p id="apiDescription" class="text-slate-300 text-sm">-</p>
                    </div>
                </div>
                
                <!-- Parameters Section -->
                <div id="parametersSection" class="bg-green-900/20 border border-green-500/30 rounded-xl p-4 w-full">
                    <h4 class="font-semibold text-white mb-3 flex items-center space-x-2">
                        <span class="text-green-400">📝</span>
                        <span>Parameters</span>
                    </h4>
                    <div id="parametersTable" class="overflow-x-auto">
                        <div class="text-slate-400 text-sm text-center py-4">No parameters defined</div>
                    </div>
                </div>
                
                <!-- Example Response Section -->
                <div id="exampleResponseSection" class="bg-purple-900/20 border border-purple-500/30 rounded-xl p-4 w-full">
                    <h4 class="font-semibold text-white mb-3 flex items-center space-x-2">
                        <span class="text-purple-400">📋</span>
                        <span>Example Response</span>
                    </h4>
                    <div id="exampleResponse" class="bg-slate-800/50 rounded p-4 font-mono text-sm text-slate-300">
                        <div class="text-slate-400 text-center py-4">No response example available</div>
                    </div>
                </div>
                
                <!-- Test Playground Section -->
                <div id="testPlaygroundSection" class="bg-slate-800/30 border border-slate-600/50 rounded-xl p-4 w-full">
                    <h4 class="font-semibold text-white mb-3 flex items-center space-x-2">
                        <span class="text-blue-400">🧪</span>
                        <span>Test Playground</span>
                    </h4>
                    
                    <div class="space-y-4">
                        <!-- Test Scenario Selector -->
                        <div id="testScenarioSelector" class="hidden">
                            <label class="block text-sm font-medium text-slate-300 mb-2">Choose Test Scenario</label>
                            <select 
                                id="scenarioSelect" 
                                onchange="loadSelectedScenario()"
                                class="w-full p-2 bg-slate-700/50 border border-slate-600 rounded-lg text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200 text-sm">
                                <option value="">Select a test scenario...</option>
                            </select>
                        </div>
                        
                        <!-- Test Input -->
                        <div>
                            <div class="flex items-center justify-between mb-2">
                                <label class="block text-sm font-medium text-slate-300">Request Data (JSON)</label>
                                <button 
                                    id="generateNewScenariosBtn" 
                                    onclick="regenerateTestScenarios()" 
                                    class="hidden px-2 py-1 text-xs bg-blue-600/20 text-blue-300 rounded border border-blue-500/30 hover:bg-blue-600/30 transition-all duration-200">
                                    🔄 Generate New
                                </button>
                            </div>
                            <textarea 
                                id="previewTestInput" 
                                class="w-full h-24 p-3 bg-slate-700/50 border border-slate-600 rounded-lg text-white placeholder-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200 font-mono text-sm" 
                                placeholder='{
  "example": "data"
}'
                            ></textarea>
                        </div>
                        
                        <!-- Test Controls -->
                        <div class="flex items-center justify-between">
                            <button onclick="runPreviewTest()" 
                                    id="previewRunTestBtn"
                                    class="px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg flex items-center space-x-2">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.828 14.828a4 4 0 01-5.656 0M9 10h1m4 0h1m-6 4h1m4 0h1m6-10V7a3 3 0 11-6 0V4h6zM4 7v10a2 2 0 002 2h12a2 2 0 002-2V7"></path>
                                </svg>
                                <span>Run Test</span>
                            </button>
                            <div class="flex items-center space-x-2">
                                <div id="previewTestStatus" class="w-3 h-3 bg-gray-500 rounded-full"></div>
                                <span id="previewTestStatusText" class="text-sm text-gray-400">Ready</span>
                            </div>
                        </div>
                        
                        <!-- Test Results -->
                        <div id="previewTestResults" class="hidden">
                            <div class="bg-slate-700/50 rounded-lg p-3">
                                <div class="flex items-center justify-between mb-2">
                                    <span class="text-sm font-medium text-slate-300">Response</span>
                                    <span id="previewResponseStatus" class="px-2 py-1 rounded text-xs font-mono"></span>
                                </div>
                                <pre id="previewResponseBody" class="text-xs text-slate-300 font-mono whitespace-pre-wrap overflow-x-auto"></pre>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Action Buttons -->
                    <div id="previewActionButtons" class="hidden pt-4 border-t border-slate-600/50">
                        <div class="flex items-center space-x-3">
                            <button onclick="deployCurrentAPI()" 
                                    id="previewDeployBtn"
                                    class="flex-1 px-4 py-3 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg flex items-center justify-center space-x-2">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"></path>
                                </svg>
                                <span>Deploy API</span>
                            </button>
                            <button onclick="modifyCurrentAPI()" 
                                    id="previewModifyBtn"
                                    class="flex-1 px-4 py-3 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg flex items-center justify-center space-x-2">
                                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                                </svg>
                                <span>Modify API</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }
    
    // Now safely access the elements
    const emptyState = document.getElementById('emptyState');
    const apiPreviewPanel = document.getElementById('apiPreviewPanel');
    
    if (emptyState && apiPreviewPanel) {
        // Show the preview panel and hide empty state
        emptyState.classList.add('hidden');
        apiPreviewPanel.classList.remove('hidden');
    } else {
        console.error('Could not find emptyState or apiPreviewPanel elements');
        return;
    }
    
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
    
    // Debug logging to understand what data we have
    console.log('updateParametersTable called with apiData:', apiData);
    console.log('sample_input:', apiData.sample_input);
    console.log('documentation:', apiData.documentation);
    console.log('curl_example:', apiData.curl_example);
    console.log('openapi_spec:', apiData.openapi_spec);
    
    // Try multiple sources for parameters
    let params = [];
    
    // First, try to extract from OpenAPI spec if available
    if (apiData.openapi_spec) {
        console.log('Trying to extract parameters from OpenAPI spec...');
        params = extractParametersFromOpenAPISpec(apiData.openapi_spec);
        console.log('Parameters from OpenAPI spec:', params);
    }
    
    // If no parameters from OpenAPI spec, try sample_input
    if (params.length === 0 && apiData.sample_input) {
        console.log('Trying to extract parameters from sample_input...');
        params = extractParametersFromSampleInput(apiData.sample_input);
        console.log('Parameters from sample_input:', params);
    }
    
    // If no parameters from sample_input, try documentation
    if (params.length === 0) {
        console.log('Trying to extract parameters from documentation...');
        params = extractParametersFromDocumentation(apiData.documentation);
        console.log('Parameters from documentation:', params);
    }
    
    // If still no parameters, try curl example
    if (params.length === 0 && apiData.curl_example) {
        console.log('Trying to extract parameters from curl example...');
        params = extractParametersFromCurlExample(apiData.curl_example);
        console.log('Parameters from curl example:', params);
    }
    
    // If still no parameters, try to extract from generated code (if available)
    if (params.length === 0 && apiData.api_slug && apiData.user_id) {
        console.log('Trying to extract parameters from generated code...');
        extractParametersFromCode(apiData.user_id, apiData.api_slug).then(codeParams => {
            if (codeParams.length > 0) {
                console.log('Parameters from code analysis:', codeParams);
                // Update the parameters table with code-extracted parameters
                updateParametersTableWithParams(codeParams);
            }
        }).catch(e => {
            console.log('Failed to extract parameters from code:', e);
        });
    }
    
    if (params.length === 0) {
        console.log('No parameters found from any source');
        container.innerHTML = '<div class="text-slate-400 text-sm text-center py-8">No parameters defined</div>';
        return;
    }
    
    console.log('Final parameters to display:', params);
    
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
        // Return empty array instead of generic parameters
        console.log('No documentation provided to extractParametersFromDocumentation');
        return params;
    }
    
    console.log('extractParametersFromDocumentation called with:', documentation);
    
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
    
    // Look for function signature in documentation to extract parameters
    if (params.length === 0) {
        const functionMatch = documentation.match(/def\s+\w+\([^)]*\)/);
        if (functionMatch) {
            const funcSig = functionMatch[0];
            const paramMatch = funcSig.match(/\(([^)]*)\)/);
            if (paramMatch && paramMatch[1].trim()) {
                const paramList = paramMatch[1].split(',').map(p => p.trim());
                paramList.forEach(param => {
                    if (param && param !== 'self' && !param.includes('=')) {
                        const name = param.replace(/:\s*\w+/, '').trim();
                        if (name) {
                            params.push({
                                name: name,
                                type: 'string',
                                required: true,
                                example: `"example ${name}"`
                            });
                        }
                    }
                });
            }
        }
    }
    
    // Look for JSON schema or input format in documentation
    if (params.length === 0) {
        const jsonMatch = documentation.match(/```json\s*\{[^}]*\}/s);
        if (jsonMatch) {
            try {
                const jsonStr = jsonMatch[0].replace(/```json\s*/, '').replace(/```\s*$/, '');
                const jsonObj = JSON.parse(jsonStr);
                Object.keys(jsonObj).forEach(key => {
                    const value = jsonObj[key];
                    let type = 'string';
                    let example = `"${value}"`;
                    
                    if (typeof value === 'number') {
                        type = 'number';
                        example = value.toString();
                    } else if (typeof value === 'boolean') {
                        type = 'boolean';
                        example = value.toString();
                    } else if (Array.isArray(value)) {
                        type = 'array';
                        example = JSON.stringify(value);
                    } else if (typeof value === 'object' && value !== null) {
                        type = 'object';
                        example = JSON.stringify(value);
                    }
                    
                    params.push({
                        name: key,
                        type: type,
                        required: true,
                        example: example
                    });
                });
            } catch (e) {
                // JSON parsing failed, continue without parameters
            }
        }
    }
    
    // Only use very specific fallbacks for very obvious cases
    if (params.length === 0) {
        console.log('No parameters found in documentation, checking for specific patterns...');
        // Only add parameters if the documentation clearly indicates specific input types
        if (doc.includes('pdf') && doc.includes('file')) {
            params.push({name: 'file', type: 'file', required: true, example: 'document.pdf'});
            console.log('Added PDF file parameter');
        } else if (doc.includes('image') && (doc.includes('upload') || doc.includes('file'))) {
            params.push({name: 'image', type: 'file', required: true, example: 'image.jpg'});
            console.log('Added image file parameter');
        } else if (doc.includes('url') && doc.includes('scrape')) {
            params.push({name: 'url', type: 'string', required: true, example: '"https://example.com"'});
            console.log('Added URL parameter');
        }
        // Don't add generic text/data parameters anymore
    }
    
    console.log('extractParametersFromDocumentation returning:', params);
    return params;
}

function extractParametersFromOpenAPISpec(openApiSpec) {
    const params = [];
    
    try {
        // Parse the OpenAPI spec if it's a string
        const spec = typeof openApiSpec === 'string' ? JSON.parse(openApiSpec) : openApiSpec;
        console.log('Parsed OpenAPI spec:', spec);
        
        // Look for paths and their request bodies
        if (spec.paths) {
            for (const [path, pathObj] of Object.entries(spec.paths)) {
                for (const [method, methodObj] of Object.entries(pathObj)) {
                    if (methodObj.requestBody && methodObj.requestBody.content) {
                        const content = methodObj.requestBody.content;
                        
                        // Check for JSON content
                        if (content['application/json'] && content['application/json'].schema) {
                            const schema = content['application/json'].schema;
                            console.log('Found request schema:', schema);
                            
                            if (schema.properties) {
                                for (const [propName, propDef] of Object.entries(schema.properties)) {
                                    let example = propDef.example || getExampleForType(propDef.type);
                                    
                                    params.push({
                                        name: propName,
                                        type: propDef.type || 'string',
                                        required: schema.required ? schema.required.includes(propName) : false,
                                        example: example,
                                        description: propDef.description || ''
                                    });
                                }
                            }
                        }
                    }
                }
            }
        }
    } catch (e) {
        console.log('Failed to parse OpenAPI spec:', e);
    }
    
    return params;
}

function getExampleForType(type) {
    switch (type) {
        case 'string':
            return '"example text"';
        case 'number':
        case 'integer':
            return '123';
        case 'boolean':
            return 'true';
        case 'array':
            return '["item1", "item2"]';
        case 'object':
            return '{"key": "value"}';
        default:
            return '"example"';
    }
}

function extractParametersFromSampleInput(sampleInput) {
    const params = [];
    
    try {
        // Try to parse as JSON
        const jsonData = JSON.parse(sampleInput);
        
        Object.keys(jsonData).forEach(key => {
            const value = jsonData[key];
            let type = 'string';
            let example = `"${value}"`;
            
            if (typeof value === 'number') {
                type = 'number';
                example = value.toString();
            } else if (typeof value === 'boolean') {
                type = 'boolean';
                example = value.toString();
            } else if (Array.isArray(value)) {
                type = 'array';
                example = JSON.stringify(value);
            } else if (typeof value === 'object' && value !== null) {
                type = 'object';
                example = JSON.stringify(value);
            }
            
            params.push({
                name: key,
                type: type,
                required: true,
                example: example
            });
        });
    } catch (e) {
        // If not JSON, try to extract from other formats
        console.log('Sample input is not JSON, trying other extraction methods');
    }
    
    return params;
}

function extractParametersFromCurlExample(curlExample) {
    const params = [];
    
    try {
        // Look for JSON data in curl example
        const jsonMatch = curlExample.match(/-d\s+['"`](.*?)['"`]/s);
        if (jsonMatch) {
            const jsonStr = jsonMatch[1].replace(/\\"/g, '"');
            const jsonData = JSON.parse(jsonStr);
            
            Object.keys(jsonData).forEach(key => {
                const value = jsonData[key];
                let type = 'string';
                let example = `"${value}"`;
                
                if (typeof value === 'number') {
                    type = 'number';
                    example = value.toString();
                } else if (typeof value === 'boolean') {
                    type = 'boolean';
                    example = value.toString();
                } else if (Array.isArray(value)) {
                    type = 'array';
                    example = JSON.stringify(value);
                } else if (typeof value === 'object' && value !== null) {
                    type = 'object';
                    example = JSON.stringify(value);
                }
                
                params.push({
                    name: key,
                    type: type,
                    required: true,
                    example: example
                });
            });
        }
    } catch (e) {
        console.log('Could not extract parameters from curl example');
    }
    
    return params;
}

async function extractParametersFromCode(userId, apiSlug) {
    try {
        // Fetch the generated code
        const response = await fetch(`/api/${userId}/${apiSlug}/code`);
        if (!response.ok) {
            throw new Error('Failed to fetch API code');
        }
        
        const codeData = await response.json();
        const code = codeData.code;
        
        const params = [];
        
        // Look for input_data access patterns in the code
        const inputPatterns = [
            /input_data\[['"](\w+)['"]\]/g,
            /input_data\.get\(['"](\w+)['"]\)/g,
            /data\[['"](\w+)['"]\]/g,
            /data\.get\(['"](\w+)['"]\)/g,
            /request_data\[['"](\w+)['"]\]/g,
            /request_data\.get\(['"](\w+)['"]\)/g
        ];
        
        const foundParams = new Set();
        
        for (const pattern of inputPatterns) {
            let match;
            while ((match = pattern.exec(code)) !== null) {
                foundParams.add(match[1]);
            }
        }
        
        // Convert to parameter objects
        foundParams.forEach(paramName => {
            params.push({
                name: paramName,
                type: 'string', // Default type, could be enhanced with more analysis
                required: true,
                example: `"example ${paramName}"`
            });
        });
        
        return params;
    } catch (e) {
        console.log('Error extracting parameters from code:', e);
        return [];
    }
}

function updateParametersTableWithParams(params) {
    const container = document.getElementById('parametersTable');
    
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
                console.log('Test data generation response:', data);
                console.log('Test scenarios received:', JSON.stringify(data.test_scenarios, null, 2));
                console.log('First scenario data:', JSON.stringify(data.test_scenarios[0], null, 2));
                
                // Debug: Check what we're actually setting in the text area
                console.log('About to set testInput.value to:', JSON.stringify(data.test_scenarios[0].data, null, 2));
                
                if (data.success && data.test_scenarios && data.test_scenarios.length > 0) {
                    // Store all scenarios globally
                    window.currentTestScenarios = data.test_scenarios;
                    
                    // Show the scenario selector if we have multiple scenarios
                    const scenarioSelector = document.getElementById('testScenarioSelector');
                    const scenarioSelect = document.getElementById('scenarioSelect');
                    const generateBtn = document.getElementById('generateNewScenariosBtn');
                    
                    if (data.test_scenarios.length > 1) {
                        // Show the selector
                        scenarioSelector.classList.remove('hidden');
                        generateBtn.classList.remove('hidden');
                        
                        // Populate the dropdown
                        scenarioSelect.innerHTML = '<option value="">Select a test scenario...</option>';
                        data.test_scenarios.forEach((scenario, index) => {
                            const option = document.createElement('option');
                            option.value = index;
                            option.textContent = `${index + 1}. ${scenario.scenario}`;
                            scenarioSelect.appendChild(option);
                        });
                        
                        // Auto-select the first scenario
                        scenarioSelect.value = '0';
                    } else {
                        // Hide the selector for single scenarios
                        scenarioSelector.classList.add('hidden');
                        generateBtn.classList.remove('hidden');
                    }
                    
                    // Load the first scenario by default
                    const firstScenario = data.test_scenarios[0];
                    testInput.value = JSON.stringify(firstScenario.data, null, 2);
                    
                    // Store for backward compatibility
                    testInput.setAttribute('data-ai-scenarios', JSON.stringify(data.test_scenarios));
                    testInput.setAttribute('data-sample-json', JSON.stringify(firstScenario.data, null, 2));
                    
                    // Update indicator to show success
                    loadingIndicator.className = 'sample-data-indicator text-xs text-green-400 mb-2 flex items-center space-x-2';
                    loadingIndicator.innerHTML = `
                        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                        </svg>
                        <span>AI-generated test data loaded (${data.test_scenarios.length} scenarios available)</span>
                    `;
                    
                    console.log('Smart test data generated successfully:', data.test_scenarios.length, 'scenarios');
                    return;
                } else {
                    console.warn('AI test data generation returned no scenarios, falling back to documentation extraction');
                    console.log('Data received:', data);
                }
            } else {
                console.warn('AI test data generation failed, falling back to documentation extraction');
                console.log('Response status:', response.status, 'Response text:', await response.text());
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
    
    // Add initial test start message
    addStreamingMessage('🧪 Starting API test...', 'step_start');
    await new Promise(resolve => setTimeout(resolve, 2400));
    
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
        } else {
        }
               
        // Call the backend test endpoint
        const response = await fetch('/test-api', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(testData)
        });


        // Add validation message
        addStreamingMessage('🔍 Validating API endpoint and test data...', 'ai_processing');
        await new Promise(resolve => setTimeout(resolve, 1200));


        // Add message for API call
        addStreamingMessage(' Executing API test request...', 'step_start');
        await new Promise(resolve => setTimeout(resolve, 2400));
        
        addStreamingMessage('📊 Processing test results...', 'ai_processing');
        await new Promise(resolve => setTimeout(resolve, 2400));
        
        const testResult = await response.json();
        
        // Show results
        results.classList.remove('hidden');
        
        // Check if the API actually succeeded - look for errors in response_data
        const responseData = testResult.response_data || testResult;
        const hasError = responseData.error || 
                        responseData.message === 'failed' || 
                        (responseData.status && responseData.status !== 'success') ||
                        !testResult.success;
        
        // Update status
        if (testResult.success && !hasError) {
            // Add success message
            addStreamingMessage('🎉 **Test completed successfully!** API is working correctly.', 'step_complete');
            await new Promise(resolve => setTimeout(resolve, 800));
            
            status.className = 'w-3 h-3 bg-green-500 rounded-full';
            statusText.textContent = 'Success';
            statusText.className = 'text-sm text-green-400';
            
            responseStatus.textContent = '200 OK';
            responseStatus.className = 'px-2 py-1 bg-green-600/20 text-green-300 rounded text-xs font-mono';
            
            // Handle binary data specially
            if (responseData.result_type === 'binary') {
                responseBody.innerHTML = `
                    <div class="space-y-2">
                        <div class="text-blue-300">
                            <div class="text-sm font-semibold mb-2">📦 Binary Data Response</div>
                            <div class="text-xs space-y-1">
                                <div>Type: <span class="text-green-300">${responseData.content_type || 'application/octet-stream'}</span></div>
                                <div>Size: <span class="text-green-300">${responseData.size_bytes} bytes</span></div>
                                <div class="text-slate-400">${responseData.message || 'Binary data returned successfully'}</div>
                            </div>
                        </div>
                        ${responseData.data_base64 && responseData.data_base64.startsWith('iVBORw') ? `
                            <div class="mt-3">
                                <div class="text-xs text-slate-400 mb-2">Preview (PNG Image):</div>
                                <img src="data:image/png;base64,${responseData.data_base64}" 
                                     alt="API Response Image" 
                                     class="max-w-full h-auto rounded border border-slate-600"
                                     style="max-height: 300px;">
                            </div>
                        ` : ''}
                        <div class="mt-2">
                            <button onclick="downloadBinaryResponse('${responseData.data_base64}', '${responseData.content_type}')" 
                                    class="px-3 py-1 bg-blue-600/20 text-blue-300 border border-blue-500/30 rounded text-xs hover:bg-blue-600/30 transition-all duration-200">
                                💾 Download Binary Data
                            </button>
                        </div>
                    </div>
                `;
            } else {
                responseBody.textContent = JSON.stringify(responseData, null, 2);
            }
            
            // Show Deploy and Modify buttons after successful test
            const actionButtons = document.getElementById('previewActionButtons');
            if (actionButtons) {
                actionButtons.classList.remove('hidden');
            }
            
            addStreamingMessage('✨ Your API is ready for deployment or further modifications!', 'default');
        } else {
            // Add failure message
            addStreamingMessage('❌ **Test failed.** Debugging the issue...', 'step_error');
            await new Promise(resolve => setTimeout(resolve, 600));
            
            status.className = 'w-3 h-3 bg-red-500 rounded-full';
            statusText.textContent = 'Failed';
            statusText.className = 'text-sm text-red-400';
            
            responseStatus.textContent = 'Error';
            responseStatus.className = 'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';
            
            // Extract error message from response
            const errorMessage = responseData.error || testResult.error || 'Test failed';
            
            // Show the full response with error highlighted
            responseBody.innerHTML = `
                <div class="text-red-300 mb-3">
                    <div class="text-sm font-semibold mb-2 text-red-400">⚠️ API Execution Failed</div>
                    <div class="text-xs bg-red-900/20 border border-red-500/30 rounded p-3 mb-3">
                        <div class="font-semibold mb-1">Error:</div>
                        <div class="text-red-200">${errorMessage}</div>
                    </div>
                    <div class="mb-3">
                        <button onclick="runPreviewTest()" 
                                class="px-3 py-1 bg-red-600/20 text-red-300 border border-red-500/30 rounded text-xs hover:bg-red-600/30 transition-all duration-200">
                            🔄 Retry Test
                        </button>
                    </div>
                    <details class="text-left">
                        <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-300">Full Response</summary>
                        <pre class="text-xs text-slate-300 font-mono bg-slate-800/50 p-2 rounded border-l-2 border-red-500/50 mt-1 overflow-x-auto">${JSON.stringify(responseData, null, 2)}</pre>
                    </details>
                </div>
            `;
            
            addStreamingMessage('🔧 Please try again', 'default');
        }
        
    } catch (error) {
        // Add error message
        addStreamingMessage('💥 **Unexpected error occurred** during testing.', 'step_error');
        await new Promise(resolve => setTimeout(resolve, 400));
        
        results.classList.remove('hidden');
        
        status.className = 'w-3 h-3 bg-red-500 rounded-full';
        statusText.textContent = 'Error';
        statusText.className = 'text-sm text-red-400';
        
        responseStatus.textContent = 'Error';
        responseStatus.className = 'px-2 py-1 bg-red-600/20 text-red-300 rounded text-xs font-mono';
        
        // Show user-friendly error message instead of raw error
        responseBody.innerHTML = `
            <div class="text-red-300 text-center py-2">
                <div class="text-sm mb-2">⚠️ Test failed - please try again</div>
                <div class="mb-2">
                    <button onclick="runPreviewTest()" 
                            class="px-3 py-1 bg-red-600/20 text-red-300 border border-red-500/30 rounded text-xs hover:bg-red-600/30 transition-all duration-200">
                        🔄 Retry
                    </button>
                </div>
                <details class="text-left">
                    <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-300">Debug info</summary>
                    <div class="text-xs text-slate-500 font-mono bg-slate-800/50 p-2 rounded border-l-2 border-red-500/50 mt-1">
                        Error: ${error.message}
                    </div>
                </details>
            </div>
        `;
        
        addStreamingMessage('🔧 Please check your connection and try again, or contact support if the issue persists.', 'default');
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
        'previewActionButtons',
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
    // Show API-specific elements (parameters, response, test playground, code snippets)
    // Note: previewActionButtons stays hidden until first successful test
    const apiElements = [
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
        proposalSection.className = 'space-y-4';
        
        // Insert after the API endpoint section
        const apiInfoSection = document.querySelector('#apiPreviewPanel .bg-blue-900\\/20');
        if (apiInfoSection) {
            apiInfoSection.parentNode.insertBefore(proposalSection, apiInfoSection.nextSibling);
        }
    }
    
    // Generate a unique ID for this proposal and store the data
    const proposalId = `proposal-${Date.now()}`;
    proposalDataStore.set(proposalId, {
        originalPrompt: originalPrompt,
        userId: userId,
        analysis: analysis
    });
    
    // Create functionality HTML
    const functionalityHtml = proposal.functionality ? 
        proposal.functionality.map(func => `<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-slate-300">${func}</span></li>`).join('') : 
        '<li class="flex items-start space-x-2"><span class="text-blue-400">•</span><span class="text-slate-300">Custom API functionality</span></li>';
    
    proposalSection.innerHTML = `
        <!-- Key Features -->
        <div class="bg-blue-900/20 border border-blue-500/30 rounded-xl p-4 w-full">
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
        <div class="w-full space-y-4">
            ${proposal.input_format ? `
            <div class="bg-green-900/20 border border-green-500/30 rounded-xl p-4 w-full">
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
            <div class="bg-purple-900/20 border border-purple-500/30 rounded-xl p-4 w-full">
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
        <div id="confirmation-buttons-${Date.now()}" class="bg-green-900/20 border border-green-500/30 rounded-xl p-4 w-full">
            <h4 class="font-semibold text-white mb-4 flex items-center space-x-2">
                <span class="text-green-400">✅</span>
                <span>Ready to build this API?</span>
            </h4>
            <div class="flex flex-wrap gap-3">
                <button data-action="build" data-proposal-id="${proposalId}"
                        class="proposal-action-btn px-4 py-2 bg-gradient-to-r from-green-600 to-emerald-600 hover:from-green-700 hover:to-emerald-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                     Build It!
                </button>
                <button data-action="modify" data-proposal-id="${proposalId}"
                        class="proposal-action-btn px-4 py-2 bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
                    ✏️ Modify
                </button>
                <button data-action="cancel"
                        class="proposal-action-btn px-4 py-2 bg-gradient-to-r from-gray-600 to-gray-700 hover:from-gray-700 hover:to-gray-800 text-white rounded-lg font-medium transition-all duration-200 transform hover:scale-105 active:scale-95 shadow-lg">
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
        exampleResponse = 'No example response available';
    }
    
    container.textContent = JSON.stringify(exampleResponse, null, 2);
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    console.log('🎉 [v2.0] Chat.js loaded - NEW VERSION with proposal data store');
    console.log('🎉 [v2.0] ProposalDataStore initialized:', proposalDataStore);
    
    // Focus on input
    document.getElementById('chatInput').focus();
    
    // Initialize character counter
    handleInputChange();
    
    // Adjust chat height on load and resize
    adjustChatHeight();
    window.addEventListener('resize', adjustChatHeight);
    
    // Ensure scroll to bottom button starts hidden
    document.getElementById('scrollToBottomBtn').classList.add('hidden');
    
    // Event delegation for proposal action buttons
    document.addEventListener('click', function(event) {
        const button = event.target.closest('.proposal-action-btn');
        if (!button) {
            return;
        }
        
        console.log('🎯 [v2.0] Proposal action button clicked!');
        
        const action = button.getAttribute('data-action');
        const proposalId = button.getAttribute('data-proposal-id');
        
        console.log('🎯 [v2.0] Action:', action, 'Proposal ID:', proposalId);
        console.log('🎯 [v2.0] ProposalDataStore size:', proposalDataStore.size);
        
        // Retrieve stored proposal data
        let proposalData = null;
        if (proposalId) {
            proposalData = proposalDataStore.get(proposalId);
            console.log('🎯 [v2.0] Retrieved proposal data:', proposalData ? 'Found' : 'NOT FOUND');
            if (proposalData) {
                console.log('🎯 [v2.0] Prompt length:', proposalData.originalPrompt?.length);
            }
        }
        
        if (!proposalData && action !== 'cancel') {
            console.error('❌ [v2.0] Proposal data not found for ID:', proposalId);
            console.error('❌ [v2.0] Available IDs in store:', Array.from(proposalDataStore.keys()));
            return;
        }
        
        const prompt = proposalData?.originalPrompt;
        const userId = proposalData?.userId;
        
        
        switch(action) {
            case 'build':
                startAPIBuild(prompt, userId, button);
                break;
            case 'modify':
                console.log('✏️ [v2.0] Requesting modifications');
                requestModifications(prompt, userId);
                break;
            case 'cancel':
                console.log('❌ [v2.0] Cancelling API build');
                cancelAPIBuild();
                break;
            default:
                console.warn('⚠️ [v2.0] Unknown proposal action:', action);
        }
    });
}); 

// Test scenario management functions
function loadSelectedScenario() {
    const scenarioSelect = document.getElementById('scenarioSelect');
    const testInput = document.getElementById('previewTestInput');
    const selectedIndex = scenarioSelect.value;
    
    if (selectedIndex !== '' && window.currentTestScenarios && window.currentTestScenarios[selectedIndex]) {
        const selectedScenario = window.currentTestScenarios[selectedIndex];
        testInput.value = JSON.stringify(selectedScenario.data, null, 2);
        console.log('Loaded test scenario:', selectedScenario.scenario);
    }
}

async function regenerateTestScenarios() {
    if (!currentAPISpec || !currentAPISpec.api_slug || !currentAPISpec.user_id) {
        console.warn('Cannot regenerate scenarios: missing API data');
        return;
    }
    
    console.log('Regenerating test scenarios...');
    
    // Clear current scenarios
    window.currentTestScenarios = null;
    
    // Also clear the test input field to prevent showing old data
    const testInput = document.getElementById('previewTestInput');
    if (testInput) {
        testInput.value = '';
    }
    const scenarioSelector = document.getElementById('testScenarioSelector');
    const generateBtn = document.getElementById('generateNewScenariosBtn');
    scenarioSelector.classList.add('hidden');
    
    // Show loading state on button
    const originalText = generateBtn.textContent;
    generateBtn.textContent = '🔄 Generating...';
    generateBtn.disabled = true;
    
    try {
        // Call the updateTestInput function to regenerate scenarios
        await updateTestInput(currentAPISpec);
    } catch (error) {
        console.error('Error regenerating test scenarios:', error);
    } finally {
        // Restore button state
        generateBtn.textContent = originalText;
        generateBtn.disabled = false;
    }
}

// ===========================
// MODE SWITCHING FUNCTIONS
// ===========================

/**
 * Switch to Generation Mode
 */
function switchToGenerationMode() {
    console.log('Switching to Generation Mode');
    
    // Clear ALL chat messages including welcome message
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
        chatMessages.innerHTML = '';
    }
    
    // Reset conversation state
    currentConversation = [];
    conversationState = null;
    currentProposalId = null;
    currentProposal = null;
    
    // Update UI
    const genBtn = document.getElementById('generationModeBtn');
    const modBtn = document.getElementById('modificationModeBtn');
    const apiSelector = document.getElementById('apiSelectorContainer');
    
    // Update button styles
    genBtn.className = 'px-3 py-1.5 bg-gradient-to-r from-blue-600 to-purple-600 text-white rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
    modBtn.className = 'px-3 py-1.5 bg-slate-700/50 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
    
    // Hide API selector
    if (apiSelector) {
        apiSelector.classList.add('hidden');
    }
    
    // Remove modification mode banner if exists
    const banner = document.getElementById('modificationModeBanner');
    if (banner) {
        banner.remove();
    }
    
    // Reset state
    isModificationMode = false;
    currentApiData = null;
    
    // Update placeholder
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.placeholder = "Describe your API requirements... (e.g., 'Create an API that extracts text from PDF files')";
        chatInput.disabled = false;
    }
    
    // Reset preview panel
    document.getElementById('emptyState').classList.remove('hidden');
    document.getElementById('apiPreviewPanel').classList.add('hidden');
    
    // Show generation mode welcome message
    showGenerationWelcomeMessage();
    
    console.log('✅ Switched to Generation Mode');
}

/**
 * Switch to Modification Mode
 */
async function switchToModificationMode() {
    console.log('Switching to Modification Mode');
    
    // Clear ALL chat messages including welcome message
    const chatMessages = document.getElementById('chatMessages');
    if (chatMessages) {
        chatMessages.innerHTML = '';
    }
    
    // Reset conversation state
    currentConversation = [];
    conversationState = null;
    currentProposalId = null;
    currentProposal = null;
    
    // Update UI
    const genBtn = document.getElementById('generationModeBtn');
    const modBtn = document.getElementById('modificationModeBtn');
    const apiSelector = document.getElementById('apiSelectorContainer');
    
    // Update button styles
    genBtn.className = 'px-3 py-1.5 bg-slate-700/50 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
    modBtn.className = 'px-3 py-1.5 bg-gradient-to-r from-orange-600 to-amber-600 text-white rounded-lg text-xs font-medium transition-all duration-200 flex items-center space-x-1.5';
    
    // Show API selector
    if (apiSelector) {
        apiSelector.classList.remove('hidden');
    }
    
    // Load user's APIs
    await loadUserAPIsForModification();
    
    // Reset preview panel to empty state
    document.getElementById('emptyState').classList.remove('hidden');
    document.getElementById('apiPreviewPanel').classList.add('hidden');
    
    // Update placeholder
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.placeholder = "First, select an API above. Then describe the changes you'd like to make...";
        chatInput.disabled = true; // Disable until API is selected
    }
    
    // Show a simple modification mode message
    addMessage('assistant', `
        <div class="flex items-start space-x-3">
            <div class="w-8 h-8 bg-gradient-to-r from-orange-500 to-amber-600 rounded-full flex items-center justify-center flex-shrink-0">
                <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
                </svg>
            </div>
            <div class="flex-1">
                <div class="mb-4">
                    <div class="flex items-center space-x-2 mb-2">
                        <span class="status-badge bg-orange-900/50 text-orange-400 border-orange-500/30">Modification Mode</span>
                        <h3 class="font-semibold text-white">Modify Your Existing APIs</h3>
                    </div>
                    <p class="text-slate-300 mb-4">Select an API from the dropdown above to get started. Then describe the changes you'd like to make.</p>
                </div>
                <div class="bg-orange-900/20 border border-orange-500/30 rounded-lg p-4">
                    <p class="text-orange-200 text-sm">
                        <strong>💡 Tip:</strong> You can add features, change behavior, remove functionality, or fix issues. Just describe what you want in plain English!
                    </p>
                </div>
            </div>
        </div>
    `, { skipDelay: true });
    
    console.log('✅ Switched to Modification Mode (awaiting API selection)');
}

/**
 * Load user's APIs for the modification selector
 */
async function loadUserAPIsForModification() {
    const apiSelector = document.getElementById('apiSelector');
    
    if (!apiSelector) return;
    
    try {
        // Get current user ID
        const userId = currentUser ? currentUser.id : null;
        
        if (!userId) {
            apiSelector.innerHTML = '<option value="">Please log in to see your APIs</option>';
            return;
        }
        
        // Fetch user's APIs
        const response = await fetch(`/api/${userId}`);
        
        if (!response.ok) {
            throw new Error('Failed to load APIs');
        }
        
        const data = await response.json();
        const apis = data.apis || [];
        
        if (!apis || apis.length === 0) {
            apiSelector.innerHTML = '<option value="">No APIs found. Generate one first!</option>';
            return;
        }
        
        // Populate selector with better formatting
        apiSelector.innerHTML = '<option value="">📋 Select an API to modify...</option>';
        
        // Sort APIs by last modified (most recent first)
        const sortedApis = apis.sort((a, b) => {
            const dateA = new Date(a.last_modified || a.created_at || 0);
            const dateB = new Date(b.last_modified || b.created_at || 0);
            return dateB - dateA;
        });
        
        sortedApis.forEach(api => {
            const option = document.createElement('option');
            option.value = api.api_slug;
            option.dataset.userId = userId; // Use the userId from request since it's the same
            
            // Format the display name with emoji indicators
            const displayName = deriveApiDisplayName(api);
            const statusEmoji = api.code_available ? '✓' : '○';
            const dateStr = formatRelativeDate(api.last_modified || api.created_at);
            
            // Show both human-friendly name and slug so users can disambiguate similarly-named APIs.
            option.textContent = (displayName && displayName === api.api_slug)
                ? `${statusEmoji} ${api.api_slug} • ${dateStr}`
                : `${statusEmoji} ${displayName} (${api.api_slug}) • ${dateStr}`;
            apiSelector.appendChild(option);
        });
        
        console.log(`✅ Loaded ${apis.length} APIs for modification`);
        
    } catch (error) {
        console.error('Error loading APIs:', error);
        apiSelector.innerHTML = '<option value="">Error loading APIs. Please try again.</option>';
    }
}

/**
 * Format relative date for API selector
 */
function formatRelativeDate(dateString) {
    if (!dateString) return 'Unknown';
    
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);
    
    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
    
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

/**
 * Handle API selection in modification mode
 */
async function handleApiSelection() {
    const apiSelector = document.getElementById('apiSelector');
    const selectedSlug = apiSelector.value;
    
    if (!selectedSlug) {
        // No API selected, disable input
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.disabled = true;
            chatInput.placeholder = "First, select an API above. Then describe the changes you'd like to make...";
        }
        return;
    }
    
    // Get user ID from selected option
    const selectedOption = apiSelector.options[apiSelector.selectedIndex];
    const userId = selectedOption.dataset.userId;
    
    console.log('API selected for modification:', selectedSlug, 'User:', userId);
    
    try {
        // Load API details
        const response = await fetch(`/api/${userId}/${selectedSlug}/apidetails`);
        
        if (!response.ok) {
            throw new Error('Failed to load API details');
        }
        
        currentApiData = await response.json();
        isModificationMode = true;
        
        // Show modification mode UI
        showModificationModeUI();
        
        // Load API details in preview
        loadAPIDetailsInPreview(currentApiData);
        
        // Enable chat input
        const chatInput = document.getElementById('chatInput');
        if (chatInput) {
            chatInput.disabled = false;
            chatInput.placeholder = "Describe the changes you'd like to make to this API...";
            chatInput.focus();
        }
        
        // Add welcome message
        addModificationWelcomeMessage(currentApiData);
        
        console.log('✅ API loaded for modification');
        
    } catch (error) {
        console.error('Error loading API for modification:', error);
        alert('Failed to load API details. Please try again.');
    }
}

// ===========================
// MODIFICATION MODE FUNCTIONS
// ===========================

/**
 * Show modification mode UI indicator (deprecated - using top bar instead)
 */
function showModificationModeUI() {
    // Update input placeholder
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.placeholder = "Describe the changes you'd like to make to your API... (e.g., 'Add email validation' or 'Change response format to XML')";
    }
    
    console.log('✅ Modification mode UI activated');
}

/**
 * Show generation mode welcome message
 */
function showGenerationWelcomeMessage() {
    const message = `
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
                            <h3 class="font-semibold text-white">Welcome to AI API Generator!</h3>
                        </div>
                        <p class="text-slate-300 mb-4">I'm here to help you create powerful APIs using natural language. Here's how it works:</p>
                    </div>
                    
                    <div class="grid md:grid-cols-2 gap-4 text-sm">
                        <div class="flex items-start space-x-3">
                            <div class="w-8 h-8 bg-blue-500/20 rounded-lg flex items-center justify-center flex-shrink-0">
                                <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path>
                                </svg>
                            </div>
                            <div>
                                <h4 class="font-medium text-white mb-1">Describe Your API</h4>
                                <p class="text-slate-400">Tell me what you want your API to do in plain English</p>
                            </div>
                        </div>
                        
                        <div class="flex items-start space-x-3">
                            <div class="w-8 h-8 bg-green-500/20 rounded-lg flex items-center justify-center flex-shrink-0">
                                <svg class="w-4 h-4 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                                </svg>
                            </div>
                            <div>
                                <h4 class="font-medium text-white mb-1">AI Generation</h4>
                                <p class="text-slate-400">I'll generate the code, documentation, and endpoint</p>
                            </div>
                        </div>
                        
                        <div class="flex items-start space-x-3">
                            <div class="w-8 h-8 bg-purple-500/20 rounded-lg flex items-center justify-center flex-shrink-0">
                                <svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"></path>
                                </svg>
                            </div>
                            <div>
                                <h4 class="font-medium text-white mb-1">Test & Deploy</h4>
                                <p class="text-slate-400">Test your API instantly and deploy it live</p>
                            </div>
                        </div>
                        
                        <div class="flex items-start space-x-3">
                            <div class="w-8 h-8 bg-yellow-500/20 rounded-lg flex items-center justify-center flex-shrink-0">
                                <svg class="w-4 h-4 text-yellow-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"></path>
                                </svg>
                            </div>
                            <div>
                                <h4 class="font-medium text-white mb-1">Save & Manage</h4>
                                <p class="text-slate-400">Save your APIs and manage them from your profile</p>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    addMessage('assistant', message, { skipDelay: true });
    console.log('✅ Showed generation welcome message');
}

/**
 * Show modification mode welcome message (before API selection)
 */
function showModificationWelcomeMessage() {
    const message = `
        <div class="message-animation">
            <div class="flex items-start space-x-3 max-w-4xl">
                <div class="w-8 h-8 bg-gradient-to-r from-orange-500 to-amber-600 rounded-full flex items-center justify-center flex-shrink-0">
                    <svg class="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>
                    </svg>
                </div>
                <div class="glass-card rounded-2xl p-6 flex-1">
                    <div class="mb-4">
                        <div class="flex items-center space-x-2 mb-2">
                            <span class="status-badge bg-orange-900/50 text-orange-400 border-orange-500/30">Modification Mode</span>
                            <h3 class="font-semibold text-white">Modify Your Existing APIs</h3>
                        </div>
                        <p class="text-slate-300 mb-4">Select an API from the dropdown above to get started. Then describe the changes you'd like to make.</p>
                    </div>
                    
                    <div class="bg-orange-900/20 border border-orange-500/30 rounded-lg p-4">
                        <p class="text-orange-200 text-sm">
                            <strong>💡 Tip:</strong> You can add features, change behavior, remove functionality, or fix issues. Just describe what you want in plain English!
                        </p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    addMessage('assistant', message, { skipDelay: true });
    console.log('✅ Showed modification welcome message');
}

/**
 * Add a modification-specific welcome message (after API selection)
 */
function addModificationWelcomeMessage(apiData) {
    const apiName = apiData.api_name || apiData.api_slug || 'Unknown API';
    
    const message = `
        <div class="glass-card rounded-2xl p-6 flex-1">
            <div class="flex items-center space-x-2 mb-3">
                <span class="status-badge bg-orange-900/50 text-orange-400 border-orange-500/30">Modification Mode</span>
                <h3 class="font-semibold text-white">Ready to modify <span class="text-orange-400">${apiName}</span></h3>
            </div>
            
            <p class="text-slate-300 text-sm mb-4">Describe the changes you'd like to make. For example:</p>
            
            <div class="grid md:grid-cols-2 gap-2 text-xs">
                <div class="flex items-start space-x-2 text-slate-400">
                    <span class="text-blue-400">•</span>
                    <span>"Add email validation to the input"</span>
                </div>
                <div class="flex items-start space-x-2 text-slate-400">
                    <span class="text-purple-400">•</span>
                    <span>"Change response format to include timestamps"</span>
                </div>
                <div class="flex items-start space-x-2 text-slate-400">
                    <span class="text-green-400">•</span>
                    <span>"Remove the debug logging"</span>
                </div>
                <div class="flex items-start space-x-2 text-slate-400">
                    <span class="text-amber-400">•</span>
                    <span>"Add error handling for edge cases"</span>
                </div>
            </div>
        </div>
    `;
    
    addMessage('assistant', message);
    console.log('✅ Added modification welcome message');
}

/**
 * Load API details into the preview panel
 */
function loadAPIDetailsInPreview(apiData) {
    // Show the preview panel
    document.getElementById('emptyState').classList.add('hidden');
    document.getElementById('apiPreviewPanel').classList.remove('hidden');
    
    // Populate basic info
    const apiName = apiData.api_name || apiData.api_slug || 'Unknown API';
    const endpoint = apiData.endpoint_url || 'Not available';
    const description = extractDescriptionFromPrompt(apiData.prompt) || 'No description available';
    
    // Update endpoint display
    document.getElementById('apiEndpoint').textContent = endpoint;
    document.getElementById('apiDescription').textContent = description;
    document.getElementById('apiMethod').textContent = 'POST';
    
    // Try to parse and display parameters from prompt or documentation
    try {
        if (apiData.prompt) {
            extractAndDisplayParametersFromPrompt(apiData.prompt);
        }
    } catch (error) {
        console.warn('Could not parse parameters:', error);
        const parametersTable = document.getElementById('parametersTable');
        if (parametersTable) {
            parametersTable.innerHTML = '<div class="text-slate-400 text-sm text-center py-4">Parameters will be shown here once analyzed</div>';
        }
    }
    
    // Update example response section with better formatting
    const exampleResponse = document.getElementById('exampleResponse');
    if (exampleResponse) {
        // Try to extract example from documentation or create a generic one
        const exampleData = extractExampleFromPrompt(apiData.prompt) || {
            success: true,
            message: "API response will be shown here",
            data: "..."
        };
        exampleResponse.textContent = JSON.stringify(exampleData, null, 2);
    }
    
    // Hide test playground action buttons in modification mode
    const actionButtons = document.getElementById('previewActionButtons');
    if (actionButtons) {
        actionButtons.classList.add('hidden');
    }
    
    console.log('✅ Loaded API details in preview panel');
}

/**
 * Exit modification mode and return to API details or profile
 */
function exitModificationMode() {
    if (currentApiData && currentApiData.user_id && currentApiData.api_slug) {
        // Return to API details page
        window.location.href = `/api/${currentApiData.user_id}/${currentApiData.api_slug}/details`;
    } else {
        // Return to profile
        window.location.href = '/profile';
    }
}

/**
 * Extract description from prompt (helper function if not already present)
 */
function extractDescriptionFromPrompt(promptText) {
    if (!promptText || typeof promptText !== 'string') return 'No description available';
    
    // Try to extract description from structured prompt
    const descMatch = promptText.match(/Description:\s*([^\n]+(?:\n(?!\s*(?:Functionality:|Endpoints:|Input Format:|Output Format:|API Name:))[^\n]*)*)/i);
    if (descMatch && descMatch[1]) {
        let description = descMatch[1].trim();
        description = description.replace(/^\s*(API Name:|Name:|Functionality:).*$/gmi, '');
        description = description.replace(/\n\s*(Functionality:|Endpoints:|Input Format:|Output Format:).*/i, '');
        return description.trim();
    }
    
    // If no structured format, return first reasonable line
    const lines = promptText.split('\n').filter(l => l.trim().length > 10);
    if (lines.length > 0) {
        return lines[0].substring(0, 200);
    }
    
    return promptText.substring(0, 200);
}

/**
 * Extract API name from a prompt (mirrors logic in templates/profile.html).
 */
function extractAPINameFromPrompt(promptText, fallbackName) {
    if (!promptText || typeof promptText !== 'string') return fallbackName;
    
    // Pattern: "API Name: ..." or "Name: ..."
    const nameMatch = promptText.match(/(?:API Name|Name):\s*([^\n]+)/i);
    if (nameMatch && nameMatch[1]) {
        return nameMatch[1].trim();
    }
    
    // Pattern: prompt starts with name, then "Description:"
    const inlineMatch = promptText.match(/^([^\n:]+?)(?:\s+Description:)/i);
    if (inlineMatch && inlineMatch[1]) {
        return inlineMatch[1].trim();
    }
    
    return fallbackName;
}

/**
 * Decide the API name to send to the backend for generation.
 * This value is persisted as `api_name` in MongoDB.
 */
function getApiNameForGeneration(promptText) {
    // Best source: proposal model-generated name
    const proposalName = currentProposal?.proposal?.api_name;
    if (proposalName && typeof proposalName === 'string' && proposalName.trim()) {
        return proposalName.trim();
    }
    
    // Fallback: if user used a structured prompt format
    const extracted = extractAPINameFromPrompt(promptText, null);
    if (extracted && typeof extracted === 'string' && extracted.trim()) {
        return extracted.trim();
    }
    
    // Allow backend to auto-generate if absent
    return null;
}

/**
 * Derive a human-friendly API display name for UI lists.
 * If the stored `api_name` looks like a slug, attempt to extract a nicer name from `api.prompt`.
 */
function deriveApiDisplayName(api) {
    const slug = api?.api_slug || '';
    const storedName = api?.api_name || '';
    const extracted = extractAPINameFromPrompt(api?.prompt, null);
    
    const looksAutoSlug =
        !storedName ||
        storedName === slug ||
        /^api[-_]\d+$/i.test(storedName) ||
        /^api[_-]\d{8}(_\d{6})?$/i.test(storedName);
    
    if (looksAutoSlug && extracted && extracted !== slug) {
        return extracted;
    }
    
    return storedName || slug || 'Unknown API';
}

/**
 * Extract and display parameters from prompt
 */
function extractAndDisplayParametersFromPrompt(prompt) {
    const parametersTable = document.getElementById('parametersTable');
    if (!parametersTable) return;
    
    // Try to extract input format or parameters from prompt
    const inputMatch = prompt.match(/Input Format:?\s*(.+?)(?=\n\s*(?:Output|Functionality|Endpoints|$))/is);
    
    if (inputMatch && inputMatch[1]) {
        const inputText = inputMatch[1].trim();
        
        // Try to parse JSON structure
        const jsonMatch = inputText.match(/\{[\s\S]*?\}/);
        if (jsonMatch) {
            try {
                const inputStructure = JSON.parse(jsonMatch[0]);
                const params = Object.entries(inputStructure).map(([key, value]) => ({
                    name: key,
                    type: typeof value,
                    required: true,
                    example: JSON.stringify(value)
                }));
                
                displayParametersTable(params);
                return;
            } catch (e) {
                console.warn('Could not parse JSON from prompt:', e);
            }
        }
        
        // Fallback: show the input format as text
        parametersTable.innerHTML = `
            <div class="text-slate-300 text-sm p-3 bg-slate-800/30 rounded">
                <div class="font-medium mb-2">Input Format:</div>
                <pre class="text-xs text-slate-400">${inputText}</pre>
            </div>
        `;
    } else {
        parametersTable.innerHTML = '<div class="text-slate-400 text-sm text-center py-4">No parameters defined in prompt</div>';
    }
}

/**
 * Display parameters in a table
 */
function displayParametersTable(params) {
    const parametersTable = document.getElementById('parametersTable');
    if (!parametersTable || !params || params.length === 0) return;
    
    const tableHTML = `
        <table class="w-full text-sm">
            <thead>
                <tr class="border-b border-slate-600/50">
                    <th class="text-left py-2 text-slate-400 font-medium">Name</th>
                    <th class="text-left py-2 text-slate-400 font-medium">Type</th>
                    <th class="text-left py-2 text-slate-400 font-medium">Required</th>
                    <th class="text-left py-2 text-slate-400 font-medium">Example</th>
                </tr>
            </thead>
            <tbody>
                ${params.map(param => `
                    <tr class="border-b border-slate-700/30">
                        <td class="py-2 text-white font-mono">${param.name}</td>
                        <td class="py-2 text-slate-300">${param.type}</td>
                        <td class="py-2">
                            <span class="px-2 py-0.5 rounded text-xs ${param.required ? 'bg-red-600/20 text-red-300' : 'bg-slate-600/20 text-slate-400'}">
                                ${param.required ? 'Required' : 'Optional'}
                            </span>
                        </td>
                        <td class="py-2 text-slate-400 font-mono text-xs">${param.example}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
    
    parametersTable.innerHTML = tableHTML;
}

/**
 * Extract example response from prompt
 */
function extractExampleFromPrompt(prompt) {
    if (!prompt) return null;
    
    // Try to extract output format
    const outputMatch = prompt.match(/Output Format:?\s*(.+?)(?=\n\s*(?:Input|Functionality|Endpoints|$))/is);
    
    if (outputMatch && outputMatch[1]) {
        const outputText = outputMatch[1].trim();
        const jsonMatch = outputText.match(/\{[\s\S]*?\}/);
        
        if (jsonMatch) {
            try {
                return JSON.parse(jsonMatch[0]);
            } catch (e) {
                console.warn('Could not parse example JSON:', e);
            }
        }
    }
    
    return null;
}

/**
 * Display parameters from documentation (legacy function)
 */
function displayParametersFromDocumentation(documentation) {
    // This is a simple implementation - enhance as needed
    const parametersTable = document.getElementById('parametersTable');
    if (parametersTable) {
        parametersTable.innerHTML = '<div class="text-slate-400 text-sm text-center py-4">View full documentation for parameter details</div>';
    }
}

// ============================================
// Database Configuration Functions
// ============================================

/**
 * Open the database configuration modal
 */
function openDatabaseModal() {
    const modal = document.getElementById('databaseModal');
    if (modal) {
        modal.classList.remove('hidden');
        // If we have existing config, populate the fields
        if (databaseConfig) {
            populateDatabaseFields(databaseConfig);
            if (databaseConfig.db_type) {
                selectDatabaseType(databaseConfig.db_type);
            }
        }
    }
}

/**
 * Close the database configuration modal
 */
function closeDatabaseModal() {
    const modal = document.getElementById('databaseModal');
    if (modal) {
        modal.classList.add('hidden');
        // Clear test result
        const testResult = document.getElementById('dbTestResult');
        if (testResult) {
            testResult.classList.add('hidden');
        }
    }
}

/**
 * Select database type (PostgreSQL or MongoDB)
 */
function selectDatabaseType(type) {
    selectedDatabaseType = type;
    
    const postgresBtn = document.getElementById('dbTypePostgres');
    const mongoBtn = document.getElementById('dbTypeMongo');
    const portInput = document.getElementById('dbPort');
    
    // Reset both buttons
    postgresBtn.classList.remove('border-blue-500', 'bg-blue-500/20');
    postgresBtn.classList.add('border-slate-600');
    mongoBtn.classList.remove('border-green-500', 'bg-green-500/20');
    mongoBtn.classList.add('border-slate-600');
    
    // Highlight selected button and set default port
    if (type === 'postgresql') {
        postgresBtn.classList.remove('border-slate-600');
        postgresBtn.classList.add('border-blue-500', 'bg-blue-500/20');
        if (!portInput.value) {
            portInput.placeholder = '5432';
        }
    } else if (type === 'mongodb') {
        mongoBtn.classList.remove('border-slate-600');
        mongoBtn.classList.add('border-green-500', 'bg-green-500/20');
        if (!portInput.value) {
            portInput.placeholder = '27017';
        }
    }
}

/**
 * Toggle password visibility
 */
function togglePasswordVisibility() {
    const passwordInput = document.getElementById('dbPassword');
    const eyeIcon = document.getElementById('passwordEyeIcon');
    
    if (passwordInput.type === 'password') {
        passwordInput.type = 'text';
        eyeIcon.innerHTML = `
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"></path>
        `;
    } else {
        passwordInput.type = 'password';
        eyeIcon.innerHTML = `
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path>
        `;
    }
}

/**
 * Test the database connection
 */
async function testDatabaseConnection() {
    const testBtn = document.getElementById('testConnectionBtn');
    const testResult = document.getElementById('dbTestResult');
    const testResultContent = document.getElementById('dbTestResultContent');
    
    let host, port, dbName, username, password;
    
    // Get values based on connection method
    if (connectionMethod === 'string') {
        const connectionString = document.getElementById('dbConnectionString').value.trim();
        
        if (!connectionString) {
            showTestResult(false, 'Please enter a connection string');
            return;
        }
        
        const parsed = parseConnectionString(connectionString);
        
        if (parsed.error) {
            showTestResult(false, parsed.error);
            return;
        }
        
        // Use parsed values
        if (!selectedDatabaseType && parsed.db_type) {
            selectDatabaseType(parsed.db_type);
        }
        
        host = parsed.host;
        port = parsed.port;
        dbName = parsed.database_name;
        username = parsed.username;
        password = parsed.password;
    } else {
        // Get from individual fields
        if (!selectedDatabaseType) {
            showTestResult(false, 'Please select a database type');
            return;
        }
        
        host = document.getElementById('dbHost').value.trim();
        port = document.getElementById('dbPort').value.trim();
        dbName = document.getElementById('dbName').value.trim();
        username = document.getElementById('dbUsername').value.trim();
        password = document.getElementById('dbPassword').value;
        
        if (!host || !port || !dbName || !username) {
            showTestResult(false, 'Please fill in all required fields');
            return;
        }
    }
    
    // Show loading state
    testBtn.disabled = true;
    testBtn.innerHTML = `
        <svg class="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>Testing...</span>
    `;
    
    try {
        const response = await fetch('/test-database-connection', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...(authToken && { 'Authorization': `Bearer ${authToken}` })
            },
            body: JSON.stringify({
                db_type: selectedDatabaseType,
                host: host,
                port: parseInt(port),
                database_name: dbName,
                username: username,
                password: password
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            const timeMsg = result.connection_time_ms ? ` (${result.connection_time_ms.toFixed(0)}ms)` : '';
            showTestResult(true, result.message + timeMsg);
        } else {
            showTestResult(false, result.message);
        }
    } catch (error) {
        console.error('Database connection test error:', error);
        showTestResult(false, 'Connection test failed: ' + error.message);
    } finally {
        // Reset button
        testBtn.disabled = false;
        testBtn.innerHTML = `
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
            </svg>
            <span>Test Connection</span>
        `;
    }
}

/**
 * Show test connection result
 */
function showTestResult(success, message) {
    const testResult = document.getElementById('dbTestResult');
    const testResultContent = document.getElementById('dbTestResultContent');
    
    testResult.classList.remove('hidden');
    
    if (success) {
        testResultContent.className = 'p-3 rounded-lg text-sm bg-emerald-500/20 border border-emerald-500/30 text-emerald-300';
        testResultContent.innerHTML = `
            <div class="flex items-center space-x-2">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>
                </svg>
                <span>${message}</span>
            </div>
        `;
    } else {
        testResultContent.className = 'p-3 rounded-lg text-sm bg-red-500/20 border border-red-500/30 text-red-300';
        testResultContent.innerHTML = `
            <div class="flex items-center space-x-2">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
                <span>${message}</span>
            </div>
        `;
    }
}

/**
 * Save the database configuration
 */
function saveDatabaseConfig() {
    let host, port, dbName, username, password, connectionString;
    
    // Get values based on connection method
    if (connectionMethod === 'string') {
        connectionString = document.getElementById('dbConnectionString').value.trim();
        
        if (!connectionString) {
            showTestResult(false, 'Please enter a connection string');
            return;
        }
        
        const parsed = parseConnectionString(connectionString);
        
        if (parsed.error) {
            showTestResult(false, parsed.error);
            return;
        }
        
        // Use parsed values
        if (!selectedDatabaseType && parsed.db_type) {
            selectDatabaseType(parsed.db_type);
        }
        
        host = parsed.host;
        port = parsed.port;
        dbName = parsed.database_name;
        username = parsed.username;
        password = parsed.password;
    } else {
        // Get from individual fields
        if (!selectedDatabaseType) {
            showTestResult(false, 'Please select a database type');
            return;
        }
        
        host = document.getElementById('dbHost').value.trim();
        port = document.getElementById('dbPort').value.trim();
        dbName = document.getElementById('dbName').value.trim();
        username = document.getElementById('dbUsername').value.trim();
        password = document.getElementById('dbPassword').value;
        
        if (!host || !port || !dbName || !username) {
            showTestResult(false, 'Please fill in all required fields');
            return;
        }
    }
    
    // Save configuration
    databaseConfig = {
        enabled: true,
        db_type: selectedDatabaseType,
        host: host,
        port: parseInt(port),
        database_name: dbName,
        username: username,
        password: password,
        connection_string: connectionString || null
    };
    
    // Update toggle button appearance
    updateDatabaseToggleButton(true);
    
    // Close modal
    closeDatabaseModal();
    
    console.log('Database configuration saved:', { ...databaseConfig, password: '***' });
}

/**
 * Clear the database configuration
 */
function clearDatabaseConfig() {
    databaseConfig = null;
    selectedDatabaseType = null;
    
    // Clear form fields
    document.getElementById('dbHost').value = '';
    document.getElementById('dbPort').value = '';
    document.getElementById('dbName').value = '';
    document.getElementById('dbUsername').value = '';
    document.getElementById('dbPassword').value = '';
    document.getElementById('dbConnectionString').value = '';
    
    // Reset button selections
    const postgresBtn = document.getElementById('dbTypePostgres');
    const mongoBtn = document.getElementById('dbTypeMongo');
    postgresBtn.classList.remove('border-blue-500', 'bg-blue-500/20');
    postgresBtn.classList.add('border-slate-600');
    mongoBtn.classList.remove('border-green-500', 'bg-green-500/20');
    mongoBtn.classList.add('border-slate-600');
    
    // Update toggle button appearance
    updateDatabaseToggleButton(false);
    
    // Hide test result
    const testResult = document.getElementById('dbTestResult');
    if (testResult) {
        testResult.classList.add('hidden');
    }
    
    console.log('Database configuration cleared');
}

/**
 * Update the database toggle button appearance
 */
function updateDatabaseToggleButton(isEnabled) {
    const toggleBtn = document.getElementById('databaseToggleBtn');
    const toggleText = document.getElementById('databaseToggleText');
    
    if (isEnabled && databaseConfig) {
        toggleBtn.classList.remove('border-slate-600', 'text-slate-400');
        toggleBtn.classList.add('border-emerald-500', 'text-emerald-400', 'bg-emerald-500/10');
        const dbType = databaseConfig.db_type === 'postgresql' ? 'PostgreSQL' : 'MongoDB';
        toggleText.textContent = dbType + ' Connected';
    } else {
        toggleBtn.classList.remove('border-emerald-500', 'text-emerald-400', 'bg-emerald-500/10');
        toggleBtn.classList.add('border-slate-600', 'text-slate-400');
        toggleText.textContent = 'Add Database';
    }
}

/**
 * Populate database fields from existing config
 */
function populateDatabaseFields(config) {
    if (config.host) document.getElementById('dbHost').value = config.host;
    if (config.port) document.getElementById('dbPort').value = config.port;
    if (config.database_name) document.getElementById('dbName').value = config.database_name;
    if (config.username) document.getElementById('dbUsername').value = config.username;
    if (config.password) document.getElementById('dbPassword').value = config.password;
}

/**
 * Get the current database configuration for API requests
 */
function getDatabaseConfigForRequest() {
    if (!databaseConfig || !databaseConfig.enabled) {
        return null;
    }
    return databaseConfig;
}

/**
 * Toggle between connection string and individual fields
 */
function toggleConnectionMethod(method) {
    connectionMethod = method;
    
    const fieldsBtn = document.getElementById('useFieldsBtn');
    const stringBtn = document.getElementById('useConnectionStringBtn');
    const fieldsSection = document.getElementById('connectionFieldsSection');
    const stringSection = document.getElementById('connectionStringSection');
    
    if (method === 'fields') {
        // Show fields, hide string
        fieldsBtn.classList.add('bg-slate-600', 'text-white');
        fieldsBtn.classList.remove('text-slate-400');
        stringBtn.classList.remove('bg-slate-600', 'text-white');
        stringBtn.classList.add('text-slate-400');
        
        fieldsSection.classList.remove('hidden');
        stringSection.classList.add('hidden');
    } else {
        // Show string, hide fields
        stringBtn.classList.add('bg-slate-600', 'text-white');
        stringBtn.classList.remove('text-slate-400');
        fieldsBtn.classList.remove('bg-slate-600', 'text-white');
        fieldsBtn.classList.add('text-slate-400');
        
        fieldsSection.classList.add('hidden');
        stringSection.classList.remove('hidden');
    }
}

/**
 * Parse connection string to extract database details
 */
function parseConnectionString(connectionString) {
    try {
        // Remove whitespace
        connectionString = connectionString.trim();
        
        // Detect database type from protocol
        let dbType = null;
        if (connectionString.startsWith('postgresql://') || connectionString.startsWith('postgres://')) {
            dbType = 'postgresql';
        } else if (connectionString.startsWith('mongodb://') || connectionString.startsWith('mongodb+srv://')) {
            dbType = 'mongodb';
        } else {
            return { error: 'Invalid connection string. Must start with postgresql:// or mongodb://' };
        }
        
        // Parse the URL
        let url;
        try {
            url = new URL(connectionString);
        } catch (e) {
            return { error: 'Invalid connection string format' };
        }
        
        // Extract components
        const host = url.hostname;
        const port = url.port || (dbType === 'postgresql' ? '5432' : '27017');
        const username = decodeURIComponent(url.username);
        const password = decodeURIComponent(url.password);
        const database = url.pathname.substring(1).split('?')[0]; // Remove leading slash and query params
        
        if (!host || !database) {
            return { error: 'Connection string must include host and database name' };
        }
        
        return {
            db_type: dbType,
            host: host,
            port: parseInt(port),
            database_name: database,
            username: username || '',
            password: password || '',
            connection_string: connectionString
        };
    } catch (error) {
        console.error('Error parsing connection string:', error);
        return { error: 'Failed to parse connection string: ' + error.message };
    }
}

/**
 * Auto-detect and parse connection string when user pastes
 */
function handleConnectionStringInput() {
    const connectionString = document.getElementById('dbConnectionString').value.trim();
    
    if (!connectionString) return;
    
    const parsed = parseConnectionString(connectionString);
    
    if (parsed.error) {
        showTestResult(false, parsed.error);
        return;
    }
    
    // Auto-select database type
    if (parsed.db_type) {
        selectDatabaseType(parsed.db_type);
    }
    
    // Show success hint
    const testResult = document.getElementById('dbTestResult');
    const testResultContent = document.getElementById('dbTestResultContent');
    testResult.classList.remove('hidden');
    testResultContent.className = 'p-3 rounded-lg text-sm bg-blue-500/20 border border-blue-500/30 text-blue-300';
    testResultContent.innerHTML = `
        <div class="flex items-center space-x-2">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <span>Connection string parsed successfully! Click "Test Connection" to verify.</span>
        </div>
    `;
}