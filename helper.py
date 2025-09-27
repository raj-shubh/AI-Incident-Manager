from langchain_groq import ChatGroq
import os
from sentence_transformers import SentenceTransformer

import os
from psycopg2.extras import Json
from slack_sdk import WebClient
import os
import requests, os
from requests.auth import HTTPBasicAuth

from dotenv import load_dotenv
from slack_sdk.errors import SlackApiError
from db import pg_conn
import os, time, random, string,requests
from typing import List
from pymongo import MongoClient
load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
slack_client = WebClient(token=SLACK_BOT_TOKEN) if SLACK_BOT_TOKEN else None


JIRA_DOMAIN = os.getenv("JIRA_DOMAIN")  
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
JIRA_PROJECT = os.getenv("JIRA_PROJECT")

MONGO_URI = os.getenv("MONGO_URI")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

llm = ChatGroq(
    model_name="llama-3.3-70b-versatile",
    temperature=0,
    groq_api_key=GROQ_API_KEY
)
def generate_incident_id():
    return ''.join(random.choices(string.digits, k=4))

def classify_severity_llm(description):
    prompt = f"""
        You are a system that classifies IT incident severity.

        Rules:
        - HIGH = if the description mentions words like: down, outage, failed, critical, panic, data loss.
        - MEDIUM = if the description mentions words like: degraded, slow, latency, timeout, intermittent.
        - LOW = everything else (minor issues, warnings, informational).

        Return only one word: High, Medium, or Low.
        Incident description: "{description}"
    """
    try:
        result = llm.invoke(prompt)
        
        output = result.content
        if output not in ["High", "Medium", "Low"]:
            return "Low"  
        return output
    except Exception as e:
        print("Groq classification failed, fallback to Low:", e)
        return "Low"

embedder = SentenceTransformer("all-MiniLM-L6-v2")


mongo_client = None
kb_collection = None

try:
    if MONGO_URI:
        mongo_client = MongoClient(MONGO_URI)
        kb_collection = mongo_client["incident"]["kb_vectors"]
        
except Exception as e:
    print("MongoDB not available", e)


def kb_semantic_search(description, top_k=2):

    vec = embedder.encode(description).tolist()
    
    results = kb_collection.aggregate([
        {
            "$vectorSearch": {
                "queryVector": vec,
                "path": "embedding",
                "numCandidates": 20,
                "limit": top_k,
                "index": "vector_index"  
            }
        }
    ])
    matches = [{"query": r["query"], "solution": r["solution"]} for r in results]
    return matches


def refine_with_llm(description, severity, kb_matches):
    context = "\n".join([f"- {m['query']}: {m['solution']}" for m in kb_matches])
    prompt = f"""
            You are an AI assistant helping with incident remediation.

            Incident description: {description}
            Severity: {severity}

            Here are some possible remediation options from the knowledge base:
            {context}

            Based on the description, severity, and the KB suggestions,
            propose the most useful initial remediation step.

            Return a short, clear recommendation (1-2 sentences).
            """
    result = llm.invoke(prompt)
    return result.content



def save_incident_to_pgdb(state: dict):
    with pg_conn.cursor() as cur:
        cur.execute("""
            INSERT INTO incident_details 
            (incident_id, type, description, severity, remediation, slack_channel, jira_ticket_url, kb_matches) 
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (incident_id) DO NOTHING
        """, (
            state["incident_id"],
            state["type"],
            state["description"],
            state["severity"],
            state["remediation"],
            state.get("slack_channel"),
            state.get("jira_ticket_url"),
            Json(state.get("kb_matches", []))
        ))

def create_slack_channel(name):
    if not slack_client: 
        print("Slack client not initialized - check SLACK_BOT_TOKEN")
        return None
    try:
        print(f"Attempting to create Slack channel: {name}")
        resp = slack_client.conversations_create(name=name)
        return resp["channel"]["id"]
    except SlackApiError as e:

        print(f"Slack API error creating channel '{name}': {e.response['error']}")
        return None

def invite_stakeholders(ch_id, emails: List[str]):
    if not slack_client: 
        return
    for email in emails:
        try:
            resp = slack_client.users_lookupByEmail(email=email)
            uid = resp["user"]["id"]
            slack_client.conversations_invite(channel=ch_id, users=uid)
        except SlackApiError as e:
            print(f"Failed to invite {email}: {e.response['error']}")

def post_slack_summary(ch_id, state,ch_name):
    if not slack_client: 
        return
    txt = (f"*Incident {state['incident_id']}*\n"
           f"Type: {state['type']} | Severity: {state['severity']}\n"
           f"Desc: {state['description']}\n"
           f"Remediation: {state['remediation']}")
    try:
        slack_client.chat_postMessage(channel=ch_id, text=txt)
        print(f'Successfully posted message on channel: {ch_name}')
    except SlackApiError as e:
        print(f"Failed to post message in {ch_id}: {e.response['error']}")

def create_jira_issue(summary, description, issue_type="Task"):
    if not (JIRA_DOMAIN and JIRA_EMAIL and JIRA_API_TOKEN and JIRA_PROJECT):
        print("Jira credentials not set properly")
        return None

    url = f"{JIRA_DOMAIN}/rest/api/3/issue"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {"Accept": "application/json", "Content-Type": "application/json"}

    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}]
                    }
                ]
            },
            "issuetype": {"name": issue_type}
        }
    }


    try:
        response = requests.post(url, json=payload, headers=headers, auth=auth)
        if response.status_code in (200, 201):
            issue_key = response.json().get("key")
            print("Jira issue created:", issue_key)
            return f"{JIRA_DOMAIN}/browse/{issue_key}"
        else:
            print("Failed:", response.status_code, response.text)
            return None
    except Exception as e:
        print("Error creating Jira issue:", e)
        return None
