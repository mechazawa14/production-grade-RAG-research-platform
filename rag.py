import os

from dotenv import load_dotenv
from google import genai
from pypdf import PdfReader
import chromadb
from sentence_transformers import SentenceTransformer


load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY is None:
    raise RuntimeError("GEMINI_API_KEY is not set")

llm_client = genai.Client(api_key=GEMINI_API_KEY)

# ---------- Embedding Model ----------

embedding_model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)


# ---------- Chroma Vector Store ----------

chroma_client = chromadb.PersistentClient(
    path="chroma_db"
)

collection = chroma_client.get_or_create_collection(
    name="document_chunks",
    metadata={"hnsw:space": "cosine"}
)


# ---------- PDF Parsing ----------

def parse_pdf(file_path: str):
    reader = PdfReader(file_path)

    pages = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()

        if text and text.strip():
            pages.append({
                "page": page_number,
                "text": text.strip()
            })

    return pages


# ---------- Chunking ----------

def chunk_text(
    text: str,
    chunk_size: int = 1000,
    overlap: int = 200
):
    chunks = []

    start = 0

    while start < len(text):
        end = start + chunk_size

        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks


# ---------- Complete Ingestion Pipeline ----------

def ingest_document(
    document_id: int,
    workspace_id: int,
    filename: str,
    file_path: str
):
    pages = parse_pdf(file_path)

    texts = []
    ids = []
    metadatas = []

    chunk_index = 0

    for page in pages:
        page_chunks = chunk_text(page["text"])

        for chunk in page_chunks:

            chunk_id = (
                f"document_{document_id}_chunk_{chunk_index}"
            )

            texts.append(chunk)

            ids.append(chunk_id)

            metadatas.append({
                "document_id": document_id,
                "workspace_id": workspace_id,
                "filename": filename,
                "page": page["page"],
                "chunk_index": chunk_index
            })

            chunk_index += 1

    if not texts:
        return 0

    embeddings = embedding_model.encode(
        texts,
        normalize_embeddings=True
    ).tolist()

    collection.upsert(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas
    )

    return len(texts)



def retrieve_chunks(
    question: str,
    workspace_id: int,
    top_k: int = 3
):
    query_embedding = embedding_model.encode(
        question,
        normalize_embeddings=True
    ).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where={
            "workspace_id": workspace_id
        }
    )

    retrieved_chunks = []

    if not results["documents"] or not results["documents"][0]:
        return retrieved_chunks

    for text, metadata, distance in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0]
    ):
        retrieved_chunks.append({
            "text": text,
            "metadata": metadata,
            "distance": distance
        })

    return retrieved_chunks




def generate_answer(
    question: str,
    retrieved_chunks: list
):
    if not retrieved_chunks:
        return "I could not find relevant information in the workspace documents."

    context_parts = []

    for index, chunk in enumerate(retrieved_chunks, start=1):
        metadata = chunk["metadata"]

        context_parts.append(
            f"""
[Source {index}]
Document: {metadata['filename']}
Page: {metadata['page']}

{chunk['text']}
"""
        )

    context = "\n".join(context_parts)

    prompt = f"""
You are a research assistant answering questions from a private document knowledge base.

Answer the user's question using ONLY the supplied context.

Rules:
- Do not use outside knowledge.
- If the context does not contain enough information, say that the available documents do not provide enough information.
- Do not invent facts.
- Be concise but complete.
- When useful, refer to the supplied source numbers.

QUESTION:
{question}

CONTEXT:
{context}
"""

    response = llm_client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt
    )

    return response.text




def build_sources(retrieved_chunks: list):
    sources = []
    seen = set()

    for chunk in retrieved_chunks:
        metadata = chunk["metadata"]

        source_key = (
            metadata["document_id"],
            metadata["page"]
        )

        if source_key not in seen:
            sources.append({
                "document_id": metadata["document_id"],
                "filename": metadata["filename"],
                "page": metadata["page"]
            })

            seen.add(source_key)

    return sources