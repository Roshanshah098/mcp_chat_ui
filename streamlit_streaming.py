import streamlit as st
from langgraph_backend import botbhai
from langchain_core.messages import HumanMessage
import uuid
from datetime import datetime


# utility functions
def generate_thread_id():
    return f"thread-{uuid.uuid4()}"


def reset_chat():
    st.session_state["thread_id"] = generate_thread_id()
    add_thread(st.session_state["thread_id"])
    st.session_state["msg_history"] = []


def add_thread(thread_id):
    if thread_id not in st.session_state["chat_threads"]:
        st.session_state["chat_threads"].append(thread_id)
        st.session_state["chat_labels"][
            thread_id
        ] = f"New Chat · {datetime.now().strftime('%b %d, %I:%M %p')}"


def load_conversation(thread_id):
    raw_msgs = botbhai.get_state(
        config={"configurable": {"thread_id": thread_id}}
    ).values.get("messages", [])

    result = []
    for msg in raw_msgs:
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        result.append({"role": role, "content": msg.content})
    return result


# session state
if "msg_history" not in st.session_state:
    st.session_state["msg_history"] = []

if "thread_id" not in st.session_state:
    st.session_state["thread_id"] = generate_thread_id()

if "chat_threads" not in st.session_state:
    st.session_state["chat_threads"] = []

if "chat_labels" not in st.session_state:
    st.session_state["chat_labels"] = {}

add_thread(st.session_state["thread_id"])


# sidebar UI
st.sidebar.title("BotBhai")
st.sidebar.caption("Your friendly neighborhood chatbot built with LangGraph")

if st.sidebar.button("＋ New Chat"):
    reset_chat()

st.sidebar.header("My Convo")

for thread_id in st.session_state["chat_threads"][::-1]:
    label = st.session_state["chat_labels"].get(thread_id, thread_id)
    if st.sidebar.button(f"💬 {label}", key=thread_id):
        st.session_state["thread_id"] = thread_id
        st.session_state["msg_history"] = load_conversation(thread_id)

# Render all previous messages
for msg in st.session_state["msg_history"]:
    with st.chat_message(msg["role"]):
        st.text(msg["content"])

# Handle new input
user_input = st.chat_input("Type your message here...")
if user_input:
    # Update label from first user message
    tid = st.session_state["thread_id"]
    if st.session_state["chat_labels"].get(tid, "").startswith("New Chat"):
        short = user_input[:30] + "..." if len(user_input) > 30 else user_input
        st.session_state["chat_labels"][
            tid
        ] = f"{short} · {datetime.now().strftime('%b %d, %I:%M %p')}"

    st.session_state["msg_history"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.text(user_input)

    with st.chat_message("assistant"):
        ai_msg = st.write_stream(
            message_chunk.content
            for message_chunk, metadata in botbhai.stream(
                {"messages": [HumanMessage(content=user_input)]},
                config={"configurable": {"thread_id": st.session_state["thread_id"]}},
                stream_mode="messages",
            )
        )
    st.session_state["msg_history"].append({"role": "assistant", "content": ai_msg})
