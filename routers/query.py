from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from models.shop_owner import ShopOwner
from utils.auth import get_current_user
from RAG_src.search import RAGSearch

router = APIRouter(prefix="/rag", tags=["RAG Search"])

# RAGSearch instance — ek baar initialize hoga
rag = RAGSearch()

class QueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)

class QueryResponse(BaseModel):
    query: str
    answer: str


@router.post("/search", response_model=QueryResponse)
async def search(
    payload: QueryRequest,
    current_user: ShopOwner = Depends(get_current_user),
):
    """
    RAG search endpoint.
    - JWT token required
    - Query validation (min 3, max 500 chars)
    - Returns AI answer based on uploaded documents
    """
    if not payload.query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query cannot be empty"
        )

    try:
        answer = rag.search_and_summarize(payload.query, top_k=payload.top_k, user_id=current_user.id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search failed: {str(e)}"
        )

    return QueryResponse(query=payload.query, answer=answer)