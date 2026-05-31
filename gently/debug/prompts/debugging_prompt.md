# Trajectory Debugging Prompt

You are reviewing a Gently copilot trajectory. Use the attached session
artifacts, transcript excerpt, expected behavior annotation, and relevant source
files to identify the smallest code or prompt change that would make the agent
behave correctly.

Focus on:

- What the user expected.
- What tool calls or events actually happened.
- Whether the agent had enough context to choose the expected action.
- Which tool descriptions, prompt sections, or orchestration code shaped the
  decision.
- A targeted fix and a regression test that would catch the issue next time.

Do not assume live hardware is available. Prefer fixes that can be verified with
offline traces, mock clients, or deterministic unit tests.
