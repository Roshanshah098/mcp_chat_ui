import streamlit as st
from langgraph_backend import botbhai
from langchain_core.messages import HumanMessage

# config for botbhai
CONFIG = {"configurable": {"thread_id": "thread-1"}}

# initialize msg history in session state
if "msg_history" not in st.session_state:
    st.session_state["msg_history"] = []

# Render ALL previous messages on every rerun
for msg in st.session_state["msg_history"]:
    with st.chat_message(msg["role"]):
        st.text(msg["content"])

# handling new input at the bottom
user_input = st.chat_input("Type your message here...")
if user_input:
    st.session_state["msg_history"].append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.text(user_input)

    response = botbhai.invoke(
        {"messages": [HumanMessage(content=user_input)]}, config=CONFIG
    )

    ai_msg = response["messages"][-1].content
    st.session_state["msg_history"].append({"role": "assistant", "content": ai_msg})
    with st.chat_message("assistant"):
        st.text(ai_msg)
