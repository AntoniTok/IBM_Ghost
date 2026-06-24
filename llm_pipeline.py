#!/usr/bin/env python3
"""
llm_pipeline.py
===============
Granite Ghost – LLM Pipeline

Connects to Ollama (model set via OLLAMA_MODEL in config.py) via HTTP,
handles tool calling, and returns a natural language string ready for TTS.

Note: Granite 4.0 via Ollama returns tool calls with an empty name field.
We infer the correct tool from the arguments instead.
"""

from __future__ import annotations

import json
import logging
import time
from collections import deque

import requests

from llm_tools import SERVICE_MANAGER_TOOLS, handle_tool_call
from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT
from latency_debug import Timer, log_mem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("llm_pipeline")

CHAT_URL = f"{OLLAMA_HOST}/api/chat"

SYSTEM_PROMPT = """You are a warm, patient voice assistant for an elderly person.
You have tools to check the weather, emails, calendar events, text messages, and control music.
You can also log daily activities when the user tells you they've done something.
Rules:
- Always use a tool when the user asks about weather, email, calendar, SMS, or music. Never guess or invent data.
- When the user says they've completed an activity (had breakfast, took medication, went for a walk, etc.), use the log_activity tool to record it.
- Keep responses short, friendly, and spoken naturally. No bullet points or lists.
- If a tool returns an error, say so simply and suggest trying again.
- If the user asks something you have no tool for, answer from your own knowledge briefly."""


# ─── Conversation history ──────────────────────────────────────────────────────
#
# Keeps the last HISTORY_MAXLEN (user, assistant) text exchanges so the
# assistant has short-term memory across utterances. Deliberately stores
# ONLY the user's spoken text and the assistant's final spoken reply —
# never tool_calls or tool result messages, which would bloat the prompt
# with raw JSON and eat into the context window. In-memory only; resets
# when main.py restarts.

HISTORY_MAXLEN = 3
_history: deque[tuple[str, str]] = deque(maxlen=HISTORY_MAXLEN)


# ─── Tool name inference ──────────────────────────────────────────────────────
#
# Granite 4.0 via Ollama returns tool calls with an empty name field.
# We infer the correct tool from the argument keys instead.
#
# Each tool has a unique signature:
#   get_weather  → args may be empty or contain 'refresh'
#   get_emails   → args may be empty or contain 'refresh'
#   get_calendar → args may be empty or contain 'refresh'
#   get_sms      → args may be empty or contain 'refresh'
#   spotify      → always contains 'intent'
#
# To disambiguate the refresh-only tools we rely on the conversation context
# (what the user asked about) passed in as a hint.

def _infer_tool_name(args: dict, user_text: str) -> str:
    """
    Infer the tool name from arguments and what the user said.
    Returns the tool name string.
    """
    # Spotify is unambiguous — always has 'intent'
    if "intent" in args:
        return "spotify"

    # For the rest, use keywords from the user's message
    text = user_text.lower()

    if any(w in text for w in ["weather", "temperature", "rain", "sunny", "cold", "warm", "coat", "umbrella", "outside", "forecast"]):
        return "get_weather"

    if any(w in text for w in ["email", "mail", "inbox", "unread"]):
        return "get_emails"

    if any(w in text for w in ["text", "sms", "message"]):
        return "get_sms"

    if any(w in text for w in ["music", "song", "play ", "pause", "skip", "spotify", "next track", "volume"]):
        return "spotify"

    # Activity logging — checked after comms tools so "read me my messages"
    # doesn't match "read" as the activity. Only "reading" is specific enough.
    activity_words = ["had my", "had a", "had breakfast", "had lunch", "had dinner",
                      "ate", "eaten", "took my", "taken my", "done my", "finished",
                      "went for a walk", "walked", "woke up", "woken",
                      "going to bed", "bedtime",
                      "breakfast", "lunch", "dinner", "medication", "tablet",
                      "medicine", "pill", "reading", "playing chess",
                      "phoned", "made a call"]
    if any(w in text for w in activity_words):
        return "log_activity"

    if any(w in text for w in ["calendar", "schedule", "appointment", "event", "today", "agenda", "what's on"]):
        return "get_calendar"

    # If we still can't tell, try to guess from argument keys
    arg_keys = set(args.keys())
    if "activity_name" in arg_keys:
        return "log_activity"
    if "city" in arg_keys or "location" in arg_keys:
        return "get_weather"
    if "query" in arg_keys:
        return "spotify"

    # Last resort — weather is the most common request
    log.warning(f"Could not infer tool name from args={args}, text={text!r}. Defaulting to get_weather.")
    return "get_weather"


