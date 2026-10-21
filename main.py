from fastapi import FastAPI
from pydantic import BaseModel

from database import SessionLocal
from models import Workspace

from fastapi import FastAPI, HTTPException
from sqlalchemy import select

app = FastAPI()

class WorkspaceCreate(BaseModel):
    name: str

class WorkspaceUpdate(BaseModel):
    name: str



@app.get("/")
def root():
    return {"message": "RAG Research Platform API"}
\

@app.post("/workspaces")
def create_workspace(workspace: WorkspaceCreate):
    db = SessionLocal()

    try:
        new_workspace = Workspace(name=workspace.name)

        db.add(new_workspace)
        db.commit()
        db.refresh(new_workspace)

        return {
            "id": new_workspace.id,
            "name": new_workspace.name
        }
    finally:
        db.close()



@app.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: int):
    db = SessionLocal()

    try:
        statement = select(Workspace).where(
            Workspace.id == workspace_id
        )

        workspace = db.scalar(statement)

        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found"
            )

        return {
            "id": workspace.id,
            "name": workspace.name
        }

    finally:
        db.close()




@app.put("/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: int,
    workspace_update: WorkspaceUpdate
):
    db = SessionLocal()

    try:
        statement = select(Workspace).where(
            Workspace.id == workspace_id
        )

        workspace = db.scalar(statement)

        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found"
            )

        workspace.name = workspace_update.name

        db.commit()
        db.refresh(workspace)

        return {
            "id": workspace.id,
            "name": workspace.name
        }

    finally:
        db.close()


@app.delete("/workspaces/{workspace_id}")
def delete_workspace(workspace_id: int):
    db = SessionLocal()

    try:
        statement = select(Workspace).where(
            Workspace.id == workspace_id
        )

        workspace = db.scalar(statement)

        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found"
            )

        db.delete(workspace)
        db.commit()

        return {
            "message": "Workspace deleted",
            "id": workspace_id
        }

    finally:
        db.close()