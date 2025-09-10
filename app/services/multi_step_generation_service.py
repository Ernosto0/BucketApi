"""
Multi-Step Code Generation Service

Service for handling multi-step API code generation with streaming capabilities.
Breaks down code generation into configurable steps with real-time progress updates.
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

from ..code_generation_config.multi_step_config import MultiStepConfig, GenerationMode, StepType
from ..prompts.claude.prompt_loader import load_claude_prompt, format_claude_prompt
from .claude_service import claude_service
from .usage_service import usage_service
from .logging_service import logging_service, LogLevel, LogCategory
from .exceptions import (
    MultiStepGenerationError, SessionNotFoundError, SessionConfigurationError,
    PipelineValidationError, StepExecutionError, StepTimeoutError,
    TemplateProcessingError, SessionCleanupError, GenerationModeError,
    LLMAPIError, CodeExtractionError, PromptBuildError, LLMBaseError, create_secure_error
)
from .usage_service import usage_service
from ..config import settings

logger = logging.getLogger(__name__)

@dataclass
class StepResult:
    """Result of a single generation step"""
    step_id: str
    step_name: str
    step_type: str
    success: bool
    content: str
    error: Optional[str] = None
    execution_time: float = 0.0
    tokens_used: int = 0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class GenerationSession:
    """Represents a multi-step generation session"""
    session_id: str
    user_id: str
    prompt: str
    pipeline_name: str
    mode: GenerationMode
    started_at: datetime
    steps_completed: List[StepResult]
    current_step: Optional[str] = None
    total_tokens_used: int = 0
    total_execution_time: float = 0.0
    final_code: Optional[str] = None
    final_documentation: Optional[str] = None
    error: Optional[str] = None
    completed_at: Optional[datetime] = None
    
    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None
    
    @property
    def progress_percentage(self) -> float:
        if not hasattr(self, '_total_steps'):
            return 0.0
        return (len(self.steps_completed) / self._total_steps) * 100

class StreamEvent:
    """SSE event types for streaming"""
    STEP_START = "step_start"
    STEP_PROGRESS = "step_progress" 
    STEP_COMPLETE = "step_complete"
    STEP_ERROR = "step_error"
    SESSION_COMPLETE = "session_complete"
    SESSION_ERROR = "session_error"
    HEARTBEAT = "heartbeat"
    # New chat message events
    CHAT_MESSAGE = "chat_message"
    STEP_PHASE = "step_phase"
    LLM_THINKING = "llm_thinking"
    CODE_PROCESSING = "code_processing"

class MultiStepGenerationService:
    """Service for multi-step code generation with streaming support"""
    
    def __init__(self):
        try:
            self.config = MultiStepConfig()
            self.active_sessions: Dict[str, GenerationSession] = {}
            logger.info("MultiStepGenerationService initialized successfully")
            
            # Log initialization success (fire and forget)
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(logging_service.log_system_event(
                    level=LogLevel.INFO,
                    category=LogCategory.SYSTEM_EVENT,
                    message="MultiStepGenerationService initialized successfully",
                    details={
                        "service": "MultiStepGenerationService",
                        "config_loaded": True,
                        "operation": "service_initialization"
                    }
                ))
            except RuntimeError:
                # No event loop running, skip async logging during initialization
                pass
                
        except Exception as e:
            logger.error(f"Failed to initialize MultiStepGenerationService: {str(e)}", exc_info=True)
            # Still create the service but with limited functionality
            self.config = None
            self.active_sessions: Dict[str, GenerationSession] = {}
            logger.warning("MultiStepGenerationService initialized with limited functionality")
            
            # Log initialization failure (fire and forget)
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(logging_service.log_system_event(
                    level=LogLevel.ERROR,
                    category=LogCategory.ERROR,
                    message="MultiStepGenerationService initialization failed",
                    details={
                        "service": "MultiStepGenerationService",
                        "config_loaded": False,
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "operation": "service_initialization"
                    },
                    error_type=type(e).__name__
                ))
            except RuntimeError:
                # No event loop running, skip async logging during initialization
                pass
        
    async def start_generation(
        self,
        prompt: str,
        user_id: str,
        sample_input: Optional[str] = None,
        expected_output: Optional[str] = None,
        api_key_id: Optional[str] = None,
        pipeline_name: str = "full_pipeline",
        mode: GenerationMode = GenerationMode.NORMAL
    ) -> str:
        """Start a new multi-step generation session"""
        
        try:
            # Validate inputs
            if not prompt or not prompt.strip():
                raise SessionConfigurationError(
                    "Prompt cannot be empty",
                    user_id=user_id,
                    details={"pipeline_name": pipeline_name}
                )
            
            if not user_id:
                raise SessionConfigurationError(
                    "User ID is required",
                    user_id="",
                    details={"pipeline_name": pipeline_name}
                )
            
            session_id = str(uuid.uuid4())
            
            # Validate pipeline
            try:
                if not self.config.validate_pipeline(pipeline_name):
                    raise PipelineValidationError(
                        f"Invalid pipeline: {pipeline_name}",
                        user_id=user_id,
                        session_id=session_id,
                        details={"available_pipelines": list(self.config.get_pipeline_info().keys())}
                    )
            except AttributeError as e:
                raise SessionConfigurationError(
                    "Configuration service unavailable",
                    user_id=user_id,
                    session_id=session_id,
                    details={"config_error": str(e)}
                )
            
            # Validate generation mode
            if not isinstance(mode, GenerationMode):
                raise GenerationModeError(
                    f"Invalid generation mode: {mode}",
                    user_id=user_id,
                    session_id=session_id,
                    details={"valid_modes": [m.value for m in GenerationMode]}
                )
            
            # Get pipeline steps configuration
            try:
                steps_config = self.config.get_steps_config(pipeline_name)
                if not steps_config:
                    raise PipelineValidationError(
                        f"No steps configured for pipeline: {pipeline_name}",
                        user_id=user_id,
                        session_id=session_id,
                        details={"pipeline_name": pipeline_name}
                    )
            except Exception as e:
                raise SessionConfigurationError(
                    "Failed to load pipeline configuration",
                    user_id=user_id,
                    session_id=session_id,
                    details={"pipeline_name": pipeline_name, "config_error": str(e)}
                )
            
            # Create session
            try:
                session = GenerationSession(
                    session_id=session_id,
                    user_id=user_id,
                    prompt=prompt,
                    pipeline_name=pipeline_name,
                    mode=mode,
                    started_at=datetime.now(),
                    steps_completed=[]
                )
                
                # Store additional context
                session.sample_input = sample_input
                session.expected_output = expected_output
                session.api_key_id = api_key_id
                session._total_steps = len(steps_config)
                
                self.active_sessions[session_id] = session
                
                # Log session start to system logs
                await logging_service.log_system_event(
                    level=LogLevel.INFO,
                    category=LogCategory.SYSTEM_EVENT,
                    message=f"Multi-step generation session started",
                    details={
                        "session_id": session_id,
                        "pipeline_name": pipeline_name,
                        "mode": mode.value,
                        "total_steps": session._total_steps,
                        "has_sample_input": bool(sample_input),
                        "has_expected_output": bool(expected_output),
                        "api_key_id": api_key_id,
                        "active_sessions_count": len(self.active_sessions)
                    },
                    user_id=user_id,
                    session_id=session_id,
                    api_key_id=api_key_id
                )
                
                logger.info(
                    f"Started generation session {session_id} for user {user_id} with pipeline {pipeline_name}",
                    extra={
                        'session_id': session_id,
                        'user_id': user_id,
                        'pipeline_name': pipeline_name,
                        'mode': mode.value,
                        'total_steps': session._total_steps
                    }
                )
                
                return session_id
                
            except Exception as e:
                logger.error(f"Failed to create session: {str(e)}")
                raise SessionConfigurationError(
                    "Failed to initialize generation session",
                    user_id=user_id,
                    session_id=session_id,
                    details={"error": str(e)}
                    )
                    
        except MultiStepGenerationError as e:
            # Log custom exceptions
            await logging_service.log_llm_error(e, additional_details={
                "operation": "start_generation",
                "pipeline_name": pipeline_name,
                "mode": mode.value if isinstance(mode, GenerationMode) else str(mode)
            })
            raise
        except Exception as e:
            # Catch any unexpected errors
            logger.error(f"Unexpected error in start_generation: {str(e)}", exc_info=True)
            
            # Log unexpected error
            await logging_service.log_error_from_exception(
                error_type=type(e).__name__,
                error_message=str(e),
                user_id=user_id or "",
                api_slug="multi_step_start_generation",
                details={
                    "operation": "start_generation",
                    "pipeline_name": pipeline_name,
                    "mode": mode.value if hasattr(mode, 'value') else str(mode),
                    "error_traceback": str(e)
                }
            )
            
            raise SessionConfigurationError(
                "An unexpected error occurred during session initialization",
                user_id=user_id or "",
                details={"error_type": type(e).__name__, "error": str(e)}
            )
    
    async def generate_normal_mode(self, session_id: str) -> Dict[str, Any]:
        """Execute generation in normal mode (single response after all steps)"""
        
        # Validate session
        if not session_id:
            raise SessionNotFoundError(
                "Session ID is required",
                user_id="",
                session_id=session_id
            )
            
        session = self.active_sessions.get(session_id)
        if not session:
            raise SessionNotFoundError(
                f"Session not found: {session_id}",
                user_id="",
                session_id=session_id,
                details={"active_sessions": len(self.active_sessions)}
            )
            
        # Check if session is already completed
        if session.is_completed:
            logger.warning(f"Attempt to generate on already completed session {session_id}")
            raise GenerationModeError(
                "Session is already completed",
                user_id=session.user_id,
                session_id=session_id,
                details={"completed_at": session.completed_at.isoformat() if session.completed_at else None}
            )
            
        try:
            # Log normal mode generation start
            await logging_service.log_system_event(
                level=LogLevel.INFO,
                category=LogCategory.SYSTEM_EVENT,
                message="Normal mode generation started",
                details={
                    "session_id": session_id,
                    "pipeline_name": session.pipeline_name,
                    "mode": "normal",
                    "total_steps": getattr(session, '_total_steps', 0),
                    "user_id": session.user_id
                },
                user_id=session.user_id,
                session_id=session_id,
                api_key_id=getattr(session, 'api_key_id', None)
            )
            
            logger.info(
                f"Starting normal mode generation for session {session_id}",
                extra={
                    'session_id': session_id,
                    'user_id': session.user_id,
                    'pipeline_name': session.pipeline_name
                }
            )
            
            # Get steps configuration
            try:
                steps_config = self.config.get_steps_config(session.pipeline_name)
                if not steps_config:
                    raise PipelineValidationError(
                        f"No steps configuration found for pipeline: {session.pipeline_name}",
                        user_id=session.user_id,
                        session_id=session_id,
                        details={"pipeline_name": session.pipeline_name}
                    )
            except Exception as e:
                raise PipelineValidationError(
                    "Failed to load pipeline steps configuration",
                    user_id=session.user_id,
                    session_id=session_id,
                    details={"pipeline_name": session.pipeline_name, "error": str(e)}
                )
            
            # Execute all steps sequentially
            step_outputs = {}
            failed_steps = []
            
            for i, step_config in enumerate(steps_config):
                try:
                    step_result = await self._execute_step(session, step_config, step_outputs)
                    session.steps_completed.append(step_result)
                    
                    if not step_result.success:
                        failed_steps.append({
                            "step_id": step_config['id'],
                            "error": step_result.error
                        })
                        
                        # Handle step failure based on configuration
                        if not self.config.ERROR_CONFIG.get("continue_on_step_failure", False):
                            raise StepExecutionError(
                                f"Step {step_config['id']} failed: {step_result.error}",
                                user_id=session.user_id,
                                session_id=session_id,
                                step_id=step_config['id'],
                                details={
                                    "step_name": step_config.get('name', ''),
                                    "step_number": i + 1,
                                    "total_steps": len(steps_config),
                                    "error": step_result.error
                                }
                            )
                        
                        logger.warning(
                            f"Step {step_config['id']} failed but continuing: {step_result.error}",
                            extra={
                                'session_id': session_id,
                                'step_id': step_config['id'],
                                'step_name': step_config.get('name', ''),
                                'error': step_result.error
                            }
                        )
                    else:
                        step_outputs[step_config['id']] = step_result.content
                        
                except StepExecutionError:
                    # Re-raise step execution errors
                    raise
                except Exception as e:
                    # Wrap unexpected errors
                    error_msg = f"Unexpected error in step {step_config['id']}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    
                    step_result = StepResult(
                        step_id=step_config['id'],
                        step_name=step_config.get('name', ''),
                        step_type=step_config.get('type', ''),
                        success=False,
                        content="",
                        error=error_msg,
                        execution_time=0.0,
                        tokens_used=0
                    )
                    session.steps_completed.append(step_result)
                    
                    if not self.config.ERROR_CONFIG.get("continue_on_step_failure", False):
                        raise StepExecutionError(
                            error_msg,
                            user_id=session.user_id,
                            session_id=session_id,
                            step_id=step_config['id'],
                            details={"error_type": type(e).__name__, "error": str(e)}
                        )
            
            # Extract final results
            logger.info(
                f"Completed steps: {[step.step_id for step in session.steps_completed]}",
                extra={
                    'session_id': session_id,
                    'completed_steps': len(session.steps_completed),
                    'failed_steps': len(failed_steps)
                }
            )
            logger.info(f"Step outputs available: {list(step_outputs.keys())}")
            
            try:
                session.final_code = self._extract_final_code(step_outputs)
                session.final_documentation = self._extract_final_documentation(step_outputs)
            except Exception as e:
                logger.error(f"Failed to extract final results: {str(e)}")
                # Don't fail the entire generation for extraction issues
                session.final_code = None
                session.final_documentation = None
            
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            # Log normal mode generation completion
            await logging_service.log_system_event(
                level=LogLevel.INFO,
                category=LogCategory.SYSTEM_EVENT,
                message="Normal mode generation completed",
                details={
                    "session_id": session_id,
                    "pipeline_name": session.pipeline_name,
                    "mode": "normal",
                    "total_execution_time": session.total_execution_time,
                    "total_tokens_used": session.total_tokens_used,
                    "steps_completed": len(session.steps_completed),
                    "failed_steps_count": len(failed_steps),
                    "final_code_length": len(session.final_code) if session.final_code else 0,
                    "final_documentation_length": len(session.final_documentation) if session.final_documentation else 0,
                    "success": True
                },
                user_id=session.user_id,
                session_id=session_id,
                api_key_id=getattr(session, 'api_key_id', None),
                duration_ms=int(session.total_execution_time * 1000) if session.total_execution_time else None
            )
            
            logger.info(
                f"Normal mode generation completed for session {session_id}",
                extra={
                    'session_id': session_id,
                    'total_execution_time': session.total_execution_time,
                    'total_tokens_used': session.total_tokens_used,
                    'final_code_length': len(session.final_code) if session.final_code else 0,
                    'failed_steps_count': len(failed_steps)
                }
            )
            
            # Record usage tracking for the completed session
            try:
                response_length = len(session.final_code) if session.final_code else 0
                prompt_length = len(session.prompt)
                duration_ms = int(session.total_execution_time * 1000) if session.total_execution_time else 0
                
                # Calculate tokens based on actual session data
                estimated_input_tokens, estimated_output_tokens = usage_service.calculate_estimated_tokens(
                    settings.CLAUDE_MODEL, 
                    session.prompt, 
                    session.final_code or "", 
                    response_length, 
                    True
                )
                
                await usage_service.record_usage(
                    user_id=session.user_id,
                    api_key_id=getattr(session, 'api_key_id', None),
                    service_type="claude",
                    operation_type="multi_step_generation",
                    model_name=settings.CLAUDE_MODEL,
                    input_tokens=estimated_input_tokens,
                    output_tokens=estimated_output_tokens,
                    prompt_length=prompt_length,
                    response_length=response_length,
                    request_duration_ms=duration_ms,
                    operation_context={
                        "pipeline_name": session.pipeline_name,
                        "mode": session.mode.value if hasattr(session.mode, 'value') else str(session.mode),
                        "steps_completed": len(session.steps_completed),
                        "total_tokens_used": session.total_tokens_used,
                        "final_code_length": response_length,
                        "final_documentation_length": len(session.final_documentation) if session.final_documentation else 0,
                        "prompt_preview": session.prompt[:100] + "..." if len(session.prompt) > 100 else session.prompt
                    },
                    api_slug="multi_step_generation",
                    success=True,
                    error_message=None
                )
                logger.info(f"Successfully recorded usage for completed session {session_id}")
                
            except Exception as usage_error:
                logger.error(f"Failed to record usage for session {session_id}: {usage_error}")
                # Don't fail the entire generation because of usage tracking issues
            
            return {
                "session_id": session_id,
                "success": True,
                "mode": "normal",
                "final_code": session.final_code,
                "final_documentation": session.final_documentation,
                "steps_completed": [asdict(step) for step in session.steps_completed],
                "total_execution_time": session.total_execution_time,
                "total_tokens_used": session.total_tokens_used,
                "completed_at": session.completed_at.isoformat(),
                "failed_steps": failed_steps if failed_steps else None
            }
            
        except MultiStepGenerationError as e:
            # Handle our custom exceptions - mark session as failed
            session.error = str(e)
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            # Log error to system logs
            await logging_service.log_system_event(
                level=LogLevel.ERROR,
                category=LogCategory.ERROR,
                message="Normal mode generation failed",
                details={
                    "session_id": session_id,
                    "pipeline_name": session.pipeline_name,
                    "mode": "normal",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "total_execution_time": session.total_execution_time,
                    "total_tokens_used": session.total_tokens_used,
                    "steps_completed": len(session.steps_completed),
                    "success": False
                },
                user_id=session.user_id,
                session_id=session_id,
                api_key_id=getattr(session, 'api_key_id', None),
                error_type=type(e).__name__,
                duration_ms=int(session.total_execution_time * 1000) if session.total_execution_time else None
            )
            
            # Log to LLM error logs
            await logging_service.log_llm_error(e, additional_details={
                "operation": "generate_normal_mode",
                "pipeline_name": session.pipeline_name,
                "mode": "normal",
                "steps_completed": len(session.steps_completed)
            })
            
            logger.error(
                f"Normal mode generation failed for session {session_id}: {str(e)}",
                extra={
                    'session_id': session_id,
                    'error_type': type(e).__name__,
                    'user_id': session.user_id
                }
            )
            
            # Record usage tracking for the failed session
            try:
                response_length = len(session.final_code) if session.final_code else 0
                prompt_length = len(session.prompt)
                duration_ms = int(session.total_execution_time * 1000) if session.total_execution_time else 0
                
                # Calculate tokens based on actual session data
                estimated_input_tokens, estimated_output_tokens = usage_service.calculate_estimated_tokens(
                    settings.CLAUDE_MODEL, 
                    session.prompt, 
                    session.final_code or "", 
                    response_length, 
                    False  # success = False for failed sessions
                )
                
                await usage_service.record_usage(
                    user_id=session.user_id,
                    api_key_id=getattr(session, 'api_key_id', None),
                    service_type="claude",
                    operation_type="multi_step_generation",
                    model_name=settings.CLAUDE_MODEL,
                    input_tokens=estimated_input_tokens,
                    output_tokens=estimated_output_tokens,
                    prompt_length=prompt_length,
                    response_length=response_length,
                    request_duration_ms=duration_ms,
                    operation_context={
                        "pipeline_name": session.pipeline_name,
                        "mode": session.mode.value if hasattr(session.mode, 'value') else str(session.mode),
                        "steps_completed": len(session.steps_completed),
                        "total_tokens_used": session.total_tokens_used,
                        "final_code_length": response_length,
                        "error_type": type(e).__name__,
                        "prompt_preview": session.prompt[:100] + "..." if len(session.prompt) > 100 else session.prompt
                    },
                    api_slug="multi_step_generation",
                    success=False,
                    error_message=str(e)
                )
                logger.info(f"Successfully recorded usage for failed session {session_id}")
                
            except Exception as usage_error:
                logger.error(f"Failed to record usage for failed session {session_id}: {usage_error}")
                # Don't fail the entire response because of usage tracking issues
            
            return {
                "session_id": session_id,
                "success": False,
                "mode": "normal", 
                "error": str(e),
                "error_type": type(e).__name__,
                "steps_completed": [asdict(step) for step in session.steps_completed],
                "total_execution_time": session.total_execution_time,
                "total_tokens_used": session.total_tokens_used,
                "failed_at": session.completed_at.isoformat()
            }
            
        except Exception as e:
            # Handle unexpected errors
            session.error = str(e)
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            logger.error(
                f"Unexpected error in normal mode generation for session {session_id}: {str(e)}",
                extra={
                    'session_id': session_id,
                    'error_type': type(e).__name__,
                    'user_id': session.user_id
                },
                exc_info=True
            )
            
            # Record usage tracking for the unexpectedly failed session
            try:
                response_length = len(session.final_code) if session.final_code else 0
                prompt_length = len(session.prompt)
                duration_ms = int(session.total_execution_time * 1000) if session.total_execution_time else 0
                
                # Calculate tokens based on actual session data
                estimated_input_tokens, estimated_output_tokens = usage_service.calculate_estimated_tokens(
                    settings.CLAUDE_MODEL, 
                    session.prompt, 
                    session.final_code or "", 
                    response_length, 
                    False  # success = False for failed sessions
                )
                
                await usage_service.record_usage(
                    user_id=session.user_id,
                    api_key_id=getattr(session, 'api_key_id', None),
                    service_type="claude",
                    operation_type="multi_step_generation",
                    model_name=settings.CLAUDE_MODEL,
                    input_tokens=estimated_input_tokens,
                    output_tokens=estimated_output_tokens,
                    prompt_length=prompt_length,
                    response_length=response_length,
                    request_duration_ms=duration_ms,
                    operation_context={
                        "pipeline_name": session.pipeline_name,
                        "mode": session.mode.value if hasattr(session.mode, 'value') else str(session.mode),
                        "steps_completed": len(session.steps_completed),
                        "total_tokens_used": session.total_tokens_used,
                        "final_code_length": response_length,
                        "error_type": type(e).__name__,
                        "error_category": "unexpected_error",
                        "prompt_preview": session.prompt[:100] + "..." if len(session.prompt) > 100 else session.prompt
                    },
                    api_slug="multi_step_generation",
                    success=False,
                    error_message="An unexpected error occurred during generation"
                )
                logger.info(f"Successfully recorded usage for unexpectedly failed session {session_id}")
                
            except Exception as usage_error:
                logger.error(f"Failed to record usage for unexpectedly failed session {session_id}: {usage_error}")
                # Don't fail the entire response because of usage tracking issues
            
            return {
                "session_id": session_id,
                "success": False,
                "mode": "normal",
                "error": "An unexpected error occurred during generation",
                "error_type": type(e).__name__,
                "steps_completed": [asdict(step) for step in session.steps_completed],
                "total_execution_time": session.total_execution_time,
                "total_tokens_used": session.total_tokens_used,
                "failed_at": session.completed_at.isoformat()
            }
    
    async def generate_streaming_mode(self, session_id: str) -> AsyncGenerator[str, None]:
        """Execute generation in streaming mode with real-time updates"""
        
        # Validate session
        if not session_id:
            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                "error": "Session ID is required",
                "error_type": "SessionNotFoundError"
            })
            return
            
        session = self.active_sessions.get(session_id)
        if not session:
            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                "error": f"Session not found: {session_id}",
                "error_type": "SessionNotFoundError",
                "active_sessions": len(self.active_sessions)
            })
            return
            
        # Check if session is already completed
        if session.is_completed:
            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                "error": "Session is already completed",
                "error_type": "GenerationModeError",
                "completed_at": session.completed_at.isoformat() if session.completed_at else None
            })
            return
            
        try:
            logger.info(
                f"Starting streaming mode generation for session {session_id}",
                extra={
                    'session_id': session_id,
                    'user_id': session.user_id,
                    'pipeline_name': session.pipeline_name
                }
            )
            
            # Get steps configuration first
            try:
                steps_config = self.config.get_steps_config(session.pipeline_name)
                if not steps_config:
                    raise PipelineValidationError(
                        f"No steps configuration found for pipeline: {session.pipeline_name}",
                        user_id=session.user_id,
                        session_id=session_id,
                        details={"pipeline_name": session.pipeline_name}
                    )
            except Exception as e:
                yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                    "session_id": session_id,
                    "error": f"Failed to load pipeline configuration: {str(e)}",
                    "error_type": "PipelineValidationError",
                    "pipeline_name": session.pipeline_name
                })
                return
            
            # Send session start event (no message, handled by frontend)
            yield self._format_sse_event(StreamEvent.STEP_START, {
                "session_id": session_id,
                "mode": "streaming",
                "pipeline": session.pipeline_name,
                "total_steps": len(steps_config),
                "message": None
            })
            
            # Execute all steps with streaming updates
            step_outputs = {}
            failed_steps = []
            
            for i, step_config in enumerate(steps_config):
                try:
                    # Send step start event (no message, handled by streaming function)
                    yield self._format_sse_event(StreamEvent.STEP_START, {
                        "step_id": step_config["id"],
                        "step_name": step_config["name"],
                        "step_number": i + 1,
                        "total_steps": len(steps_config),
                        "message": None
                    })
                    
                    # Execute the step with streaming chat messages
                    step_result = None
                    async for message, result in self._execute_step_with_streaming(session, step_config, step_outputs):
                        if message:
                            # It's a chat message, yield it
                            yield message
                        if result:
                            # It's the step result
                            step_result = result
                            break
                    
                    if step_result:
                        session.steps_completed.append(step_result)
                    
                    # Send step complete/error event
                    if step_result.success:
                        step_outputs[step_config['id']] = step_result.content
                        yield self._format_sse_event(StreamEvent.STEP_COMPLETE, {
                            "step_id": step_config["id"],
                            "step_name": step_config["name"],
                            "step_number": i + 1,
                            "execution_time": step_result.execution_time,
                            "tokens_used": step_result.tokens_used,
                            "content_preview": step_result.content[:200] + "..." if len(step_result.content) > 200 else step_result.content,
                            "message": f"✅ {step_config['name']} completed successfully"
                        })
                    else:
                        failed_steps.append({
                            "step_id": step_config['id'],
                            "step_name": step_config['name'],
                            "error": step_result.error
                        })
                        
                        yield self._format_sse_event(StreamEvent.STEP_ERROR, {
                            "step_id": step_config["id"],
                            "step_name": step_config["name"],
                            "step_number": i + 1,
                            "error": step_result.error,
                            "error_type": "StepExecutionError",
                            "message": f"❌ {step_config['name']} failed: {step_result.error}"
                        })
                        
                        if not self.config.ERROR_CONFIG.get("continue_on_step_failure", False):
                            # Stop processing further steps
                            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                                "session_id": session_id,
                                "error": f"Step {step_config['id']} failed and continue_on_step_failure is disabled",
                                "error_type": "StepExecutionError",
                                "failed_step": step_config['id'],
                                "message": f"❌ Generation stopped due to step failure: {step_result.error}"
                            })
                            
                            # Mark session as failed and return
                            session.error = f"Step {step_config['id']} failed: {step_result.error}"
                            session.completed_at = datetime.now()
                            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
                            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
                            return
                    
                    # Send progress update
                    progress = ((i + 1) / len(steps_config)) * 100
                    yield self._format_sse_event(StreamEvent.STEP_PROGRESS, {
                        "progress": progress,
                        "steps_completed": i + 1,
                        "total_steps": len(steps_config),
                        "failed_steps": len(failed_steps)
                    })
                    
                except Exception as e:
                    # Handle unexpected step errors
                    error_msg = f"Unexpected error in step {step_config['id']}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    
                    failed_steps.append({
                        "step_id": step_config['id'],
                        "step_name": step_config.get('name', ''),
                        "error": error_msg
                    })
                    
                    # Create failed step result
                    step_result = StepResult(
                        step_id=step_config['id'],
                        step_name=step_config.get('name', ''),
                        step_type=step_config.get('type', ''),
                        success=False,
                        content="",
                        error=error_msg,
                        execution_time=0.0,
                        tokens_used=0
                    )
                    session.steps_completed.append(step_result)
                    
                    yield self._format_sse_event(StreamEvent.STEP_ERROR, {
                        "step_id": step_config["id"],
                        "step_name": step_config.get("name", ""),
                        "step_number": i + 1,
                        "error": error_msg,
                        "error_type": type(e).__name__,
                        "message": f"❌ {step_config.get('name', '')} failed: {error_msg}"
                    })
                    
                    if not self.config.ERROR_CONFIG.get("continue_on_step_failure", False):
                        yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                            "session_id": session_id,
                            "error": error_msg,
                            "error_type": type(e).__name__,
                            "failed_step": step_config['id'],
                            "message": f"❌ Generation stopped due to unexpected error: {error_msg}"
                        })
                        
                        session.error = error_msg
                        session.completed_at = datetime.now()
                        session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
                        session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
                        return
            
            # Finalize session
            try:
                session.final_code = self._extract_final_code(step_outputs)
                session.final_documentation = self._extract_final_documentation(step_outputs)
            except Exception as e:
                logger.error(f"Failed to extract final results: {str(e)}")
                # Don't fail the entire generation for extraction issues
                session.final_code = None
                session.final_documentation = None
                
                yield self._format_sse_event(StreamEvent.STEP_ERROR, {
                    "step_id": "result_extraction",
                    "step_name": "Result Extraction",
                    "error": f"Failed to extract final results: {str(e)}",
                    "error_type": "CodeExtractionError",
                    "message": f"⚠️ Warning: Failed to extract final results: {str(e)}"
                })
            
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            # Send session complete event
            success_message = "🎉 Multi-step code generation completed successfully!"
            if failed_steps:
                success_message = f"⚠️ Multi-step code generation completed with {len(failed_steps)} failed steps"
            
            yield self._format_sse_event(StreamEvent.SESSION_COMPLETE, {
                "session_id": session_id,
                "final_code": session.final_code,
                "final_documentation": session.final_documentation,
                "total_execution_time": session.total_execution_time,
                "total_tokens_used": session.total_tokens_used,
                "steps_completed": len(session.steps_completed),
                "failed_steps": failed_steps if failed_steps else None,
                "failed_steps_count": len(failed_steps),
                "message": success_message
            })
            
            logger.info(
                f"Streaming mode generation completed for session {session_id}",
                extra={
                    'session_id': session_id,
                    'total_execution_time': session.total_execution_time,
                    'total_tokens_used': session.total_tokens_used,
                    'failed_steps_count': len(failed_steps)
                }
            )
            
        except MultiStepGenerationError as e:
            session.error = str(e)
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            logger.error(
                f"Multi-step generation error in streaming mode for session {session_id}: {str(e)}",
                extra={
                    'session_id': session_id,
                    'error_type': type(e).__name__,
                    'user_id': session.user_id
                }
            )
            
            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                "session_id": session_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "step_id": getattr(e, 'step_id', None),
                "message": f"❌ Generation failed: {str(e)}"
            })
            
        except Exception as e:
            session.error = str(e)
            session.completed_at = datetime.now()
            session.total_execution_time = sum(step.execution_time for step in session.steps_completed)
            session.total_tokens_used = sum(step.tokens_used for step in session.steps_completed)
            
            logger.error(
                f"Unexpected error in streaming mode generation for session {session_id}: {str(e)}",
                extra={
                    'session_id': session_id,
                    'error_type': type(e).__name__,
                    'user_id': session.user_id
                },
                exc_info=True
            )
            
            yield self._format_sse_event(StreamEvent.SESSION_ERROR, {
                "session_id": session_id,
                "error": "An unexpected error occurred during generation",
                "error_type": type(e).__name__,
                "internal_error": str(e),
                "message": f"❌ Generation failed due to unexpected error"
            })
    
    async def _execute_step_with_streaming(
        self, 
        session: GenerationSession, 
        step_config: Dict[str, Any], 
        previous_outputs: Dict[str, str]
    ) -> AsyncGenerator[Tuple[str, Optional[StepResult]], None]:
        """Execute a single generation step with streaming chat messages"""
        
        start_time = time.time()
        step_id = step_config.get("id", "unknown_step")
        step_name = step_config.get("name", "Unknown Step")
        step_type = step_config.get("type", "unknown")
        
        # Get step-specific chat messages
        chat_messages = self._get_step_chat_messages(step_id, step_name)
        
        try:
            # Phase 1: Starting step - single message only
            yield (self._format_chat_message(
                chat_messages["starting"], 
                step_id=step_id, 
                phase="initialization"
            ), None)
            
            # Validation phase
            if not step_id:
                raise StepExecutionError(
                    "Step configuration missing required 'id' field",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    details={"step_config": step_config}
                )
            
            prompt_template_name = step_config.get("prompt_template")
            if not prompt_template_name:
                raise StepExecutionError(
                    f"Step {step_id} missing prompt_template configuration",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"step_config": step_config}
                )
            
            # Skip template loading message - too verbose
            
            # Load prompt template
            try:
                prompt_config = load_claude_prompt(prompt_template_name)
                if not prompt_config:
                    raise TemplateProcessingError(
                        f"Failed to load prompt template: {prompt_template_name}",
                        user_id=session.user_id,
                        session_id=session.session_id,
                        step_id=step_id,
                        details={"template_name": prompt_template_name}
                    )
            except FileNotFoundError as e:
                raise TemplateProcessingError(
                    f"Prompt template not found: {prompt_template_name}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"template_name": prompt_template_name, "error": str(e)}
                )
            except Exception as e:
                raise TemplateProcessingError(
                    f"Error loading prompt template {prompt_template_name}: {str(e)}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"template_name": prompt_template_name, "error": str(e)}
                )
            
            # Skip prompt preparation message - combine with AI call
            
            # Prepare template variables
            try:
                template_vars = {
                    "prompt": session.prompt or "",
                    "original_prompt": session.prompt or "",
                    "sample_input_section": f"\nSample Input: {session.sample_input}" if session.sample_input else "",
                    "expected_output_section": f"\nExpected Output: {session.expected_output}" if session.expected_output else "",
                }
                
                # Add previous step outputs
                for output_id, output_content in previous_outputs.items():
                    if output_content:
                        # Create both the cleaned name and keep the original
                        cleaned_name = output_id.replace("step", "").replace("_", "")
                        template_vars[cleaned_name] = output_content
                        template_vars[output_id] = output_content  # Keep original key too
                    
                # Special handling for specific steps
                if step_id == "step1_analysis_design":
                    # First step, no special handling needed
                    pass
                elif step_id == "step2_implementation":
                    template_vars["analysis_design"] = previous_outputs.get("step1_analysis_design",
                        f"Basic requirements analysis and design based on: {session.prompt}")
                elif step_id == "step3_testing":
                    # Testing step needs specific variable names
                    template_vars["implemented_code"] = previous_outputs.get("step2_implementation",
                        "async def run(file_bytes=None, input_data=None):\n    return {'result': 'API implementation', 'message': 'success'}")
                    template_vars["structure_design"] = previous_outputs.get("step1_analysis_design",
                        f"Basic requirements analysis and design based on: {session.prompt}")
                    template_vars["requirements_analysis"] = previous_outputs.get("step1_analysis_design",
                        f"Requirements analysis: {session.prompt}")
                    template_vars["original_prompt"] = session.prompt or ""
                        
            except Exception as e:
                raise TemplateProcessingError(
                    f"Error preparing template variables for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"error": str(e)}
                )
            
            # Format prompts
            try:
                system_prompt, user_prompt = format_claude_prompt(prompt_config, **template_vars)
                
                if not system_prompt or not user_prompt:
                    raise PromptBuildError(
                        f"Empty prompts generated for step {step_id}",
                        user_id=session.user_id,
                        request_id=session.session_id,
                        api_slug=f"multi_step_{step_id}",
                        model_name="claude",
                        details={"template_name": prompt_template_name}
                    )
                    
            except KeyError as e:
                raise TemplateProcessingError(
                    f"Missing template variable for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={
                        "missing_variable": str(e),
                        "available_variables": list(template_vars.keys()),
                        "template_name": prompt_template_name
                    }
                )
            except Exception as e:
                raise PromptBuildError(
                    f"Error formatting prompts for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    request_id=session.session_id,
                    api_slug=f"multi_step_{step_id}",
                    model_name="claude",
                    details={"template_name": prompt_template_name, "error": str(e)}
                )
            
            # Phase 2: AI Processing - single message with thinking
            yield (self._format_chat_message(
                chat_messages["calling_ai"], 
                step_id=step_id, 
                phase="ai_processing",
                typing_delay=1.0
            ), None)
            
            # Make Claude API call
            try:
                api_start_time = time.time()
                response = await claude_service._make_claude_request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    user_id=session.user_id,
                    api_key_id=session.api_key_id,
                    operation_type=step_config.get("operation_type", "multi_step_generation"),
                    api_slug=f"multi_step_{step_id}"
                )
                api_duration = (time.time() - api_start_time) * 1000
                
                if not response:
                    raise LLMAPIError(
                        f"Empty response from Claude API for step {step_id}",
                        user_id=session.user_id,
                        request_id=session.session_id,
                        api_slug=f"multi_step_{step_id}",
                        model_name="claude"
                    )
                
            except LLMAPIError:
                raise
            except Exception as e:
                raise LLMAPIError(
                    f"Claude API request failed for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    request_id=session.session_id,
                    api_slug=f"multi_step_{step_id}",
                    model_name="claude",
                    details={"error": str(e), "error_type": type(e).__name__}
                )
            
            # Phase 3: Processing response - only for implementation steps
            if step_id == "step2_implementation":
                yield (self._format_chat_message(
                    chat_messages["processing_response"], 
                    step_id=step_id, 
                    phase="response_processing"
                ), None)
            
            execution_time = time.time() - start_time
            tokens_used = len(response) // 4
            
            # For implementation steps, extract code
            content = response
            if step_id == "step2_implementation":
                yield (self._format_chat_message(
                    "🔍 Extracting and validating the generated code...", 
                    step_id=step_id, 
                    phase="code_extraction"
                ), None)
                
                try:
                    extracted_code = claude_service._extract_code_from_response(response)
                    if extracted_code:
                        content = extracted_code
                        yield (self._format_chat_message(
                            f"✅ Successfully extracted {len(extracted_code)} characters of clean code!", 
                            step_id=step_id, 
                            phase="code_validation"
                        ), None)
                    else:
                        content = response
                        yield (self._format_chat_message(
                            "⚠️ Using raw response as no specific code blocks were found", 
                            step_id=step_id, 
                            phase="code_validation"
                        ), None)
                except Exception as e:
                    content = response
                    yield (self._format_chat_message(
                        f"⚠️ Code extraction failed: {str(e)}, using raw response", 
                        step_id=step_id, 
                        phase="code_validation"
                    ), None)
            
            # Phase 4: Completion - single message
            yield (self._format_chat_message(
                chat_messages["completing"], 
                step_id=step_id, 
                phase="finalization"
            ), None)
            
            # Log successful step
            await logging_service.log_system_event(
                level=LogLevel.INFO,
                category=LogCategory.SYSTEM_EVENT,
                message=f"Step execution completed: {step_name}",
                details={
                    "session_id": session.session_id,
                    "step_id": step_id,
                    "step_name": step_name,
                    "step_type": step_type,
                    "execution_time": execution_time,
                    "response_length": len(response),
                    "tokens_used": tokens_used,
                    "success": True
                },
                user_id=session.user_id,
                session_id=session.session_id,
                duration_ms=int(execution_time * 1000)
            )
            
            result = StepResult(
                step_id=step_id,
                step_name=step_name,
                step_type=step_type,
                success=True,
                content=content,
                execution_time=execution_time,
                tokens_used=tokens_used
            )
            
            yield ("", result)
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = str(e)
            
            yield (self._format_chat_message(
                f"❌ {step_name} failed: {error_msg}", 
                step_id=step_id, 
                phase="error"
            ), None)
            
            result = StepResult(
                step_id=step_id,
                step_name=step_name,
                step_type=step_type,
                success=False,
                content="",
                error=error_msg,
                execution_time=execution_time,
                tokens_used=0
            )
            
            yield ("", result)

    async def _execute_step(
        self, 
        session: GenerationSession, 
        step_config: Dict[str, Any], 
        previous_outputs: Dict[str, str]
    ) -> StepResult:
        """Execute a single generation step"""
        
        start_time = time.time()
        step_id = step_config.get("id", "unknown_step")
        step_name = step_config.get("name", "Unknown Step")
        step_type = step_config.get("type", "unknown")
        
        # Log step start
        await logging_service.log_system_event(
            level=LogLevel.INFO,
            category=LogCategory.SYSTEM_EVENT,
            message=f"Step execution started: {step_name}",
            details={
                "session_id": session.session_id,
                "step_id": step_id,
                "step_name": step_name,
                "step_type": step_type,
                "pipeline_name": session.pipeline_name,
                "step_number": len(session.steps_completed) + 1,
                "total_steps": getattr(session, '_total_steps', 0)
            },
            user_id=session.user_id,
            session_id=session.session_id,
            api_key_id=getattr(session, 'api_key_id', None)
        )
        
        logger.info(
            f"Executing step {step_id} for session {session.session_id}",
            extra={
                'session_id': session.session_id,
                'step_id': step_id,
                'step_name': step_name,
                'user_id': session.user_id
            }
        )
        
        try:
            # Validate step configuration
            if not step_id:
                raise StepExecutionError(
                    "Step configuration missing required 'id' field",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    details={"step_config": step_config}
                )
            
            prompt_template_name = step_config.get("prompt_template")
            if not prompt_template_name:
                raise StepExecutionError(
                    f"Step {step_id} missing prompt_template configuration",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"step_config": step_config}
                )
            
            # Load prompt template
            try:
                prompt_config = load_claude_prompt(prompt_template_name)
                if not prompt_config:
                    raise TemplateProcessingError(
                        f"Failed to load prompt template: {prompt_template_name}",
                        user_id=session.user_id,
                        session_id=session.session_id,
                        step_id=step_id,
                        details={"template_name": prompt_template_name}
                    )
            except FileNotFoundError as e:
                raise TemplateProcessingError(
                    f"Prompt template not found: {prompt_template_name}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"template_name": prompt_template_name, "error": str(e)}
                )
            except Exception as e:
                raise TemplateProcessingError(
                    f"Error loading prompt template {prompt_template_name}: {str(e)}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"template_name": prompt_template_name, "error": str(e)}
                )
            
            # Prepare template variables
            try:
                template_vars = {
                    "prompt": session.prompt or "",
                    "original_prompt": session.prompt or "",
                    "sample_input_section": f"\nSample Input: {session.sample_input}" if session.sample_input else "",
                    "expected_output_section": f"\nExpected Output: {session.expected_output}" if session.expected_output else "",
                }
                
                # Add previous step outputs to template vars  
                for output_id, output_content in previous_outputs.items():
                    if output_content:  # Only add non-empty outputs
                        # Create both the cleaned name and keep the original
                        cleaned_name = output_id.replace("step", "").replace("_", "")
                        template_vars[cleaned_name] = output_content
                        template_vars[output_id] = output_content  # Keep original key too
                    
                # Special handling for specific steps with fallbacks
                if step_id == "step1_analysis_design":
                    # First step, no special handling needed
                    pass
                elif step_id == "step2_implementation":
                    template_vars["analysis_design"] = previous_outputs.get("step1_analysis_design",
                        f"Basic requirements analysis and design based on: {session.prompt}")
                elif step_id == "step3_testing":
                    # Testing step needs specific variable names
                    template_vars["implemented_code"] = previous_outputs.get("step2_implementation",
                        "async def run(file_bytes=None, input_data=None):\n    return {'result': 'API implementation', 'message': 'success'}")
                    template_vars["structure_design"] = previous_outputs.get("step1_analysis_design",
                        f"Basic requirements analysis and design based on: {session.prompt}")
                    template_vars["requirements_analysis"] = previous_outputs.get("step1_analysis_design",
                        f"Requirements analysis: {session.prompt}")
                    template_vars["original_prompt"] = session.prompt or ""
                        
            except Exception as e:
                raise TemplateProcessingError(
                    f"Error preparing template variables for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={"error": str(e)}
                )
            
            # Format prompts
            try:
                system_prompt, user_prompt = format_claude_prompt(prompt_config, **template_vars)
                
                if not system_prompt or not user_prompt:
                    raise PromptBuildError(
                        f"Empty prompts generated for step {step_id}",
                        user_id=session.user_id,
                        request_id=session.session_id,
                        api_slug=f"multi_step_{step_id}",
                        model_name="claude",
                        details={"template_name": prompt_template_name}
                    )
                    
            except KeyError as e:
                raise TemplateProcessingError(
                    f"Missing template variable for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    session_id=session.session_id,
                    step_id=step_id,
                    details={
                        "missing_variable": str(e),
                        "available_variables": list(template_vars.keys()),
                        "template_name": prompt_template_name
                    }
                )
            except Exception as e:
                raise PromptBuildError(
                    f"Error formatting prompts for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    request_id=session.session_id,
                    api_slug=f"multi_step_{step_id}",
                    model_name="claude",
                    details={"template_name": prompt_template_name, "error": str(e)}
                )
            
            # Make Claude API call
            try:
                api_start_time = time.time()
                response = await claude_service._make_claude_request(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    user_id=session.user_id,
                    api_key_id=session.api_key_id,
                    operation_type=step_config.get("operation_type", "multi_step_generation"),
                    api_slug=f"multi_step_{step_id}"
                )
                api_duration = (time.time() - api_start_time) * 1000  # Convert to ms
                
                if not response:
                    raise LLMAPIError(
                        f"Empty response from Claude API for step {step_id}",
                        user_id=session.user_id,
                        request_id=session.session_id,
                        api_slug=f"multi_step_{step_id}",
                        model_name="claude"
                    )
                
                # Log successful LLM call
                await logging_service.log_llm_call(
                    service_type="claude",
                    model_name="claude",
                    operation_type=step_config.get("operation_type", "multi_step_generation"),
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    prompt_length=len(system_prompt) + len(user_prompt),
                    response_content=response,
                    response_length=len(response),
                    input_tokens=None,  # Claude service should handle token calculation
                    output_tokens=None,
                    total_tokens=len(response) // 4,  # Rough estimate
                    estimated_cost_cents=None,  # Claude service should handle cost calculation
                    duration_ms=int(api_duration),
                    user_id=session.user_id,
                    api_key_id=session.api_key_id,
                    api_slug=f"multi_step_{step_id}",
                    success=True,
                    operation_context={
                        "session_id": session.session_id,
                        "step_id": step_id,
                        "step_name": step_name,
                        "step_type": step_type,
                        "pipeline_name": session.pipeline_name,
                        "step_number": len(session.steps_completed) + 1
                    },
                    request_id=session.session_id
                )
                    
            except LLMAPIError:
                # Re-raise LLM API errors
                raise
            except Exception as e:
                raise LLMAPIError(
                    f"Claude API request failed for step {step_id}: {str(e)}",
                    user_id=session.user_id,
                    request_id=session.session_id,
                    api_slug=f"multi_step_{step_id}",
                    model_name="claude",
                    details={"error": str(e), "error_type": type(e).__name__}
                )
            
            execution_time = time.time() - start_time
            
            # Estimate tokens used (rough approximation)
            tokens_used = len(response) // 4  # Rough estimate: 1 token ≈ 4 characters
            
            # Log step completion
            await logging_service.log_system_event(
                level=LogLevel.INFO,
                category=LogCategory.SYSTEM_EVENT,
                message=f"Step execution completed: {step_name}",
                details={
                    "session_id": session.session_id,
                    "step_id": step_id,
                    "step_name": step_name,
                    "step_type": step_type,
                    "pipeline_name": session.pipeline_name,
                    "execution_time": execution_time,
                    "response_length": len(response),
                    "tokens_used": tokens_used,
                    "success": True,
                    "step_number": len(session.steps_completed) + 1
                },
                user_id=session.user_id,
                session_id=session.session_id,
                api_key_id=getattr(session, 'api_key_id', None),
                duration_ms=int(execution_time * 1000)
            )
            
            logger.info(
                f"Step {step_id} completed successfully in {execution_time:.2f}s",
                extra={
                    'session_id': session.session_id,
                    'step_id': step_id,
                    'execution_time': execution_time,
                    'response_length': len(response),
                    'tokens_used': tokens_used
                }
            )
            logger.debug(f"Response preview: {response[:200]}...")
            
            # For implementation steps, extract code from response
            content = response
            if step_id == "step2_implementation":
                try:
                    # Use claude_service to extract code from response
                    extracted_code = claude_service._extract_code_from_response(response)
                    if extracted_code:
                        logger.info(f"Extracted code from {step_id}: {len(extracted_code)} characters")
                        content = extracted_code
                    else:
                        logger.warning(f"No code found in {step_id} response, using raw response")
                        # Still use the raw response rather than failing
                        content = response
                except Exception as e:
                    logger.warning(f"Code extraction failed for {step_id}: {e}, using raw response")
                    # Don't fail the step for extraction issues, use raw response
                    content = response
            
            return StepResult(
                step_id=step_id,
                step_name=step_name,
                step_type=step_type,
                success=True,
                content=content,
                execution_time=execution_time,
                tokens_used=tokens_used
            )
            
        except (MultiStepGenerationError, LLMBaseError) as e:
            # Re-raise our custom exceptions with timing info
            execution_time = time.time() - start_time
            
            # Log step failure
            await logging_service.log_system_event(
                level=LogLevel.ERROR,
                category=LogCategory.ERROR,
                message=f"Step execution failed: {step_name}",
                details={
                    "session_id": session.session_id,
                    "step_id": step_id,
                    "step_name": step_name,
                    "step_type": step_type,
                    "pipeline_name": session.pipeline_name,
                    "execution_time": execution_time,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "success": False,
                    "step_number": len(session.steps_completed) + 1
                },
                user_id=session.user_id,
                session_id=session.session_id,
                api_key_id=getattr(session, 'api_key_id', None),
                error_type=type(e).__name__,
                duration_ms=int(execution_time * 1000)
            )
            
            # Log to LLM error logs if it's an LLM-related error
            if isinstance(e, LLMBaseError):
                await logging_service.log_llm_error(e, additional_details={
                    "operation": "step_execution",
                    "step_id": step_id,
                    "step_name": step_name,
                    "step_type": step_type,
                    "pipeline_name": session.pipeline_name,
                    "execution_time": execution_time
                })
            
            logger.error(
                f"Step {step_id} failed after {execution_time:.2f}s: {str(e)}",
                extra={
                    'session_id': session.session_id,
                    'step_id': step_id,
                    'error_type': type(e).__name__,
                    'execution_time': execution_time
                }
            )
            
            return StepResult(
                step_id=step_id,
                step_name=step_name,
                step_type=step_type,
                success=False,
                content="",
                error=str(e),
                execution_time=execution_time,
                tokens_used=0
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            error_msg = f"Unexpected error in step {step_id}: {str(e)}"
            
            # Log unexpected step failure
            await logging_service.log_system_event(
                level=LogLevel.ERROR,
                category=LogCategory.ERROR,
                message=f"Step execution failed with unexpected error: {step_name}",
                details={
                    "session_id": session.session_id,
                    "step_id": step_id,
                    "step_name": step_name,
                    "step_type": step_type,
                    "pipeline_name": session.pipeline_name,
                    "execution_time": execution_time,
                    "error_type": type(e).__name__,
                    "error_message": error_msg,
                    "success": False,
                    "step_number": len(session.steps_completed) + 1,
                    "unexpected_error": True
                },
                user_id=session.user_id,
                session_id=session.session_id,
                api_key_id=getattr(session, 'api_key_id', None),
                error_type=type(e).__name__,
                duration_ms=int(execution_time * 1000)
            )
            
            # Log to error logs
            await logging_service.log_error_from_exception(
                error_type=type(e).__name__,
                error_message=error_msg,
                user_id=session.user_id,
                request_id=session.session_id,
                api_slug=f"multi_step_{step_id}",
                details={
                    "operation": "step_execution",
                    "step_id": step_id,
                    "step_name": step_name,
                    "step_type": step_type,
                    "pipeline_name": session.pipeline_name,
                    "execution_time": execution_time,
                    "unexpected_error": True
                }
            )
            
            logger.error(
                f"Step {step_id} failed after {execution_time:.2f}s: {error_msg}",
                extra={
                    'session_id': session.session_id,
                    'step_id': step_id,
                    'error_type': type(e).__name__,
                    'execution_time': execution_time
                },
                exc_info=True
            )
            
            return StepResult(
                step_id=step_id,
                step_name=step_name,
                step_type=step_type,
                success=False,
                content="",
                error=error_msg,
                execution_time=execution_time,
                tokens_used=0
            )
            
    def _extract_final_code(self, step_outputs: Dict[str, str]) -> Optional[str]:
        """Extract the final code from step outputs"""
        logger.info(f"Extracting final code from step outputs: {list(step_outputs.keys())}")
        
        # Implementation step contains the final code
        if "step2_implementation" in step_outputs:
            code = step_outputs["step2_implementation"]
            logger.info(f"Found implementation code: {len(code) if code else 0} characters")
            return code
        
        logger.warning(f"No final code found in step outputs: {list(step_outputs.keys())}")
        return None
    
    def _extract_final_documentation(self, step_outputs: Dict[str, str]) -> Optional[str]:
        """Extract the final documentation from step outputs"""
        # Testing step contains documentation
        if "step3_testing" in step_outputs:
            return step_outputs["step3_testing"]
        return None
    
    def _format_sse_event(self, event_type: str, data: Dict[str, Any]) -> str:
        """Format data as SSE event"""
        event_data = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            "data": data
        }
        return f"data: {json.dumps(event_data)}\n\n"
    
    def _format_chat_message(self, message: str, step_id: str = None, phase: str = None, typing_delay: float = 1.0) -> str:
        """Format a chat message event with typing indicator simulation"""
        chat_data = {
            "message": message,
            "step_id": step_id,
            "phase": phase,
            "typing_delay": typing_delay,
            "is_ai": True,
            "message_type": "status_update"
        }
        return self._format_sse_event(StreamEvent.CHAT_MESSAGE, chat_data)
    
    def _format_step_phase(self, step_id: str, phase: str, description: str, progress: float = None) -> str:
        """Format a step phase update event"""
        phase_data = {
            "step_id": step_id,
            "phase": phase,
            "description": description,
            "progress": progress,
            "timestamp": datetime.now().isoformat()
        }
        return self._format_sse_event(StreamEvent.STEP_PHASE, phase_data)
    
    def _get_step_chat_messages(self, step_id: str, step_name: str) -> Dict[str, str]:
        """Get chat messages for different phases of step execution"""
        
        # Default messages that work for any step
        default_messages = {
            "starting": f"🚀 Starting {step_name}...",
            "loading_template": "📝 Loading prompt template and configuration...",
            "preparing_prompts": "🔧 Preparing AI prompts with your requirements...",
            "calling_ai": "🤖 Sending request to AI model...",
            "thinking": "🧠 AI is analyzing and processing your request...",
            "processing_response": "⚡ Processing AI response...",
            "completing": f"✅ {step_name} completed successfully!",
        }
        
        # Step-specific chat messages - simplified
        step_specific_messages = {
            "step1_analysis_design": {
                "starting": "🔍 Analyzing your requirements and designing API structure...",
                "calling_ai": "🧠 AI is analyzing your requirements and designing the optimal structure...",
                "processing_response": "📊 Processing analysis and design...",
                "completing": "✅ Analysis and design completed!",
            },
            "step2_implementation": {
                "starting": "⚡ Implementing your API based on the design...",
                "calling_ai": "🤖 AI is generating your API implementation code...",
                "processing_response": "🔧 Processing and validating the generated code...",
                "completing": "✅ API implementation completed!",
            },
            "step3_testing": {
                "starting": "📚 Generating comprehensive tests and documentation...",
                "calling_ai": "🧪 AI is creating tests and documentation for your API...",
                "processing_response": "📋 Processing tests and documentation...",
                "completing": "✅ Tests and documentation completed!",
            },
            "step4_optimization": {
                "starting": "⚡ Optimizing your API for performance and security...",
                "calling_ai": "🔧 AI is optimizing your API...",
                "processing_response": "⚡ Processing optimizations...",
                "completing": "✅ API optimization completed!",
            }
        }
        
        # Return step-specific messages if available, otherwise use defaults
        if step_id in step_specific_messages:
            return step_specific_messages[step_id]
        else:
            return default_messages
    
    def get_session_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a generation session"""
        
        try:
            if not session_id:
                logger.warning("get_session_status called with empty session_id")
                return None
                
            session = self.active_sessions.get(session_id)
            if not session:
                logger.info(f"Session not found: {session_id}")
                return None
                
            return {
                "session_id": session_id,
                "user_id": session.user_id,
                "pipeline_name": session.pipeline_name,
                "mode": session.mode.value if hasattr(session.mode, 'value') else str(session.mode),
                "started_at": session.started_at.isoformat() if session.started_at else None,
                "is_completed": session.is_completed,
                "progress_percentage": session.progress_percentage,
                "steps_completed": len(session.steps_completed),
                "total_steps": getattr(session, '_total_steps', 0),
                "current_step": session.current_step,
                "total_tokens_used": session.total_tokens_used,
                "total_execution_time": session.total_execution_time,
                "error": session.error,
                "completed_at": session.completed_at.isoformat() if session.completed_at else None
            }
            
        except Exception as e:
            logger.error(f"Error getting session status for {session_id}: {str(e)}", exc_info=True)
            return None
    
    async def cleanup_session(self, session_id: str) -> bool:
        """Clean up a completed session"""
        
        try:
            if not session_id:
                logger.warning("cleanup_session called with empty session_id")
                return False
                
            if session_id in self.active_sessions:
                session = self.active_sessions[session_id]
                user_id = getattr(session, 'user_id', 'unknown')
                
                try:
                    del self.active_sessions[session_id]
                    
                    # Log session cleanup
                    await logging_service.log_system_event(
                        level=LogLevel.INFO,
                        category=LogCategory.SYSTEM_EVENT,
                        message="Multi-step generation session cleaned up",
                        details={
                            "session_id": session_id,
                            "user_id": user_id,
                            "remaining_sessions": len(self.active_sessions),
                            "operation": "session_cleanup"
                        },
                        user_id=user_id,
                        session_id=session_id
                    )
                    
                    logger.info(
                        f"Cleaned up session {session_id}",
                        extra={
                            'session_id': session_id,
                            'user_id': user_id,
                            'remaining_sessions': len(self.active_sessions)
                        }
                    )
                    return True
                except Exception as e:
                    logger.error(f"Error deleting session {session_id}: {str(e)}")
                    raise SessionCleanupError(
                        f"Failed to cleanup session: {str(e)}",
                        user_id=user_id,
                        session_id=session_id,
                        details={"error": str(e)}
                    )
            else:
                logger.warning(f"Attempted to cleanup non-existent session: {session_id}")
                return False
                
        except SessionCleanupError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Unexpected error during session cleanup for {session_id}: {str(e)}", exc_info=True)
            raise SessionCleanupError(
                f"Unexpected error during session cleanup: {str(e)}",
                user_id="unknown",
                session_id=session_id,
                details={"error": str(e), "error_type": type(e).__name__}
            )
    
    async def get_available_pipelines(self) -> Dict[str, Any]:
        """Get information about available pipelines"""
        
        try:
            if not self.config:
                logger.error("Configuration service not available")
                raise SessionConfigurationError(
                    "Configuration service not available",
                    user_id="",
                    details={"config_service": "MultiStepConfig"}
                )
                
            pipeline_info = self.config.get_pipeline_info()
            if not pipeline_info:
                logger.warning("No pipeline information available")
                
                await logging_service.log_system_event(
                    level=LogLevel.WARNING,
                    category=LogCategory.SYSTEM_EVENT,
                    message="No pipeline information available",
                    details={
                        "operation": "get_available_pipelines",
                        "config_service_available": bool(self.config)
                    }
                )
                return {}
            
            # Log successful pipeline retrieval
            await logging_service.log_system_event(
                level=LogLevel.INFO,
                category=LogCategory.SYSTEM_EVENT,
                message="Pipeline information retrieved",
                details={
                    "operation": "get_available_pipelines",
                    "pipelines_count": len(pipeline_info),
                    "available_pipelines": list(pipeline_info.keys()) if isinstance(pipeline_info, dict) else []
                }
            )
                
            return pipeline_info
            
        except SessionConfigurationError:
            # Re-raise our custom exceptions
            raise
        except Exception as e:
            logger.error(f"Error getting available pipelines: {str(e)}", exc_info=True)
            raise SessionConfigurationError(
                f"Failed to get pipeline information: {str(e)}",
                user_id="",
                details={"error": str(e), "error_type": type(e).__name__}
            )

# Create service instance
multi_step_generation_service = MultiStepGenerationService()
