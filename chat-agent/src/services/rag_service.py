#!/usr/bin/env python3
"""
示例RAG服务
"""
from w_agent.core.decorators import PostConstruct, PreDestroy
from w_agent.config.dynamic_config import DynamicConfigManager
from w_agent.observability.logging import LogEnable
import openai
import asyncio


class RAGService:
    """示例RAG服务"""
    
    def __init__(self, config_manager, llm_service, redis_service):
        """初始化"""
        self.config_manager = config_manager
        self.llm_service = llm_service
        self.redis_service = redis_service
        
        self.embedding_model = None
        self.vector_store = None
        self.chunk_size = None
        self.chunk_overlap = None
        self.top_k = None
        
        # 嵌入向量缓存
        self._embedding_cache = {}
        # 文档缓存
        self._document_cache = {}
        
        # 绑定配置
        self.config_manager.bind("rag.embedding_model", self, "embedding_model")
        self.config_manager.bind("rag.vector_store", self, "vector_store")
        self.config_manager.bind("rag.chunk_size", self, "chunk_size")
        self.config_manager.bind("rag.chunk_overlap", self, "chunk_overlap")
        self.config_manager.bind("rag.top_k", self, "top_k")
    
    @PostConstruct(order=1)
    def init(self):
        """初始化后执行"""
        print("RAGService initialized")
    
    @PreDestroy(order=1)
    def destroy(self):
        """销毁前执行"""
        print("RAGService destroyed")
    
    @LogEnable(log_args=True, log_result=False, log_duration=True)
    async def embed_text(self, text):
        """生成文本嵌入"""
        # 检查缓存
        if text in self._embedding_cache:
            return self._embedding_cache[text]
            
        if not self.llm_service.client:
            return None
        try:
            response = await asyncio.to_thread(
                self.llm_service.client.embeddings.create,
                input=text,
                model=self.embedding_model
            )
            embedding = response.data[0].embedding
            # 缓存结果
            self._embedding_cache[text] = embedding
            return embedding
        except Exception as e:
            print(f"Embed text failed: {e}")
            return None
    
    @LogEnable(log_args=True, log_result=True, log_duration=True)
    async def store_document(self, document_id, text, metadata=None):
        """存储文档"""
        try:
            # 检查缓存
            if document_id in self._document_cache:
                return True
            
            # 生成嵌入
            embedding = await self.embed_text(text)
            if not embedding:
                return False
            
            # 存储到向量存储
            if self.vector_store == "redis":
                # 使用Redis存储
                key = f"doc:{document_id}"
                data = {
                    "text": text,
                    "embedding": str(embedding),
                    "metadata": metadata or {}
                }
                success = self.redis_service.set(key, str(data))
                if success:
                    # 缓存文档
                    self._document_cache[document_id] = data
                return success
            else:
                print(f"Unsupported vector store: {self.vector_store}")
                return False
        except Exception as e:
            print(f"Store document failed: {e}")
            return False
    
    @LogEnable(log_args=True, log_result=False, log_duration=True)
    async def retrieve_documents(self, query, top_k=None):
        """检索相关文档"""
        try:
            # 生成查询嵌入
            query_embedding = await self.embed_text(query)
            if not query_embedding:
                return []
            
            # 检查缓存
            cache_key = f"query:{query}:{top_k or self.top_k}"
            if cache_key in self._document_cache:
                return self._document_cache[cache_key]
            
            # 从向量存储中检索
            if self.vector_store == "redis" and self.redis_service.client:
                # 使用Redis的向量搜索功能
                documents = await self._retrieve_from_redis(query_embedding, top_k or self.top_k)
            elif self.vector_store == "memory":
                # 使用内存存储（用于测试）
                documents = await self._retrieve_from_memory(query_embedding, top_k or self.top_k)
            else:
                print(f"Unsupported vector store: {self.vector_store}")
                return []
            
            # 缓存结果
            self._document_cache[cache_key] = documents
            return documents
        except Exception as e:
            print(f"Retrieve documents failed: {e}")
            return []
    
    async def _retrieve_from_redis(self, query_embedding, top_k):
        """从Redis中检索文档"""
        try:
            # 使用Redis的向量搜索功能
            # 实际项目中应该使用Redis的FT.SEARCH命令
            # 这里使用简化实现，遍历所有文档并计算相似度
            
            # 获取所有文档键
            keys = self.redis_service.client.keys("doc:*")
            documents = []
            
            if keys:
                import numpy as np
                
                # 计算余弦相似度
                def cosine_similarity(a, b):
                    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
                
                # 批量获取文档数据
                data_strs = self.redis_service.client.mget(keys)
                
                # 遍历所有文档并计算相似度
                for key, data_str in zip(keys, data_strs):
                    try:
                        if data_str:
                            import ast
                            data = ast.literal_eval(data_str)
                            doc_embedding = data.get('embedding')
                            if doc_embedding:
                                # 转换嵌入为列表
                                if isinstance(doc_embedding, str):
                                    doc_embedding = ast.literal_eval(doc_embedding)
                                similarity = cosine_similarity(query_embedding, doc_embedding)
                                documents.append((data, similarity))
                    except Exception as e:
                        print(f"Process document {key} failed: {e}")
                
                # 按相似度排序并返回前top_k个
                documents.sort(key=lambda x: x[1], reverse=True)
                top_documents = [doc for doc, _ in documents[:top_k]]
                return top_documents
            else:
                return []
        except Exception as e:
            print(f"Retrieve from Redis failed: {e}")
            return []
    
    async def _retrieve_from_memory(self, query_embedding, top_k):
        """从内存中检索文档（用于测试）"""
        try:
            # 计算相似度并返回最相似的文档
            import numpy as np
            
            # 模拟内存存储的文档
            # 实际项目中应该维护一个内存中的文档和嵌入列表
            memory_documents = getattr(self, '_memory_documents', [])
            
            if not memory_documents:
                return []
            
            # 计算余弦相似度
            def cosine_similarity(a, b):
                return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
            
            # 计算查询向量与每个文档向量的相似度
            similarities = []
            for doc in memory_documents:
                doc_embedding = doc.get('embedding')
                if doc_embedding:
                    try:
                        # 转换嵌入为列表
                        if isinstance(doc_embedding, str):
                            import ast
                            doc_embedding = ast.literal_eval(doc_embedding)
                        similarity = cosine_similarity(query_embedding, doc_embedding)
                        similarities.append((doc, similarity))
                    except Exception as e:
                        print(f"Calculate similarity failed: {e}")
            
            # 按相似度排序并返回前top_k个
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_documents = [doc for doc, _ in similarities[:top_k]]
            
            return top_documents
        except Exception as e:
            print(f"Retrieve from memory failed: {e}")
            return []
    
    @LogEnable(log_args=True, log_result=False, log_duration=True)
    async def generate_with_rag(self, query, context=None):
        """使用RAG生成回复"""
        try:
            # 检索相关文档
            if not context:
                context = await self.retrieve_documents(query)
            
            # 构建提示
            context_str = "\n".join([doc.get("text", "") for doc in context])
            prompt = f"基于以下上下文回答问题：\n{context_str}\n\n问题：{query}"
            
            # 调用LLM生成回复
            system_prompt = "你是一个基于检索增强的聊天机器人，请根据提供的上下文回答用户问题，不要使用上下文之外的信息。"
            return await self.llm_service.generate(prompt, system_prompt)
        except Exception as e:
            print(f"Generate with RAG failed: {e}")
            return "抱歉，生成回复失败"
