from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class WorkspaceCreate(BaseModel):
    name: str

@app.get("/")
def root():
    return {"message": "RAG Research Platform API"}

@app.post("/workspaces")
def create_workspace(workspace: WorkspaceCreate):
    return {
        "message": "Workspace received",
        "workspace_name": workspace.name
    }