import os
from typing import TypedDict, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from slack_sdk import WebClient
from pymongo import MongoClient
from helper import classify_severity_llm,generate_incident_id,kb_semantic_search,refine_with_llm,save_incident_to_pgdb
from helper import invite_stakeholders,create_slack_channel,post_slack_summary,create_jira_issue

from langgraph.graph import StateGraph, END, START
from graphviz import Source

from sentence_transformers import SentenceTransformer

load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
slack_client = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None
STAKEHOLDERS = os.getenv("STAKEHOLDERS")

MONGO_URI = os.getenv("MONGO_URI")

KB = [
    {
        "query": "database connection error",
        "solution": "Restart DB service, check credentials, inspect logs.",
        "keywords": ["db","database","connection","auth","timeout"]
    },
    {
        "query": "api timeout",
        "solution": "Restart API service or rollback. Check retry configs.",
        "keywords": ["timeout","502","503","api"]
    },
    {
        "query": "high latency",
        "solution": "Check CPU/memory, scale horizontally.",
        "keywords": ["latency","slow","degraded"]
    },
    {
        "query": "disk full",
        "solution": "Clear old logs, free up space, or increase disk.",
        "keywords": ["disk","storage","space"]
    }
]

sbert_model = None
kb_embeddings = None

embedder = SentenceTransformer("all-MiniLM-L6-v2")

try:
    if MONGO_URI:
        mongo_client = MongoClient(MONGO_URI)
        kb_collection = mongo_client["incident"]["kb_vectors"]
        
        print("Using MongoDB vector search for KB")
except Exception as e:
    print("MongoDB not available", e)

def init_kb(kb_entries):
    for entry in kb_entries:
        vec = embedder.encode(entry["query"]).tolist()
        
        kb_collection.update_one(
            {"query": entry["query"]},
            {"$set": {"embedding": vec, "solution": entry["solution"]}},
            upsert=True
        )
init_kb(KB)

class IncidentState(TypedDict):
    incident_id: str
    type: str
    description: str
    severity: str
    remediation: str
    kb_matches: list
    slack_channel: Optional[str]
    jira_ticket_url: Optional[str]


def classify_node(state: IncidentState):
    state["incident_id"]=generate_incident_id()
    state["severity"]=classify_severity_llm(state["description"])
    return state

def kb_RAG_node(state: IncidentState):
    matches = kb_semantic_search(state["description"], top_k=2)
    state["kb_matches"] = matches
    state["remediation"] = refine_with_llm(state["description"], state["severity"], matches)
    return state

def db_node(state: IncidentState):
    save_incident_to_pgdb(state)
    return state

def slack_node(state: IncidentState):
    if not slack_client:
        print("Slack client not configured - skipping Slack operations")
        return state
    try:
        ch_name = "incident-" + state["incident_id"].replace(":", "-").lower()
        print(f"Creating Slack channel: {ch_name}")
        ch_id = create_slack_channel(ch_name)
        if ch_id:
            state["slack_channel"] = ch_name
            print(f"Slack channel created: {ch_name}")
            emails = [e.strip() for e in STAKEHOLDERS.split(",") if e.strip()] if STAKEHOLDERS else []
            if emails:
                print(f"Inviting stakeholders: {emails}")
                invite_stakeholders(ch_id, emails)
                print(f"Invited successfully stakeholders: {emails}")
            print(f"Posting incident summary to Slack")
            post_slack_summary(ch_id, state, ch_name)
        else:
            print("Failed to create Slack channel")
    except Exception as e:
        print(f"Slack node failed: {e}")
    return state


def jira_node(state: IncidentState) -> dict:
    try:
        summary = f"[INCIDENT] {state['incident_id']} - {state['type']} ({state['severity']})"
        description = state["description"] + "\n\nSuggested Remediation: " + state["remediation"]
        print(f"Creating Jira ticket")
        
        url = create_jira_issue(summary, description, issue_type="Task")
        
        if url:
            state["jira_ticket_url"] = url
            print(f"Jira ticket created: {url}")
        else:
            print("Failed to create Jira ticket - check credentials or issue type")
    except Exception as e:
        print(f"Jira node failed: {e}")
    return state

#Langgraph workflow
workflow=StateGraph(IncidentState)
workflow.add_node("classify", classify_node)
workflow.add_node("kb", kb_RAG_node)
workflow.add_node("db", db_node)
workflow.add_node("slack", slack_node)
workflow.add_node("jira", jira_node)

workflow.add_edge(START,"classify")
workflow.add_edge("classify","kb")
workflow.add_edge("kb","slack")     
workflow.add_edge("slack","jira")  
workflow.add_edge("jira","db")
workflow.add_edge("db",END)   

incident_graph=workflow.compile()


app=FastAPI(title="Incident Tracker Agent with LangGraph")

class IncidentIn(BaseModel):
    type: str
    description: str

@app.post("/incident")
def receive_incident(inc: IncidentIn):
    try:
        init_state={"type":inc.type,"description":inc.description,
                    "incident_id":"","severity":"","remediation":"",
                    "kb_matches":[],"slack_channel":None,"jira_ticket_url":None}
        result=incident_graph.invoke(init_state)
        return {"status":"ok","incident":result}
    except Exception as e:
        raise HTTPException(status_code=500,detail=str(e))

