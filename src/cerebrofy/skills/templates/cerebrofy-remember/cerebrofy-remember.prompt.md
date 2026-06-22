You have access to Cerebrofy's writable memory layer. Use it to persist knowledge that future agents will need.

## After completing any significant task, call `cerebrofy_remember` to record:
- The decision made and why (type: decision)
- Any gotcha or edge case you encountered (type: warning)
- What you actually did (type: agent_action)

## Before starting any task, call `cerebrofy_recall` to surface:
- Past decisions that constrain your approach
- Known warnings about the code you are about to touch
- Prior agent actions on the same neuron or lobe

## Rules
- Always attach memories to the most specific neuron available (`neuron` param)
- If no neuron fits, attach to the lobe (`lobe` param)
- Keep `title` under 80 characters; put full detail in `body`
- Use `cerebrofy_link_memories` when you know two memories are causally related
- Use `cerebrofy_trace_history` before modifying any neuron that has a `warning` memory
