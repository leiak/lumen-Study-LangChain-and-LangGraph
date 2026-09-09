这个 `SummarizationMiddleware` 类是一个用于 **LangChain / LangGraph 智能体**的中间件，其核心作用是**自动压缩对话历史**，防止上下文窗口溢出。

---

### 主要功能

1. **监控 token 用量**  
   - 在每次模型调用前（`before_model` 方法），统计当前消息列表的总 token 数。
   - 如果总 token 数超过设定的阈值（`max_tokens_before_summary`），则触发摘要流程。

2. **智能截断消息**  
   - 保留最近的 `messages_to_keep` 条消息（默认 20 条），作为“上下文延续”部分。
   - 对较早的消息进行截断，但**确保不会拆散 AI 消息与对应的 Tool 消息**（即工具调用和结果需保持在同一侧），避免上下文断裂。

3. **生成摘要**  
   - 将截断下来的旧消息传入大语言模型（通过 `model` 参数指定），使用提示模板 `summary_prompt` 生成一段精炼的摘要。
   - 摘要生成前，还会对旧消息进行二次裁剪（`_trim_messages_for_summary`），避免摘要本身也超出 token 限制。

4. **重构消息列表**  
   - 删除全部旧消息（使用 `RemoveMessage(id=REMOVE_ALL_MESSAGES)`）。
   - 插入一条包含摘要的 `HumanMessage`（格式固定为“Here is a summary of the conversation to date:\n\n{summary}”）。
   - 追加保留下来的最近消息，构成新的消息历史，供后续模型调用使用。

---

### 关键参数

| 参数 | 说明 |
|------|------|
| `model` | 用于生成摘要的模型（可以是模型名称字符串或 `BaseChatModel` 实例） |
| `max_tokens_before_summary` | 触发摘要的 token 阈值；若为 `None`，则禁用摘要功能 |
| `messages_to_keep` | 摘要后保留的最新消息条数（默认 20） |
| `token_counter` | 自定义 token 计数器（默认使用 `count_tokens_approximately`） |
| `summary_prompt` | 摘要生成的提示模板（默认包含详细的角色指令） |
| `summary_prefix` | 摘要前缀（未在类中直接使用，但可供扩展） |

---

### 内部安全机制

- **避免分离 AI/Tool 配对**：截断点会向前搜索（范围 5 条消息），确保所有带有 `tool_calls` 的 AI 消息与对应的 `ToolMessage` 位于截断线的同一侧。
- **摘要内容降级**：若摘要生成失败，会返回错误信息；若旧消息过长，会先用 `trim_messages` 截取到 4000 token 以内，否则仅保留最后 15 条消息作为备选。

---

### 适用场景

适用于**长对话**或**工具调用频繁**的智能体应用，帮助在有限上下文窗口下保持关键信息不丢失，同时控制成本与延迟。

> 该中间件是 **LangChain Agents** 生态的一部分，通过修改 `state["messages"]` 来影响后续模型输入，属于“模型前处理”型中间件。