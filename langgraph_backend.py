from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, BaseMessage
from pydantic import Field
from dotenv import load_dotenv
from typing import Annotated, TypedDict, List
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

load_dotenv()


llm = ChatGroq(model="llama-3.1-8b-instant")


class ChatState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]


def chat_node(state: ChatState) -> ChatState:
    messages = state["messages"]
    response = llm.invoke(messages)
    return {"messages": [response]}


# checkpoint = MemorySaver("chat_checkpoint")
checkpointer = MemorySaver()
graph = StateGraph(ChatState)

graph.add_node("chat_node", chat_node)
graph.add_edge(START, "chat_node")
graph.add_edge("chat_node", END)

botbhai = graph.compile(checkpointer=checkpointer)
