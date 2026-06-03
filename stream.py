import streamlit as st
from langgraph_backend import botbhai
from langchain_core.messages import HumanMessage
import uuid
from datetime import datetime

# Page config
st.set_page_config(
    page_title="BotBhai 🤖",
    page_icon="🤖",
    layout="wide",
)
 
# CSS: background + transparent UI
st.markdown(
    """
    <style>
        /* Hide streamlit default clutter */
        #MainMenu, footer, header { visibility: hidden; }

        /* Animated gradient background on the whole page */
        .stApp {
            background: linear-gradient(-45deg, #0d0d2b, #1a1a4e, #0a2a4a, #0d3b2e);
            background-size: 400% 400%;
            animation: gradientShift 12s ease infinite;
        }

        @keyframes gradientShift {
            0%   { background-position: 0% 50%; }
            50%  { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        /* Transparent sidebar */
        [data-testid="stSidebar"] {
            background: rgba(255, 255, 255, 0.05) !important;
            backdrop-filter: blur(12px);
            border-right: 1px solid rgba(255, 255, 255, 0.1);
        }

        /* Transparent main chat area */
        .block-container {
            background: transparent !important;
            padding-top: 2rem;
        }

        /* User message bubble */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
            background: rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 16px;
            padding: 8px;
            margin: 6px 0;
        }

        /* Assistant message bubble */
        [data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-assistant"]) {
            background: rgba(100, 200, 255, 0.07);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(100, 200, 255, 0.15);
            border-radius: 16px;
            padding: 8px;
            margin: 6px 0;
        }

        /* Chat input box */
        [data-testid="stChatInput"] {
            background: rgba(255, 255, 255, 0.07) !important;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.15) !important;
            border-radius: 12px;
        }

        /* All text white */
        * { color: #f0f0f0 !important; }

        /* Sidebar buttons */
        .stButton > button {
            background: rgba(255, 255, 255, 0.08);
            border: 1px solid rgba(255, 255, 255, 0.15);
            border-radius: 10px;
            color: #f0f0f0 !important;
            transition: all 0.2s ease;
        }
        .stButton > button:hover {
            background: rgba(255, 255, 255, 0.18);
            border-color: rgba(255, 255, 255, 0.3);
            transform: translateY(-1px);
        }

        /* New Chat button — make it pop */
        .stButton:first-child > button {
            background: linear-gradient(135deg, rgba(100, 200, 255, 0.25), rgba(150, 100, 255, 0.25));
            border: 1px solid rgba(100, 200, 255, 0.4);
            font-weight: 600;
        }

        /* Title styling */
        .chat-title {
            text-align: center;
            font-size: 2.2rem;
            font-weight: 800;
            background: linear-gradient(90deg, #64c8ff, #a064ff);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.2rem;
        }
        .chat-subtitle {
            text-align: center;
            font-size: 0.85rem;
            color: rgba(255,255,255,0.5) !important;
            margin-bottom: 1rem;
        }
    </style>
""",
    unsafe_allow_html=True,
)


# Session state setup
if "all_chats" not in st.session_state:
    st.session_state["all_chats"] = {}

if "active_chat_id" not in st.session_state:
    st.session_state["active_chat_id"] = None


# Helpers
def create_new_chat():
    chat_id = str(uuid.uuid4())
    st.session_state["all_chats"][chat_id] = {
        "title": f"Chat · {datetime.now().strftime('%b %d, %H:%M')}",
        "messages": [],
    }
    st.session_state["active_chat_id"] = chat_id


def delete_chat(chat_id):
    del st.session_state["all_chats"][chat_id]
    if st.session_state["active_chat_id"] == chat_id:
        st.session_state["active_chat_id"] = None


# Sidebar
with st.sidebar:
    st.markdown("## 🤖 BotBhai")
    st.button("＋ New Chat", use_container_width=True, on_click=create_new_chat)
    st.divider()

    if st.session_state["all_chats"]:
        st.markdown("**💬 Previous Chats**")

        for chat_id, chat_data in reversed(list(st.session_state["all_chats"].items())):
            col1, col2 = st.columns([5, 1])

            with col1:
                is_active = chat_id == st.session_state["active_chat_id"]
                label = f"{'▶ ' if is_active else ''}{chat_data['title']}"
                if st.button(label, key=f"select_{chat_id}", use_container_width=True):
                    st.session_state["active_chat_id"] = chat_id

            with col2:
                if st.button("🗑", key=f"delete_{chat_id}"):
                    delete_chat(chat_id)
                    st.rerun()
    else:
        st.caption("No chats yet. Start a new one!")

    st.divider()
    st.caption("Made for LangGraph by SunBhai")


# Main area
active_id = st.session_state["active_chat_id"]

st.markdown('<div class="chat-title">🤖 BotBhai</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="chat-subtitle">Made with my inner soul for LangGraph by SunBhai</div>',
    unsafe_allow_html=True,
)
st.divider()

if active_id is None:
    # Welcome screen when no chat is selected
    st.markdown(
        """
        <div style='text-align:center; margin-top: 5rem; opacity: 0.6;'>
            <div style='font-size: 4rem;'>✨</div>
            <div style='font-size: 1.1rem; margin-top: 1rem;'>Click <b>＋ New Chat</b> to get started</div>
        </div>
    """,
        unsafe_allow_html=True,
    )

else:
    current_chat = st.session_state["all_chats"][active_id]

    # Render chat history
    for msg in current_chat["messages"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Handle new input
    user_input = st.chat_input("Ask BotBhai anything...")

    if user_input:
        current_chat["messages"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        # Each chat has its own thread_id → separate LangGraph memory
        config = {"configurable": {"thread_id": active_id}}

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                response = botbhai.invoke(
                    {"messages": [HumanMessage(content=user_input)]},
                    config=config,
                )
                ai_msg = response["messages"][-1].content
            st.markdown(ai_msg)

        current_chat["messages"].append({"role": "assistant", "content": ai_msg})

        # Auto-rename chat from first message
        if len(current_chat["messages"]) == 2:
            current_chat["title"] = user_input[:30] + (
                "..." if len(user_input) > 30 else ""
            )