# ─── Ollama client ────────────────────────────────────────────────────────────

def _chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    payload = {
        "model":    OLLAMA_MODEL,
        "messages": messages,
        "stream":   False,
    }
    if tools:
        payload["tools"] = tools

    response = requests.post(CHAT_URL, json=payload, timeout=OLLAMA_TIMEOUT)
    response.raise_for_status()
    return response.json()["message"]


# ─── Core pipeline ────────────────────────────────────────────────────────────

def run(user_text: str) -> str:
    log.info(f"User: {user_text}")

    run_start = time.monotonic()
    log_mem("run() start")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for past_user, past_assistant in _history:
        messages.append({"role": "user",      "content": past_user})
        messages.append({"role": "assistant", "content": past_assistant})
    messages.append({"role": "user", "content": user_text})

    log.info(f"[debug] history: {len(_history)}/{HISTORY_MAXLEN} prior exchange(s) included")

    # ── Pass 1: let Granite decide whether to call a tool ────────────────────

    log.info(f"[debug] pass1 payload size: {len(json.dumps(messages)) + len(json.dumps(SERVICE_MANAGER_TOOLS))} chars (messages + tools)")

    try:
        with Timer("pass1_llm_call"):
            assistant_msg = _chat(messages, tools=SERVICE_MANAGER_TOOLS)
    except requests.exceptions.ConnectionError:
        log.error("Cannot reach Ollama — is it running?")
        return "I'm having trouble thinking right now. Please make sure the assistant service is running."
    except Exception as exc:
        log.error(f"Ollama error: {exc}")
        return "Sorry, something went wrong. Please try again."

    tool_calls = assistant_msg.get("tool_calls")

    if tool_calls:
        messages.append(assistant_msg)

        for call in tool_calls:
            raw_name  = call["function"].get("name", "")
            tool_args = call["function"].get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except Exception:
                    tool_args = {}

            # Always infer — Granite 4.0 via Ollama frequently returns the
            # wrong tool name (e.g. get_calendar when user says "I had lunch").
            # Our keyword-based inference is far more reliable.
            tool_name = _infer_tool_name(tool_args, user_text)

            log.info(f"Tool call: {tool_name}({tool_args})")
            with Timer(f"tool_call:{tool_name}"):
                tool_result = handle_tool_call(tool_name, tool_args)
            log.info(f"Tool result: {tool_result[:200]}{'…' if len(tool_result) > 200 else ''}")

            messages.append({
                "role":    "tool",
                "content": tool_result,
            })

        # ── Pass 2: get the spoken response ──────────────────────────────────

        log.info(f"[debug] pass2 payload size: {len(json.dumps(messages)) + len(json.dumps(SERVICE_MANAGER_TOOLS))} chars (messages + tools)")

        try:
            with Timer("pass2_llm_call"):
                final_msg = _chat(messages, tools=SERVICE_MANAGER_TOOLS)
        except Exception as exc:
            log.error(f"Ollama error on second pass: {exc}")
            return "I got the information but had trouble putting it into words. Please try again."

        response = final_msg.get("content", "").strip()

    else:
        response = assistant_msg.get("content", "").strip()

    final_response = response or "I'm not sure how to answer that."

    # Only the final spoken exchange goes into history — no tool calls/results.
    _history.append((user_text, final_response))

    log.info(f"Assistant: {final_response}")
    log.info(f"[timing] run() TOTAL                  |   {time.monotonic() - run_start:6.2f}s")
    log_mem("run() end")
    return final_response


# ─── Standalone test loop ─────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Granite Ghost – LLM Pipeline (Ollama / {OLLAMA_MODEL})")
    print(f"Make sure 'ollama run {OLLAMA_MODEL}' and service_manager.py are running.")
    print(f"Remembers the last {HISTORY_MAXLEN} exchange(s) in this session.")
    print("Type a message and press Enter. Ctrl+C to exit.\n")

    while True:
        try:
            user_input = input("You: ").strip()
            if not user_input:
                continue
            print(f"Assistant: {run(user_input)}\n")
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        except Exception as exc:
            log.error(f"Unexpected error: {exc}")
            print("Something went wrong. Check the logs.\n")
