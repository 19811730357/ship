# 对话记忆方案

## 如果需要 Agent 记住对话历史

### 方案1：添加对话历史表

在 MySQL 中添加新表：

```sql
CREATE TABLE conversation_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(50),
    user_message TEXT,
    agent_response TEXT,
    context_data TEXT,  -- JSON 格式的上下文
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_session (session_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

### 方案2：使用 LangChain Memory

修改 `agent.py`，添加记忆功能：

```python
from langchain.memory import ConversationBufferMemory

class BillingAgent:
    def __init__(self, accounting_entity: str, use_mock: bool = False):
        # 添加记忆
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        # 创建带记忆的链
        self.chain = (
            {
                "accounting_entity": lambda x: self.accounting_entity,
                "material_content": lambda x: x["material_content"],
                "ledger_summary": lambda x: x["ledger_summary"],
                "chat_history": lambda x: self.memory.load_memory_variables({})["chat_history"]
            }
            | self.prompt
            | self.llm
            | self.output_parser
        )
```

### 方案3：Session-based Memory

在 Streamlit 中使用 `st.session_state`：

```python
# 初始化会话记忆
if 'conversation_history' not in st.session_state:
    st.session_state.conversation_history = []

# 保存对话
st.session_state.conversation_history.append({
    'timestamp': datetime.now(),
    'user_input': uploaded_files,
    'agent_decision': results
})

# 显示历史
with st.expander("对话历史"):
    for item in st.session_state.conversation_history:
        st.write(f"**{item['timestamp']}**")
        st.json(item['agent_decision'])
```

---

## 🎯 当前系统的记忆能力

### ✅ 已实现（数据库级别）
1. **账本记录记忆** - 所有费用记录永久保存
2. **处理历史记忆** - 每次决策过程完整记录
3. **文档指纹记忆** - 避免重复处理同一文档
4. **跨会话记忆** - 重启后数据依然存在

### ❌ 未实现（对话级别）
1. **对话历史记忆** - Agent 不记得之前的对话
2. **用户偏好记忆** - 不记得用户的特殊要求
3. **上下文理解** - 不能基于之前的对话理解新请求

---

## 💡 推荐做法

**对于账单处理系统**，当前的 **数据库记忆已经足够**：
- ✅ 记住所有处理过的单据
- ✅ 记住每次决策
- ✅ 支持增量更新
- ✅ 完整审计追踪

**如果需要对话记忆**，可以添加：
1. 会话管理（记住用户是谁）
2. 对话历史（记住说过什么）
3. 用户偏好（记住用户习惯）

---

## 🔧 快速验证当前记忆能力

在 Navicat 中查询：

```sql
-- 查看所有记录（记忆）
SELECT 
    record_id,
    charge_name,
    amount,
    currency,
    document_number,
    created_at,
    updated_at
FROM ledger_records
ORDER BY updated_at DESC;

-- 查看处理历史（记忆）
SELECT 
    operation,
    model_suggestion,
    final_decision,
    model_reasoning,
    processed_at
FROM processing_history
ORDER BY processed_at DESC
LIMIT 10;
```

---

**你说的"记忆问题"具体指什么？是数据持久化还是对话历史？**
