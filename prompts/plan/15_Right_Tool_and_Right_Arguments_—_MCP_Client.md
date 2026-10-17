AREA 2 -- Tool calls, right tool / right args. PRIORITY: P0, candidate for "in depth".

TESTS

1\. [P0] Disambiguation between near-duplicate tools. Two tools, `calc` (server A) and `calc2` (server B), both exposing an `add(a, b)` signature with different internal behavior (e.g. calc2 silently also logs a side-effect string). Prompt forces a specific one by name; assert from the wire log which tool actually ran and with which exact arguments -- not just that "some add tool returned the right number", since two different tools could coincidentally return the same sum.

2\. [P0] Argument fidelity on a rich schema. A `create_ticket` tool with a structured schema (title: string, priority: enum[low,medium,high], tags: array[string], due: string date). Prompt supplies all fields including an array and an enum; assert the arguments object Claude Code actually sent matches field-for-field, including array order and enum spelling -- catches silent coercion or truncation.

3\. [P0] Return value fidelity. Same ticket tool returns a structured result (id, echoed fields). Assert the model's final answer correctly reflects a value that only exists in the tool's response (e.g. a server-generated ticket ID), proving the result actually flowed back through tool_result and into the model's context rather than being hallucinated.

4\. [P1] Chained tool calls. A second tool `get_ticket(id)` that only succeeds if given the exact ID `create_ticket` returned. Prompt: "create a ticket for X, then fetch it by its new ID." Assert both calls happen, in order, with the second call's `id` argument equal to the first call's result -- real multi-step tool chaining, not just two independent single calls.

5\. [P1] Argument type edge cases. Tool parameter typed as integer; prompt supplies a value verbally (e.g. "twelve", "0", a negative number); assert what Claude Code actually sends on the wire (coerced int vs string) -- documents real behavior rather than assuming the SDK always coerces correctly.

6\. [P2, observe only] outputSchema + structuredContent. Tool declares outputSchema; assert the result the server sends under structuredContent round-trips into a text content block too (per spec: SHOULD also serialize to text for back-compat). Clients SHOULD validate `structuredContent` against `outputSchema`: send data that does not match and record what reaches `tool_result`.
