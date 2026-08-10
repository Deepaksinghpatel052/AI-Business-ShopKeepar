import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helper import delete_document_from_vector_db
from utils.database import SessionLocal
from models.document import Document


def delete_document(document_id: int) -> dict:
    """
    Document ko vector DB aur documents table dono se delete karo.
    """
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id).first()

        if not doc:
            return {"success": False, "message": f"Document ID {document_id} not found"}

        # Step 1 — Vector DB se delete karo
        vector_deleted = delete_document_from_vector_db(doc, user_id=doc.user_id)

        # Step 2 — Documents table se delete karo
        db.delete(doc)
        db.commit()

        return {
            "success": True,
            "message": f"Document '{doc.original_name}' deleted successfully",
            "document_id": document_id,
            "vector_db_deleted": vector_deleted,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "message": f"Error: {str(e)}"}

    finally:
        db.close()

# Test
if __name__ == "__main__":
    result = delete_document(document_id=9)
    print(result)