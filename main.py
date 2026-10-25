import os
from datetime import datetime, timedelta, timezone
from rag import (
    build_sources,
    generate_answer,
    ingest_document,
    retrieve_chunks
)
import jwt
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel
from pwdlib import PasswordHash
from sqlalchemy import select

from database import SessionLocal
from models import Document, User, Workspace
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from pathlib import Path
import shutil
import uuid


# ---------- Environment ----------

load_dotenv()

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

if JWT_SECRET_KEY is None:
    raise RuntimeError("JWT_SECRET_KEY is not set")


UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_CONTENT_TYPES = {
    "application/pdf"
    # "text/plain"
}


# ---------- Application ----------

app = FastAPI()

password_hash = PasswordHash.recommended()


# ---------- Pydantic Schemas ----------

class UserCreate(BaseModel):
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceUpdate(BaseModel):
    name: str


class QueryRequest(BaseModel):
    question: str


# ---------- Authentication Helpers ----------

def create_access_token(user_id: int):
    expiration = datetime.now(timezone.utc) + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": str(user_id),
        "exp": expiration
    }

    return jwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm=JWT_ALGORITHM
    )


security = HTTPBearer()
def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[JWT_ALGORITHM]
        )

        user_id = payload.get("sub")

        if user_id is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication token"
            )

    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        )

    db = SessionLocal()

    try:
        user = db.get(User, int(user_id))

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="User no longer exists"
            )

        return user

    finally:
        db.close()


# ---------- Root ----------

@app.get("/")
def root():
    return {"message": "RAG Research Platform API"}


# ---------- Authentication ----------

@app.post("/register")
def register_user(user_data: UserCreate):
    db = SessionLocal()

    try:
        statement = select(User).where(
            User.email == user_data.email
        )

        existing_user = db.scalar(statement)

        if existing_user is not None:
            raise HTTPException(
                status_code=409,
                detail="Email already registered"
            )

        hashed_password = password_hash.hash(
            user_data.password
        )

        new_user = User(
            email=user_data.email,
            hashed_password=hashed_password
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "id": new_user.id,
            "email": new_user.email
        }

    finally:
        db.close()


@app.post("/login")
def login(user_data: UserLogin):
    db = SessionLocal()

    try:
        statement = select(User).where(
            User.email == user_data.email
        )

        user = db.scalar(statement)

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        password_is_correct = password_hash.verify(
            user_data.password,
            user.hashed_password
        )

        if not password_is_correct:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )

        access_token = create_access_token(user.id)

        return {
            "access_token": access_token,
            "token_type": "bearer"
        }

    finally:
        db.close()


# ---------- Workspace CRUD ----------

@app.post("/workspaces")
def create_workspace(
    workspace: WorkspaceCreate,
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        new_workspace = Workspace(
            name=workspace.name,
            owner_id=current_user.id
)

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
def get_workspace(
    workspace_id: int,
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        statement = select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == current_user.id
        )

        workspace = db.scalar(statement)

        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found"
            )

        return {
            "id": workspace.id,
            "name": workspace.name,
            "owner_id": workspace.owner_id
        }

    finally:
        db.close()


@app.put("/workspaces/{workspace_id}")
def update_workspace(
    workspace_id: int,
    workspace_update: WorkspaceUpdate,
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        statement = select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == current_user.id
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
            "name": workspace.name,
            "owner_id": workspace.owner_id
        }

    finally:
        db.close()


@app.delete("/workspaces/{workspace_id}")
def delete_workspace(
    workspace_id: int,
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        statement = select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == current_user.id
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


@app.post("/workspaces/{workspace_id}/documents")
def upload_document(
    workspace_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        # 1. Verify workspace ownership
        statement = select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == current_user.id
        )

        workspace = db.scalar(statement)

        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found"
            )

        # 2. Validate file type
        if file.content_type not in ALLOWED_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Only PDF files are supported"
            )

        # 3. Create workspace-specific directory
        workspace_directory = UPLOAD_DIR / str(workspace_id)
        workspace_directory.mkdir(
            parents=True,
            exist_ok=True
        )

        # 4. Generate safe unique stored filename
        original_filename = file.filename or "document"

        extension = Path(original_filename).suffix

        stored_filename = f"{uuid.uuid4()}{extension}"

        file_path = workspace_directory / stored_filename

        # 5. Save actual file
        with file_path.open("wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer
            )

        # 6. Store metadata in PostgreSQL
        document = Document(
            filename=original_filename,
            file_path=str(file_path),
            content_type=file.content_type,
            status="uploaded",
            workspace_id=workspace.id
        )

        db.add(document)
        db.commit()
        db.refresh(document)

        try:
            chunk_count = ingest_document(
                document_id=document.id,
                workspace_id=document.workspace_id,
                filename=document.filename,
                file_path=document.file_path
            )

            document.status = "ready"

            db.commit()
            db.refresh(document)

        except Exception:
            document.status = "failed"

            db.commit()

            raise HTTPException(
                status_code=500,
                detail="Document processing failed"
            )

        return {
    "id": document.id,
    "filename": document.filename,
    "content_type": document.content_type,
    "status": document.status,
    "workspace_id": document.workspace_id,
    "uploaded_at": document.uploaded_at,
    "chunks_created": chunk_count
}

    finally:
        db.close()





@app.post("/workspaces/{workspace_id}/query")
def query_workspace(
    workspace_id: int,
    query: QueryRequest,
    current_user: User = Depends(get_current_user)
):
    db = SessionLocal()

    try:
        # Verify that the authenticated user owns this workspace
        statement = select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.owner_id == current_user.id
        )

        workspace = db.scalar(statement)

        if workspace is None:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found"
            )

        # Semantic retrieval from Chroma
        chunks = retrieve_chunks(
            question=query.question,
            workspace_id=workspace.id,
            top_k=3
        )

        answer = generate_answer(
        question=query.question,
        retrieved_chunks=chunks)

        sources = build_sources(chunks)

        return {
    "question": query.question,
    "answer": answer,
    "sources": sources
}

    finally:
        db.close()