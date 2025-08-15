import json
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc
from .database import (
    Base, AsyncSessionLocal, database_service,
    SystemLogDB, HTTPRequestLogDB, LLMCallLogDB, ChatMessageLogDB
)
from ..models import User
from enum import Enum

# Configure logger
logger = logging.getLogger(__name__)

class LogLevel(str, Enum):
    """Log level enumeration"""
    DEBUG = "DEBUG"
    INFO = "INFO" 
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

class LogCategory(str, Enum):
    """Log category enumeration"""
    HTTP_REQUEST = "HTTP_REQUEST"
    LLM_CALL = "LLM_CALL"
    CHAT_MESSAGE = "CHAT_MESSAGE"
    API_EXECUTION = "API_EXECUTION"
    AUTHENTICATION = "AUTHENTICATION"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    DATABASE_OPERATION = "DATABASE_OPERATION"
    FILE_OPERATION = "FILE_OPERATION"
    ERROR = "ERROR"

class LoggingService:
    """Comprehensive logging service for the AI API Generator"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    async def log_system_event(
        self,
        level: LogLevel,
        category: LogCategory,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        status_code: Optional[int] = None,
        duration_ms: Optional[int] = None,
        memory_usage_mb: Optional[float] = None,
        error_type: Optional[str] = None,
        error_traceback: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """Log a system event with comprehensive details"""
        
        log_id = str(uuid.uuid4())
        
        try:
            async with AsyncSessionLocal() as session:
                log_entry = SystemLogDB(
                    id=log_id,
                    level=level.value,
                    category=category.value,
                    message=message,
                    details=json.dumps(details) if details else None,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    session_id=session_id,
                    request_id=request_id,
                    endpoint=endpoint,
                    method=method,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    memory_usage_mb=memory_usage_mb,
                    error_type=error_type,
                    error_traceback=error_traceback,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                
                session.add(log_entry)
                await session.commit()
                
        except Exception as e:
            # Fallback to standard logging if database fails
            self.logger.error(f"Failed to log to database: {str(e)}")
            self.logger.log(
                getattr(logging, level.value),
                f"[{category.value}] {message} - Details: {details}"
            )
            
        return log_id
    
    async def log_http_request(
        self,
        request_id: str,
        method: str,
        endpoint: str,
        full_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        query_params: Optional[Dict[str, Any]] = None,
        body: Optional[Union[str, Dict[str, Any]]] = None,
        body_size: Optional[int] = None,
        status_code: Optional[int] = None,
        response_headers: Optional[Dict[str, str]] = None,
        response_body: Optional[Union[str, Dict[str, Any]]] = None,
        response_size: Optional[int] = None,
        duration_ms: Optional[int] = None,
        user_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: Optional[bool] = None,
        error_message: Optional[str] = None
    ) -> str:
        """Log HTTP request details"""
        
        log_id = str(uuid.uuid4())
        
        try:
            # Sanitize sensitive data from headers
            safe_headers = self._sanitize_headers(headers) if headers else None
            safe_response_headers = self._sanitize_headers(response_headers) if response_headers else None
            
            # Limit body size for logging
            safe_body = self._limit_body_size(body) if body else None
            safe_response_body = self._limit_body_size(response_body) if response_body else None
            
            async with AsyncSessionLocal() as session:
                log_entry = HTTPRequestLogDB(
                    id=log_id,
                    request_id=request_id,
                    method=method,
                    endpoint=endpoint,
                    full_url=full_url,
                    headers=json.dumps(safe_headers) if safe_headers else None,
                    query_params=json.dumps(query_params) if query_params else None,
                    body=json.dumps(safe_body) if isinstance(safe_body, dict) else str(safe_body) if safe_body else None,
                    body_size=body_size,
                    status_code=status_code,
                    response_headers=json.dumps(safe_response_headers) if safe_response_headers else None,
                    response_body=json.dumps(safe_response_body) if isinstance(safe_response_body, dict) else str(safe_response_body) if safe_response_body else None,
                    response_size=response_size,
                    duration_ms=duration_ms,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    success=success,
                    error_message=error_message
                )
                
                session.add(log_entry)
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to log HTTP request: {str(e)}")
            
        return log_id
    
    async def log_llm_call(
        self,
        service_type: str,
        model_name: str,
        operation_type: str,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        prompt_length: Optional[int] = None,
        response_content: Optional[str] = None,
        response_length: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        estimated_cost_cents: Optional[int] = None,
        duration_ms: Optional[int] = None,
        user_id: Optional[str] = None,
        api_key_id: Optional[str] = None,
        api_slug: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
        operation_context: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None
    ) -> str:
        """Log LLM API call details"""
        
        log_id = str(uuid.uuid4())
        
        try:
            # Limit prompt and response content for logging
            safe_system_prompt = self._limit_text_size(system_prompt, 5000) if system_prompt else None
            safe_user_prompt = self._limit_text_size(user_prompt, 5000) if user_prompt else None
            safe_response_content = self._limit_text_size(response_content, 10000) if response_content else None
            
            async with AsyncSessionLocal() as session:
                log_entry = LLMCallLogDB(
                    id=log_id,
                    request_id=request_id,
                    service_type=service_type,
                    model_name=model_name,
                    operation_type=operation_type,
                    system_prompt=safe_system_prompt,
                    user_prompt=safe_user_prompt,
                    prompt_length=prompt_length,
                    response_content=safe_response_content,
                    response_length=response_length,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    estimated_cost_cents=estimated_cost_cents,
                    duration_ms=duration_ms,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    api_slug=api_slug,
                    success=success,
                    error_message=error_message,
                    operation_context=json.dumps(operation_context) if operation_context else None
                )
                
                session.add(log_entry)
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to log LLM call: {str(e)}")
            
        return log_id
    
    async def log_chat_message(
        self,
        user_id: str,
        message_type: str,
        content: str,
        session_id: Optional[str] = None,
        ai_model_used: Optional[str] = None,
        response_time_ms: Optional[int] = None,
        confidence_score: Optional[float] = None,
        conversation_id: Optional[str] = None,
        parent_message_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log chat message"""
        
        log_id = str(uuid.uuid4())
        
        try:
            # Limit content size
            safe_content = self._limit_text_size(content, 10000)
            
            async with AsyncSessionLocal() as session:
                log_entry = ChatMessageLogDB(
                    id=log_id,
                    user_id=user_id,
                    session_id=session_id,
                    message_type=message_type,
                    content=safe_content,
                    content_length=len(content),
                    ai_model_used=ai_model_used,
                    response_time_ms=response_time_ms,
                    confidence_score=confidence_score,
                    conversation_id=conversation_id,
                    parent_message_id=parent_message_id,
                    message_metadata=json.dumps(metadata) if metadata else None
                )
                
                session.add(log_entry)
                await session.commit()
                
        except Exception as e:
            self.logger.error(f"Failed to log chat message: {str(e)}")
            
        return log_id
    
    # Query Methods
    async def get_logs(
        self,
        level: Optional[LogLevel] = None,
        category: Optional[LogCategory] = None,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get system logs with filters"""
        
        try:
            async with AsyncSessionLocal() as session:
                query = select(SystemLogDB)
                
                # Apply filters
                conditions = []
                if level:
                    conditions.append(SystemLogDB.level == level.value)
                if category:
                    conditions.append(SystemLogDB.category == category.value)
                if user_id:
                    conditions.append(SystemLogDB.user_id == user_id)
                if start_time:
                    conditions.append(SystemLogDB.timestamp >= start_time)
                if end_time:
                    conditions.append(SystemLogDB.timestamp <= end_time)
                
                if conditions:
                    query = query.where(and_(*conditions))
                
                query = query.order_by(desc(SystemLogDB.timestamp)).limit(limit).offset(offset)
                
                result = await session.execute(query)
                logs = result.scalars().all()
                
                return [self._log_to_dict(log) for log in logs]
                
        except Exception as e:
            self.logger.error(f"Failed to get logs: {str(e)}")
            return []
    
    async def get_http_request_logs(
        self,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        status_code: Optional[int] = None,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get HTTP request logs with filters"""
        
        try:
            async with AsyncSessionLocal() as session:
                query = select(HTTPRequestLogDB)
                
                # Apply filters
                conditions = []
                if endpoint:
                    conditions.append(HTTPRequestLogDB.endpoint.like(f"%{endpoint}%"))
                if method:
                    conditions.append(HTTPRequestLogDB.method == method)
                if status_code:
                    conditions.append(HTTPRequestLogDB.status_code == status_code)
                if user_id:
                    conditions.append(HTTPRequestLogDB.user_id == user_id)
                if start_time:
                    conditions.append(HTTPRequestLogDB.timestamp >= start_time)
                if end_time:
                    conditions.append(HTTPRequestLogDB.timestamp <= end_time)
                
                if conditions:
                    query = query.where(and_(*conditions))
                
                query = query.order_by(desc(HTTPRequestLogDB.timestamp)).limit(limit).offset(offset)
                
                result = await session.execute(query)
                logs = result.scalars().all()
                
                return [self._http_log_to_dict(log) for log in logs]
                
        except Exception as e:
            self.logger.error(f"Failed to get HTTP request logs: {str(e)}")
            return []
    
    async def get_llm_call_logs(
        self,
        service_type: Optional[str] = None,
        model_name: Optional[str] = None,
        operation_type: Optional[str] = None,
        user_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get LLM call logs with filters"""
        
        try:
            async with AsyncSessionLocal() as session:
                query = select(LLMCallLogDB)
                
                # Apply filters
                conditions = []
                if service_type:
                    conditions.append(LLMCallLogDB.service_type == service_type)
                if model_name:
                    conditions.append(LLMCallLogDB.model_name == model_name)
                if operation_type:
                    conditions.append(LLMCallLogDB.operation_type == operation_type)
                if user_id:
                    conditions.append(LLMCallLogDB.user_id == user_id)
                if start_time:
                    conditions.append(LLMCallLogDB.timestamp >= start_time)
                if end_time:
                    conditions.append(LLMCallLogDB.timestamp <= end_time)
                
                if conditions:
                    query = query.where(and_(*conditions))
                
                query = query.order_by(desc(LLMCallLogDB.timestamp)).limit(limit).offset(offset)
                
                result = await session.execute(query)
                logs = result.scalars().all()
                
                return [self._llm_log_to_dict(log) for log in logs]
                
        except Exception as e:
            self.logger.error(f"Failed to get LLM call logs: {str(e)}")
            return []
    
    async def get_chat_message_logs(
        self,
        user_id: Optional[str] = None,
        message_type: Optional[str] = None,
        conversation_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get chat message logs with filters"""
        
        try:
            async with AsyncSessionLocal() as session:
                query = select(ChatMessageLogDB)
                
                # Apply filters
                conditions = []
                if user_id:
                    conditions.append(ChatMessageLogDB.user_id == user_id)
                if message_type:
                    conditions.append(ChatMessageLogDB.message_type == message_type)
                if conversation_id:
                    conditions.append(ChatMessageLogDB.conversation_id == conversation_id)
                if start_time:
                    conditions.append(ChatMessageLogDB.timestamp >= start_time)
                if end_time:
                    conditions.append(ChatMessageLogDB.timestamp <= end_time)
                
                if conditions:
                    query = query.where(and_(*conditions))
                
                query = query.order_by(desc(ChatMessageLogDB.timestamp)).limit(limit).offset(offset)
                
                result = await session.execute(query)
                logs = result.scalars().all()
                
                return [self._chat_log_to_dict(log) for log in logs]
                
        except Exception as e:
            self.logger.error(f"Failed to get chat message logs: {str(e)}")
            return []
    
    async def get_log_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get logging statistics"""
        
        try:
            if not start_time:
                start_time = datetime.utcnow() - timedelta(days=7)
            if not end_time:
                end_time = datetime.utcnow()
            
            async with AsyncSessionLocal() as session:
                # System logs stats
                system_logs_count = await session.execute(
                    select(func.count(SystemLogDB.id)).where(
                        and_(
                            SystemLogDB.timestamp >= start_time,
                            SystemLogDB.timestamp <= end_time
                        )
                    )
                )
                system_logs_count = system_logs_count.scalar()
                
                # HTTP request logs stats
                http_logs_count = await session.execute(
                    select(func.count(HTTPRequestLogDB.id)).where(
                        and_(
                            HTTPRequestLogDB.timestamp >= start_time,
                            HTTPRequestLogDB.timestamp <= end_time
                        )
                    )
                )
                http_logs_count = http_logs_count.scalar()
                
                # LLM call logs stats
                llm_logs_count = await session.execute(
                    select(func.count(LLMCallLogDB.id)).where(
                        and_(
                            LLMCallLogDB.timestamp >= start_time,
                            LLMCallLogDB.timestamp <= end_time
                        )
                    )
                )
                llm_logs_count = llm_logs_count.scalar()
                
                # Chat message logs stats
                chat_logs_count = await session.execute(
                    select(func.count(ChatMessageLogDB.id)).where(
                        and_(
                            ChatMessageLogDB.timestamp >= start_time,
                            ChatMessageLogDB.timestamp <= end_time
                        )
                    )
                )
                chat_logs_count = chat_logs_count.scalar()
                
                # Error count
                error_count = await session.execute(
                    select(func.count(SystemLogDB.id)).where(
                        and_(
                            SystemLogDB.timestamp >= start_time,
                            SystemLogDB.timestamp <= end_time,
                            SystemLogDB.level == LogLevel.ERROR.value
                        )
                    )
                )
                error_count = error_count.scalar()
                
                return {
                    "period_start": start_time.isoformat(),
                    "period_end": end_time.isoformat(),
                    "total_logs": {
                        "system_logs": system_logs_count,
                        "http_requests": http_logs_count,
                        "llm_calls": llm_logs_count,
                        "chat_messages": chat_logs_count,
                        "total": system_logs_count + http_logs_count + llm_logs_count + chat_logs_count
                    },
                    "error_count": error_count
                }
                
        except Exception as e:
            self.logger.error(f"Failed to get log statistics: {str(e)}")
            return {}
    
    # Helper Methods
    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Remove sensitive information from headers"""
        sensitive_keys = {'authorization', 'cookie', 'x-api-key', 'api-key', 'token'}
        return {
            k: '***REDACTED***' if k.lower() in sensitive_keys else v
            for k, v in headers.items()
        }
    
    def _limit_body_size(self, body: Union[str, Dict[str, Any]], max_size: int = 5000) -> Union[str, Dict[str, Any]]:
        """Limit body size for logging"""
        if isinstance(body, str):
            return body[:max_size] + '...' if len(body) > max_size else body
        elif isinstance(body, dict):
            body_str = json.dumps(body)
            if len(body_str) > max_size:
                return {"truncated": True, "original_size": len(body_str), "preview": body_str[:max_size]}
            return body
        return body
    
    def _limit_text_size(self, text: str, max_size: int = 5000) -> str:
        """Limit text size for logging"""
        return text[:max_size] + '...' if len(text) > max_size else text
    
    def _log_to_dict(self, log: SystemLogDB) -> Dict[str, Any]:
        """Convert SystemLogDB to dictionary"""
        return {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "level": log.level,
            "category": log.category,
            "message": log.message,
            "details": json.loads(log.details) if log.details else None,
            "user_id": log.user_id,
            "api_key_id": log.api_key_id,
            "session_id": log.session_id,
            "request_id": log.request_id,
            "endpoint": log.endpoint,
            "method": log.method,
            "status_code": log.status_code,
            "duration_ms": log.duration_ms,
            "memory_usage_mb": log.memory_usage_mb,
            "error_type": log.error_type,
            "error_traceback": log.error_traceback,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent
        }
    
    def _http_log_to_dict(self, log: HTTPRequestLogDB) -> Dict[str, Any]:
        """Convert HTTPRequestLogDB to dictionary"""
        return {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "request_id": log.request_id,
            "method": log.method,
            "endpoint": log.endpoint,
            "full_url": log.full_url,
            "headers": json.loads(log.headers) if log.headers else None,
            "query_params": json.loads(log.query_params) if log.query_params else None,
            "body": json.loads(log.body) if log.body else None,
            "body_size": log.body_size,
            "status_code": log.status_code,
            "response_headers": json.loads(log.response_headers) if log.response_headers else None,
            "response_body": json.loads(log.response_body) if log.response_body else None,
            "response_size": log.response_size,
            "duration_ms": log.duration_ms,
            "user_id": log.user_id,
            "api_key_id": log.api_key_id,
            "ip_address": log.ip_address,
            "user_agent": log.user_agent,
            "success": log.success,
            "error_message": log.error_message
        }
    
    def _llm_log_to_dict(self, log: LLMCallLogDB) -> Dict[str, Any]:
        """Convert LLMCallLogDB to dictionary"""
        return {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "request_id": log.request_id,
            "service_type": log.service_type,
            "model_name": log.model_name,
            "operation_type": log.operation_type,
            "system_prompt": log.system_prompt,
            "user_prompt": log.user_prompt,
            "prompt_length": log.prompt_length,
            "response_content": log.response_content,
            "response_length": log.response_length,
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "total_tokens": log.total_tokens,
            "estimated_cost_cents": log.estimated_cost_cents,
            "duration_ms": log.duration_ms,
            "user_id": log.user_id,
            "api_key_id": log.api_key_id,
            "api_slug": log.api_slug,
            "success": log.success,
            "error_message": log.error_message,
            "operation_context": json.loads(log.operation_context) if log.operation_context else None
        }
    
    def _chat_log_to_dict(self, log: ChatMessageLogDB) -> Dict[str, Any]:
        """Convert ChatMessageLogDB to dictionary"""
        return {
            "id": log.id,
            "timestamp": log.timestamp.isoformat(),
            "user_id": log.user_id,
            "session_id": log.session_id,
            "message_type": log.message_type,
            "content": log.content,
            "content_length": log.content_length,
            "ai_model_used": log.ai_model_used,
            "response_time_ms": log.response_time_ms,
            "confidence_score": log.confidence_score,
            "conversation_id": log.conversation_id,
            "parent_message_id": log.parent_message_id,
            "metadata": json.loads(log.message_metadata) if log.message_metadata else None
        }

# Global instance
logging_service = LoggingService()
