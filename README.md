# Incident Management System

A smart incident tracker that automatically handles IT incidents using AI and workflow automation. When an incident happens, the system classifies it, finds solutions from a knowledge base, creates a Slack channel for team communication, and opens a Jira ticket for tracking and saves all details to a database.

## How It Works

**Step 1: Knowledge Base Setup**
- First, we save our small knowledge base in MongoDB Atlas cloud
- Each query gets converted to vector embeddings so we can do semantic search later
- This helps us find similar past incidents quickly

Here's what happens when an incident comes in:

**Step 2: Incident Report**
- Someone reports an incident through our FastAPI endpoint
- The system receives the incident type and description

**Step 3: AI Classification**
- We use an LLM (Large Language Model) to classify the incident
- It reads the description and decides if it's Low, Medium, or High severity
- Uses a simple prompt that looks for keywords like "down", "outage", "critical" for High severity

**Step 4: Find Solutions**
- We search our MongoDB database using semantic search
- Finds the 2 most similar past incidents and their solutions
- Takes these results, the original query, and severity level
- Sends everything to the LLM again to generate a better, more specific solution

**Step 5: Slack Notification**
- Creates a new Slack channel for this incident
- Posts a summary message with all the details
- Invites relevant team members to the channel

**Step 6: Jira Ticket**
- Creates a Jira issue for tracking
- Includes the incident description and suggested solution
- Links back to the Slack channel

**Step 7: Database Storage**
- Finally saves all incident details in PostgreSQL database
- Stores everything: ID, type, description, severity, solution, Slack channel, Jira ticket URL

## Architecture

```
Incident Report → FastAPI → LangGraph Workflow
                                    ↓
                            AI Classification
                                    ↓
                            Knowledge Base Search
                                    ↓
                            Slack Channel Creation
                                    ↓
                            Jira ticket creation
                                    ↓
                            PostgreSQL Database
                                    ↓
                                    End
```

### Components

- **FastAPI**: Web API that receives incident reports
- **LangGraph**: Workflow engine that manages the incident processing steps
- **Groq LLM**: AI model for classifying severity and generating remediation advice
- **PostgreSQL**: Stores incident details and history
- **MongoDB**: Vector database for semantic search of knowledge base
- **Slack SDK**: Creates channels and sends notifications
- **Jira API**: Creates tracking tickets

## Setup Instructions

**Tech stack need:**
- Python 3.10+
- PostgreSQL database
- MongoDB Atlas account
- Slack workspace
- Jira account

**Quick setup:**
1. Install dependencies: `pip install -r requirements.txt`
2. Create `.env` file
3. Start PostgreSQL: `createdb incident_details`
4. Run: `uvicorn main:app --reload`

**Environment variables (.env file):**
```env
MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/
GROQ_API_KEY=groq_key
SLACK_BOT_TOKEN=xoxb-token
STAKEHOLDERS=user1@company.com,user2@company.com
JIRA_DOMAIN=https://domain.atlassian.net
JIRA_EMAIL=email
JIRA_API_TOKEN=jira_token
JIRA_PROJECT=PROJ
```

## Trade-offs and Assumptions

**Good choice according to me:**
- LangGraph handles workflows nicely

**Current limitations:**
- Only 4 incident types in knowledge base
- No user authentication

**What I assume:**
- Incidents are text descriptions only
- Team has Slack accounts with email
- Jira project exists with proper permissions
- MongoDB vector index is set up
- PostgreSQL runs locally


