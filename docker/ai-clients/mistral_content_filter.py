"""
title: Mistral Structured Content
description: Display Mistral text and thinking chunks in Open WebUI streaming chats.
version: 0.1.0
"""


class Filter:
    def stream(self, event: dict) -> dict:
        for choice in event.get("choices", []):
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            chunks = delta.get("content")
            if not isinstance(chunks, list) or not all(
                isinstance(chunk, dict) and chunk.get("type") in ("text", "thinking")
                for chunk in chunks
            ):
                continue
            text, thinking = [], []
            for chunk in chunks:
                if chunk["type"] == "text":
                    text.append(chunk.get("text", ""))
                else:
                    value = chunk.get("thinking", [])
                    if isinstance(value, str):
                        thinking.append(value)
                    elif isinstance(value, list):
                        thinking.extend(
                            part.get("text", "")
                            for part in value
                            if isinstance(part, dict) and part.get("type") == "text"
                        )
            delta["content"] = "".join(text)
            if thinking:
                delta["reasoning_content"] = delta.get("reasoning_content", "") + "".join(thinking)
        return event
